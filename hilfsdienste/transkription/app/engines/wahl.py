"""Wahl der Engine nach Einstellung und Installation; baut die Beschreibung für Arbeiterprozesse."""

from __future__ import annotations

import importlib
from importlib.util import find_spec

from ..konfiguration import Einstellungen
from .basis import Engine, EngineBeschreibung

VORGABE_MODELL: dict[str, str] = {
    "mlx": "mlx-community/whisper-large-v3-mlx",
    "faster": "large-v3-turbo",
}
MODULE: dict[str, tuple[str, str, str]] = {
    "mlx": ("mlx_whisper", "app.engines.mlx_engine", "MlxEngine"),
    "faster": ("faster_whisper", "app.engines.faster_engine", "FasterEngine"),
}


def verfuegbare() -> list[str]:
    """Installierte Engines in Vorzugsreihenfolge (mlx vor faster)."""
    return [k for k, (paket, _, _) in MODULE.items() if find_spec(paket) is not None]


def kennung_fuer(gewuenscht: str) -> str:
    vorhanden = verfuegbare()
    if gewuenscht != "auto":
        if gewuenscht not in MODULE:
            raise RuntimeError(f"Unbekannte Engine '{gewuenscht}'; möglich sind auto, mlx, faster")
        if gewuenscht not in vorhanden:
            raise RuntimeError(f"Die Engine '{gewuenscht}' ist nicht installiert (Paket {MODULE[gewuenscht][0]})")
        return gewuenscht
    if not vorhanden:
        raise RuntimeError("Keine Whisper-Engine installiert: mlx-whisper (Apple Silicon) oder faster-whisper (alle anderen)")
    return vorhanden[0]


def beschreibung_fuer(e: Einstellungen) -> EngineBeschreibung:
    kennung = kennung_fuer(e.engine)
    _, modul, klasse = MODULE[kennung]
    modell = e.modell or VORGABE_MODELL[kennung]
    cache = str((e.modelle_verzeichnis / "hf").resolve())
    argumente: dict[str, str] = {"modell": modell, "cache": cache}
    if kennung == "faster":
        argumente["rechner"] = e.rechner
    return EngineBeschreibung(kennung=kennung, modul=modul, klasse=klasse, argumente=argumente)


def baue(b: EngineBeschreibung) -> Engine:
    klasse = getattr(importlib.import_module(b.modul), b.klasse)
    return klasse(**b.argumente)
