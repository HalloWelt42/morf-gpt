"""Textstellen (Chunks): durchblättern, ansehen, bearbeiten, teilen, zusammenlegen,
neu stückeln, einbetten."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.engine import sitzung_abhaengigkeit
from ..db.modelle import Chunk, Dokument, DokumentAbschnitt, Einbettung, Video
from ..dienste.anbieter.basis import AnbieterFehler
from ..dienste.auftraege.laeufer import auftrag_anlegen
from ..dienste.einbettung import dienst as einbettung_dienst
from ..dienste.einstellungen import dienst as einstellungen_dienst
from ..dienste.ereignisse import bus
from ..domaene.fliessband import Auftragsart, Stufe, stufen_index, vorstufe

router = APIRouter(prefix="/chunks", tags=["chunks"])


class ChunkEintrag(BaseModel):
    """Ein Stück mit seinem Werk: Video (video_id gesetzt) oder Dokument (dokument_id gesetzt)."""

    id: str
    werkart: str  # "video" oder "dokument"
    video_id: str
    video_titel: str  # Titel des Werks (Video oder Dokument)
    serie: str
    folge_nr: int | None
    original_url: str
    miniatur_url: str | None
    dokument_id: str
    abschnitt: str
    abschnitt_nr: int | None
    position_von: int | None
    reihenfolge: int
    anzahl_im_video: int
    text: str
    start_s: float
    end_s: float
    zeichen: int
    thema: str
    ueberlappung_vor: int
    ueberlappung_nach: int
    manuell_bearbeitet: bool
    einbettungen: list[str]
    erstellt: datetime
    aktualisiert: datetime


class ChunkSeite(BaseModel):
    eintraege: list[ChunkEintrag]
    gesamt: int
    seite: int
    je_seite: int


class Nachbar(BaseModel):
    id: str
    reihenfolge: int
    start_s: float
    end_s: float
    text: str


class EinbettungInfo(BaseModel):
    modell: str
    anbieter: str
    dimension: int
    erstellt: datetime


class ChunkDetail(ChunkEintrag):
    vorheriger: Nachbar | None
    naechster: Nachbar | None
    einbettung_details: list[EinbettungInfo]
    korrektur_id: str | None


class TextEingabe(BaseModel):
    text: str = Field(min_length=1)


class TeilenEingabe(BaseModel):
    position: int = Field(ge=1)


class AenderungErgebnis(BaseModel):
    chunk: ChunkDetail
    hinweis: str


class AuftragAusgabe(BaseModel):
    auftrag_id: str | None
    hinweis: str


class EinbettungErgebnis(BaseModel):
    chunk_id: str
    modell: str
    dimension: int


async def _anzahl_im_werk(session: AsyncSession, werk_id: str) -> int:
    return int(await session.scalar(select(func.count(Chunk.id)).where(or_(Chunk.video_id == werk_id, Chunk.dokument_id == werk_id))) or 0)


Werk = tuple[Video | None, Dokument | None, DokumentAbschnitt | None]


def _werk_id(w: Werk) -> str:
    video, dokument, _ = w
    return video.id if video is not None else (dokument.id if dokument is not None else "")


def _werke(q):  # noqa: ANN001, ANN202 - Select mit beiden Werken, äußere Verbünde
    return (
        q.outerjoin(Video, Video.id == Chunk.video_id)
        .outerjoin(Dokument, Dokument.id == Chunk.dokument_id)
        .outerjoin(DokumentAbschnitt, DokumentAbschnitt.id == Chunk.abschnitt_id)
    )


async def _modelle(session: AsyncSession, chunk_ids: list[str]) -> dict[str, list[str]]:
    if not chunk_ids:
        return {}
    rows = (await session.execute(select(Einbettung.chunk_id, Einbettung.modell).where(Einbettung.chunk_id.in_(chunk_ids)))).all()
    aus: dict[str, list[str]] = {}
    for cid, modell in rows:
        aus.setdefault(cid, []).append(modell)
    return aus


def _eintrag(c: Chunk, w: Werk, anzahl: int, modelle: list[str]) -> ChunkEintrag:
    v, d, a = w
    return ChunkEintrag(
        id=c.id,
        werkart="dokument" if d is not None else "video",
        video_id=v.id if v is not None else "",
        video_titel=v.titel if v is not None else (d.titel if d is not None else ""),
        serie=v.serie if v is not None else "",
        folge_nr=v.folge_nr if v is not None else None,
        original_url=v.original_url if v is not None else "",
        miniatur_url=f"/api/videos/{v.id}/miniatur" if v is not None and v.miniatur_pfad else None,
        dokument_id=d.id if d is not None else "",
        abschnitt=a.titel if a is not None else "",
        abschnitt_nr=a.reihenfolge if a is not None else None,
        position_von=c.position_von,
        reihenfolge=c.reihenfolge,
        anzahl_im_video=anzahl,
        text=c.text,
        start_s=c.start_s,
        end_s=c.end_s,
        zeichen=c.zeichen,
        thema=c.thema,
        ueberlappung_vor=c.ueberlappung_vor,
        ueberlappung_nach=c.ueberlappung_nach,
        manuell_bearbeitet=c.manuell_bearbeitet,
        einbettungen=modelle,
        erstellt=c.erstellt,
        aktualisiert=c.aktualisiert,
    )


async def _laden(session: AsyncSession, chunk_id: str) -> tuple[Chunk, Werk]:
    row = (await session.execute(_werke(select(Chunk, Video, Dokument, DokumentAbschnitt)).where(Chunk.id == chunk_id))).first()
    if row is None:
        raise HTTPException(404, "Textstelle nicht gefunden")
    return row[0], (row[1], row[2], row[3])


async def _nachbar(session: AsyncSession, werk_id: str, reihenfolge: int) -> Nachbar | None:
    c = (
        await session.execute(
            select(Chunk).where(or_(Chunk.video_id == werk_id, Chunk.dokument_id == werk_id), Chunk.reihenfolge == reihenfolge)
        )
    ).scalar_one_or_none()
    if c is None:
        return None
    return Nachbar(id=c.id, reihenfolge=c.reihenfolge, start_s=c.start_s, end_s=c.end_s, text=c.text)


async def _detail(session: AsyncSession, c: Chunk, w: Werk) -> ChunkDetail:
    werk_id = _werk_id(w)
    anzahl = await _anzahl_im_werk(session, werk_id)
    eb = (await session.execute(select(Einbettung).where(Einbettung.chunk_id == c.id).order_by(Einbettung.erstellt))).scalars().all()
    basis = _eintrag(c, w, anzahl, [e.modell for e in eb])
    return ChunkDetail(
        **basis.model_dump(),
        vorheriger=await _nachbar(session, werk_id, c.reihenfolge - 1),
        naechster=await _nachbar(session, werk_id, c.reihenfolge + 1),
        einbettung_details=[EinbettungInfo(modell=e.modell, anbieter=e.anbieter, dimension=e.dimension, erstellt=e.erstellt) for e in eb],
        korrektur_id=c.korrektur_id,
    )


async def _neu_nummerieren(session: AsyncSession, werk_id: str) -> None:
    chunks = (
        (
            await session.execute(
                select(Chunk).where(or_(Chunk.video_id == werk_id, Chunk.dokument_id == werk_id)).order_by(Chunk.reihenfolge, Chunk.start_s)
            )
        )
        .scalars()
        .all()
    )
    # Zwei Durchgänge wegen der Eindeutigkeit (werk, reihenfolge)
    for i, c in enumerate(chunks, start=1):
        c.reihenfolge = -i
    await session.flush()
    for i, c in enumerate(chunks, start=1):
        c.reihenfolge = i
    await session.flush()


@router.get("", response_model=ChunkSeite)
async def liste(
    video_id: str | None = None,
    dokument_id: str | None = None,
    werkart: str | None = None,
    q: str | None = None,
    serie: str | None = None,
    thema: str | None = None,
    ohne_einbettung: bool = False,
    seite: int = Query(1, ge=1),
    je_seite: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(sitzung_abhaengigkeit),
) -> ChunkSeite:
    basis = _werke(select(Chunk, Video, Dokument, DokumentAbschnitt))
    if video_id:
        basis = basis.where(Chunk.video_id == video_id)
    if dokument_id:
        basis = basis.where(Chunk.dokument_id == dokument_id)
    if werkart == "video":
        basis = basis.where(Chunk.video_id.is_not(None))
    elif werkart == "dokument":
        basis = basis.where(Chunk.dokument_id.is_not(None))
    if serie:
        basis = basis.where(Video.serie == serie)
    if thema:
        basis = basis.where(Chunk.thema.ilike(f"%{thema}%"))
    if q:
        basis = basis.where(or_(Chunk.text.ilike(f"%{q}%"), Video.titel.ilike(f"%{q}%"), Dokument.titel.ilike(f"%{q}%")))
    if ohne_einbettung:
        basis = basis.where(~select(Einbettung.id).where(Einbettung.chunk_id == Chunk.id).exists())
    gesamt = int(await session.scalar(select(func.count()).select_from(basis.subquery())) or 0)
    rows = (
        await session.execute(
            basis.order_by(Video.veroeffentlicht.desc().nulls_last(), Dokument.erstellt.desc().nulls_last(), Chunk.reihenfolge)
            .offset((seite - 1) * je_seite)
            .limit(je_seite)
        )
    ).all()
    modelle = await _modelle(session, [c.id for c, _, _, _ in rows])
    anzahlen: dict[str, int] = {}
    if rows:
        video_ids = list({v.id for _, v, _, _ in rows if v is not None})
        dokument_ids = list({d.id for _, _, d, _ in rows if d is not None})
        if video_ids:
            for vid, n in (
                await session.execute(
                    select(Chunk.video_id, func.count(Chunk.id)).where(Chunk.video_id.in_(video_ids)).group_by(Chunk.video_id)
                )
            ).all():
                anzahlen[str(vid)] = int(n)
        if dokument_ids:
            for did, n in (
                await session.execute(
                    select(Chunk.dokument_id, func.count(Chunk.id)).where(Chunk.dokument_id.in_(dokument_ids)).group_by(Chunk.dokument_id)
                )
            ).all():
                anzahlen[str(did)] = int(n)
    return ChunkSeite(
        eintraege=[_eintrag(c, (v, d, a), anzahlen.get(_werk_id((v, d, a)), 0), modelle.get(c.id, [])) for c, v, d, a in rows],
        gesamt=gesamt,
        seite=seite,
        je_seite=je_seite,
    )


@router.get("/themen", response_model=list[str])
async def themen(video_id: str | None = None, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> list[str]:
    q = select(Chunk.thema).where(Chunk.thema != "").distinct().order_by(Chunk.thema)
    if video_id:
        q = q.where(Chunk.video_id == video_id)
    return [t for t in (await session.execute(q)).scalars().all()]


@router.get("/{chunk_id}", response_model=ChunkDetail)
async def detail(chunk_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> ChunkDetail:
    c, w = await _laden(session, chunk_id)
    return await _detail(session, c, w)


@router.put("/{chunk_id}", response_model=AenderungErgebnis)
async def bearbeiten(chunk_id: str, e: TextEingabe, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> AenderungErgebnis:
    c, w = await _laden(session, chunk_id)
    c.text = e.text.strip()
    c.zeichen = len(c.text)
    c.manuell_bearbeitet = True
    await session.execute(delete(Einbettung).where(Einbettung.chunk_id == c.id))
    await session.commit()
    bus.veroeffentliche("chunks", aktion="bearbeitet", video_id=c.video_id, dokument_id=c.dokument_id, chunk_id=c.id)
    return AenderungErgebnis(
        chunk=await _detail(session, c, w), hinweis="Text gespeichert. Die Einbettung wurde entfernt - bitte neu einbetten."
    )


@router.post("/{chunk_id}/teilen", response_model=AenderungErgebnis)
async def teilen(chunk_id: str, e: TeilenEingabe, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> AenderungErgebnis:
    """Teilt an einer Zeichenposition (an der nächsten Wortgrenze) in zwei Stücke."""
    c, w = await _laden(session, chunk_id)
    text = c.text
    pos = min(e.position, len(text) - 1)
    while 0 < pos < len(text) and not text[pos].isspace():
        pos += 1
    links, rechts = text[:pos].strip(), text[pos:].strip()
    if not links or not rechts:
        raise HTTPException(422, "An dieser Position bleibt kein Text für beide Teile")
    dauer = max(0.0, c.end_s - c.start_s)
    grenze = c.start_s + dauer * (len(links) / max(1, len(text)))
    neu = Chunk(
        video_id=c.video_id,
        dokument_id=c.dokument_id,
        abschnitt_id=c.abschnitt_id,
        position_von=c.position_von,
        position_bis=c.position_bis,
        korrektur_id=c.korrektur_id,
        reihenfolge=c.reihenfolge * 1000 + 1,  # vorläufig, wird neu nummeriert
        text=rechts,
        start_s=grenze,
        end_s=c.end_s,
        zeichen=len(rechts),
        thema=c.thema,
        ueberlappung_vor=0,
        ueberlappung_nach=c.ueberlappung_nach,
        manuell_bearbeitet=True,
    )
    c.text, c.zeichen, c.end_s, c.ueberlappung_nach, c.manuell_bearbeitet = links, len(links), grenze, 0, True
    await session.execute(delete(Einbettung).where(Einbettung.chunk_id == c.id))
    session.add(neu)
    await session.flush()
    await _neu_nummerieren(session, _werk_id(w))
    await session.commit()
    bus.veroeffentliche("chunks", aktion="geteilt", video_id=c.video_id, dokument_id=c.dokument_id, chunk_id=c.id)
    return AenderungErgebnis(chunk=await _detail(session, c, w), hinweis="Stück geteilt. Beide Teile müssen neu eingebettet werden.")


@router.post("/{chunk_id}/zusammenlegen", response_model=AenderungErgebnis)
async def zusammenlegen(chunk_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> AenderungErgebnis:
    """Legt das Stück mit dem nächsten zusammen; die Überlappung wird nicht doppelt genommen."""
    c, w = await _laden(session, chunk_id)
    n = (
        await session.execute(
            select(Chunk).where(
                or_(Chunk.video_id == _werk_id(w), Chunk.dokument_id == _werk_id(w)), Chunk.reihenfolge == c.reihenfolge + 1
            )
        )
    ).scalar_one_or_none()
    if n is None:
        raise HTTPException(409, "Es gibt kein nächstes Stück")
    rest = n.text[n.ueberlappung_vor :].lstrip() if n.ueberlappung_vor and len(n.text) > n.ueberlappung_vor else n.text
    c.text = f"{c.text.rstrip()} {rest}".strip()
    c.zeichen = len(c.text)
    c.end_s = max(c.end_s, n.end_s)
    c.ueberlappung_nach = n.ueberlappung_nach
    c.manuell_bearbeitet = True
    await session.execute(delete(Einbettung).where(Einbettung.chunk_id == c.id))
    await session.delete(n)
    await session.flush()
    await _neu_nummerieren(session, _werk_id(w))
    await session.commit()
    bus.veroeffentliche("chunks", aktion="zusammengelegt", video_id=c.video_id, dokument_id=c.dokument_id, chunk_id=c.id)
    return AenderungErgebnis(chunk=await _detail(session, c, w), hinweis="Stücke zusammengelegt. Bitte neu einbetten.")


@router.delete("/{chunk_id}", status_code=204)
async def loeschen(chunk_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> None:
    c, w = await _laden(session, chunk_id)
    await session.delete(c)
    await session.flush()
    await _neu_nummerieren(session, _werk_id(w))
    await session.commit()
    bus.veroeffentliche("chunks", aktion="geloescht", video_id=c.video_id, dokument_id=c.dokument_id, chunk_id=chunk_id)


@router.post("/video/{video_id}/neu", response_model=AuftragAusgabe)
async def neu_stueckeln(video_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> AuftragAusgabe:
    v = await session.get(Video, video_id)
    if v is None:
        raise HTTPException(404, "Video nicht gefunden")
    if stufen_index(Stufe(v.stufe)) < stufen_index(vorstufe(Auftragsart.STUECKELUNG)):
        raise HTTPException(409, "Das Video ist noch nicht transkribiert - Stückeln braucht mindestens ein Transkript")
    a = await auftrag_anlegen(session, Auftragsart.STUECKELUNG, video_id, prioritaet=10)
    await session.commit()
    if a is None:
        return AuftragAusgabe(auftrag_id=None, hinweis="Für dieses Video wartet oder läuft bereits eine Stückelung")
    return AuftragAusgabe(auftrag_id=a.id, hinweis="Stückelung angelegt; die Einbettung folgt bei aktiver Automatik")


@router.post("/{chunk_id}/einbetten", response_model=EinbettungErgebnis)
async def einbetten(chunk_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> EinbettungErgebnis:
    """Bettet nur dieses Stück sofort ein (nach einer Bearbeitung)."""
    c, w = await _laden(session, chunk_id)
    werte = await einstellungen_dienst.alle(session)
    try:
        ergebnis = await einbettung_dienst.chunks_einbetten(c.video_id, werte, dokument_id=c.dokument_id, nur_chunk_ids=[c.id])
    except (AnbieterFehler, RuntimeError) as e:
        raise HTTPException(502, str(e)) from e
    bus.veroeffentliche("chunks", aktion="eingebettet", video_id=c.video_id, dokument_id=c.dokument_id, chunk_id=c.id)
    return EinbettungErgebnis(chunk_id=c.id, modell=ergebnis.modell, dimension=ergebnis.dimension)
