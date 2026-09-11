"""Transkripte: aktuelles Transkript mit Segmenten, Versionen, Segmenttexte korrigieren, löschen.

Segmente liegen in der Datenbank in der Form des Whisper-Dienstes (start, end, text,
words); die API gibt sie in der Form der übrigen Oberfläche aus (start_s, end_s,
woerter). Übersetzt wird ausschließlich hier.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.engine import sitzung_abhaengigkeit
from ..db.modelle import Transkript, Video
from ..dienste.ereignisse import bus
from ..dienste.transkription.basis import (
    Segment,
    SegmentKorrektur,
    segmente_korrigieren,
    volltext_aus_segmenten,
)

router = APIRouter(prefix="/transkripte", tags=["transkripte"])


# ---------------------------------------------------------------- Schemata


class WortAusgabe(BaseModel):
    wort: str
    start_s: float
    end_s: float


class SegmentAusgabe(BaseModel):
    index: int
    start_s: float
    end_s: float
    text: str
    woerter: list[WortAusgabe]


class TranskriptKopf(BaseModel):
    """Ein Transkript ohne Inhalt - für Versionslisten."""

    id: str
    video_id: str
    engine: str
    modell: str
    sprache: str
    zeichen: int
    segmente_anzahl: int
    dauer_verarbeitung_s: float | None
    aktuell: bool
    erstellt: datetime


class TranskriptAusgabe(TranskriptKopf):
    volltext: str
    segmente: list[SegmentAusgabe]


class SegmentKorrekturEingabe(BaseModel):
    index: int = Field(ge=0)
    text: str = Field(max_length=20000)


class SegmenteEingabe(BaseModel):
    segmente: list[SegmentKorrekturEingabe] = Field(min_length=1, max_length=5000)


# ---------------------------------------------------------------- Abbildung


def _wort_ausgabe(segment: Segment) -> list[WortAusgabe]:
    return [WortAusgabe(wort=w.wort, start_s=w.start, end_s=w.end) for w in segment.woerter]


def _kopf(t: Transkript) -> TranskriptKopf:
    return TranskriptKopf(
        id=t.id,
        video_id=t.video_id,
        engine=t.engine,
        modell=t.modell,
        sprache=t.sprache,
        zeichen=len(t.volltext or ""),
        segmente_anzahl=len(t.segmente or []),
        dauer_verarbeitung_s=t.dauer_verarbeitung_s,
        aktuell=bool(t.aktuell),
        erstellt=t.erstellt,
    )


def _ausgabe(t: Transkript, mit_wortzeiten: bool) -> TranskriptAusgabe:
    segmente = [Segment.aus_speicherform(roh, mit_wortzeiten) for roh in (t.segmente or [])]
    return TranskriptAusgabe(
        **_kopf(t).model_dump(),
        volltext=t.volltext or "",
        segmente=[
            SegmentAusgabe(index=i, start_s=s.start, end_s=s.end, text=s.text, woerter=_wort_ausgabe(s)) for i, s in enumerate(segmente)
        ],
    )


# ---------------------------------------------------------------- Laden


async def _video_pruefen(session: AsyncSession, video_id: str) -> None:
    if await session.get(Video, video_id) is None:
        raise HTTPException(404, "Video nicht gefunden")


async def _aktuelles(session: AsyncSession, video_id: str) -> Transkript:
    t = await session.scalar(
        select(Transkript)
        .where(Transkript.video_id == video_id, Transkript.aktuell.is_(True))
        .order_by(Transkript.erstellt.desc())
        .limit(1)
    )
    if t is None:
        raise HTTPException(404, "Für dieses Video liegt noch kein Transkript vor")
    return t


async def _versionen(session: AsyncSession, video_id: str) -> list[Transkript]:
    """Alle Transkripte eines Videos, neueste zuerst."""
    rows = await session.execute(select(Transkript).where(Transkript.video_id == video_id).order_by(Transkript.erstellt.desc()))
    return list(rows.scalars().all())


async def _laden(session: AsyncSession, transkript_id: str) -> Transkript:
    t = await session.get(Transkript, transkript_id)
    if t is None:
        raise HTTPException(404, "Transkript nicht gefunden")
    return t


# ---------------------------------------------------------------- Endpunkte


@router.get("/{video_id}", response_model=TranskriptAusgabe)
async def aktuelles(
    video_id: str, mit_wortzeiten: bool = True, session: AsyncSession = Depends(sitzung_abhaengigkeit)
) -> TranskriptAusgabe:
    """Das aktuelle Transkript eines Videos mit allen Segmenten (Wortzeiten abwählbar)."""
    await _video_pruefen(session, video_id)
    t = await _aktuelles(session, video_id)
    return _ausgabe(t, mit_wortzeiten)


@router.get("/{video_id}/alle", response_model=list[TranskriptKopf])
async def versionen(video_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> list[TranskriptKopf]:
    """Alle Transkript-Versionen eines Videos ohne Segmente, neueste zuerst."""
    await _video_pruefen(session, video_id)
    return [_kopf(t) for t in await _versionen(session, video_id)]


@router.put("/{transkript_id}/segmente", response_model=TranskriptAusgabe)
async def segmente_setzen(
    transkript_id: str, eingabe: SegmenteEingabe, session: AsyncSession = Depends(sitzung_abhaengigkeit)
) -> TranskriptAusgabe:
    """Manuelle Textkorrektur je Segment. Der Volltext wird aus den Segmenten neu gebildet."""
    t = await _laden(session, transkript_id)
    vorher = [Segment.aus_speicherform(roh) for roh in (t.segmente or [])]
    korrekturen = [SegmentKorrektur(index=k.index, text=k.text) for k in eingabe.segmente]
    try:
        nachher = segmente_korrigieren(vorher, korrekturen)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    # Neue Liste zuweisen (kein Ändern in der alten): nur so erkennt die Datenbank die Änderung.
    t.segmente = [s.als_speicherform() for s in nachher]
    t.volltext = volltext_aus_segmenten(nachher)
    await session.commit()
    bus.veroeffentliche("transkript", aktion="geaendert", video_id=t.video_id, transkript_id=t.id, segmente=len(eingabe.segmente))
    return _ausgabe(t, mit_wortzeiten=True)


@router.delete("/{transkript_id}", status_code=204)
async def loeschen(transkript_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> None:
    """Löscht eine Transkript-Version. War sie aktuell, wird die neueste verbleibende aktuell.

    Das einzige Transkript eines Videos bleibt stehen: ohne Transkript stimmte die
    Stufe des Videos nicht mehr. Ersatz ist eine neue Transkription.
    """
    t = await _laden(session, transkript_id)
    andere = [v for v in await _versionen(session, t.video_id) if v.id != t.id]
    if not andere:
        raise HTTPException(409, "Das einzige Transkript dieses Videos kann nicht gelöscht werden - stattdessen neu transkribieren")
    nachfolger_id: str | None = None
    if t.aktuell:
        andere[0].aktuell = True
        nachfolger_id = andere[0].id
    await session.delete(t)
    await session.commit()
    bus.veroeffentliche("transkript", aktion="geloescht", video_id=t.video_id, transkript_id=transkript_id, aktuell_id=nachfolger_id)
