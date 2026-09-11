"""Unit-Tests für das Audio-Modul: Bezug, Stufe, Router (nur Fakes, kein Netz, keine Datenbank)."""

from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import einstellungen
from app.db.engine import sitzung_abhaengigkeit
from app.db.modelle import Audio, Quelle, Video
from app.dienste.audio import bezug
from app.dienste.stufen import audio as stufe_audio
from app.routers import audio as router_audio

TEST_WURZEL = Path(__file__).resolve().parents[1] / ".test-tmp"


# ------------------------------------------------------------------ Hilfen


@pytest.fixture
def ablage(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Eigenes Datenverzeichnis je Test unter backend/.test-tmp, wird danach entfernt."""
    verzeichnis = TEST_WURZEL / f"audio-{uuid.uuid4().hex[:8]}"
    verzeichnis.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(einstellungen, "daten_verzeichnis", verzeichnis)
    try:
        yield verzeichnis
    finally:
        shutil.rmtree(verzeichnis, ignore_errors=True)


class Fortschrittssammler:
    def __init__(self) -> None:
        self.meldungen: list[tuple[float, str]] = []

    async def __call__(self, anteil: float, meldung: str = "") -> None:
        self.meldungen.append((anteil, meldung))


async def _sonde_fake(pfad: Path) -> bezug.AudioEigenschaften:
    return bezug.AudioEigenschaften(dauer_s=12.5, abtastrate=24000, kanaele=1, groesse_bytes=pfad.stat().st_size)


async def _stueckstrom(inhalt: bytes) -> AsyncIterator[bytes]:
    yield inhalt[:400]
    yield inhalt[400:]


def _antwort_bytes(inhalt: bytes, mit_laenge: bool = True) -> httpx.Response:
    """Antwort mit Bytes; ohne Content-Length als Stückstrom (httpx setzt die Länge bei Bytes selbst)."""
    if mit_laenge:
        return httpx.Response(200, content=inhalt, headers={"content-length": str(len(inhalt))})
    return httpx.Response(200, content=_stueckstrom(inhalt))


# ------------------------------------------------------------------ Range-Parsing


@pytest.mark.parametrize(
    ("kopf", "erwartet"),
    [
        ("bytes=0-99", (0, 99)),
        ("bytes=100-", (100, 999)),
        ("bytes=-100", (900, 999)),
        ("bytes=0-5000", (0, 999)),
        ("bytes=-5000", (0, 999)),
        ("bytes=10-20, 30-40", (10, 20)),
        ("BYTES = 5-5", (5, 5)),
    ],
)
def test_bereich_parsen_gueltig(kopf: str, erwartet: tuple[int, int]) -> None:
    bereich = router_audio.bereich_parsen(kopf, 1000)
    assert bereich is not None
    assert (bereich.start, bereich.ende) == erwartet
    assert bereich.gesamt == 1000
    assert bereich.laenge == erwartet[1] - erwartet[0] + 1
    assert bereich.content_range() == f"bytes {erwartet[0]}-{erwartet[1]}/1000"


@pytest.mark.parametrize("kopf", [None, "", "items=0-9", "bytes=", "bytes=-", "bytes=abc-def", "bytes=12", "bytes=1x-5"])
def test_bereich_parsen_unverstaendlich_liefert_ganze_datei(kopf: str | None) -> None:
    assert router_audio.bereich_parsen(kopf, 1000) is None


@pytest.mark.parametrize(
    ("kopf", "gesamt"),
    [
        ("bytes=1000-", 1000),
        ("bytes=1500-1600", 1000),
        ("bytes=50-10", 1000),
        ("bytes=-0", 1000),
        ("bytes=0-", 0),
    ],
)
def test_bereich_parsen_nicht_erfuellbar(kopf: str, gesamt: int) -> None:
    with pytest.raises(router_audio.BereichNichtErfuellbar):
        router_audio.bereich_parsen(kopf, gesamt)


# ------------------------------------------------------------------ ffmpeg und ffprobe


def test_ffmpeg_kommandozeile() -> None:
    kommando = bezug.ffmpeg_kommandozeile("/pfad/ffmpeg", Path("/tmp/in.mp4"), Path("/tmp/out.m4a"), bezug.Wandlung(24000, 64))
    assert kommando[0] == "/pfad/ffmpeg"
    assert kommando[-1] == "/tmp/out.m4a"
    text = " ".join(kommando)
    assert "-i /tmp/in.mp4" in text
    assert "-vn -ac 1 -ar 24000 -c:a aac -b:a 64k -movflags +faststart" in text
    assert "-progress pipe:1" in text
    assert kommando.index("-i") < kommando.index("-vn")


def test_ffmpeg_zeit_aus_zeile() -> None:
    assert bezug.ffmpeg_zeit_aus_zeile("out_time_us=1500000\n") == 1.5
    assert bezug.ffmpeg_zeit_aus_zeile("frame=12") is None
    assert bezug.ffmpeg_zeit_aus_zeile("out_time_us=N/A") is None


def test_eigenschaften_aus_ffprobe() -> None:
    daten = {
        "format": {"duration": "123.456", "size": "999"},
        "streams": [
            {"codec_type": "video", "sample_rate": "0"},
            {"codec_type": "audio", "sample_rate": "24000", "channels": 1},
        ],
    }
    e = bezug.eigenschaften_aus_ffprobe(daten, 999)
    assert e.dauer_s == pytest.approx(123.456)
    assert e.abtastrate == 24000
    assert e.kanaele == 1
    assert e.groesse_bytes == 999


def test_eigenschaften_aus_ffprobe_leer() -> None:
    e = bezug.eigenschaften_aus_ffprobe({}, 0)
    assert e.dauer_s is None and e.abtastrate is None and e.kanaele is None


def test_werkzeug_pfad_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bezug.shutil, "which", lambda name: None)
    assert bezug.ffmpeg_pfad() == bezug.FFMPEG_FALLBACK
    assert bezug.ffprobe_pfad() == bezug.FFPROBE_FALLBACK
    monkeypatch.setattr(bezug.shutil, "which", lambda name: f"/usr/local/bin/{name}")
    assert bezug.ffmpeg_pfad() == "/usr/local/bin/ffmpeg"


async def test_ffmpeg_ausfuehren_fehler_mit_stderr(ablage: Path) -> None:
    """Ein Prozess mit Fehlercode liefert die letzten stderr-Zeilen in der Meldung."""
    skript = ablage / "fehler.sh"
    skript.write_text("#!/bin/sh\necho 'Zeile eins' 1>&2\necho 'Kaputt: Eingabe fehlt' 1>&2\nexit 3\n")
    skript.chmod(0o755)
    with pytest.raises(bezug.AudioBezugFehler, match="Code 3.*Kaputt: Eingabe fehlt"):
        await bezug.ffmpeg_ausfuehren([str(skript)], asyncio.Event())


async def test_ffmpeg_ausfuehren_abbruch_beendet_prozess(ablage: Path) -> None:
    """Das Abbruch-Ereignis beendet einen laufenden Prozess und wirft CancelledError."""
    skript = ablage / "lang.sh"
    marke = ablage / "beendet.txt"
    # Das Kind (sleep) wird mit beendet, sonst hielte es die Pipes offen.
    skript.write_text(f"#!/bin/sh\nsleep 30 &\nKIND=$!\ntrap 'kill $KIND; echo weg > {marke}; exit 0' TERM\nwait $KIND\n")
    skript.chmod(0o755)
    abbruch = asyncio.Event()
    asyncio.get_running_loop().call_later(0.3, abbruch.set)
    with pytest.raises(asyncio.CancelledError):
        await bezug.ffmpeg_ausfuehren([str(skript)], abbruch)
    await asyncio.sleep(0.2)
    assert marke.exists()


async def test_ffmpeg_ausfuehren_meldet_fortschritt(ablage: Path) -> None:
    skript = ablage / "fortschritt.sh"
    skript.write_text("#!/bin/sh\necho out_time_us=5000000\necho out_time_us=10000000\nexit 0\n")
    skript.chmod(0o755)
    sammler = Fortschrittssammler()
    await bezug.ffmpeg_ausfuehren([str(skript)], asyncio.Event(), sammler, erwartete_dauer_s=10.0, von=0.5, bis=1.0)
    assert [round(a, 2) for a, _ in sammler.meldungen] == [0.75, 1.0]
    assert "0:05 von 0:10" in sammler.meldungen[0][1]


# ------------------------------------------------------------------ Strom in Datei (MockTransport)


async def test_stream_zu_datei_mit_fortschritt(ablage: Path) -> None:
    inhalt = bytes(range(256)) * 4096  # 1 Megabyte
    transport = httpx.MockTransport(lambda anfrage: _antwort_bytes(inhalt))
    ziel = ablage / "tmp" / "video.mp4"
    sammler = Fortschrittssammler()
    async with httpx.AsyncClient(transport=transport) as client:
        anzahl = await bezug.stream_zu_datei(
            client,
            "http://quelle/api/player/x",
            ziel,
            sammler,
            asyncio.Event(),
            von=0.0,
            bis=0.7,
            meldung="Hole Video",
        )
    assert anzahl == len(inhalt)
    assert ziel.read_bytes() == inhalt
    anteile = [a for a, _ in sammler.meldungen]
    assert anteile == sorted(anteile)
    assert anteile[-1] == pytest.approx(0.7)
    assert sammler.meldungen[-1][1] == "Hole Video: 1,0 von 1,0 Megabyte"


async def test_stream_zu_datei_ohne_content_length(ablage: Path) -> None:
    inhalt = b"x" * 1000
    transport = httpx.MockTransport(lambda anfrage: _antwort_bytes(inhalt, mit_laenge=False))
    ziel = ablage / "ohne.bin"
    sammler = Fortschrittssammler()
    async with httpx.AsyncClient(transport=transport) as client:
        await bezug.stream_zu_datei(client, "http://quelle/x", ziel, sammler, asyncio.Event(), von=0.2, bis=0.9)
    assert ziel.read_bytes() == inhalt
    assert all(a == pytest.approx(0.2) for a, _ in sammler.meldungen)


async def test_stream_zu_datei_http_fehler_loescht_teildatei(ablage: Path) -> None:
    transport = httpx.MockTransport(lambda anfrage: httpx.Response(404, content=b"nicht da"))
    ziel = ablage / "fehlt.bin"
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(bezug.AudioBezugFehler, match="HTTP 404"):
            await bezug.stream_zu_datei(client, "http://quelle/x", ziel, Fortschrittssammler(), asyncio.Event())
    assert not ziel.exists()


async def test_stream_zu_datei_abbruch(ablage: Path) -> None:
    transport = httpx.MockTransport(lambda anfrage: _antwort_bytes(b"y" * 5000))
    ziel = ablage / "abbruch.bin"
    abbruch = asyncio.Event()
    abbruch.set()
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(asyncio.CancelledError):
            await bezug.stream_zu_datei(client, "http://quelle/x", ziel, Fortschrittssammler(), abbruch)
    assert not ziel.exists()


async def test_stream_zu_datei_unvollstaendig(ablage: Path) -> None:
    def kurz(anfrage: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"nur die Haelfte", headers={"content-length": "999"})

    ziel = ablage / "kurz.bin"
    async with httpx.AsyncClient(transport=httpx.MockTransport(kurz)) as client:
        with pytest.raises((bezug.AudioBezugFehler, httpx.HTTPError)):
            await bezug.stream_zu_datei(client, "http://quelle/x", ziel, Fortschrittssammler(), asyncio.Event())
    assert not ziel.exists()


# ------------------------------------------------------------------ Bezugswege


def test_waehle_bezug() -> None:
    w = bezug.Wandlung(24000, 64)
    assert isinstance(bezug.waehle_bezug("videostrom_ffmpeg", w), bezug.VideostromFfmpeg)
    assert isinstance(bezug.waehle_bezug("quelle_extraktion", w), bezug.QuellExtraktion)
    with pytest.raises(bezug.AudioBezugFehler, match="Unbekannter Bezugsweg 'irgendwas'"):
        bezug.waehle_bezug("irgendwas", w)


def test_adressen() -> None:
    assert bezug.video_url("http://pi:8031/", "abc") == "http://pi:8031/api/player/abc"
    assert bezug.extraktions_url("http://pi:8031", "abc") == "http://pi:8031/api/player/abc/audio/extract"
    assert bezug.audio_url("http://pi:8031", "abc") == "http://pi:8031/api/player/abc/audio"


def test_pfad_speicherform_und_aufloesen(ablage: Path) -> None:
    ziel = bezug.ziel_pfad("v1")
    assert ziel == ablage / "audio" / "v1.m4a"
    gespeichert = bezug.pfad_speicherform(ziel)
    assert gespeichert == "audio/v1.m4a"
    assert bezug.pfad_aufloesen(gespeichert) == ziel
    assert bezug.pfad_aufloesen("/anderswo/x.m4a") == Path("/anderswo/x.m4a")
    assert bezug.teil_pfad(ziel).name == "v1.teil.m4a"


async def test_quell_extraktion_mit_mock_transport(ablage: Path) -> None:
    audio_bytes = b"m4a-inhalt" * 100
    aufrufe: list[str] = []

    def quelle(anfrage: httpx.Request) -> httpx.Response:
        aufrufe.append(f"{anfrage.method} {anfrage.url}")
        if anfrage.method == "POST" and anfrage.url.path.endswith("/audio/extract"):
            assert anfrage.url.params["format"] == "m4a"
            return httpx.Response(
                200,
                json={
                    "video_id": "abc",
                    "format": "m4a",
                    "path": "/pi/abc.m4a",
                    "file_size": len(audio_bytes),
                },
            )
        if anfrage.method == "GET" and anfrage.url.path.endswith("/audio"):
            return _antwort_bytes(audio_bytes)
        return httpx.Response(404)

    weg = bezug.QuellExtraktion(sonde=_sonde_fake, transport=httpx.MockTransport(quelle))
    ziel = bezug.ziel_pfad("v2")
    sammler = Fortschrittssammler()
    ergebnis = await weg.beschaffe("http://pi:8031", "abc", ziel, sammler, asyncio.Event())
    assert aufrufe == [
        "POST http://pi:8031/api/player/abc/audio/extract?format=m4a",
        "GET http://pi:8031/api/player/abc/audio",
    ]
    assert ziel.read_bytes() == audio_bytes
    assert not bezug.teil_pfad(ziel).exists()
    assert ergebnis.bezugsweg == "quelle_extraktion"
    assert ergebnis.eigenschaften.groesse_bytes == len(audio_bytes)
    assert sammler.meldungen[0] == (0.05, "Quelle extrahiert das Audio")


async def test_quell_extraktion_fehler_der_quelle(ablage: Path) -> None:
    transport = httpx.MockTransport(lambda anfrage: httpx.Response(500, content=b"ffmpeg kaputt"))
    weg = bezug.QuellExtraktion(sonde=_sonde_fake, transport=transport)
    with pytest.raises(bezug.AudioBezugFehler, match="HTTP 500"):
        await weg.beschaffe("http://pi:8031", "abc", bezug.ziel_pfad("v3"), Fortschrittssammler(), asyncio.Event())


async def test_videostrom_ffmpeg_mit_fake_ffmpeg(ablage: Path) -> None:
    """Der Videostrom landet in tmp, ein Fake-ffmpeg schreibt das Ziel, tmp wird geräumt."""
    video_bytes = b"mp4" * 5000
    fake_ffmpeg = ablage / "ffmpeg.sh"
    # Letztes Argument ist das Ziel: dorthin den Inhalt der Eingabe (nach -i) kopieren.
    fake_ffmpeg.write_text(
        '#!/bin/sh\nwhile [ $# -gt 1 ]; do if [ "$1" = "-i" ]; then EIN="$2"; fi; shift; done\ncp "$EIN" "$1"\necho out_time_us=1000000\n'
    )
    fake_ffmpeg.chmod(0o755)
    transport = httpx.MockTransport(lambda anfrage: _antwort_bytes(video_bytes))
    weg = bezug.VideostromFfmpeg(
        bezug.Wandlung(24000, 64),
        ffmpeg=str(fake_ffmpeg),
        sonde=_sonde_fake,
        transport=transport,
    )
    ziel = bezug.ziel_pfad("v4")
    sammler = Fortschrittssammler()
    ergebnis = await weg.beschaffe("http://pi:8031", "abc", ziel, sammler, asyncio.Event(), erwartete_dauer_s=2.0)
    assert ziel.read_bytes() == video_bytes
    assert ergebnis.bezugsweg == "videostrom_ffmpeg"
    assert list(bezug.temp_verzeichnis().iterdir()) == []
    assert not bezug.teil_pfad(ziel).exists()
    assert (0.7, "Wandle in Audio") in sammler.meldungen
    assert any(m.startswith("Wandle in Audio: 0:01 von 0:02") for _, m in sammler.meldungen)


async def test_videostrom_ffmpeg_fehler_raeumt_auf(ablage: Path) -> None:
    fake_ffmpeg = ablage / "ffmpeg-kaputt.sh"
    fake_ffmpeg.write_text("#!/bin/sh\necho 'Invalid data found' 1>&2\nexit 1\n")
    fake_ffmpeg.chmod(0o755)
    transport = httpx.MockTransport(lambda anfrage: _antwort_bytes(b"kaputt"))
    weg = bezug.VideostromFfmpeg(bezug.Wandlung(16000, 48), ffmpeg=str(fake_ffmpeg), sonde=_sonde_fake, transport=transport)
    ziel = bezug.ziel_pfad("v5")
    with pytest.raises(bezug.AudioBezugFehler, match="Invalid data found"):
        await weg.beschaffe("http://pi:8031", "abc", ziel, Fortschrittssammler(), asyncio.Event())
    assert not ziel.exists()
    assert not bezug.teil_pfad(ziel).exists()
    assert list(bezug.temp_verzeichnis().iterdir()) == []


# ------------------------------------------------------------------ Stufe (Fake-Kontext, Fake-Sitzung)


class FakeErgebnis:
    def __init__(self, wert: Any) -> None:
        self._wert = wert

    def scalar_one_or_none(self) -> Any:
        return self._wert


@dataclass
class FakeSitzung:
    objekte: dict[tuple[type, str], Any]
    audio: Audio | None = None
    hinzugefuegt: list[Any] = field(default_factory=list)
    commits: int = 0
    geloescht: list[Any] = field(default_factory=list)

    async def get(self, modell: type, kennung: str) -> Any:
        return self.objekte.get((modell, kennung))

    async def execute(self, stmt: Any) -> FakeErgebnis:
        return FakeErgebnis(self.audio)

    def add(self, obj: Any) -> None:
        self.hinzugefuegt.append(obj)
        if isinstance(obj, Audio):
            self.audio = obj

    async def delete(self, obj: Any) -> None:
        self.geloescht.append(obj)
        if obj is self.audio:
            self.audio = None

    async def commit(self) -> None:
        self.commits += 1


def _fake_sitzung_kontext(fake: FakeSitzung) -> Any:
    class _Kontext:
        async def __aenter__(self) -> FakeSitzung:
            return fake

        async def __aexit__(self, *args: object) -> None:
            return None

    return lambda: _Kontext()


class FakeKontext:
    def __init__(self, video_id: str, werte: dict[str, Any]) -> None:
        self.auftrag_id = "a1"
        self.video_id = video_id
        self.werte = werte
        self.art = "audio"
        self.abbruch = asyncio.Event()
        self.protokolle: list[tuple[str, str]] = []
        self.fortschritte: list[tuple[float, str]] = []

    def wert(self, schluessel: str) -> Any:
        return self.werte[schluessel]

    async def protokoll(self, text: str, stufe: str = "info") -> None:
        self.protokolle.append((stufe, text))

    async def fortschritt(self, anteil: float, meldung: str = "") -> None:
        self.fortschritte.append((anteil, meldung))


class FakeBezug:
    kennung = "fake_weg"

    def __init__(self, inhalt: bytes = b"audio") -> None:
        self.inhalt = inhalt
        self.aufrufe: list[tuple[str, str]] = []

    async def beschaffe(
        self,
        basis_url: str,
        extern_id: str,
        ziel: Path,
        fortschritt: Any,
        abbruch: asyncio.Event,
        erwartete_dauer_s: float | None = None,
    ) -> bezug.AudioErgebnis:
        self.aufrufe.append((basis_url, extern_id))
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(self.inhalt)
        await fortschritt(0.5, "Fake")
        return bezug.AudioErgebnis(ziel, self.kennung, await _sonde_fake(ziel))


WERTE = {"audio.bezugsweg": "videostrom_ffmpeg", "audio.abtastrate": 24000, "audio.bitrate_kbit": 64}


def _video_und_quelle() -> tuple[Video, Quelle]:
    quelle = Quelle(id="q1", typ="tubevault", name="TubeVault", basis_url="http://pi:8031", kanal_id="UC1")
    video = Video(id="v10", quelle_id="q1", extern_id="yt123", titel="Folge | mmM#1", dauer_s=600)
    return video, quelle


async def test_stufe_beschafft_und_schreibt_zeile(ablage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video, quelle = _video_und_quelle()
    fake = FakeSitzung({(Video, "v10"): video, (Quelle, "q1"): quelle})
    monkeypatch.setattr(stufe_audio, "sitzung", _fake_sitzung_kontext(fake))
    weg = FakeBezug()
    gewaehlt: list[tuple[str, bezug.Wandlung]] = []

    def waehle(bezugsweg: str, wandlung: bezug.Wandlung, **kw: Any) -> FakeBezug:
        gewaehlt.append((bezugsweg, wandlung))
        return weg

    monkeypatch.setattr(stufe_audio.bezug, "waehle_bezug", waehle)
    k = FakeKontext("v10", dict(WERTE))
    ergebnis = await stufe_audio.ausfuehren(k, {})  # type: ignore[arg-type]

    assert gewaehlt == [("videostrom_ffmpeg", bezug.Wandlung(24000, 64))]
    assert weg.aufrufe == [("http://pi:8031", "yt123")]
    assert ergebnis["pfad"] == "audio/v10.m4a"
    assert ergebnis["dauer_s"] == 12.5
    assert ergebnis["groesse_bytes"] == 5
    assert ergebnis["bezugsweg"] == "fake_weg"
    assert ergebnis["wiederverwendet"] is False
    assert fake.audio is not None and fake.audio.video_id == "v10" and fake.audio.abtastrate == 24000
    assert fake.commits == 1
    assert k.fortschritte[-1] == (1.0, "Audio bereit")


async def test_stufe_verwendet_vorhandene_datei(ablage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video, quelle = _video_und_quelle()
    vorhanden = Audio(id="alt", video_id="v10", pfad="audio/v10.m4a", bezugsweg="quelle_extraktion")
    fake = FakeSitzung({(Video, "v10"): video, (Quelle, "q1"): quelle}, audio=vorhanden)
    monkeypatch.setattr(stufe_audio, "sitzung", _fake_sitzung_kontext(fake))
    monkeypatch.setattr(stufe_audio.bezug, "ffprobe_eigenschaften", _sonde_fake)

    def nie(*args: Any, **kw: Any) -> Any:
        raise AssertionError("Bezug darf bei vorhandener Datei nicht gewählt werden")

    monkeypatch.setattr(stufe_audio.bezug, "waehle_bezug", nie)
    ziel = bezug.ziel_pfad("v10")
    ziel.parent.mkdir(parents=True)
    ziel.write_bytes(b"schon da")

    ergebnis = await stufe_audio.ausfuehren(FakeKontext("v10", dict(WERTE)), {})  # type: ignore[arg-type]
    assert ergebnis["wiederverwendet"] is True
    assert ergebnis["bezugsweg"] == "quelle_extraktion"
    assert fake.audio is vorhanden and vorhanden.groesse_bytes == 8 and vorhanden.dauer_s == 12.5
    assert fake.hinzugefuegt == []


async def test_stufe_erneut_erzwingt_bezug(ablage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video, quelle = _video_und_quelle()
    fake = FakeSitzung({(Video, "v10"): video, (Quelle, "q1"): quelle})
    monkeypatch.setattr(stufe_audio, "sitzung", _fake_sitzung_kontext(fake))
    weg = FakeBezug(b"neu")
    monkeypatch.setattr(stufe_audio.bezug, "waehle_bezug", lambda *a, **kw: weg)
    ziel = bezug.ziel_pfad("v10")
    ziel.parent.mkdir(parents=True)
    ziel.write_bytes(b"alt")
    k = FakeKontext("v10", dict(WERTE))
    ergebnis = await stufe_audio.ausfuehren(k, {"erneut": True})  # type: ignore[arg-type]
    assert ergebnis["wiederverwendet"] is False
    assert ziel.read_bytes() == b"neu"


async def test_stufe_ohne_quelle_meldet_fehler(ablage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = Video(id="v11", quelle_id=None, extern_id="x", titel="Ohne Quelle")
    fake = FakeSitzung({(Video, "v11"): video})
    monkeypatch.setattr(stufe_audio, "sitzung", _fake_sitzung_kontext(fake))
    with pytest.raises(RuntimeError, match="keine Quelle"):
        await stufe_audio.ausfuehren(FakeKontext("v11", dict(WERTE)), {})  # type: ignore[arg-type]


async def test_stufe_abbruch_vor_start(ablage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    k = FakeKontext("v10", dict(WERTE))
    k.abbruch.set()
    with pytest.raises(asyncio.CancelledError):
        await stufe_audio.ausfuehren(k, {})  # type: ignore[arg-type]


# ------------------------------------------------------------------ Router (TestClient, Fake-Sitzung)


@pytest.fixture
def client_mit_audio(ablage: Path) -> Iterator[tuple[TestClient, FakeSitzung, bytes]]:
    inhalt = bytes(range(256)) * 10  # 2560 Bytes
    ziel = bezug.ziel_pfad("v20")
    ziel.parent.mkdir(parents=True)
    ziel.write_bytes(inhalt)
    zeile = Audio(
        id="au1",
        video_id="v20",
        pfad="audio/v20.m4a",
        format="m4a",
        dauer_s=12.5,
        groesse_bytes=len(inhalt),
        abtastrate=24000,
        kanaele=1,
        bezugsweg="videostrom_ffmpeg",
    )
    fake = FakeSitzung({}, audio=zeile)

    async def fake_abhaengigkeit() -> Any:
        yield fake

    app = FastAPI()
    app.include_router(router_audio.router)
    app.dependency_overrides[sitzung_abhaengigkeit] = fake_abhaengigkeit
    with TestClient(app) as client:
        yield client, fake, inhalt


def test_router_ganze_datei(client_mit_audio: tuple[TestClient, FakeSitzung, bytes]) -> None:
    client, _, inhalt = client_mit_audio
    r = client.get("/audio/v20")
    assert r.status_code == 200
    assert r.content == inhalt
    assert r.headers["accept-ranges"] == "bytes"
    assert r.headers["content-type"] == "audio/mp4"
    assert r.headers["content-length"] == str(len(inhalt))
    assert "content-range" not in r.headers


def test_router_bereich(client_mit_audio: tuple[TestClient, FakeSitzung, bytes]) -> None:
    client, _, inhalt = client_mit_audio
    r = client.get("/audio/v20", headers={"Range": "bytes=100-199"})
    assert r.status_code == 206
    assert r.content == inhalt[100:200]
    assert r.headers["content-range"] == f"bytes 100-199/{len(inhalt)}"
    assert r.headers["content-length"] == "100"
    r = client.get("/audio/v20", headers={"Range": "bytes=2500-"})
    assert r.status_code == 206
    assert r.content == inhalt[2500:]
    r = client.get("/audio/v20", headers={"Range": "bytes=-60"})
    assert r.status_code == 206
    assert r.content == inhalt[-60:]


def test_router_bereich_nicht_erfuellbar(client_mit_audio: tuple[TestClient, FakeSitzung, bytes]) -> None:
    client, _, inhalt = client_mit_audio
    r = client.get("/audio/v20", headers={"Range": "bytes=99999-"})
    assert r.status_code == 416
    assert r.headers["content-range"] == f"bytes */{len(inhalt)}"


def test_router_if_range_veraltet(client_mit_audio: tuple[TestClient, FakeSitzung, bytes]) -> None:
    client, _, inhalt = client_mit_audio
    r = client.get("/audio/v20", headers={"Range": "bytes=0-9", "If-Range": '"veraltet"'})
    assert r.status_code == 200
    assert r.content == inhalt


def test_router_head(client_mit_audio: tuple[TestClient, FakeSitzung, bytes]) -> None:
    client, _, inhalt = client_mit_audio
    r = client.head("/audio/v20")
    assert r.status_code == 200
    assert r.headers["content-length"] == str(len(inhalt))
    assert r.content == b""


def test_router_info(client_mit_audio: tuple[TestClient, FakeSitzung, bytes]) -> None:
    client, _, inhalt = client_mit_audio
    r = client.get("/audio/v20/info")
    assert r.status_code == 200
    daten = r.json()
    assert daten["video_id"] == "v20"
    assert daten["mime"] == "audio/mp4"
    assert daten["vorhanden"] is True
    assert daten["groesse_bytes"] == len(inhalt)
    assert daten["bezugsweg"] == "videostrom_ffmpeg"


def test_router_unbekannt(client_mit_audio: tuple[TestClient, FakeSitzung, bytes]) -> None:
    client, fake, _ = client_mit_audio
    fake.audio = None
    assert client.get("/audio/v99").status_code == 404
    assert client.get("/audio/v99/info").status_code == 404
    assert client.delete("/audio/v99").status_code == 404


def test_router_datei_fehlt_auf_platte(client_mit_audio: tuple[TestClient, FakeSitzung, bytes]) -> None:
    client, _, _ = client_mit_audio
    bezug.ziel_pfad("v20").unlink()
    r = client.get("/audio/v20")
    assert r.status_code == 404
    assert "erneut beschaffen" in r.json()["detail"]
    assert client.get("/audio/v20/info").json()["vorhanden"] is False


def test_router_loeschen(client_mit_audio: tuple[TestClient, FakeSitzung, bytes]) -> None:
    client, fake, _ = client_mit_audio
    zeile = fake.audio
    r = client.delete("/audio/v20")
    assert r.status_code == 200
    daten = r.json()
    assert daten["datei_geloescht"] is True
    assert "Stufe des Videos bleibt unverändert" in daten["meldung"]
    assert not bezug.ziel_pfad("v20").exists()
    assert fake.geloescht == [zeile]
    assert fake.commits == 1


def test_stufe_ergebnis_ist_json_tauglich() -> None:
    """Das Ergebnis der Stufe landet als JSONB im Auftrag; nur einfache Typen."""
    beispiel = {
        "pfad": "audio/x.m4a",
        "dauer_s": 1.5,
        "groesse_bytes": 3,
        "bezugsweg": "videostrom_ffmpeg",
        "wiederverwendet": False,
    }
    assert json.loads(json.dumps(beispiel)) == beispiel
