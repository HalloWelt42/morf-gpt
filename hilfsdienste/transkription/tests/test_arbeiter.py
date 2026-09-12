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
        a, b = await asyncio.gather(
            pool.transkribiere(pool_ablage / "hallo_welt.wav", "de", True),
            pool.transkribiere(pool_ablage / "zweite_datei.wav", None, False),
        )
        dauer = time.monotonic() - start
        assert a.text == "hallo welt" and [w.wort for w in a.segmente[0].woerter] == ["hallo", "welt"]
        assert b.text == "zweite datei" and b.segmente[0].woerter == []
        assert dauer < 0.55, f"zwei Arbeiter sollten gleichzeitig arbeiten, gebraucht: {dauer:.2f} s"

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
        schnell = await pool.transkribiere(pool_ablage / "danach.wav", "de", False)
        assert schnell.text == "danach"
    finally:
        await pool.beenden_alle()


async def test_maximum_begrenzt():
    pool = Arbeiterpool(ATTRAPPE, maximum=1, reserve_gb=0, ladefrist_s=60)
    try:
        await pool.anpassen(3)
        assert pool.bereite() == 1 and pool.stand()["gewuenscht"] == 1
    finally:
        await pool.beenden_alle()
