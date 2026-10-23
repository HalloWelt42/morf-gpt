"""Systemauskunft: Gesundheit, Version, Zähler, Erreichbarkeit der Werkstatt-Dienste."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.engine import sitzung_abhaengigkeit
from ..db.modelle import Auftrag, Chunk, Dokument, Einbettung, Video
from ..dienste import speicherplatz as speicherplatz_dienst
from ..dienste.auftraege.laeufer import laeufer
from ..dienste.einstellungen import dienst as einstellungen_dienst
from ..dienste.transkription import register as transkription_register
from ..domaene.fliessband import STUFEN_REIHENFOLGE, STUFEN_TITEL
from ..version import version_lesen

router = APIRouter(prefix="/system", tags=["system"])


class Gesundheit(BaseModel):
    status: str
    version: str
    version_voll: str
    laeufer_aktiv: bool


class StufenZaehler(BaseModel):
    stufe: str
    titel: str
    anzahl: int


class Uebersicht(BaseModel):
    version: str
    version_voll: str
    videos_gesamt: int
    videos_ausgewaehlt: int
    dokumente: int
    chunks: int
    einbettungen: int
    auftraege_wartend: int
    auftraege_laufend: int
    auftraege_fehler: int
    stufen: list[StufenZaehler]
    laeufer_aktiv: bool


class Dienst(BaseModel):
    kennung: str
    titel: str
    adresse: str
    erreichbar: bool
    hinweis: str


@router.get("/health", response_model=Gesundheit)
async def health() -> Gesundheit:
    v = version_lesen()
    return Gesundheit(status="ok", version=v["version"], version_voll=v["voll"], laeufer_aktiv=laeufer.laeuft())


@router.get("/uebersicht", response_model=Uebersicht)
async def uebersicht(session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> Uebersicht:
    v = version_lesen()
    stufen_rows = (
        await session.execute(select(Video.stufe, func.count(Video.id)).where(Video.ausgewaehlt.is_(True)).group_by(Video.stufe))
    ).all()
    je_stufe = {s: n for s, n in stufen_rows}
    auftrag_rows = (await session.execute(select(Auftrag.status, func.count(Auftrag.id)).group_by(Auftrag.status))).all()
    je_status = {s: n for s, n in auftrag_rows}
    return Uebersicht(
        version=v["version"],
        version_voll=v["voll"],
        videos_gesamt=int(await session.scalar(select(func.count(Video.id))) or 0),
        videos_ausgewaehlt=int(await session.scalar(select(func.count(Video.id)).where(Video.ausgewaehlt.is_(True))) or 0),
        dokumente=int(await session.scalar(select(func.count(Dokument.id))) or 0),
        chunks=int(await session.scalar(select(func.count(Chunk.id))) or 0),
        einbettungen=int(await session.scalar(select(func.count(Einbettung.id))) or 0),
        auftraege_wartend=int(je_status.get("wartend", 0)),
        auftraege_laufend=int(je_status.get("laeuft", 0)),
        auftraege_fehler=int(je_status.get("fehler", 0)),
        stufen=[StufenZaehler(stufe=s, titel=STUFEN_TITEL[s], anzahl=int(je_stufe.get(s, 0))) for s in STUFEN_REIHENFOLGE],
        laeufer_aktiv=laeufer.laeuft(),
    )


async def _pruefe(url: str) -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(6, connect=3)) as c:
            r = await c.get(url)
        return (r.status_code < 500), f"HTTP {r.status_code}"
    except httpx.HTTPError as e:
        return False, f"nicht erreichbar ({e.__class__.__name__})"


@router.get("/dienste", response_model=list[Dienst])
async def dienste(session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> list[Dienst]:
    werte = await einstellungen_dienst.alle(session)
    eigen = str(werte["transkription.dienst_url"])
    ok, hinweis = await _pruefe(eigen.rstrip("/") + "/health")
    aus = [Dienst(kennung="morf", titel="morf-Transkription (eigener Dienst)", adresse=eigen, erreichbar=ok, hinweis=hinweis)]
    # Die App Transkription prüft die Engine selbst (Anmeldung mit dem App-Schlüssel bei der Kellerwolke)
    verbund = transkription_register.BAUER["transkription"](werte)
    ok, hinweis = await verbund.erreichbar()
    aus.append(Dienst(kennung="transkription", titel="App Transkription (über die Kellerwolke)",
                      adresse=str(werte["transkription.kellerwolke_url"]), erreichbar=ok, hinweis=hinweis))
    return aus


@router.get("/speicherplatz", response_model=dict[str, Any])
async def speicherplatz(frisch: bool = False) -> dict[str, Any]:
    """Platz des Datenverzeichnisses nach Bereichen (Audio, Datenbank, Modelle, ...), kurz zwischengespeichert."""
    return (await speicherplatz_dienst.speicherplatz(frisch)).als_dict()


@router.get("/laeufer", response_model=dict[str, Any])
async def laeufer_status() -> dict[str, Any]:
    return {"aktiv": laeufer.laeuft(), "laufende_auftraege": laeufer.aktive()}
