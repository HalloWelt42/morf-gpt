import json
from pathlib import Path

import httpx
import pytest

from app.dienste.transkription import register
from app.dienste.transkription.basis import TranskriptionsFehler
from app.dienste.transkription.eigener_dienst import EigenerDienst

ABLAGE = Path(__file__).resolve().parent.parent / ".test-tmp"


def _dienst(antworten: dict[str, httpx.Response], gesehen: list[httpx.Request], wortzeiten: bool = True) -> EigenerDienst:
    def handler(request: httpx.Request) -> httpx.Response:
        gesehen.append(request)
        return antworten.get(request.url.path, httpx.Response(404, json={"detail": "unbekannt"}))

    return EigenerDienst("http://dienst:8463/", wortzeiten_behalten=wortzeiten, transport=httpx.MockTransport(handler))


@pytest.fixture
def audio() -> Path:
    ABLAGE.mkdir(exist_ok=True)
    pfad = ABLAGE / "probe.m4a"
    pfad.write_bytes(b"\x00\x01\x02")
    return pfad


async def test_transkription_liest_antwort_und_sendet_felder(audio: Path):
    gesehen: list[httpx.Request] = []
    antwort = {
        "text": "Guten Tag.",
        "segmente": [{"start": 0.0, "end": 1.2, "text": "Guten Tag.", "words": [{"word": "Guten", "start": 0.0, "end": 0.5}]}],
        "sprache": "de",
        "modell": "mlx-community/whisper-large-v3-mlx",
        "engine": "mlx",
        "dauer_s": 2.5,
    }
    d = _dienst({"/transkription": httpx.Response(200, json=antwort)}, gesehen)
    e = await d.transkribiere(audio, "german", 60)
    assert e.text == "Guten Tag." and e.sprache == "de" and e.engine == "morf" and e.modell.endswith("large-v3-mlx")
    assert len(e.segmente) == 1 and e.segmente[0].woerter[0].wort == "Guten"
    koerper = gesehen[0].content
    assert b'name="sprache"\r\n\r\ngerman' in koerper and b'name="wortzeiten"\r\n\r\ntrue' in koerper and b'name="datei"' in koerper

    ohne = _dienst({"/transkription": httpx.Response(200, json=antwort)}, [], wortzeiten=False)
    e2 = await ohne.transkribiere(audio, "german", 60)
    assert e2.segmente[0].woerter == []


async def test_fehler_werden_gemeldet(audio: Path):
    d = _dienst({"/transkription": httpx.Response(500, json={"detail": "Arbeiter 1 ist ausgefallen"})}, [])
    with pytest.raises(TranskriptionsFehler, match="Arbeiter 1 ist ausgefallen"):
        await d.transkribiere(audio, "german", 60)
    d = _dienst({"/transkription": httpx.Response(200, json={"unsinn": 1})}, [])
    with pytest.raises(TranskriptionsFehler, match="weder Text noch Segmente"):
        await d.transkribiere(audio, "german", 60)


async def test_erreichbar_stand_und_arbeiter():
    gesehen: list[httpx.Request] = []
    stand = {"engine": "mlx", "modell": "m", "gewuenscht": 2, "maximum": 4, "arbeiter": [], "wartend": 0, "speicher": {}, "hinweise": []}
    d = _dienst(
        {
            "/health": httpx.Response(200, json={"status": "ok", "arbeiter": 1, "engine": "mlx", "modell": "m"}),
            "/stand": httpx.Response(200, json=stand),
            "/arbeiter": httpx.Response(200, json={**stand, "hinweise": ["Nicht genug freier Speicher"]}),
        },
        gesehen,
    )
    ok, hinweis = await d.erreichbar()
    assert ok and "1 Arbeiter" in hinweis
    assert (await d.stand())["gewuenscht"] == 2
    ergebnis = await d.arbeiter_setzen(3)
    assert ergebnis["hinweise"] == ["Nicht genug freier Speicher"]
    assert json.loads(gesehen[-1].content) == {"anzahl": 3}

    laedt = _dienst({"/health": httpx.Response(200, json={"status": "laedt", "arbeiter": 0})}, [])
    ok, hinweis = await laedt.erreichbar()
    assert ok and "lädt" in hinweis


def test_registriert_als_vorgabe():
    assert "morf" in register.kennungen()
    assert register.titel_fuer("morf").startswith("Eigener Dienst")
    engine = register.engine_aus_werten(
        {
            "transkription.engine": "morf",
            "transkription.dienst_url": "http://127.0.0.1:8463",
            "transkription.wortzeiten_speichern": True,
        }
    )
    assert isinstance(engine, EigenerDienst) and engine.basis_url == "http://127.0.0.1:8463"
