"""Einbettung: Instanzen des Modells in LM Studio verwalten (Stand, sicherstellen, abbauen) mit Speicherstand."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.engine import sitzung_abhaengigkeit
from ..dienste.anbieter import dienst as anbieter_dienst
from ..dienste.anbieter.basis import AnbieterFehler
from ..dienste.einbettung import instanzen
from ..dienste.einstellungen import dienst as einstellungen_dienst

router = APIRouter(prefix="/einbettung", tags=["einbettung"])


async def _anbieter(session: AsyncSession) -> tuple[str, str, str]:
    try:
        zeile = await anbieter_dienst.anbieter_fuer_rolle(session, "einbettung")
    except AnbieterFehler as e:
        raise HTTPException(409, str(e)) from e
    return zeile.typ, zeile.basis_url, zeile.modell


@router.get("/instanzen")
async def stand(session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> dict[str, Any]:
    typ, basis, modell = await _anbieter(session)
    werte = await einstellungen_dienst.alle(session)
    s = await instanzen.stand(basis, modell, werte)
    if typ != "lmstudio":
        s.hinweise.append(f"Der Einbettungsanbieter ist {typ}; mehrere Instanzen gibt es nur bei LM Studio.")
    return {**s.als_dict(), "anbieter_typ": typ}


@router.post("/instanzen/sicherstellen")
async def sicherstellen(session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> dict[str, Any]:
    """Fehlende Instanzen bis zur eingestellten Zahl laden, soweit der Speicher reicht."""
    typ, basis, modell = await _anbieter(session)
    if typ != "lmstudio":
        raise HTTPException(409, f"Der Einbettungsanbieter ist {typ}; mehrere Instanzen gibt es nur bei LM Studio.")
    werte = await einstellungen_dienst.alle(session)
    s = await instanzen.sicherstellen(basis, modell, werte)
    return {**s.als_dict(), "anbieter_typ": typ}


@router.post("/instanzen/abbauen")
async def abbauen(session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> dict[str, Any]:
    """Alle zusätzlichen Instanzen entladen; das Modell selbst bleibt geladen."""
    typ, basis, modell = await _anbieter(session)
    if typ != "lmstudio":
        raise HTTPException(409, f"Der Einbettungsanbieter ist {typ}; mehrere Instanzen gibt es nur bei LM Studio.")
    werte = await einstellungen_dienst.alle(session)
    s = await instanzen.abbauen(basis, modell, werte)
    return {**s.als_dict(), "anbieter_typ": typ}
