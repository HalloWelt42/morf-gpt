"""Wahl der Transkriptions-Engine nach Einstellung.

Die Einstellung `transkription.engine` nennt eine Kennung; hier steht je Kennung ein
Bauer, der aus den Einstellungswerten die fertige Engine macht. Die Titel der
Kennungen stehen nur im Einstellungsregister (eine Wahrheit); ein Test sichert, dass
jede dort wählbare Kennung hier einen Bauer hat.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...config import einstellungen as umgebung
from ..einstellungen import register as einstellungen_register
from .basis import TranskriptionsEngine, TranskriptionsFehler
from .eigener_dienst import EigenerDienst
from .transkription_app import TranskriptionApp

Bauer = Callable[[dict[str, Any]], TranskriptionsEngine]

EINSTELLUNG_ENGINE = "transkription.engine"

# Vorgabewert, bis das Einstellungsregister den Schlüssel transkription.verbindungs_zeitgrenze_s
# kennt (vorgeschlagen: ganzzahl, 20 Sekunden, 1 bis 300). Sobald er existiert, greift er
# über werte.get(...) automatisch.
VERBINDUNGS_ZEITGRENZE_S_VORGABE: float = 20.0


def _verbindungs_zeitgrenze(werte: dict[str, Any]) -> float:
    return float(werte.get("transkription.verbindungs_zeitgrenze_s", VERBINDUNGS_ZEITGRENZE_S_VORGABE))


def _morf(werte: dict[str, Any]) -> TranskriptionsEngine:
    return EigenerDienst(
        basis_url=str(werte["transkription.dienst_url"]),
        wortzeiten_behalten=bool(werte["transkription.wortzeiten_speichern"]),
        verbindungs_zeitgrenze_s=_verbindungs_zeitgrenze(werte),
    )


def _transkription(werte: dict[str, Any]) -> TranskriptionsEngine:
    return TranskriptionApp(
        kellerwolke_url=str(werte["transkription.kellerwolke_url"]),
        schluessel=umgebung.kellerwolke_schluessel,
        app=str(werte["transkription.app"]),
        ca=hausstelle_ca(),
        wortzeiten_behalten=bool(werte["transkription.wortzeiten_speichern"]),
        verbindungs_zeitgrenze_s=_verbindungs_zeitgrenze(werte),
    )


BAUER: dict[str, Bauer] = {
    EigenerDienst.kennung: _morf,
    TranskriptionApp.kennung: _transkription,
}


def hausstelle_ca() -> str:
    """Stammzertifikat der Hausstelle: aus MORF_HAUSSTELLE_CA, sonst das von mkcert am Mac, sonst leer."""
    if umgebung.hausstelle_ca:
        return umgebung.hausstelle_ca
    datei = Path(os.environ.get("CAROOT") or Path.home() / "Library" / "Application Support" / "mkcert") / "rootCA.pem"
    return str(datei) if datei.is_file() else ""


def kennungen() -> tuple[str, ...]:
    return tuple(BAUER)


def titel_fuer(kennung: str) -> str:
    """Anzeigename einer Engine aus dem Einstellungsregister; unbekannte Kennungen kommen unverändert zurück."""
    for wert, titel in einstellungen_register.definition(EINSTELLUNG_ENGINE).auswahl:
        if wert == kennung:
            return titel
    return kennung


def engine_aus_werten(werte: dict[str, Any]) -> TranskriptionsEngine:
    """Baut die gewählte Engine aus einem vollständigen Einstellungssatz (siehe einstellungen.dienst.alle)."""
    kennung = str(werte.get(EINSTELLUNG_ENGINE) or "")
    bauer = BAUER.get(kennung)
    if bauer is None:
        raise TranskriptionsFehler(f"Unbekannte Transkriptions-Engine '{kennung}' - bekannt sind: {', '.join(kennungen())}")
    return bauer(werte)
