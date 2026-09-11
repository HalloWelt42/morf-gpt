"""Version des Dienstes: dieselbe wie das Projekt (version.json im Wurzelverzeichnis).

Die Datei wird aufwärts gesucht, weil der Dienst an zwei Orten liegt: im Projekt unter
hilfsdienste/transkription (version.json drei Ebenen höher) und im Container unter /dienst
(version.json daneben in /).
"""

from __future__ import annotations

import json
from pathlib import Path


def _wurzel() -> Path:
    hier = Path(__file__).resolve()
    for eltern in hier.parents:
        if (eltern / "version.json").exists():
            return eltern
    return hier.parents[min(3, len(hier.parents) - 1)]


PROJEKT_WURZEL: Path = _wurzel()


def version_lesen() -> str:
    try:
        with (PROJEKT_WURZEL / "version.json").open(encoding="utf-8") as f:
            return str(json.load(f).get("version", "0.0.0"))
    except (OSError, ValueError):
        return "0.0.0"


VERSION: str = version_lesen()
