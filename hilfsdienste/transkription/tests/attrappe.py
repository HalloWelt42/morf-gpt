"""Engine-Attrappe für Tests: lädt sofort, transkribiert nach kurzer Wartezeit aus dem Dateinamen."""

from __future__ import annotations

import time
from pathlib import Path

from app.engines.basis import Rohtranskript, Segment, Wort


class AttrappenEngine:
    kennung = "attrappe"

    def __init__(self, modell: str = "attrappe", dauer_s: float = 0.3, laden_scheitert: bool = False) -> None:
        self.modell = modell
        self._dauer_s = dauer_s
        self._laden_scheitert = laden_scheitert

    def laden(self) -> None:
        if self._laden_scheitert:
            raise RuntimeError("Modell fehlt")

    def groesse_gb(self) -> float:
        return 0.5

    def speicher_gb(self) -> float:
        return 0.6

    def transkribiere(self, pfad: Path, sprache_code: str | None, wortzeiten: bool) -> Rohtranskript:
        time.sleep(self._dauer_s)
        if "kaputt" in pfad.name:
            raise ValueError("unlesbar")
        text = pfad.stem.split("-", 1)[-1].replace("_", " ")
        woerter = [Wort(w, i * 0.5, i * 0.5 + 0.4) for i, w in enumerate(text.split())] if wortzeiten else []
        return Rohtranskript(text=text, segmente=[Segment(0.0, 2.0, text, woerter)], sprache=sprache_code or "de", modell=self.modell)
