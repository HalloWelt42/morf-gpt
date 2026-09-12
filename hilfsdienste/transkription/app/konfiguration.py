"""Konfiguration des Transkriptionsdienstes: Umgebungswerte mit Präfix MORF_TRANSKRIPTION_.

Auch die .env im Projektwurzelverzeichnis wird gelesen, damit ein Wert an einer Stelle
steht. Modelle liegen unter data/modelle des Projekts, nie im Home-Verzeichnis.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .version import PROJEKT_WURZEL


class Einstellungen(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MORF_TRANSKRIPTION_",
        env_file=(str(PROJEKT_WURZEL / ".env"), ".env"),
        case_sensitive=False,
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8463

    # Engine: auto (mlx wenn vorhanden, sonst faster), mlx oder faster
    engine: str = "auto"
    # Modell je Engine; leer = Vorgabe (mlx: whisper-large-v3 als MLX-Gewichte, faster: large-v3-turbo)
    modell: str = ""
    # Rechenwerk der Engine faster: auto, cpu oder cuda
    rechner: str = "auto"
    # Engine mlx: Grenze des Puffer-Zwischenspeichers je Arbeiter (Gigabyte); ohne Grenze wächst er über
    # lange Videos auf zig Gigabyte
    mlx_cache_gb: float = 2.0
    # Ablage der Modelle (Zwischenspeicher der Modellablage darunter)
    modelle_verzeichnis: Path = Field(default=PROJEKT_WURZEL / "data" / "modelle")
    # Zwischenablage hochgeladener Audiodateien
    tmp_verzeichnis: Path = Field(default=PROJEKT_WURZEL / "data" / "tmp" / "transkription")

    # Arbeiter: je einer hält das Modell geladen und transkribiert eine Datei zur Zeit
    arbeiter: int = 1
    arbeiter_maximum: int = 8
    # So viel Speicher muss nach dem Laden eines weiteren Arbeiters frei bleiben
    speicher_reserve_gb: float = 8.0
    # Frist für das Laden eines Arbeiters (erster Start lädt das Modell aus dem Netz)
    ladefrist_s: float = 1800.0

    # Nachbearbeitung der Segmente: Zusammenführen zu Blöcken zwischen min und max Sekunden,
    # getrennt an Pausen ab pause_s
    segment_min_s: float = 6.0
    segment_max_s: float = 15.0
    pause_s: float = 0.3

    log_stufe: str = "INFO"


einstellungen = Einstellungen()
