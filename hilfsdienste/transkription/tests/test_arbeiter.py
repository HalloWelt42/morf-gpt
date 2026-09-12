import asyncio
import time
from pathlib import Path

import pytest

from app.arbeiter import ArbeiterFehler, Arbeiterpool
from app.engines.basis import EngineBeschreibung

ATTRAPPE = EngineBeschreibung(kennung="attrappe", modul="tests.attrappe", klasse="AttrappenEngine", argumente={"dauer_s": 0.3})
ABLAGE = Path(__file__).resolve().parent.parent / ".test-tmp"


@pytest.fixture
def pool_ablage() -> Path:
    ABLAGE.mkdir(exist_ok=True)
    return ABLAGE


async def test_pool_arbeitet_parallel_und_baut_ab(pool_ablage: Path):
    pool = Arbeiterpool(ATTRAPPE, maximum=4, reserve_gb=0, ladefrist_s=60)
    try:
        assert await pool.anpassen(2) == []
        assert pool.bereite() == 2
        start = time.monotonic()
        (a, wer_a), (b, wer_b) = await asyncio.gather(
            pool.transkribiere(pool_ablage / "hallo_welt.wav", "de", True),
            pool.transkribiere(pool_ablage / "zweite_datei.wav", None, False),
        )
        dauer = time.monotonic() - start
        assert a.text == "hallo welt" and [w.wort for w in a.segmente[0].woerter] == ["hallo", "welt"]
        assert b.text == "zweite datei" and b.segmente[0].woerter == []
        assert dauer < 0.55, f"zwei Arbeiter sollten gleichzeitig arbeiten, gebraucht: {dauer:.2f} s"
        assert wer_a.nummer != wer_b.nummer and wer_a.prozess.pid != wer_b.prozess.pid, "zwei verschiedene Prozesse"
        assert wer_a.zuletzt["datei"] == "hallo_welt.wav" and wer_a.zuletzt["fehler"] == "" and wer_a.aktuell is None

        await pool.anpassen(1)
        assert pool.bereite() == 1
        stand = pool.stand()
        assert stand["gewuenscht"] == 1 and len(stand["arbeiter"]) == 1 and stand["arbeiter"][0]["auftraege"] == 1
        assert stand["arbeiter"][0]["speicher_gb"] == 0.6, "der Speicher nach dem Auftrag kommt vom Arbeiter"

        with pytest.raises(ArbeiterFehler, match="unlesbar"):
            await pool.transkribiere(pool_ablage / "kaputt.wav", "de", True)
        assert pool.bereite() == 1, "ein Fehler in der Datei darf den Arbeiter nicht kosten"
    finally:
        await pool.beenden_alle()
    assert pool.bereite() == 0


async def test_pool_meldet_ladefehler():
    kaputt = EngineBeschreibung(kennung="attrappe", modul="tests.attrappe", klasse="AttrappenEngine", argumente={"laden_scheitert": True})
    pool = Arbeiterpool(kaputt, maximum=2, reserve_gb=0, ladefrist_s=60)
    hinweise = await pool.anpassen(1)
    assert hinweise and "Modell fehlt" in hinweise[0]
    assert pool.bereite() == 0
    with pytest.raises(ArbeiterFehler):
        await pool.transkribiere(Path("x.wav"), "de", True)
    await pool.beenden_alle()


async def test_abbruch_ersetzt_den_arbeiter(pool_ablage: Path):
    langsam = EngineBeschreibung(kennung="attrappe", modul="tests.attrappe", klasse="AttrappenEngine", argumente={"dauer_s": 5.0})
    pool = Arbeiterpool(langsam, maximum=2, reserve_gb=0, ladefrist_s=60)
    try:
        await pool.anpassen(1)
        alter_pid = pool.stand()["arbeiter"][0]["pid"]
        aufgabe = asyncio.create_task(pool.transkribiere(pool_ablage / "lang.wav", "de", True))
        await asyncio.sleep(0.3)
        start = time.monotonic()
        aufgabe.cancel()
        with pytest.raises(asyncio.CancelledError):
            await aufgabe
        assert time.monotonic() - start < 2, "der Abbruch wartet nicht auf das Ende der Transkription"
        assert pool._ersatz is not None
        await pool._ersatz
        stand = pool.stand()
        assert pool.bereite() == 1 and stand["arbeiter"][0]["pid"] != alter_pid, "ein neuer Arbeiter ersetzt den abgebrochenen"
        schnell, _ = await pool.transkribiere(pool_ablage / "danach.wav", "de", False)
        assert schnell.text == "danach"
    finally:
        await pool.beenden_alle()


async def test_zwischenstand_und_warteposition(pool_ablage: Path):
    langsam = EngineBeschreibung(kennung="attrappe", modul="tests.attrappe", klasse="AttrappenEngine", argumente={"dauer_s": 3.0})
    pool = Arbeiterpool(langsam, maximum=1, reserve_gb=0, ladefrist_s=60)
    try:
        await pool.anpassen(1)
        erster = asyncio.create_task(pool.transkribiere(pool_ablage / "erster.wav", "de", False, kennung="a-1"))
        zweiter = asyncio.create_task(pool.transkribiere(pool_ablage / "zweiter.wav", "de", False, kennung="a-2"))
        await asyncio.sleep(1.6)
        laeuft = pool.auftrag_stand("a-1")
        assert laeuft["zustand"] == "laeuft" and laeuft["arbeiter"] == 1 and laeuft["audio_s"] == 60.0
        assert laeuft["verarbeitet_s"] >= 20.0 and 0 < laeuft["anteil"] < 1, laeuft
        wartet = pool.auftrag_stand("a-2")
        assert wartet == {"zustand": "wartet", "position": 1, "wartend": 1}
        assert pool.stand()["arbeiter"][0]["aktuell"]["anteil"] == laeuft["anteil"]
        await erster
        await zweiter
        assert pool.auftrag_stand("a-1")["zustand"] == "unbekannt" and pool.stand()["wartend"] == 0
    finally:
        await pool.beenden_alle()


async def test_maximum_begrenzt():
    pool = Arbeiterpool(ATTRAPPE, maximum=1, reserve_gb=0, ladefrist_s=60)
    try:
        await pool.anpassen(3)
        assert pool.bereite() == 1 and pool.stand()["gewuenscht"] == 1
    finally:
        await pool.beenden_alle()
