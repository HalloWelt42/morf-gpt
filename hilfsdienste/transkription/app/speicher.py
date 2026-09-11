"""Arbeitsspeicher des Rechners: gesamt und verfügbar, für die Entscheidung über weitere Arbeiter.

macOS: vm_stat (frei plus spekulativ plus inaktiv gilt als verfügbar). Linux: /proc/meminfo.
Andere Systeme melden "unbekannt"; dann wird ohne Prüfung geladen und das gesagt.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

GB = 1024**3


@dataclass(slots=True)
class Speicherstand:
    gesamt_gb: float
    verfuegbar_gb: float
    bekannt: bool

    def als_dict(self) -> dict[str, float | bool]:
        return {"gesamt_gb": round(self.gesamt_gb, 1), "verfuegbar_gb": round(self.verfuegbar_gb, 1), "bekannt": self.bekannt}


def _macos() -> Speicherstand:
    gesamt = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5).stdout.strip())
    vm = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
    seite = 4096
    m = re.search(r"page size of (\d+) bytes", vm)
    if m:
        seite = int(m.group(1))
    seiten: dict[str, int] = {}
    for zeile in vm.splitlines():
        if ":" in zeile:
            name, wert = zeile.split(":", 1)
            wert = wert.strip().rstrip(".")
            if wert.isdigit():
                seiten[name.strip()] = int(wert)
    verfuegbar = (seiten.get("Pages free", 0) + seiten.get("Pages speculative", 0) + seiten.get("Pages inactive", 0)) * seite
    return Speicherstand(gesamt / GB, verfuegbar / GB, True)


def _linux() -> Speicherstand:
    werte: dict[str, int] = {}
    for zeile in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        teile = zeile.split()
        if len(teile) >= 2 and teile[1].isdigit():
            werte[teile[0].rstrip(":")] = int(teile[1]) * 1024
    if "MemTotal" not in werte:
        raise ValueError("MemTotal fehlt")
    return Speicherstand(werte["MemTotal"] / GB, werte.get("MemAvailable", 0) / GB, True)


def speicherstand() -> Speicherstand:
    try:
        if sys.platform == "darwin":
            return _macos()
        if sys.platform.startswith("linux"):
            return _linux()
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return Speicherstand(0.0, 0.0, False)


def darf_laden(stand: Speicherstand, groesse_gb: float, reserve_gb: float) -> tuple[bool, str]:
    """(erlaubt, Hinweis): ein weiterer Arbeiter darf laden, wenn danach die Reserve frei bleibt."""
    if not stand.bekannt:
        return True, "Der Speicherstand dieses Systems ist unbekannt; geladen wird ohne Prüfung."
    if stand.verfuegbar_gb - groesse_gb >= reserve_gb:
        return True, ""
    return False, (
        f"Nicht genug freier Speicher für einen weiteren Arbeiter: {stand.verfuegbar_gb:.1f} GB verfügbar, "
        f"nötig sind {groesse_gb:.1f} GB plus {reserve_gb:.1f} GB Reserve."
    )
