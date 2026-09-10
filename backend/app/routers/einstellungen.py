"""Einstellungen: alle Definitionen mit aktuellen Werten lesen, einzeln setzen, zurücksetzen."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.engine import sitzung_abhaengigkeit
from ..dienste.einstellungen import dienst, register
from ..dienste.ereignisse import bus

router = APIRouter(prefix="/einstellungen", tags=["einstellungen"])


class Auswahloption(BaseModel):
    wert: str
    titel: str


class EinstellungAusgabe(BaseModel):
    schluessel: str
    titel: str
    beschreibung: str
    typ: str
    gruppe: str
    gruppe_titel: str
    einheit: str
    minimum: float | None
    maximum: float | None
    schritt: float | None
    auswahl: list[Auswahloption]
    vorgabe: Any
    wert: Any
    geaendert: bool


class WertEingabe(BaseModel):
    wert: Any


def _ausgabe(d: register.Definition, wert: Any) -> EinstellungAusgabe:
    return EinstellungAusgabe(
        schluessel=d.schluessel,
        titel=d.titel,
        beschreibung=d.beschreibung,
        typ=d.typ,
        gruppe=d.gruppe,
        gruppe_titel=register.GRUPPEN_TITEL.get(d.gruppe, d.gruppe),
        einheit=d.einheit,
        minimum=d.minimum,
        maximum=d.maximum,
        schritt=d.schritt,
        auswahl=[Auswahloption(wert=w, titel=t) for w, t in d.auswahl],
        vorgabe=d.vorgabe,
        wert=wert,
        geaendert=wert != d.vorgabe,
    )


@router.get("", response_model=list[EinstellungAusgabe])
async def alle(session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> list[EinstellungAusgabe]:
    werte = await dienst.alle(session)
    return [_ausgabe(d, werte[d.schluessel]) for d in register.DEFINITIONEN]


@router.get("/werte", response_model=dict[str, Any])
async def werte(session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> dict[str, Any]:
    return await dienst.alle(session)


@router.put("/{schluessel}", response_model=EinstellungAusgabe)
async def setzen(schluessel: str, eingabe: WertEingabe, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> EinstellungAusgabe:
    try:
        d = register.definition(schluessel)
        neu = await dienst.setze(session, schluessel, eingabe.wert)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    await session.commit()
    bus.veroeffentliche("einstellung", schluessel=schluessel, wert=neu)
    return _ausgabe(d, neu)


@router.delete("/{schluessel}", response_model=EinstellungAusgabe)
async def zuruecksetzen(schluessel: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> EinstellungAusgabe:
    try:
        d = register.definition(schluessel)
        neu = await dienst.zuruecksetzen(session, schluessel)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    await session.commit()
    bus.veroeffentliche("einstellung", schluessel=schluessel, wert=neu)
    return _ausgabe(d, neu)
