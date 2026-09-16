"""Grundkonfiguration des Backends.

Hier stehen nur Dinge, die technisch außerhalb der App liegen (Pfade, Ports,
Datenbankadresse). Alles, was der Nutzer steuern soll (Anbieter, Grenzen, Quellen),
liegt in der Datenbank und wird über die Oberfläche gepflegt.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJEKT_WURZEL: Path = Path(__file__).resolve().parents[2]


class Einstellungen(BaseSettings):
    """Umgebungswerte mit Präfix MORF_ (auch aus ../.env)."""

    model_config = SettingsConfigDict(
        env_prefix="MORF_",
        env_file=(str(PROJEKT_WURZEL / ".env"), ".env"),
        case_sensitive=False,
        extra="ignore",
    )

    backend_host: str = "127.0.0.1"
    backend_port: int = 8460
    frontend_port: int = 5460

    db_name: str = "morfgpt"
    db_nutzer: str = "morf"
    db_passwort: str = "morf"
    db_port: int = 5462
    db_host: str = "127.0.0.1"
    db_url: str = ""

    daten_verzeichnis: Path = Field(default=PROJEKT_WURZEL / "data")
    frontend_dist: Path = Field(default=PROJEKT_WURZEL / "frontend" / "dist")

    # Vektordimension des Einbettungsindex (bge-m3: 1024). Ein Wechsel braucht eine
    # Migration der Spalte; die Oberfläche zeigt die Dimension je Anbieter.
    einbettung_dimension: int = 1024

    # Protokollstufe des Backends
    log_stufe: str = "INFO"
    # Beim Start des Backends ausstehende Migrationen anwenden (vor dem Auftragsläufer).
    migration_beim_start: bool = True

    @property
    def datenbank_url(self) -> str:
        if self.db_url:
            return self.db_url
        return f"postgresql+asyncpg://{self.db_nutzer}:{self.db_passwort}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def datenbank_url_sync(self) -> str:
        """Für Alembic (psycopg-frei: asyncpg wird auch dort asynchron genutzt)."""
        return self.datenbank_url

    @property
    def audio_verzeichnis(self) -> Path:
        return self.daten_verzeichnis / "audio"

    @property
    def miniaturen_verzeichnis(self) -> Path:
        return self.daten_verzeichnis / "miniaturen"

    @property
    def dokumente_verzeichnis(self) -> Path:
        return self.daten_verzeichnis / "dokumente"

    @property
    def export_verzeichnis(self) -> Path:
        return self.daten_verzeichnis / "export"

    @property
    def uebergabe_verzeichnis(self) -> Path:
        """Fertige Übergaben (je Kennung ein Ordner zum Hochladen) und der Eingang geholter Übergaben."""
        return self.daten_verzeichnis / "uebergabe"

    @property
    def modelle_verzeichnis(self) -> Path:
        """Ablage lokaler Modelle (fastembed) - im Projekt, nie im Home-Verzeichnis."""
        return self.daten_verzeichnis / "modelle"

    def verzeichnisse_anlegen(self) -> None:
        for p in (
            self.daten_verzeichnis,
            self.audio_verzeichnis,
            self.dokumente_verzeichnis,
            self.miniaturen_verzeichnis,
            self.export_verzeichnis,
            self.modelle_verzeichnis,
        ):
            p.mkdir(parents=True, exist_ok=True)


einstellungen = Einstellungen()
