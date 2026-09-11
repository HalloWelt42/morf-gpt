"""Korrekturen: aktuelle Fassung, Vergleich je Block, manuelle Bearbeitung, Übernahme."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ..db.engine import sitzung_abhaengigkeit
from ..db.modelle import Korrektur, Transkript
from ..dienste.ereignisse import bus
from ..dienste.korrektur import bloecke as blockmodul

router = APIRouter(prefix="/korrekturen", tags=["korrekturen"])


class AbsatzAusgabe(BaseModel):
    start_s: float
    end_s: float
    text: str
    block: int = 0
    verworfen: bool = False


class ThemaAusgabe(BaseModel):
    titel: str
    start_s: float
    end_s: float
    kurz: str = ""


class KorrekturAusgabe(BaseModel):
    id: str
    video_id: str
    transkript_id: str | None
    engine: str
    anbieter: str
    modell: str
    absaetze: list[AbsatzAusgabe]
    themen: list[ThemaAusgabe]
    zusammenfassung: str
    aehnlichkeit: float | None
    bloecke_gesamt: int
    bloecke_verworfen: int
    dauer_verarbeitung_s: float | None
    manuell_bearbeitet: bool
    aktuell: bool
    erstellt: datetime


class BlockVergleich(BaseModel):
    index: int
    start_s: float
    end_s: float
    roh: str
    korrigiert: str
    absaetze: list[AbsatzAusgabe]
    aehnlichkeit: float | None
    verworfen: bool
    grund: str
    vorschlag: str


class VergleichAusgabe(BaseModel):
    korrektur_id: str
    video_id: str
    bloecke: list[BlockVergleich]
    gesamt: int


class AbsaetzeEingabe(BaseModel):
    absaetze: list[AbsatzAusgabe] = Field(min_length=1)


class ThemenEingabe(BaseModel):
    themen: list[ThemaAusgabe]
    zusammenfassung: str | None = None


def _ausgabe(k: Korrektur) -> KorrekturAusgabe:
    return KorrekturAusgabe(
        id=k.id,
        video_id=k.video_id,
        transkript_id=k.transkript_id,
        engine=k.engine,
        anbieter=k.anbieter,
        modell=k.modell,
        absaetze=[
            AbsatzAusgabe(**{f: a.get(f, AbsatzAusgabe.model_fields[f].default) for f in AbsatzAusgabe.model_fields}) for a in k.absaetze
        ],
        themen=[ThemaAusgabe(**{f: t.get(f, "") for f in ThemaAusgabe.model_fields}) for t in k.themen],
        zusammenfassung=k.zusammenfassung,
        aehnlichkeit=k.aehnlichkeit,
        bloecke_gesamt=k.bloecke_gesamt,
        bloecke_verworfen=k.bloecke_verworfen,
        dauer_verarbeitung_s=k.dauer_verarbeitung_s,
        manuell_bearbeitet=k.manuell_bearbeitet,
        aktuell=k.aktuell,
        erstellt=k.erstellt,
    )


async def _aktuelle(session: AsyncSession, video_id: str) -> Korrektur:
    k = (
        await session.execute(
            select(Korrektur)
            .where(Korrektur.video_id == video_id, Korrektur.aktuell.is_(True))
            .order_by(Korrektur.erstellt.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if k is None:
        raise HTTPException(404, "Für dieses Video gibt es noch keine Korrektur")
    return k


async def _laden(session: AsyncSession, korrektur_id: str) -> Korrektur:
    k = await session.get(Korrektur, korrektur_id)
    if k is None:
        raise HTTPException(404, "Korrektur nicht gefunden")
    return k


def _bloecke(k: Korrektur, segmente_roh: list[dict[str, Any]]) -> list[BlockVergleich]:
    """Gruppiert die Absätze nach Block und holt den Rohtext des Blocks aus dem Zeitfenster."""
    segmente = blockmodul.segmente_lesen(segmente_roh)
    gruppen: dict[int, list[dict[str, Any]]] = {}
    for a in k.absaetze:
        gruppen.setdefault(int(a.get("block", 0)), []).append(a)
    aus: list[BlockVergleich] = []
    for index in sorted(gruppen):
        absaetze = gruppen[index]
        start = min(float(a.get("start_s", 0)) for a in absaetze)
        ende = max(float(a.get("end_s", 0)) for a in absaetze)
        kopf = absaetze[0]
        aus.append(
            BlockVergleich(
                index=index,
                start_s=start,
                end_s=ende,
                roh=blockmodul.rohtext_im_fenster(segmente, start, ende),
                korrigiert="\n\n".join(str(a.get("text", "")) for a in absaetze),
                absaetze=[
                    AbsatzAusgabe(
                        start_s=float(a.get("start_s", 0)),
                        end_s=float(a.get("end_s", 0)),
                        text=str(a.get("text", "")),
                        block=index,
                        verworfen=bool(a.get("verworfen", False)),
                    )
                    for a in absaetze
                ],
                aehnlichkeit=kopf.get("aehnlichkeit"),
                verworfen=bool(kopf.get("verworfen", False)),
                grund=str(kopf.get("grund", "")),
                vorschlag=str(kopf.get("vorschlag", "")),
            )
        )
    return aus


@router.get("/{video_id}", response_model=KorrekturAusgabe)
async def aktuelle(video_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> KorrekturAusgabe:
    return _ausgabe(await _aktuelle(session, video_id))


@router.get("/{video_id}/alle", response_model=list[KorrekturAusgabe])
async def versionen(video_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> list[KorrekturAusgabe]:
    rows = (
        (await session.execute(select(Korrektur).where(Korrektur.video_id == video_id).order_by(Korrektur.erstellt.desc()))).scalars().all()
    )
    return [_ausgabe(k) for k in rows]


@router.get("/{video_id}/vergleich", response_model=VergleichAusgabe)
async def vergleich(video_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> VergleichAusgabe:
    """Roh und korrigiert je Block nebeneinander; Rohtext aus dem Zeitfenster des Transkripts."""
    k = await _aktuelle(session, video_id)
    t = await session.get(Transkript, k.transkript_id) if k.transkript_id else None
    if t is None:
        t = (
            await session.execute(
                select(Transkript)
                .where(Transkript.video_id == video_id, Transkript.aktuell.is_(True))
                .order_by(Transkript.erstellt.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    segmente = t.segmente if t else []
    bloecke = _bloecke(k, segmente)
    return VergleichAusgabe(korrektur_id=k.id, video_id=video_id, bloecke=bloecke, gesamt=len(bloecke))


@router.put("/{korrektur_id}/absaetze", response_model=KorrekturAusgabe)
async def absaetze_setzen(
    korrektur_id: str, e: AbsaetzeEingabe, session: AsyncSession = Depends(sitzung_abhaengigkeit)
) -> KorrekturAusgabe:
    """Manuelle Bearbeitung: die Absatzliste wird komplett ersetzt (Stücke müssen danach neu entstehen)."""
    k = await _laden(session, korrektur_id)
    k.absaetze = [
        {"start_s": a.start_s, "end_s": a.end_s, "text": a.text.strip(), "block": a.block, "verworfen": a.verworfen}
        for a in e.absaetze
        if a.text.strip()
    ]
    k.manuell_bearbeitet = True
    flag_modified(k, "absaetze")
    await session.commit()
    bus.veroeffentliche("korrektur", aktion="bearbeitet", video_id=k.video_id, korrektur_id=k.id)
    return _ausgabe(k)


@router.put("/{korrektur_id}/themen", response_model=KorrekturAusgabe)
async def themen_setzen(korrektur_id: str, e: ThemenEingabe, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> KorrekturAusgabe:
    k = await _laden(session, korrektur_id)
    k.themen = [t.model_dump() for t in sorted(e.themen, key=lambda t: t.start_s) if t.titel.strip()]
    if e.zusammenfassung is not None:
        k.zusammenfassung = e.zusammenfassung.strip()
    k.manuell_bearbeitet = True
    flag_modified(k, "themen")
    await session.commit()
    bus.veroeffentliche("korrektur", aktion="bearbeitet", video_id=k.video_id, korrektur_id=k.id)
    return _ausgabe(k)


@router.post("/{korrektur_id}/bloecke/{index}/uebernehmen", response_model=KorrekturAusgabe)
async def block_uebernehmen(korrektur_id: str, index: int, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> KorrekturAusgabe:
    """Den vom Wächter verworfenen Vorschlag eines Blocks bewusst übernehmen."""
    k = await _laden(session, korrektur_id)
    absaetze = [a for a in k.absaetze if int(a.get("block", 0)) == index]
    if not absaetze:
        raise HTTPException(404, "Block nicht gefunden")
    vorschlag = str(absaetze[0].get("vorschlag") or "").strip()
    if not vorschlag:
        raise HTTPException(409, "Für diesen Block liegt kein Vorschlag vor")
    start = min(float(a.get("start_s", 0)) for a in absaetze)
    ende = max(float(a.get("end_s", 0)) for a in absaetze)
    teile = [t.strip() for t in re.split(r"\n\s*\n", vorschlag) if t.strip()]
    gesamt = sum(len(t) for t in teile) or 1
    neue: list[dict[str, Any]] = []
    lauf = 0
    a_start = start
    for i, t in enumerate(teile):
        lauf += len(t)
        a_ende = ende if i == len(teile) - 1 else start + (ende - start) * (lauf / gesamt)
        neue.append({"start_s": round(a_start, 3), "end_s": round(a_ende, 3), "text": t, "block": index, "verworfen": False})
        a_start = a_ende
    neue[0]["aehnlichkeit"] = absaetze[0].get("aehnlichkeit")
    neue[0]["uebernommen"] = True
    rest = [a for a in k.absaetze if int(a.get("block", 0)) != index]
    k.absaetze = sorted(rest + neue, key=lambda a: float(a.get("start_s", 0)))
    k.bloecke_verworfen = max(0, k.bloecke_verworfen - 1)
    k.manuell_bearbeitet = True
    flag_modified(k, "absaetze")
    await session.commit()
    bus.veroeffentliche("korrektur", aktion="bearbeitet", video_id=k.video_id, korrektur_id=k.id)
    return _ausgabe(k)


@router.delete("/{korrektur_id}", status_code=204)
async def loeschen(korrektur_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> None:
    k = await _laden(session, korrektur_id)
    video_id = k.video_id
    war_aktuell = k.aktuell
    await session.delete(k)
    await session.flush()
    if war_aktuell:
        nachfolger = (
            await session.execute(select(Korrektur).where(Korrektur.video_id == video_id).order_by(Korrektur.erstellt.desc()).limit(1))
        ).scalar_one_or_none()
        if nachfolger is not None:
            nachfolger.aktuell = True
    await session.commit()
    bus.veroeffentliche("korrektur", aktion="geloescht", video_id=video_id, korrektur_id=korrektur_id)
