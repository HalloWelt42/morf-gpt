"""Chat: Unterhaltungen, Fragen als SSE-Strom, reine Suche, Nachrichten."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from ..db.engine import sitzung_abhaengigkeit
from ..db.modelle import Nachricht, Unterhaltung
from ..dienste.anbieter.basis import AnbieterFehler
from ..dienste.chat.orchestrierung import orchestrierung
from ..dienste.einstellungen import dienst as einstellungen_dienst
from ..dienste.ereignisse import bus
from ..dienste.suche.retrieval import Suchparameter, suche

router = APIRouter(prefix="/chat", tags=["chat"])


class UnterhaltungEintrag(BaseModel):
    id: str
    titel: str
    suchparameter: dict[str, Any]
    nachrichten: int
    letzte: datetime | None
    erstellt: datetime
    aktualisiert: datetime


class UnterhaltungSeite(BaseModel):
    eintraege: list[UnterhaltungEintrag]
    gesamt: int
    seite: int
    je_seite: int


class NachrichtAusgabe(BaseModel):
    id: str
    rolle: str
    inhalt: str
    stellen: list[dict[str, Any]]
    parameter: dict[str, Any]
    modell: str
    dauer_ms: int | None
    tokens_ein: int | None
    tokens_aus: int | None
    fehler: str
    erstellt: datetime


class UnterhaltungDetail(UnterhaltungEintrag):
    verlauf: list[NachrichtAusgabe]


class UnterhaltungEingabe(BaseModel):
    titel: str | None = None
    suchparameter: dict[str, Any] | None = None


class FrageEingabe(BaseModel):
    frage: str = Field(min_length=1)
    parameter: dict[str, Any] = Field(default_factory=dict)
    chunk_ids: list[str] | None = None


class SucheEingabe(BaseModel):
    frage: str = Field(min_length=1)
    parameter: dict[str, Any] = Field(default_factory=dict)
    unterhaltung_id: str | None = None


class SucheAusgabe(BaseModel):
    stellen: list[dict[str, Any]]
    hinweise: list[str]
    einbettungsmodell: str
    neubewertung: str
    parameter: dict[str, Any]


async def _eintrag(s: AsyncSession, u: Unterhaltung) -> UnterhaltungEintrag:
    anzahl, letzte = (
        await s.execute(select(func.count(Nachricht.id), func.max(Nachricht.erstellt)).where(Nachricht.unterhaltung_id == u.id))
    ).one()
    return UnterhaltungEintrag(
        id=u.id,
        titel=u.titel,
        suchparameter=u.suchparameter or {},
        nachrichten=int(anzahl or 0),
        letzte=letzte,
        erstellt=u.erstellt,
        aktualisiert=u.aktualisiert,
    )


def _nachricht(n: Nachricht) -> NachrichtAusgabe:
    return NachrichtAusgabe(
        id=n.id,
        rolle=n.rolle,
        inhalt=n.inhalt,
        stellen=n.stellen or [],
        parameter=n.parameter or {},
        modell=n.modell,
        dauer_ms=n.dauer_ms,
        tokens_ein=n.tokens_ein,
        tokens_aus=n.tokens_aus,
        fehler=n.fehler,
        erstellt=n.erstellt,
    )


async def _laden(s: AsyncSession, unterhaltung_id: str) -> Unterhaltung:
    u = await s.get(Unterhaltung, unterhaltung_id)
    if u is None:
        raise HTTPException(404, "Unterhaltung nicht gefunden")
    return u


@router.get("/unterhaltungen", response_model=UnterhaltungSeite)
async def unterhaltungen(
    seite: int = Query(1, ge=1), je_seite: int = Query(50, ge=1, le=500), session: AsyncSession = Depends(sitzung_abhaengigkeit)
) -> UnterhaltungSeite:
    gesamt = int(await session.scalar(select(func.count(Unterhaltung.id))) or 0)
    rows = (
        (
            await session.execute(
                select(Unterhaltung).order_by(Unterhaltung.aktualisiert.desc()).offset((seite - 1) * je_seite).limit(je_seite)
            )
        )
        .scalars()
        .all()
    )
    return UnterhaltungSeite(eintraege=[await _eintrag(session, u) for u in rows], gesamt=gesamt, seite=seite, je_seite=je_seite)


@router.post("/unterhaltungen", response_model=UnterhaltungEintrag, status_code=201)
async def anlegen(e: UnterhaltungEingabe | None = None, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> UnterhaltungEintrag:
    u = Unterhaltung(
        titel=(e.titel.strip() if e and e.titel else "Neue Unterhaltung"), suchparameter=(e.suchparameter if e and e.suchparameter else {})
    )
    session.add(u)
    await session.commit()
    return await _eintrag(session, u)


@router.get("/unterhaltungen/{unterhaltung_id}", response_model=UnterhaltungDetail)
async def detail(unterhaltung_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> UnterhaltungDetail:
    u = await _laden(session, unterhaltung_id)
    rows = (await session.execute(select(Nachricht).where(Nachricht.unterhaltung_id == u.id).order_by(Nachricht.erstellt))).scalars().all()
    basis = await _eintrag(session, u)
    return UnterhaltungDetail(**basis.model_dump(), verlauf=[_nachricht(n) for n in rows])


@router.put("/unterhaltungen/{unterhaltung_id}", response_model=UnterhaltungEintrag)
async def aendern(
    unterhaltung_id: str, e: UnterhaltungEingabe, session: AsyncSession = Depends(sitzung_abhaengigkeit)
) -> UnterhaltungEintrag:
    u = await _laden(session, unterhaltung_id)
    if e.titel is not None and e.titel.strip():
        u.titel = e.titel.strip()
    if e.suchparameter is not None:
        u.suchparameter = e.suchparameter
    await session.commit()
    return await _eintrag(session, u)


@router.delete("/unterhaltungen/{unterhaltung_id}", status_code=204)
async def loeschen(unterhaltung_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> None:
    u = await _laden(session, unterhaltung_id)
    await session.delete(u)
    await session.commit()


@router.post("/unterhaltungen/{unterhaltung_id}/fragen")
async def fragen(
    unterhaltung_id: str, e: FrageEingabe, request: Request, session: AsyncSession = Depends(sitzung_abhaengigkeit)
) -> EventSourceResponse:
    """SSE: treffer (Stellen), delta (Textstücke), fertig, fehler."""
    await _laden(session, unterhaltung_id)

    async def _gen() -> AsyncIterator[dict[str, str]]:
        async for ereignis in orchestrierung.frage_stellen(unterhaltung_id, e.frage, e.parameter, e.chunk_ids):
            if await request.is_disconnected():
                break
            art = str(ereignis.pop("art"))
            yield {"event": art, "data": json.dumps(ereignis, ensure_ascii=False)}
        bus.veroeffentliche("chat", aktion="antwort", unterhaltung_id=unterhaltung_id)

    return EventSourceResponse(_gen(), ping=15)


@router.post("/suche", response_model=SucheAusgabe)
async def nur_suchen(e: SucheEingabe, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> SucheAusgabe:
    """Reine Suche ohne Antwort - zur Vorschau und zum Abwählen vor der Antwort."""
    werte = await einstellungen_dienst.alle(session)
    basis: dict[str, Any] = {}
    if e.unterhaltung_id:
        u = await session.get(Unterhaltung, e.unterhaltung_id)
        if u is not None:
            basis = u.suchparameter or {}
    p = Suchparameter.aus_einstellungen(werte, basis, e.parameter)
    try:
        ergebnis = await suche.suchen(session, e.frage, p)
    except AnbieterFehler as err:
        raise HTTPException(502, str(err)) from err
    except ValueError as err:
        raise HTTPException(422, str(err)) from err
    return SucheAusgabe(
        stellen=[t.als_dict() for t in ergebnis.stellen],
        hinweise=ergebnis.hinweise,
        einbettungsmodell=ergebnis.einbettungsmodell,
        neubewertung=ergebnis.neubewertung,
        parameter=p.als_dict(),
    )


@router.delete("/nachrichten/{nachricht_id}", status_code=204)
async def nachricht_loeschen(nachricht_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> None:
    n = await session.get(Nachricht, nachricht_id)
    if n is None:
        raise HTTPException(404, "Nachricht nicht gefunden")
    await session.delete(n)
    await session.commit()
