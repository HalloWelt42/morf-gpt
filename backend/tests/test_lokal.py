"""Tests für lokale Dateien als Videoquelle und die Handpflege von Videofeldern (keine Datenbank, kein ffmpeg)."""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.db.modelle import Quelle, Video
from app.dienste.quellen import abgleich, lokal
from app.dienste.quellen.basis import QuellenFehler, alle_seiten

TEST_WURZEL = Path(__file__).resolve().parents[1] / ".test-tmp"


@pytest.fixture
def ordner() -> Iterator[Path]:
    pfad = TEST_WURZEL / f"lokal-{uuid.uuid4().hex}"
    (pfad / "unterordner").mkdir(parents=True)
    (pfad / ".versteckt").mkdir()
    (pfad / "Vortrag_ueber_Zeit.mp4").write_bytes(b"x")
    (pfad / "unterordner" / "B_Folge.m4a").write_bytes(b"x")
    (pfad / "unterordner" / "notizen.txt").write_bytes(b"x")
    (pfad / ".versteckt" / "geheim.mp4").write_bytes(b"x")
    (pfad / "Vortrag_ueber_Zeit.info.json").write_text(
        json.dumps({"title": "Über die Zeit | mmM#12", "upload_date": "20240301", "webpage_url": "https://youtu.be/abc", "tags": ["zeit", " "], "duration": 900}),
        encoding="utf-8",
    )
    try:
        yield pfad
    finally:
        shutil.rmtree(pfad, ignore_errors=True)


async def keine_dauer(_pfad: Path) -> float | None:
    return None


async def feste_dauer(_pfad: Path) -> float | None:
    return 123.0


def test_endungen_parsen_und_vorgabe() -> None:
    assert lokal.endungen_parsen("MP4, .mkv ,, m4a") == frozenset({".mp4", ".mkv", ".m4a"})
    assert ".mp3" in lokal.endungen_parsen("")


def test_kennung_stabil_und_kurz() -> None:
    a = lokal.kennung_aus_pfad("unterordner/B_Folge.m4a")
    assert a == lokal.kennung_aus_pfad("unterordner/B_Folge.m4a")
    assert a != lokal.kennung_aus_pfad("B_Folge.m4a")
    assert a.startswith("datei-") and len(a) <= 64


def test_titel_aus_dateiname() -> None:
    assert lokal.titel_aus_dateiname("2024-03-01_Vortrag_ueber_Zeit.mp4") == "2024-03-01 Vortrag ueber Zeit"


def test_dateien_auflisten_sortiert_und_ohne_versteckte(ordner: Path) -> None:
    dateien = lokal.dateien_auflisten(ordner, lokal.endungen_parsen(""))
    relativ = [str(d.relative_to(ordner)) for d in dateien]
    assert relativ == ["unterordner/B_Folge.m4a", "Vortrag_ueber_Zeit.mp4"]


async def test_videoseite_mit_beiblatt_und_dateiname(ordner: Path) -> None:
    quelle = lokal.LokaleDateien(str(ordner), lokal.endungen_parsen(""), dauersonde=keine_dauer)
    kanal = await quelle.kanal()
    assert kanal.videos_gesamt == 2 and kanal.name == ordner.name
    seite = await quelle.videoseite(1, 50)
    assert seite.gesamt == 2
    mit_beiblatt = next(v for v in seite.videos if v.roh["pfad"] == "Vortrag_ueber_Zeit.mp4")
    assert mit_beiblatt.titel == "Über die Zeit | mmM#12"
    assert mit_beiblatt.original_url == "https://youtu.be/abc"
    assert mit_beiblatt.dauer_s == 900
    assert mit_beiblatt.schlagworte == ["zeit"]
    assert mit_beiblatt.veroeffentlicht is not None and mit_beiblatt.veroeffentlicht.year == 2024
    assert mit_beiblatt.heruntergeladen is True
    ohne = next(v for v in seite.videos if v.roh["pfad"].endswith("B_Folge.m4a"))
    assert ohne.titel == "B Folge"
    assert ohne.original_url == ""
    assert ohne.veroeffentlicht is not None  # Änderungsdatum der Datei


async def test_seitenlauf_und_dauer_per_sonde(ordner: Path) -> None:
    quelle = lokal.LokaleDateien(str(ordner), lokal.endungen_parsen(""), dauersonde=feste_dauer)
    gesehen = [v.extern_id async for seite in alle_seiten(quelle, 1) for v in seite.videos]
    assert len(gesehen) == 2 and len(set(gesehen)) == 2
    ohne_beiblatt = quelle.datei(lokal.kennung_aus_pfad("unterordner/B_Folge.m4a"))
    assert ohne_beiblatt.name == "B_Folge.m4a"
    seite = await quelle.videoseite(1, 50)
    assert next(v for v in seite.videos if v.roh["pfad"].endswith("m4a")).dauer_s == 123


async def test_fehlendes_verzeichnis_und_kennung(ordner: Path) -> None:
    with pytest.raises(QuellenFehler):
        await lokal.LokaleDateien(str(ordner / "gibt-es-nicht"), lokal.endungen_parsen("")).kanal()
    with pytest.raises(QuellenFehler):
        lokal.datei_finden(str(ordner), "datei-unbekannt", lokal.endungen_parsen(""))
    assert lokal.datei_finden(str(ordner), lokal.kennung_aus_pfad("Vortrag_ueber_Zeit.mp4"), lokal.endungen_parsen("")).name == "Vortrag_ueber_Zeit.mp4"


def test_baue_quelle_kennt_beide_typen() -> None:
    werte = {"quelle.dateiendungen": "mp4", "quelle.zeitgrenze_s": 5}
    assert isinstance(abgleich.baue_quelle("lokal", "/tmp", "", werte), lokal.LokaleDateien)
    with pytest.raises(QuellenFehler):
        abgleich.baue_quelle("tubevault", "http://x", "", werte)
    with pytest.raises(QuellenFehler):
        abgleich.baue_quelle("fremd", "http://x", "k", werte)


def _quelle() -> Quelle:
    return Quelle(id="q1", typ="lokal", name="Ordner", basis_url="/x", kanal_id="", kanal_name="Ordner")


async def test_handpflege_haelt_felder_gegen_abgleich(ordner: Path) -> None:
    quelle = lokal.LokaleDateien(str(ordner), lokal.endungen_parsen(""), dauersonde=keine_dauer)
    qv = next(v for v in (await quelle.videoseite(1, 50)).videos if v.roh["pfad"].endswith("m4a"))
    video = Video(id="v1", extern_id=qv.extern_id, titel="", felder_manuell=[], metadaten_original={}, schlagworte=[])
    assert abgleich.felder_uebernehmen(video, qv, _quelle()) is True
    assert video.titel == "B Folge" and video.original_url == ""
    video.titel = "Von Hand"
    video.original_url = "https://youtu.be/hand"
    video.felder_manuell = ["titel", "original_url"]
    abgleich.felder_uebernehmen(video, qv, _quelle())
    assert video.titel == "Von Hand" and video.original_url == "https://youtu.be/hand"
    video.felder_manuell = []
    abgleich.felder_uebernehmen(video, qv, _quelle())
    assert video.titel == "B Folge" and video.original_url == ""
