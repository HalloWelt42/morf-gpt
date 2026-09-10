"""Einzige Versionsquelle: version.json im Projektwurzelverzeichnis.

Nirgends sonst steht eine Versionsnummer. Wer die Version braucht, liest sie hier.
"""

from __future__ import annotations

import json
from pathlib import Path

_WURZEL = Path(__file__).resolve().parents[2]
_DATEI = _WURZEL / "version.json"


def _lese() -> dict[str, str]:
    try:
        with _DATEI.open(encoding="utf-8") as f:
            daten = json.load(f)
    except (OSError, ValueError):
        return {"version": "0.0.0", "id": "000000", "voll": "v0.0.0-000000"}
    return {
        "version": str(daten.get("version", "0.0.0")),
        "id": str(daten.get("id", "000000")),
        "voll": str(daten.get("voll", f"v{daten.get('version', '0.0.0')}")),
    }


def version_lesen() -> dict[str, str]:
    """Liest version.json bei jedem Aufruf frisch (kein veralteter Modulwert)."""
    return _lese()


VERSION: str = _lese()["version"]
