"""Register der Stufen-Ausführer.

Jede Auftragsart zeigt auf eine Funktion `async def (kontext, parameter) -> dict`.
Die Stufen-Module registrieren sich hier beim Import (siehe `registriere`), der
Läufer kennt nur dieses Register. Neue Stufen: Funktion schreiben, registrieren,
Titel und Zielstufe eintragen - der Läufer bleibt unverändert.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from ...domaene.fliessband import AUFTRAGSART_TITEL, STUFE_JE_AUFTRAG, Auftragsart, Stufe

if TYPE_CHECKING:
    from .laeufer import AuftragKontext

Ausfuehrer = Callable[["AuftragKontext", dict[str, Any]], Awaitable[dict[str, Any]]]

REGISTER: dict[Auftragsart, Ausfuehrer] = {}
TITEL: dict[Auftragsart, str] = dict(AUFTRAGSART_TITEL)
ZIELSTUFE: dict[Auftragsart, Stufe] = dict(STUFE_JE_AUFTRAG)


def registriere(art: Auftragsart) -> Callable[[Ausfuehrer], Ausfuehrer]:
    def _deko(fn: Ausfuehrer) -> Ausfuehrer:
        REGISTER[art] = fn
        return fn

    return _deko


def alle_laden() -> None:
    """Importiert alle Stufen-Module, damit sie sich registrieren."""
    from ..stufen import audio, einbettung, korrektur, quelle_abgleich, stueckelung, transkription  # noqa: F401
