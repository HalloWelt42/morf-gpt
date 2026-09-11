"""Schema beim Start auf den neuesten Stand bringen.

Das Backend führt vor dem Start des Auftragsläufers `alembic upgrade head` aus. So kann
kein Auftrag mehr auf ein Modell treffen, dessen Spalte in der Datenbank noch fehlt, etwa
wenn uvicorn nach einer Modelländerung neu lädt, bevor jemand die Migration angestoßen
hat. Migrationen sind je Revision genau einmal wirksam; ein Lauf ohne Änderung ist billig.

Alembic wird ohne alembic.ini konfiguriert, damit seine Logging-Einstellungen die der
Anwendung nicht überschreiben. Die Umgebung (alembic/env.py) holt die Datenbankadresse
selbst aus der App-Konfiguration.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command

log = logging.getLogger(__name__)

BACKEND_VERZEICHNIS = Path(__file__).resolve().parents[2]


def konfiguration() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_VERZEICHNIS / "alembic"))
    return cfg


def _aktualisieren() -> str:
    """Blockierend (läuft in einem Arbeitsthread, weil env.py selbst asyncio.run nutzt)."""
    cfg = konfiguration()
    command.upgrade(cfg, "head")
    return ScriptDirectory.from_config(cfg).get_current_head() or "?"


async def schema_aktualisieren() -> None:
    """Alle ausstehenden Migrationen anwenden. Ein Fehler bricht den Start ab (lieber kein Läufer als ein falscher)."""
    kopf = await asyncio.to_thread(_aktualisieren)
    log.info("Datenbankschema auf dem Stand %s", kopf)
