"""Dokumente: hochladen (EPUB, Markdown, Text), eigene Texte, Liste, Detail, Leseansicht,
Handpflege, Aufträge (Stückeln, Einbetten), Löschen."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.engine import sitzung_abhaengigkeit
from ..db.modelle import Auftrag, Chunk, Dokument, DokumentAbschnitt
from ..dienste.auftraege.laeufer import auftrag_anlegen
from ..dienste.dokumente import basis, import_
from ..dienste.einstellungen import dienst as einstellungen_dienst
from ..dienste.ereignisse import bus
from ..domaene.fliessband import (
    AUFTRAGSART_TITEL,
    DOKUMENT_AUFTRAGSARTEN,
    DOKUMENT_STUFEN_TITEL,
    Auftragsart,
    Auftragsstatus,
    Dokumentstufe,
    dokument_vorstufe,
    dokumentstufen_index,
)
from ..schemata.dokumente import (
    AbschnittEintrag,
    AbschnittText,
    ArtEintrag,
    DokumentAenderung,
    DokumentDetail,
    DokumentEintrag,
    DokumentInhalt,
    DokumentSeite,
    EigenerText,
)
from ..schemata.videos import AuftragAngelegt, AuftragKurz, OffenerAuftrag

router = APIRouter(prefix="/dokumente", tags=["dokumente"])

OFFENE_STATUS = (Auftragsstatus.WARTEND, Auftragsstatus.LAEUFT)
PFLEGBARE_FELDER = ("titel", "autor", "sprache", "beschreibung", "veroeffentlicht")


async def _chunks_je_dokument(session: AsyncSession, ids: list[str]) -> dict[str, int]:
    if not ids:
        return {}
    rows = (
        await session.execute(select(Chunk.dokument_id, func.count(Chunk.id)).where(Chunk.dokument_id.in_(ids)).group_by(Chunk.dokument_id))
    ).all()
    return {str(d): int(n) for d, n in rows}


async def _abschnitte_je_dokument(session: AsyncSession, ids: list[str]) -> dict[str, int]:
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(DokumentAbschnitt.dokument_id, func.count(DokumentAbschnitt.id))
            .where(DokumentAbschnitt.dokument_id.in_(ids))
            .group_by(DokumentAbschnitt.dokument_id)
        )
    ).all()
    return {str(d): int(n) for d, n in rows}


async def _offene(session: AsyncSession, ids: list[str]) -> dict[str, Auftrag]:
    if not ids:
        return {}
    rows = (
        (
            await session.execute(
                select(Auftrag)
                .where(Auftrag.dokument_id.in_(ids), Auftrag.status.in_(OFFENE_STATUS))
                .order_by(desc(Auftrag.status == Auftragsstatus.LAEUFT), Auftrag.erstellt)
            )
        )
        .scalars()
        .all()
    )
    offene: dict[str, Auftrag] = {}
    for a in rows:
        if a.dokument_id and a.dokument_id not in offene:
            offene[a.dokument_id] = a
    return offene


def _eintrag(d: Dokument, chunks: int, abschnitte: int, offener: Auftrag | None) -> DokumentEintrag:
    return DokumentEintrag(
        id=d.id,
        titel=d.titel,
        autor=d.autor,
        art=d.art,
        art_titel=basis.ARTEN_TITEL.get(d.art, d.art),
        sprache=d.sprache,
        veroeffentlicht=d.veroeffentlicht,
        dateiname=d.dateiname,
        groesse_bytes=d.groesse_bytes,
        zeichen=d.zeichen,
        abschnitte_anzahl=abschnitte,
        chunks_anzahl=chunks,
        stufe=d.stufe,
        stufe_titel=DOKUMENT_STUFEN_TITEL.get(Dokumentstufe(d.stufe), d.stufe),
        fehler=d.fehler,
        offener_auftrag=(
            OffenerAuftrag(
                id=offener.id,
                art=offener.art,
                art_titel=AUFTRAGSART_TITEL.get(Auftragsart(offener.art), offener.art),
                status=offener.status,
                fortschritt=offener.fortschritt,
                meldung=offener.meldung,
            )
            if offener
            else None
        ),
        erstellt=d.erstellt,
        aktualisiert=d.aktualisiert,
    )


async def _laden(session: AsyncSession, dokument_id: str) -> Dokument:
    d = await session.get(Dokument, dokument_id)
    if d is None:
        raise HTTPException(404, "Dokument nicht gefunden")
    return d


async def _abschnitte(session: AsyncSession, d: Dokument) -> list[DokumentAbschnitt]:
    return list(
        (
            await session.execute(
                select(DokumentAbschnitt).where(DokumentAbschnitt.dokument_id == d.id).order_by(DokumentAbschnitt.reihenfolge)
            )
        )
        .scalars()
        .all()
    )


async def _chunks_je_abschnitt(session: AsyncSession, d: Dokument) -> dict[str, int]:
    rows = (
        await session.execute(
            select(Chunk.abschnitt_id, func.count(Chunk.id)).where(Chunk.dokument_id == d.id).group_by(Chunk.abschnitt_id)
        )
    ).all()
    return {str(a): int(n) for a, n in rows if a}


def _abschnitt_eintrag(a: DokumentAbschnitt, chunks: int) -> AbschnittEintrag:
    return AbschnittEintrag(
        id=a.id,
        reihenfolge=a.reihenfolge,
        ebene=a.ebene,
        titel=a.titel,
        zeichen=a.zeichen,
        anker=a.anker,
        seite_von=a.seite_von,
        seite_bis=a.seite_bis,
        chunks_anzahl=chunks,
    )


async def _detail(session: AsyncSession, d: Dokument) -> DokumentDetail:
    chunks = await _chunks_je_dokument(session, [d.id])
    abschnitte = await _abschnitte(session, d)
    je_abschnitt = await _chunks_je_abschnitt(session, d)
    offene = await _offene(session, [d.id])
    basis_eintrag = _eintrag(d, chunks.get(d.id, 0), len(abschnitte), offene.get(d.id))
    auftraege = (
        (await session.execute(select(Auftrag).where(Auftrag.dokument_id == d.id).order_by(Auftrag.erstellt.desc()).limit(10)))
        .scalars()
        .all()
    )
    return DokumentDetail(
        **basis_eintrag.model_dump(),
        beschreibung=d.beschreibung,
        notizen=d.notizen,
        prioritaet=d.prioritaet,
        felder_manuell=list(d.felder_manuell or []),
        metadaten_original=d.metadaten_original or {},
        abschnitte=[_abschnitt_eintrag(a, je_abschnitt.get(a.id, 0)) for a in abschnitte],
        auftraege=[
            AuftragKurz(
                id=a.id,
                art=a.art,
                art_titel=AUFTRAGSART_TITEL.get(Auftragsart(a.art), a.art),
                status=a.status,
                fortschritt=a.fortschritt,
                meldung=a.meldung,
                fehler=a.fehler,
                versuche=a.versuche,
                gestartet=a.gestartet,
                beendet=a.beendet,
                erstellt=a.erstellt,
            )
            for a in auftraege
        ],
    )


# ---------------------------------------------------------------- Liste und Arten
@router.get("/arten", response_model=list[ArtEintrag])
async def arten() -> list[ArtEintrag]:
    """Welche Dateiarten sich hochladen lassen."""
    je_art: dict[str, list[str]] = {}
    for endung, art in basis.ENDUNGEN.items():
        je_art.setdefault(art, []).append(endung)
    return [ArtEintrag(kennung=art, titel=basis.ARTEN_TITEL.get(art, art), endungen=sorted(endungen)) for art, endungen in je_art.items()]


@router.get("", response_model=DokumentSeite)
async def liste(
    q: str | None = None,
    art: str | None = None,
    stufe: str | None = None,
    seite: int = Query(1, ge=1),
    je_seite: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(sitzung_abhaengigkeit),
) -> DokumentSeite:
    basis_q = select(Dokument)
    if q:
        basis_q = basis_q.where(or_(Dokument.titel.ilike(f"%{q}%"), Dokument.autor.ilike(f"%{q}%"), Dokument.beschreibung.ilike(f"%{q}%")))
    if art:
        basis_q = basis_q.where(Dokument.art == art)
    if stufe:
        basis_q = basis_q.where(Dokument.stufe == stufe)
    gesamt = int(await session.scalar(select(func.count()).select_from(basis_q.subquery())) or 0)
    rows = (
        (await session.execute(basis_q.order_by(Dokument.erstellt.desc()).offset((seite - 1) * je_seite).limit(je_seite))).scalars().all()
    )
    ids = [d.id for d in rows]
    chunks = await _chunks_je_dokument(session, ids)
    abschnitte = await _abschnitte_je_dokument(session, ids)
    offene = await _offene(session, ids)
    return DokumentSeite(
        eintraege=[_eintrag(d, chunks.get(d.id, 0), abschnitte.get(d.id, 0), offene.get(d.id)) for d in rows],
        gesamt=gesamt,
        seite=seite,
        je_seite=je_seite,
    )


# ---------------------------------------------------------------- Anlegen
async def _automatik(session: AsyncSession) -> bool:
    return bool(await einstellungen_dienst.wert(session, "band.automatik"))


@router.post("/hochladen", response_model=DokumentDetail, status_code=201)
async def hochladen(
    datei: UploadFile = File(...), titel: str = "", session: AsyncSession = Depends(sitzung_abhaengigkeit)
) -> DokumentDetail:
    """EPUB, Markdown oder Text hochladen; das Dokument wird gelesen und bei Automatik gestückelt."""
    roh = await datei.read()
    try:
        d = await import_.anlegen_aus_datei(session, datei.filename or "dokument", roh, titel=titel, automatik=await _automatik(session))
    except basis.DokumentFehler as e:
        raise HTTPException(422, str(e)) from e
    await session.commit()
    bus.veroeffentliche("dokument", aktion="angelegt", dokument_id=d.id)
    return await _detail(session, d)


@router.post("/text", response_model=DokumentDetail, status_code=201)
async def eigener_text(e: EigenerText, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> DokumentDetail:
    """Eigenen Text (Markdown oder reiner Text) als Dokument anlegen."""
    try:
        d = await import_.anlegen_aus_text(session, e.titel, e.text, autor=e.autor, art=e.art, automatik=await _automatik(session))
    except basis.DokumentFehler as ex:
        raise HTTPException(422, str(ex)) from ex
    await session.commit()
    bus.veroeffentliche("dokument", aktion="angelegt", dokument_id=d.id)
    return await _detail(session, d)


# ---------------------------------------------------------------- Detail, Inhalt, Datei
@router.get("/{dokument_id}", response_model=DokumentDetail)
async def detail(dokument_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> DokumentDetail:
    return await _detail(session, await _laden(session, dokument_id))


@router.get("/{dokument_id}/inhalt", response_model=DokumentInhalt)
async def inhalt(dokument_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> DokumentInhalt:
    d = await _laden(session, dokument_id)
    je_abschnitt = await _chunks_je_abschnitt(session, d)
    return DokumentInhalt(
        id=d.id,
        titel=d.titel,
        abschnitte=[
            AbschnittText(**_abschnitt_eintrag(a, je_abschnitt.get(a.id, 0)).model_dump(), text=a.text)
            for a in await _abschnitte(session, d)
        ],
    )


@router.get("/{dokument_id}/datei", include_in_schema=False)
async def datei(dokument_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> FileResponse:
    d = await _laden(session, dokument_id)
    pfad = Path(d.datei_pfad) if d.datei_pfad else None
    if pfad is None or not pfad.exists():
        raise HTTPException(404, "Die Originaldatei liegt nicht mehr vor")
    return FileResponse(pfad, filename=d.dateiname or pfad.name)


# ---------------------------------------------------------------- Ändern, Aufträge, Löschen
@router.put("/{dokument_id}", response_model=DokumentDetail)
async def aendern(dokument_id: str, e: DokumentAenderung, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> DokumentDetail:
    d = await _laden(session, dokument_id)
    festgehalten = set(d.felder_manuell or [])
    werte: list[tuple[str, Any]] = []
    if e.titel is not None and e.titel.strip():
        werte.append(("titel", e.titel.strip()))
    if e.autor is not None:
        werte.append(("autor", e.autor.strip()))
    if e.sprache is not None and e.sprache.strip():
        werte.append(("sprache", e.sprache.strip()))
    if e.beschreibung is not None:
        werte.append(("beschreibung", e.beschreibung))
    if e.veroeffentlicht is not None:
        werte.append(("veroeffentlicht", e.veroeffentlicht))
    for attribut, wert in werte:
        setattr(d, attribut, wert)
        festgehalten.add(attribut)
    if e.handpflege_aufheben:
        festgehalten.clear()
    d.felder_manuell = sorted(festgehalten & set(PFLEGBARE_FELDER))
    if e.notizen is not None:
        d.notizen = e.notizen
    if e.prioritaet is not None:
        d.prioritaet = e.prioritaet
    await session.commit()
    bus.veroeffentliche("dokument", aktion="geaendert", dokument_id=d.id)
    return await _detail(session, d)


@router.post("/{dokument_id}/auftrag/{art}", response_model=AuftragAngelegt)
async def auftrag(dokument_id: str, art: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> AuftragAngelegt:
    d = await _laden(session, dokument_id)
    try:
        a_art = Auftragsart(art)
    except ValueError as e:
        raise HTTPException(422, f"Unbekannte Auftragsart '{art}'") from e
    if a_art not in DOKUMENT_AUFTRAGSARTEN:
        raise HTTPException(422, f"{AUFTRAGSART_TITEL[a_art]} gibt es für Dokumente nicht")
    noetig = dokument_vorstufe(a_art)
    if dokumentstufen_index(Dokumentstufe(d.stufe)) < dokumentstufen_index(noetig):
        raise HTTPException(
            409,
            f"{AUFTRAGSART_TITEL[a_art]} braucht mindestens die Stufe '{DOKUMENT_STUFEN_TITEL[noetig]}', "
            f"das Dokument steht auf '{DOKUMENT_STUFEN_TITEL[Dokumentstufe(d.stufe)]}'",
        )
    a = await auftrag_anlegen(session, a_art, None, prioritaet=d.prioritaet, dokument_id=d.id)
    await session.commit()
    if a is None:
        raise HTTPException(409, "Ein solcher Auftrag wartet bereits oder läuft")
    return AuftragAngelegt(auftrag_id=a.id, dokument_id=d.id, art=a.art, art_titel=AUFTRAGSART_TITEL[a_art], status=a.status)


@router.delete("/{dokument_id}", status_code=204)
async def loeschen(dokument_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> None:
    """Entfernt das Dokument samt Abschnitten, Stücken, Einbettungen, Aufträgen und Originaldatei."""
    d = await _laden(session, dokument_id)
    pfad = Path(d.datei_pfad) if d.datei_pfad else None
    await session.delete(d)
    await session.commit()
    if pfad is not None and pfad.exists():
        pfad.unlink()
    bus.veroeffentliche("dokument", aktion="geloescht", dokument_id=dokument_id)
