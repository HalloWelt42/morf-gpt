"""Übergabe: erstellen (Paket, Audioteile, Modelle, Manifest, Prüfsummen) und holen (aus Ordner und über
eine Webadresse mit Fortsetzen), ohne Datenbank: Fake-Quelle und Fake-Ziel aus test_export."""

from __future__ import annotations

import hashlib
import shutil
import tarfile
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from app.dienste.export import holen, uebergabe
from app.dienste.export.uebergabe import Audiodatei, audio_in_teile
from tests.test_export import DIMENSION, FakeQuelle, FakeZiel

TEST_WURZEL = Path(__file__).resolve().parents[1] / ".test-tmp" / "uebergabe"


@pytest.fixture
def ordner() -> Iterator[Path]:
    pfad = TEST_WURZEL / uuid.uuid4().hex
    pfad.mkdir(parents=True)
    try:
        yield pfad
    finally:
        shutil.rmtree(pfad, ignore_errors=True)


def test_audio_in_teile_haelt_die_grenze() -> None:
    d = [Audiodatei(f"{i:032x}", Path(f"{i}.m4a"), groesse) for i, groesse in enumerate([600, 500, 900, 1200, 100])]
    teile = audio_in_teile(d, teil_bytes=1000)
    assert [[x.bytes for x in t] for t in teile] == [[600], [500], [900], [1200], [100]]
    teile = audio_in_teile(d, teil_bytes=1500)
    assert [[x.bytes for x in t] for t in teile] == [[600, 500], [900], [1200, 100]]
    assert audio_in_teile([], 1000) == []


def test_modellnamen_aus_ablage(ordner: Path) -> None:
    hub = ordner / "hf" / "hub" / "models--mlx-community--whisper-large-v3-mlx"
    (hub / "snapshots" / "abc").mkdir(parents=True)
    (hub / "blobs").mkdir()
    (hub / "blobs" / "x").write_bytes(b"gewicht")
    (hub / "snapshots" / "abc" / "weights.npz").symlink_to(hub / "blobs" / "x")
    (hub / "snapshots" / "alt").mkdir()
    (hub / "snapshots" / "alt" / "weights.npz").write_bytes(b"alte gewichte")
    (hub / "refs").mkdir()
    (hub / "refs" / "main").write_text("abc")
    (hub / ".locks").mkdir()
    (hub / ".locks" / "x.lock").write_bytes(b"")
    (ordner / "fast-bge-m3" / "onnx").mkdir(parents=True)
    (ordner / "fast-bge-m3" / "onnx" / "model.onnx").write_bytes(b"onnx")
    assert uebergabe.modell_namen(ordner) == ["fast-bge-m3", "mlx-community/whisper-large-v3-mlx"]
    namen = [str(p.relative_to(ordner)) for p in uebergabe.modell_dateien(ordner)]
    assert namen == [
        "fast-bge-m3/onnx/model.onnx",
        "hf/hub/models--mlx-community--whisper-large-v3-mlx/refs/main",
        "hf/hub/models--mlx-community--whisper-large-v3-mlx/snapshots/abc/weights.npz",
    ], "nur der Schnappschuss aus refs/main, keine Blobs, keine Sperren"


async def _audio_anlegen(ordner: Path, video_ids: list[str]) -> list[Audiodatei]:
    aus = []
    for i, vid in enumerate(video_ids):
        p = ordner / "audio" / f"{vid}.m4a"
        p.parent.mkdir(exist_ok=True)
        p.write_bytes(bytes([i]) * (700 + i))
        aus.append(Audiodatei(vid, p, p.stat().st_size))
    return aus


async def _erstelle(ordner: Path, monkeypatch: pytest.MonkeyPatch, mit_audio: bool = True) -> uebergabe.Uebergabeergebnis:
    bild = ordner / "bild.jpg"
    bild.write_bytes(b"\xff\xd8\xff\xe0JPEGPROBE")
    buch = ordner / "buch.epub"
    buch.write_bytes(b"PK\x03\x04EPUBPROBE")
    quelle = FakeQuelle(bild, buch)
    dateien = await _audio_anlegen(ordner, [quelle.v1.id, quelle.v2.id, "c" * 32])

    async def audiodateien() -> list[Audiodatei]:
        return dateien

    monkeypatch.setattr(uebergabe, "audiodateien", audiodateien)
    modelle = ordner / "modelle" / "hf" / "hub" / "models--org--modell" / "snapshots" / "rev"
    modelle.mkdir(parents=True)
    (modelle / "weights.npz").write_bytes(b"gewichte")
    meldungen: list[tuple[float, str]] = []

    async def melde(anteil: float, meldung: str) -> None:
        meldungen.append((anteil, meldung))

    ergebnis = await uebergabe.erstelle(
        quelle,
        ordner / "uebergaben",
        version="0.6.0",
        dimension=DIMENSION,
        mit_audio=mit_audio,
        mit_modellen=True,
        modelle_verzeichnis=ordner / "modelle",
        melde=melde,
        teil_bytes=1500,
    )
    assert meldungen[-1][0] == 1.0 and all(0 <= a <= 1 for a, _ in meldungen)
    return ergebnis


