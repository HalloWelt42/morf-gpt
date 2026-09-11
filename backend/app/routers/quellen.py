"""Quellen verwalten: anlegen (mit Kanalprüfung), ändern, entfernen, abgleichen, Vorschau."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.engine import sitzung_abhaengigkeit
from ..db.modelle import Quelle, Video
from ..dienste.auftraege.laeufer import auftrag_anlegen
from ..dienste.einstellungen import dienst as einstellungen_dienst
from ..dienste.ereignisse import bus
from ..dienste.quellen import abgleich, tubevault
from ..dienste.quellen.basis import QuellenFehler
from ..domaene.fliessband import Auftragsart

router = APIRouter(prefix="/quellen", tags=["quellen"])


class QuelleEingabe(BaseModel):
    """`basis_url`: bei lokalen Dateien das Verzeichnis; TubeVault nutzt die zentrale Adresse aus den
    Einstellungen (quelle.tubevault_api). `kanal_id` nur bei TubeVault."""

    typ: str = "tubevault"
    name: str = Field(min_length=1, max_length=200)
    basis_url: str = ""
    kanal_id: str = ""
    regeln: dict[str, Any] = Field(default_factory=dict)
    aktiv: bool = True


class QuelleAenderung(BaseModel):
    name: str | None = None
    basis_url: str | None = None
    kanal_id: str | None = None
    regeln: dict[str, Any] | None = None
    aktiv: bool | None = None


class KanalPruefung(BaseModel):
    typ: str = "tubevault"
    basis_url: str = ""
    kanal_id: str = ""


class KanalAusgabe(BaseModel):
    kanal_id: str
    name: str
    beschreibung: str
    videos_gesamt: int | None
    videos_heruntergeladen: int | None


class QuelleAusgabe(BaseModel):
    id: str
    typ: str
    typ_titel: str
    name: str
    basis_url: str  # bei TubeVault die zentrale Adresse aus den Einstellungen
    adresse_zentral: bool
    kanal_id: str
    kanal_name: str
    kanal_beschreibung: str
    regeln: dict[str, Any]
    aktiv: bool
    zuletzt_abgeglichen: datetime | None
    erstellt: datetime
    videos: int
    videos_ausgewaehlt: int


class VorschauEintrag(BaseModel):
    extern_id: str
    titel: str
    veroeffentlicht: datetime | None
    dauer_s: int | None
    typ: str
    heruntergeladen: bool
    wuerde_aufgenommen: bool
    bekannt: bool


class VorschauSeite(BaseModel):
    eintraege: list[VorschauEintrag]
    gesamt: int
    seite: int
    je_seite: int


class AuftragAusgabe(BaseModel):
    auftrag_id: str | None
    hinweis: str


async def _ausgabe(s: AsyncSession, q: Quelle) -> QuelleAusgabe:
    videos = int(await s.scalar(select(func.count(Video.id)).where(Video.quelle_id == q.id)) or 0)
    ausgewaehlt = int(await s.scalar(select(func.count(Video.id)).where(Video.quelle_id == q.id, Video.ausgewaehlt.is_(True))) or 0)
    zentral = q.typ == tubevault.TYP_KENNUNG
    adresse = q.basis_url
    if zentral:
        werte = await einstellungen_dienst.alle(s)
        adresse = str(werte.get("quelle.tubevault_api") or "")
    return QuelleAusgabe(
        id=q.id,
        typ=q.typ,
        typ_titel=abgleich.TYPEN.get(q.typ, q.typ),
        name=q.name,
        basis_url=adresse,
        adresse_zentral=zentral,
        kanal_id=q.kanal_id,
        kanal_name=q.kanal_name,
        kanal_beschreibung=q.kanal_beschreibung,
        regeln=q.regeln or {},
        aktiv=q.aktiv,
        zuletzt_abgeglichen=q.zuletzt_abgeglichen,
        erstellt=q.erstellt,
        videos=videos,
        videos_ausgewaehlt=ausgewaehlt,
    )


async def _laden(s: AsyncSession, quelle_id: str) -> Quelle:
    q = await s.get(Quelle, quelle_id)
    if q is None:
        raise HTTPException(404, "Quelle nicht gefunden")
    return q


async def _kanal_pruefen(typ: str, basis_url: str, kanal_id: str, werte: dict[str, Any]) -> KanalAusgabe:
    try:
        videoquelle = abgleich.baue_quelle(typ, basis_url, kanal_id, werte)
    except QuellenFehler as e:
        raise HTTPException(422, str(e)) from e
    try:
        kanal = await videoquelle.kanal()
    except QuellenFehler as e:
        raise HTTPException(502, str(e)) from e
    finally:
        await videoquelle.schliessen()
    return KanalAusgabe(
        kanal_id=kanal.kanal_id,
        name=kanal.name,
        beschreibung=kanal.beschreibung,
        videos_gesamt=kanal.videos_gesamt,
        videos_heruntergeladen=kanal.videos_heruntergeladen,
    )


@router.get("", response_model=list[QuelleAusgabe])
async def alle(session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> list[QuelleAusgabe]:
    rows = (await session.execute(select(Quelle).order_by(Quelle.erstellt))).scalars().all()
    return [await _ausgabe(session, q) for q in rows]


@router.get("/typen", response_model=dict[str, str])
async def typen() -> dict[str, str]:
    """Bekannte Quellentypen (Kennung -> Titel)."""
    return dict(abgleich.TYPEN)


@router.post("/pruefen", response_model=KanalAusgabe)
async def pruefen(e: KanalPruefung, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> KanalAusgabe:
    """Kanal bei der Quelle nachschlagen, ohne etwas zu speichern."""
    werte = await einstellungen_dienst.alle(session)
    return await _kanal_pruefen(e.typ, e.basis_url.strip(), e.kanal_id.strip(), werte)


@router.post("", response_model=QuelleAusgabe, status_code=201)
async def anlegen(e: QuelleEingabe, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> QuelleAusgabe:
    werte = await einstellungen_dienst.alle(session)
    zentral = e.typ == tubevault.TYP_KENNUNG
    basis_url = "" if zentral else e.basis_url.strip().rstrip("/")
    if not zentral and not basis_url:
        raise HTTPException(422, "Lokale Dateien brauchen ein Verzeichnis")
    kanal = await _kanal_pruefen(e.typ, basis_url, e.kanal_id.strip(), werte)
    doppelt = await session.scalar(
        select(func.count(Quelle.id)).where(Quelle.typ == e.typ, Quelle.basis_url == basis_url, Quelle.kanal_id == e.kanal_id.strip())
    )
    if doppelt:
        raise HTTPException(409, "Diese Quelle ist bereits angelegt")
    q = Quelle(
        typ=e.typ,
        name=e.name.strip(),
        basis_url=basis_url,
        kanal_id=e.kanal_id.strip(),
        kanal_name=kanal.name,
        kanal_beschreibung=kanal.beschreibung,
        regeln=e.regeln,
        aktiv=e.aktiv,
    )
    session.add(q)
    await session.commit()
    bus.veroeffentliche("quelle", aktion="angelegt", quelle_id=q.id)
    return await _ausgabe(session, q)


@router.put("/{quelle_id}", response_model=QuelleAusgabe)
async def aendern(quelle_id: str, e: QuelleAenderung, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> QuelleAusgabe:
    q = await _laden(session, quelle_id)
    if e.name is not None:
        q.name = e.name.strip() or q.name
    if e.basis_url is not None and q.typ != tubevault.TYP_KENNUNG:
        q.basis_url = e.basis_url.strip().rstrip("/") or q.basis_url
    if e.kanal_id is not None:
        q.kanal_id = e.kanal_id.strip() or q.kanal_id
    if e.regeln is not None:
        q.regeln = e.regeln
    if e.aktiv is not None:
        q.aktiv = e.aktiv
    await session.commit()
    bus.veroeffentliche("quelle", aktion="geaendert", quelle_id=q.id)
    return await _ausgabe(session, q)


@router.delete("/{quelle_id}", status_code=204)
async def entfernen(quelle_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> None:
    """Entfernt die Quelle; ihre Videos bleiben erhalten (ohne Quellbezug)."""
    q = await _laden(session, quelle_id)
    videos = (await session.execute(select(Video).where(Video.quelle_id == q.id))).scalars().all()
    for v in videos:
        v.quelle_id = None
    await session.delete(q)
    await session.commit()
    bus.veroeffentliche("quelle", aktion="entfernt", quelle_id=quelle_id)


@router.post("/{quelle_id}/abgleich", response_model=AuftragAusgabe)
async def abgleich_starten(quelle_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> AuftragAusgabe:
    q = await _laden(session, quelle_id)
    if not q.aktiv:
        raise HTTPException(409, "Die Quelle ist deaktiviert")
    a = await auftrag_anlegen(session, Auftragsart.QUELLE_ABGLEICH, None, parameter={"quelle_id": q.id})
    await session.commit()
    if a is None:
        return AuftragAusgabe(auftrag_id=None, hinweis="Ein Abgleich wartet bereits oder läuft")
    return AuftragAusgabe(auftrag_id=a.id, hinweis="Abgleich angelegt")


@router.get("/{quelle_id}/vorschau", response_model=VorschauSeite)
async def vorschau(
    quelle_id: str,
    seite: int = Query(1, ge=1),
    je_seite: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(sitzung_abhaengigkeit),
) -> VorschauSeite:
    """Kanalvideos direkt aus der Quelle zeigen (ohne zu speichern), mit Auswahlvorhersage."""
    q = await _laden(session, quelle_id)
    werte = await einstellungen_dienst.alle(session)
    regeln = abgleich.Auswahlregeln.aus_werten(werte, q.regeln)
    try:
        videoquelle = abgleich.baue_quelle(q.typ, q.basis_url, q.kanal_id, werte)
    except QuellenFehler as e:
        raise HTTPException(422, str(e)) from e
    try:
        vs = await videoquelle.videoseite(seite, je_seite)
    except QuellenFehler as e:
        raise HTTPException(502, str(e)) from e
    finally:
        await videoquelle.schliessen()
    bekannte = set(
        (
            await session.execute(
                select(Video.extern_id).where(Video.quelle_id == q.id, Video.extern_id.in_([v.extern_id for v in vs.videos]))
            )
        )
        .scalars()
        .all()
    )
    return VorschauSeite(
        eintraege=[
            VorschauEintrag(
                extern_id=v.extern_id,
                titel=v.titel,
                veroeffentlicht=v.veroeffentlicht,
                dauer_s=v.dauer_s,
                typ=v.typ,
                heruntergeladen=v.heruntergeladen,
                wuerde_aufgenommen=abgleich.ist_im_umfang(v, regeln),
                bekannt=v.extern_id in bekannte,
            )
            for v in vs.videos
        ],
        gesamt=vs.gesamt,
        seite=vs.seite,
        je_seite=vs.je_seite,
    )
