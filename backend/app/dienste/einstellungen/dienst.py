"""Einstellungen lesen und schreiben (Datenbank), mit Vorgaben aus dem Register."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.modelle import Einstellung
from . import register


async def alle(session: AsyncSession) -> dict[str, Any]:
    """Alle Werte: Datenbank vor Vorgabe. Unbekannte Datenbankschlüssel werden ignoriert."""
    werte: dict[str, Any] = {d.schluessel: d.vorgabe for d in register.DEFINITIONEN}
    rows = (await session.execute(select(Einstellung))).scalars().all()
    for row in rows:
        if row.schluessel in werte:
            werte[row.schluessel] = row.wert
    return werte


async def wert(session: AsyncSession, schluessel: str) -> Any:
    d = register.definition(schluessel)
    row = await session.get(Einstellung, schluessel)
    if row is None:
        return d.vorgabe
    return row.wert


async def werte(session: AsyncSession, *schluessel: str) -> dict[str, Any]:
    alle_werte = await alle(session)
    return {s: alle_werte[s] for s in schluessel}


async def setze(session: AsyncSession, schluessel: str, neuer_wert: Any) -> Any:
    """Prüft gegen das Register und speichert. Gibt den normalisierten Wert zurück."""
    d = register.definition(schluessel)
    normal = register.pruefe_wert(d, neuer_wert)
    row = await session.get(Einstellung, schluessel)
    if row is None:
        row = Einstellung(schluessel=schluessel, wert=normal)
        session.add(row)
    else:
        row.wert = normal
    await session.flush()
    return normal


async def zuruecksetzen(session: AsyncSession, schluessel: str) -> Any:
    d = register.definition(schluessel)
    row = await session.get(Einstellung, schluessel)
    if row is not None:
        await session.delete(row)
        await session.flush()
    return d.vorgabe
