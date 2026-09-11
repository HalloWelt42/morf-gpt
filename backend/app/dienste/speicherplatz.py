"""Speicherplatz des Projekts auf der Platte: das Datenverzeichnis, aufgeschlüsselt nach Bereichen.

Gemessen wird durch Ablaufen der Verzeichnisse (in einem Thread, weil viele Dateien);
das Ergebnis bleibt kurz zwischengespeichert, damit die Oberfläche nicht jede Anzeige
neu zählt. Unlesbare Einträge zählen nicht und brechen die Messung nicht ab.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config import einstellungen

ZWISCHENSPEICHER_S = 60.0

# Bereiche des Datenverzeichnisses in Anzeigereihenfolge: (Kennung, Titel, Unterverzeichnis)
BEREICHE: tuple[tuple[str, str, str], ...] = (
    ("audio", "Audio (Werkstatt)", "audio"),
    ("postgres", "Datenbank", "postgres"),
    ("modelle", "Modelle", "modelle"),
    ("dokumente", "Dokumente", "dokumente"),
    ("miniaturen", "Vorschaubilder", "miniaturen"),
    ("export", "Umzugspakete", "export"),
    ("tmp", "Zwischenablage", "tmp"),
)


@dataclass(slots=True)
class Bereich:
    kennung: str
    titel: str
    pfad: str
    bytes: int
    dateien: int

    def als_dict(self) -> dict[str, Any]:
        return {"kennung": self.kennung, "titel": self.titel, "pfad": self.pfad, "bytes": self.bytes, "dateien": self.dateien}


@dataclass(slots=True)
class Speicherplatz:
    gesamt_bytes: int
    bereiche: list[Bereich]
    gemessen: str
    dauer_ms: int
    verzeichnis: str
    platte_frei_bytes: int = 0
    platte_gesamt_bytes: int = 0
    _stand: float = field(default=0.0, repr=False)

    def als_dict(self) -> dict[str, Any]:
        return {
            "gesamt_bytes": self.gesamt_bytes,
            "bereiche": [b.als_dict() for b in self.bereiche],
            "gemessen": self.gemessen,
            "dauer_ms": self.dauer_ms,
            "verzeichnis": self.verzeichnis,
            "platte_frei_bytes": self.platte_frei_bytes,
            "platte_gesamt_bytes": self.platte_gesamt_bytes,
        }


def verzeichnis_messen(pfad: Path) -> tuple[int, int]:
    """(Bytes, Dateien) unterhalb von pfad; Symbolverknüpfungen zählen als Datei, nicht ihr Ziel."""
    groesse = 0
    dateien = 0
    stapel = [pfad]
    while stapel:
        aktuell = stapel.pop()
        try:
            with os.scandir(aktuell) as eintraege:
                for e in eintraege:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stapel.append(Path(e.path))
                        else:
                            groesse += e.stat(follow_symlinks=False).st_size
                            dateien += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return groesse, dateien


def messen(wurzel: Path) -> Speicherplatz:
    start = time.monotonic()
    bereiche: list[Bereich] = []
    erfasst: set[str] = set()
    for kennung, titel, unter in BEREICHE:
        groesse, dateien = verzeichnis_messen(wurzel / unter) if (wurzel / unter).exists() else (0, 0)
        bereiche.append(Bereich(kennung, titel, unter, groesse, dateien))
        erfasst.add(unter)
    # Was sonst noch im Datenverzeichnis liegt (einzelne Dateien, unbekannte Ordner)
    sonst_bytes = 0
    sonst_dateien = 0
    try:
        for e in os.scandir(wurzel):
            if e.name in erfasst:
                continue
            if e.is_dir(follow_symlinks=False):
                g, d = verzeichnis_messen(Path(e.path))
            else:
                g, d = e.stat(follow_symlinks=False).st_size, 1
            sonst_bytes += g
            sonst_dateien += d
    except OSError:
        pass
    if sonst_dateien:
        bereiche.append(Bereich("sonstiges", "Sonstiges", "", sonst_bytes, sonst_dateien))
    try:
        platte = os.statvfs(wurzel)
        frei, gesamt = platte.f_bavail * platte.f_frsize, platte.f_blocks * platte.f_frsize
    except OSError:
        frei, gesamt = 0, 0
    return Speicherplatz(
        gesamt_bytes=sum(b.bytes for b in bereiche),
        bereiche=bereiche,
        gemessen=datetime.now(UTC).isoformat(timespec="seconds"),
        dauer_ms=int((time.monotonic() - start) * 1000),
        verzeichnis=str(wurzel),
        platte_frei_bytes=frei,
        platte_gesamt_bytes=gesamt,
        _stand=time.monotonic(),
    )


_letzter: Speicherplatz | None = None
_sperre = asyncio.Lock()


async def speicherplatz(frisch: bool = False) -> Speicherplatz:
    """Zwischengespeicherte Messung des Datenverzeichnisses; frisch=True misst neu."""
    global _letzter
    async with _sperre:
        if not frisch and _letzter is not None and time.monotonic() - _letzter._stand < ZWISCHENSPEICHER_S:
            return _letzter
        _letzter = await asyncio.to_thread(messen, einstellungen.daten_verzeichnis)
        return _letzter
