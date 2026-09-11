"""Transkription: Stand des eigenen Dienstes (Arbeiter, Speicher) lesen und die Zahl der Arbeiter anpassen."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.engine import sitzung_abhaengigkeit
from ..dienste.einstellungen import dienst as einstellungen_dienst
from ..dienste.transkription import register
from ..dienste.transkription.basis import TranskriptionsEngine, TranskriptionsFehler
from ..dienste.transkription.eigener_dienst import EigenerDienst

router = APIRouter(prefix="/transkription", tags=["transkription"])
NICHT_EIGENER = "Der gewählte Transkriptionsdienst ist nicht der eigene; Arbeiter gibt es nur dort."


class ArbeiterWunsch(BaseModel):
    anzahl: int | None = Field(default=None, ge=1, le=16, description="leer: Wert der Einstellung transkription.arbeiter")


async def _engine(session: AsyncSession) -> tuple[dict[str, Any], TranskriptionsEngine, dict[str, Any]]:
    werte = await einstellungen_dienst.alle(session)
    try:
        engine = register.engine_aus_werten(werte)
    except TranskriptionsFehler as e:
        raise HTTPException(409, str(e)) from e
    grund = {
        "engine_kennung": engine.kennung,
        "engine_titel": register.titel_fuer(engine.kennung),
        "eigener": isinstance(engine, EigenerDienst),
        "arbeiter_einstellung": int(werte["transkription.arbeiter"]),
        "adresse": getattr(engine, "basis_url", ""),
    }
    return werte, engine, grund


@router.get("/dienst")
async def dienst(session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> dict[str, Any]:
    """Stand des gewählten Transkriptionsdienstes; Arbeiter und Speicher gibt es nur beim eigenen Dienst."""
    _, engine, grund = await _engine(session)
    if not isinstance(engine, EigenerDienst):
        return {**grund, "erreichbar": False, "hinweis": NICHT_EIGENER}
    try:
        stand = await engine.stand()
    except TranskriptionsFehler as e:
        return {**grund, "erreichbar": False, "hinweis": str(e)}
    return {**grund, "erreichbar": True, "hinweis": "", **stand}


@router.post("/dienst/arbeiter")
async def arbeiter(wunsch: ArbeiterWunsch, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> dict[str, Any]:
    """Bringt den eigenen Dienst auf die gewünschte Zahl Arbeiter (ohne Angabe: die Einstellung); er prüft den Speicher."""
    _, engine, grund = await _engine(session)
    if not isinstance(engine, EigenerDienst):
        raise HTTPException(409, NICHT_EIGENER)
    anzahl = wunsch.anzahl or int(grund["arbeiter_einstellung"])
    try:
        stand = await engine.arbeiter_setzen(anzahl)
    except TranskriptionsFehler as e:
        raise HTTPException(502, str(e)) from e
    return {**grund, "erreichbar": True, "hinweis": "", **stand}
