"""Wahl der Transkriptions-Engine nach Einstellung.

Die Einstellung `transkription.engine` nennt eine Kennung; hier steht je Kennung ein
Bauer, der aus den Einstellungswerten die fertige Engine macht. Die Titel der
Kennungen stehen nur im Einstellungsregister (eine Wahrheit); ein Test sichert, dass
jede dort wählbare Kennung hier einen Bauer hat.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..einstellungen import register as einstellungen_register
from .basis import TranskriptionsEngine, TranskriptionsFehler
from .eigener_dienst import EigenerDienst
from .txt2voice_app import Txt2VoiceApp
from .txt2voice_worker import Txt2VoiceWorker

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


def _worker(werte: dict[str, Any]) -> TranskriptionsEngine:
    return Txt2VoiceWorker(
        basis_url=str(werte["transkription.worker_url"]),
        wortzeiten_behalten=bool(werte["transkription.wortzeiten_speichern"]),
        verbindungs_zeitgrenze_s=_verbindungs_zeitgrenze(werte),
    )


def _app(werte: dict[str, Any]) -> TranskriptionsEngine:
    return Txt2VoiceApp(
        basis_url=str(werte["transkription.app_url"]),
        wortzeiten_behalten=bool(werte["transkription.wortzeiten_speichern"]),
        verbindungs_zeitgrenze_s=_verbindungs_zeitgrenze(werte),
    )


BAUER: dict[str, Bauer] = {
    EigenerDienst.kennung: _morf,
    Txt2VoiceWorker.kennung: _worker,
    Txt2VoiceApp.kennung: _app,
}


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
