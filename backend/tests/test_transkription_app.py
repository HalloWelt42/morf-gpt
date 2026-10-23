"""Engine "App Transkription": Dienstweg über eine nachgestellte Kellerwolke (Ordner, Hochladen, Weitergeben, auf das
Transkript warten, lesen, danach in den Papierkorb) und die Fehlerwege."""

import json
from pathlib import Path

import httpx
import pytest

from app.dienste.transkription import register
from app.dienste.transkription.basis import TranskriptionsFehler
from app.dienste.transkription.transkription_app import TranskriptionApp, sprachkuerzel

ABLAGE = Path(__file__).resolve().parent.parent / ".test-tmp"
TRANSKRIPT = {
    "format": "transkript/1", "name": "probe", "sprache": "de", "erzeugt_mit": {"dienst": "klangwerk-hoeren"},
    "sprecher": [{"kennung": "s1", "name": "Sprecher 1"}],
    "segmente": [{"start": 0.0, "ende": 1.5, "sprecher": "s1", "text": "Guten Tag.",
                  "woerter": [{"wort": "Guten", "start": 0.0, "ende": 0.6}, {"wort": "Tag.", "start": 0.7, "ende": 1.5}]},
                 {"start": 2.0, "ende": 3.0, "sprecher": "s1", "text": "  "}],
}


class Kellerwolke:
    """Nachgestellte Ablage: das Transkript erscheint nach `runden` Abfragen der Begleiter."""

    def __init__(self, runden: int = 1, zustand: str = "laeuft") -> None:
        self.runden, self.zustand = runden, zustand
        self.gesehen: list[tuple[str, str]] = []
        self.weitergegeben: dict = {}
        self.geloescht: list[str] = []

    def __call__(self, r: httpx.Request) -> httpx.Response:
        pfad = r.url.path.removeprefix("/api/v1/ablage")
        self.gesehen.append((r.method, pfad))
        assert r.headers["authorization"] == "Bearer kw_app_morf"
        if pfad == "/ich":
            return httpx.Response(200, json={"app": "morf-gpt", "konto": "admin", "rechte": []})
        if pfad == "/ordner":
            assert json.loads(r.content) == {"pfad": "Apps/morf-gpt/Dienst"}
            return httpx.Response(200, json={"id": "o1"})
        if pfad == "/datei":
            assert r.url.params["pfad"].startswith("Apps/morf-gpt/Dienst/probe-") and r.headers["if-none-match"] == "*"
            return httpx.Response(200, json={"id": "h1"})
        if pfad == "/anfragen" and r.method == "POST":
            self.weitergegeben = json.loads(r.content)
            return httpx.Response(200, json={"anfrage": {"id": "a1"}})
        if pfad == "/anfragen/a1":
            return httpx.Response(200, json={"zustand": self.zustand, "meldung": "Hörmodell weg" if self.zustand == "fehler" else None})
        if pfad == "/knoten/h1/begleiter":
            self.runden -= 1
            return httpx.Response(200, json=[{"id": "t1", "rolle": "transkript"}] if self.runden < 0 else [])
        if pfad == "/knoten/t1/inhalt":
            return httpx.Response(200, content=json.dumps(TRANSKRIPT).encode())
        if pfad == "/knoten/h1" and r.method == "DELETE":
            self.geloescht.append("h1")
            return httpx.Response(204)
        return httpx.Response(404, json={"detail": "unbekannt"})


@pytest.fixture
def audio() -> Path:
    ABLAGE.mkdir(exist_ok=True)
    pfad = ABLAGE / "probe.m4a"
    pfad.write_bytes(b"\x00\x01\x02")
    return pfad


def _engine(kw: Kellerwolke, schluessel: str = "kw_app_morf") -> TranskriptionApp:
    return TranskriptionApp("http://kw.test:39278/", schluessel, takt_s=0, transport=httpx.MockTransport(kw))


async def test_dienstweg_bis_zum_transkript(audio: Path):
    kw = Kellerwolke(runden=2)
    erg = await _engine(kw).transkribiere(audio, "german", 60)
    assert kw.weitergegeben == {"app": "Transkription", "aktion": "transkribieren", "knoten_id": "h1", "optionen": {"sprache": "de"}}
    assert erg.text == "Guten Tag." and erg.sprache == "de" and erg.engine == "transkription"
    assert [(s.start, s.end, s.text) for s in erg.segmente] == [(0.0, 1.5, "Guten Tag.")]
    assert [(w.wort, w.end) for w in erg.segmente[0].woerter] == [("Guten", 0.6), ("Tag.", 1.5)]
    assert kw.geloescht == ["h1"]                                         # Aufnahme samt Transkript in den Papierkorb


async def test_fehler_der_transkription_kommt_an_und_raeumt_auf(audio: Path):
    kw = Kellerwolke(runden=99, zustand="fehler")
    with pytest.raises(TranskriptionsFehler, match="Hörmodell weg"):
        await _engine(kw).transkribiere(audio, "auto", 60)
    assert kw.geloescht == ["h1"]


async def test_ohne_schluessel_kein_aufruf(audio: Path):
    kw = Kellerwolke()
    with pytest.raises(TranskriptionsFehler, match="MORF_KELLERWOLKE_SCHLUESSEL"):
        await _engine(kw, schluessel="").transkribiere(audio, "german", 60)
    assert kw.gesehen == []
    assert (await _engine(kw, schluessel="").erreichbar())[0] is False


def test_sprachen_und_register():
    assert [sprachkuerzel(s) for s in ("german", "en", "AUTO", "klingonisch")] == ["de", "en", "auto", "auto"]
    assert register.kennungen() == ("morf", "transkription")
