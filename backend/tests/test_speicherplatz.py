from pathlib import Path

from app.dienste.speicherplatz import messen, verzeichnis_messen

ABLAGE = Path(__file__).resolve().parent / ".." / ".test-tmp" / "speicherplatz"


def test_messung_nach_bereichen():
    wurzel = ABLAGE.resolve()
    for unter in ("audio", "modelle/hf", "tmp/transkription"):
        (wurzel / unter).mkdir(parents=True, exist_ok=True)
    (wurzel / "audio" / "a.m4a").write_bytes(b"x" * 1000)
    (wurzel / "audio" / "b.m4a").write_bytes(b"x" * 500)
    (wurzel / "modelle" / "hf" / "w.npz").write_bytes(b"x" * 2000)
    (wurzel / "notiz.txt").write_bytes(b"x" * 10)
    assert verzeichnis_messen(wurzel / "audio") == (1500, 2)
    s = messen(wurzel)
    je = {b.kennung: b for b in s.bereiche}
    assert je["audio"].bytes == 1500 and je["audio"].dateien == 2
    assert je["modelle"].bytes == 2000 and je["tmp"].bytes == 0 and je["export"].bytes == 0
    assert je["sonstiges"].bytes == 10 and je["sonstiges"].dateien == 1
    assert s.gesamt_bytes == 3510 and s.platte_gesamt_bytes > 0
    d = s.als_dict()
    assert d["gesamt_bytes"] == 3510 and "_stand" not in d and d["gemessen"]