async def test_erstellen_schreibt_alle_teile(ordner: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ergebnis = await _erstelle(ordner, monkeypatch)
    m = ergebnis.manifest
    uuid.UUID(m.kennung)
    assert ergebnis.ordner.name == m.kennung
    namen = sorted(p.name for p in ergebnis.ordner.iterdir())
    erwartet = [uebergabe.MANIFEST, uebergabe.PRUEFSUMMEN, uebergabe.ANLEITUNG, m.bibliothek, "audio-01.tar", "audio-02.tar", "modelle.tar"]
    assert namen == sorted(erwartet)
    assert [t.art for t in m.teile] == ["bibliothek", "audio", "audio", "modelle"]
    assert m.audio_dateien == 3 and m.audio_bytes == 700 + 701 + 702 and m.modelle == ["org/modell"]
    assert m.zaehler.videos == 2 and m.zaehler.dokumente == 1
    for t in m.teile:
        pfad = ergebnis.ordner / t.name
        assert pfad.stat().st_size == t.bytes and hashlib.sha256(pfad.read_bytes()).hexdigest() == t.sha256
    pruefsummen = (ergebnis.ordner / uebergabe.PRUEFSUMMEN).read_text().splitlines()
    assert pruefsummen == [f"{t.sha256}  {t.name}" for t in m.teile]
    with tarfile.open(ergebnis.ordner / "audio-01.tar") as tar:
        assert tar.getnames() == [f"audio/{'video01' + '0' * 25}.m4a", f"audio/{'video02' + '0' * 25}.m4a"]
    with tarfile.open(ergebnis.ordner / "modelle.tar") as tar:
        assert tar.getnames() == ["hf/hub/models--org--modell/snapshots/rev/weights.npz"]
    anleitung = (ergebnis.ordner / uebergabe.ANLEITUNG).read_text()
    assert m.kennung in anleitung and "Übergabe holen" in anleitung and "Schlüssel" in anleitung
    assert uebergabe.vorhandene(ordner / "uebergaben")[0].kennung == m.kennung


async def test_erstellen_ohne_audio(ordner: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ergebnis = await _erstelle(ordner, monkeypatch, mit_audio=False)
    assert [t.art for t in ergebnis.manifest.teile] == ["bibliothek", "modelle"] and ergebnis.manifest.audio_dateien == 0


class _FakeSitzung:
    """Ersatz für die Datenbanksitzung beim Eintragen der Audiozeilen: kennt zwei Videos."""

    def __init__(self, video_ids: set[str]) -> None:
        self.video_ids = video_ids
        self.zeilen: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def get(self, _modell, video_id):
        if video_id in self.video_ids:

            class V:
                dauer_s = 1201

            return V()
        return None

    async def scalar(self, _stmt):
        return None

    def add(self, zeile):
        self.zeilen.append(zeile)

    async def commit(self):
        return None


async def _hole(
    ordner: Path, herkunft: holen.Herkunft, sitzung: _FakeSitzung, monkeypatch: pytest.MonkeyPatch
) -> tuple[holen.Holergebnis, FakeZiel]:
    monkeypatch.setattr(holen, "sitzung", lambda: sitzung)
    ziel = FakeZiel(ordner)

    async def ziel_bauen():
        async def schliessen() -> None:
            return None

        return ziel, schliessen

    ergebnis = await holen.hole(
        herkunft,
        ziel_bauen=ziel_bauen,
        erwartete_dimension=DIMENSION,
        audio_verzeichnis=ordner / "ziel-audio",
        modelle_verzeichnis=ordner / "ziel-modelle",
    )
    return ergebnis, ziel


async def test_holen_aus_ordner(ordner: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    erstellt = await _erstelle(ordner, monkeypatch)
    v1, v2 = "video01" + "0" * 25, "video02" + "0" * 25
    sitzung = _FakeSitzung({v1, v2})
    ergebnis, ziel = await _hole(ordner, holen.OrdnerHerkunft(erstellt.ordner), sitzung, monkeypatch)
    assert ergebnis.kennung == erstellt.manifest.kennung and ergebnis.version == "0.6.0"
    assert ergebnis.bibliothek.videos_neu == 2 and ergebnis.bibliothek.dokumente_neu == 1 and ziel.abgeschlossen
    assert ergebnis.audio_dateien == 2 and ergebnis.audio_neu == 2, "die Datei ohne Video wird abgelegt, aber nicht eingetragen"
    assert sorted(p.name for p in (ordner / "ziel-audio").iterdir()) == sorted([f"{v1}.m4a", f"{v2}.m4a", "c" * 32 + ".m4a"])
    assert (ordner / "ziel-audio" / f"{v1}.m4a").read_bytes() == bytes([0]) * 700
    assert [z.video_id for z in sitzung.zeilen] == [v1, v2] and sitzung.zeilen[0].dauer_s == 1201.0
    gewichte = ordner / "ziel-modelle" / "hf/hub/models--org--modell/snapshots/rev/weights.npz"
    assert ergebnis.modelle_dateien == 1 and gewichte.read_bytes() == b"gewichte"
    assert ergebnis.geladen_bytes == erstellt.manifest.gesamt_bytes
    assert (erstellt.ordner / uebergabe.MANIFEST).is_file(), "aus einem Ordner wird nichts gelöscht"


def _webserver(ordner: Path, abbruch_nach: dict[str, int]) -> httpx.MockTransport:
    """Liefert die Dateien des Ordners; unterstützt Bereiche und bricht auf Wunsch einmal mitten im Teil ab."""

    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        pfad = ordner / name
        if not pfad.is_file():
            return httpx.Response(404)
        daten = pfad.read_bytes()
        bereich = request.headers.get("Range")
        if bereich:
            start = int(bereich.removeprefix("bytes=").rstrip("-"))
            return httpx.Response(206, content=daten[start:])
        grenze = abbruch_nach.pop(name, None)
        if grenze is not None:
            return httpx.Response(200, content=daten[:grenze])  # zu kurz: der Leser muss es merken
        return httpx.Response(200, content=daten)

    return httpx.MockTransport(handler)


async def test_holen_ueber_web_mit_fortsetzen(ordner: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    erstellt = await _erstelle(ordner, monkeypatch)
    v1 = "video01" + "0" * 25
    eingang = ordner / "eingang"
    transport = _webserver(erstellt.ordner, {"audio-01.tar": 900})
    herkunft = holen.WebHerkunft(f"http://ablage/morf/{erstellt.manifest.kennung}", eingang, transport=transport)
    sitzung = _FakeSitzung({v1})
    with pytest.raises(uebergabe.UebergabeFehler, match="statt .* Byte geladen"):
        await _hole(ordner, herkunft, sitzung, monkeypatch)
    assert not list((eingang / erstellt.manifest.kennung).glob("audio-01.tar*")), "ein zu kurzer Teil wird verworfen"

    herkunft = holen.WebHerkunft(f"http://ablage/morf/{erstellt.manifest.kennung}/", eingang, transport=_webserver(erstellt.ordner, {}))
    ergebnis, _ = await _hole(ordner, herkunft, _FakeSitzung({v1}), monkeypatch)
    assert ergebnis.audio_dateien == 1 and ergebnis.bibliothek.videos_neu == 2
    assert not (eingang / erstellt.manifest.kennung).exists(), "der Eingang wird nach dem Holen aufgeräumt"


async def test_holen_erkennt_falsche_pruefsumme(ordner: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    erstellt = await _erstelle(ordner, monkeypatch, mit_audio=False)
    (erstellt.ordner / "modelle.tar").write_bytes(b"kaputt")
    with pytest.raises(uebergabe.UebergabeFehler, match="Prüfsumme stimmt nicht"):
        await _hole(ordner, holen.OrdnerHerkunft(erstellt.ordner), _FakeSitzung(set()), monkeypatch)


def test_herkunft_und_namen(ordner: Path) -> None:
    assert isinstance(holen.herkunft_fuer("https://x.de/a/", ordner), holen.WebHerkunft)
    assert isinstance(holen.herkunft_fuer(str(ordner), ordner), holen.OrdnerHerkunft)
    with pytest.raises(uebergabe.UebergabeFehler):
        holen.herkunft_fuer("/gibt/es/nicht", ordner)
    with pytest.raises(uebergabe.UebergabeFehler):
        holen.pruefe_teilname("../etc/passwd")
    with pytest.raises(uebergabe.UebergabeFehler):
        uebergabe.pruefe_kennung("nicht-uuid")
