"""Anbindung an Dienste im Heimnetz: Stammzertifikat der Hausstelle und App-Schlüssel der Kellerwolke (HELF-169: im
Heimnetz nur HTTPS; Programme melden sich am Vorbau und an den Apps mit dem App-Schlüssel an)."""

from __future__ import annotations

import os
from pathlib import Path

from .config import einstellungen as umgebung


def hausstelle_ca() -> str:
    """Stammzertifikat der Hausstelle: aus MORF_HAUSSTELLE_CA, sonst das von mkcert am Mac, sonst leer."""
    if umgebung.hausstelle_ca:
        return umgebung.hausstelle_ca
    datei = Path(os.environ.get("CAROOT") or Path.home() / "Library" / "Application Support" / "mkcert") / "rootCA.pem"
    return str(datei) if datei.is_file() else ""


def app_schluessel() -> str:
    """App-Schlüssel der Kellerwolke (Zugang "morf-gpt"), nur aus der .env; leer: keiner eingerichtet."""
    return umgebung.kellerwolke_schluessel
