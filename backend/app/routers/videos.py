"""Videos: Liste mit Filtern, Serien, Detail, Vorschaubild, Auswahl, Aufträge, Zurücksetzen."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import case, delete, desc, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import einstellungen
from ..db.engine import sitzung_abhaengigkeit
from ..db.modelle import Audio, Auftrag, Chunk, Einbettung, Korrektur, Quelle, Transkript, Video
from ..dienste.audio import bezug
from ..dienste.auftraege.laeufer import auftrag_anlegen, auftrag_fuer_naechste_stufe, laeufer
from ..dienste.einstellungen import dienst as einstellungen_dienst
from ..dienste.ereignisse import bus
from ..dienste.quellen import abgleich, lokal
from ..dienste.quellen.basis import QuellenFehler, QuellVideo
from ..domaene.fliessband import (
    AUFTRAGSART_TITEL,
    STUFEN_REIHENFOLGE,
    STUFEN_TITEL,
    Auftragsart,
    Auftragsstatus,
    Stufe,
    stufen_index,
    vorstufe,
)
from ..schemata.videos import (
    AudioInfo,
    AuftragAngelegt,
    AuftragKurz,
    AuswahlregelAusgabe,
    AuswahlRegelErgebnis,
    AuswahlStapelEingabe,
    AuswahlStapelErgebnis,
    GeloeschteArtefakte,
    KorrekturMeta,
    OffenerAuftrag,
    SerieEintrag,
    TranskriptMeta,
    VideoAenderung,
    VideoDetail,
    VideoEintrag,
    VideoSeite,
    ZuruecksetzErgebnis,
)

router = APIRouter(prefix="/videos", tags=["videos"])

SORTIERUNGEN = {
    "veroeffentlicht": Video.veroeffentlicht,
    "titel": Video.titel,
    "dauer": Video.dauer_s,
    "folge": Video.folge_nr,
    "stufe": Video.stufe,
    "aktualisiert": Video.aktualisiert,
}
OFFENE_STATUS = (Auftragsstatus.WARTEND, Auftragsstatus.LAEUFT)


def _miniatur_url(v: Video) -> str | None:
    """Nur das lokal gespeicherte Vorschaubild; nie eine fremde Bildadresse an den Browser geben."""
    if v.miniatur_pfad and Path(v.miniatur_pfad).exists():
        return f"/api/videos/{v.id}/miniatur"
    return None


def _eintrag(v: Video, hat_audio: bool, chunks: int, offener: Auftrag | None) -> VideoEintrag:
    return VideoEintrag(
        id=v.id,
        extern_id=v.extern_id,
        titel=v.titel,
        serie=v.serie,
        folge_nr=v.folge_nr,
        veroeffentlicht=v.veroeffentlicht,
        dauer_s=v.dauer_s,
        typ=v.typ,
        stufe=v.stufe,
        stufe_titel=STUFEN_TITEL.get(Stufe(v.stufe), v.stufe),
        ausgewaehlt=v.ausgewaehlt,
        auswahl_manuell=v.auswahl_manuell,
        fehler=v.fehler,
        original_url=v.original_url,
        miniatur_url=_miniatur_url(v),
        hat_audio=hat_audio,
        chunks_anzahl=chunks,
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
    )


async def _zusatz(session: AsyncSession, video_ids: list[str]) -> tuple[set[str], dict[str, int], dict[str, Auftrag]]:
    if not video_ids:
        return set(), {}, {}
    audio_ids = set((await session.execute(select(Audio.video_id).where(Audio.video_id.in_(video_ids)))).scalars().all())
    chunks = {
        vid: int(n)
        for vid, n in (
            await session.execute(
                select(Chunk.video_id, func.count(Chunk.id)).where(Chunk.video_id.in_(video_ids)).group_by(Chunk.video_id)
            )
        ).all()
    }
    offene: dict[str, Auftrag] = {}
    rows = (
        (
            await session.execute(
                select(Auftrag)
                .where(Auftrag.video_id.in_(video_ids), Auftrag.status.in_(OFFENE_STATUS))
                .order_by(desc(Auftrag.status == Auftragsstatus.LAEUFT), Auftrag.erstellt)
            )
        )
        .scalars()
        .all()
    )
    for a in rows:
        if a.video_id and a.video_id not in offene:
            offene[a.video_id] = a
    return audio_ids, chunks, offene


async def _laden(session: AsyncSession, video_id: str) -> Video:
    v = await session.get(Video, video_id)
    if v is None:
        raise HTTPException(404, "Video nicht gefunden")
    return v


@router.get("", response_model=VideoSeite)
async def liste(
    q: str | None = None,
    serie: str | None = None,
    stufe: str | None = None,
    ausgewaehlt: bool | None = None,
    typ: str | None = None,
    mit_fehler: bool | None = None,
    sortierung: str = Query("veroeffentlicht"),
    richtung: str = Query("ab", pattern="^(auf|ab)$"),
    seite: int = Query(1, ge=1),
    je_seite: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(sitzung_abhaengigkeit),
) -> VideoSeite:
    basis = select(Video)
    if q:
        basis = basis.where(or_(Video.titel.ilike(f"%{q}%"), Video.beschreibung.ilike(f"%{q}%"), Video.extern_id == q))
    if serie is not None:
        basis = basis.where(Video.serie == serie)
    if stufe:
        basis = basis.where(Video.stufe == stufe)
    if ausgewaehlt is not None:
        basis = basis.where(Video.ausgewaehlt.is_(ausgewaehlt))
    if typ:
        basis = basis.where(Video.typ == typ)
    if mit_fehler is not None:
        basis = basis.where(Video.fehler != "" if mit_fehler else Video.fehler == "")
    spalte = SORTIERUNGEN.get(sortierung)
    if spalte is None:
        raise HTTPException(422, f"Unbekannte Sortierung '{sortierung}'")
    if sortierung == "stufe":
        reihung = case({s.value: i for i, s in enumerate(STUFEN_REIHENFOLGE)}, value=Video.stufe, else_=literal_column("0"))
        ordnung = reihung.desc() if richtung == "ab" else reihung.asc()
    else:
        ordnung = spalte.desc().nulls_last() if richtung == "ab" else spalte.asc().nulls_last()
    gesamt = int(await session.scalar(select(func.count()).select_from(basis.subquery())) or 0)
    rows = (
        (await session.execute(basis.order_by(ordnung, Video.erstellt.desc()).offset((seite - 1) * je_seite).limit(je_seite)))
        .scalars()
        .all()
    )
    audio_ids, chunks, offene = await _zusatz(session, [v.id for v in rows])
    return VideoSeite(
        eintraege=[_eintrag(v, v.id in audio_ids, chunks.get(v.id, 0), offene.get(v.id)) for v in rows],
        gesamt=gesamt,
        seite=seite,
        je_seite=je_seite,
    )


@router.get("/serien", response_model=list[SerieEintrag])
async def serien(session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> list[SerieEintrag]:
    rows = (
        await session.execute(
            select(
                Video.serie,
                func.count(Video.id),
                func.sum(case((Video.ausgewaehlt.is_(True), 1), else_=0)),
                func.min(Video.folge_nr),
                func.max(Video.folge_nr),
            )
            .group_by(Video.serie)
            .order_by(func.count(Video.id).desc())
        )
    ).all()
    return [SerieEintrag(serie=s or "", anzahl=int(n), ausgewaehlt=int(a or 0), min_folge=mn, max_folge=mx) for s, n, a, mn, mx in rows]


def _regel_ausgabe(r: abgleich.Auswahlregeln) -> AuswahlregelAusgabe:
    return AuswahlregelAusgabe(
        mindest_dauer_s=r.mindest_dauer_s,
        hoechst_dauer_s=r.hoechst_dauer_s,
        typen=sorted(r.typen),
        nur_heruntergeladene=r.nur_heruntergeladene,
    )


@router.get("/auswahl/regel", response_model=AuswahlregelAusgabe)
async def auswahlregel(session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> AuswahlregelAusgabe:
    werte = await einstellungen_dienst.alle(session)
    r = abgleich.Auswahlregeln.aus_werten(werte)
    return _regel_ausgabe(r)


def _als_quellvideo(v: Video) -> QuellVideo:
    return QuellVideo(extern_id=v.extern_id, titel=v.titel, dauer_s=v.dauer_s, typ=v.typ, heruntergeladen=v.quelle_heruntergeladen)


async def _nach_auswahl(session: AsyncSession, v: Video, automatik: bool) -> tuple[int, int]:
    """Nach einer Auswahländerung: Folgeauftrag anlegen bzw. wartende Aufträge abbrechen."""
    angelegt = abgebrochen = 0
    if v.ausgewaehlt:
        if automatik and await auftrag_fuer_naechste_stufe(session, v) is not None:
            angelegt = 1
    else:
        rows = (
            (await session.execute(select(Auftrag).where(Auftrag.video_id == v.id, Auftrag.status == Auftragsstatus.WARTEND)))
            .scalars()
            .all()
        )
        for a in rows:
            a.status = Auftragsstatus.ABGEBROCHEN
            a.fehler = "Video aus dem Umfang genommen"
            abgebrochen += 1
    return angelegt, abgebrochen


@router.post("/auswahl/regel", response_model=AuswahlRegelErgebnis)
async def auswahlregel_anwenden(session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> AuswahlRegelErgebnis:
    """Wendet die Auswahlregel auf alle Videos an, die der Nutzer nicht von Hand entschieden hat."""
    werte = await einstellungen_dienst.alle(session)
    r = abgleich.Auswahlregeln.aus_werten(werte)
    automatik = bool(werte["band.automatik"])
    rows = (await session.execute(select(Video).where(Video.auswahl_manuell.is_(False)))).scalars().all()
    aufgenommen = entfernt = unveraendert = angelegt = abgebrochen = 0
    for v in rows:
        neu = abgleich.ist_im_umfang(_als_quellvideo(v), r)
        if neu == v.ausgewaehlt:
            unveraendert += 1
            continue
        v.ausgewaehlt = neu
        a, b = await _nach_auswahl(session, v, automatik)
        angelegt += a
        abgebrochen += b
        if neu:
            aufgenommen += 1
        else:
            entfernt += 1
    await session.commit()
    bus.veroeffentliche("video", aktion="auswahl", aufgenommen=aufgenommen, entfernt=entfernt)
    return AuswahlRegelErgebnis(
        regel=_regel_ausgabe(r),
        geprueft=len(rows),
        aufgenommen=aufgenommen,
        entfernt=entfernt,
        unveraendert=unveraendert,
        auftraege_angelegt=angelegt,
        auftraege_abgebrochen=abgebrochen,
    )


@router.post("/auswahl/stapel", response_model=AuswahlStapelErgebnis)
async def auswahl_stapel(e: AuswahlStapelEingabe, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> AuswahlStapelErgebnis:
    automatik = bool(await einstellungen_dienst.wert(session, "band.automatik"))
    rows = (await session.execute(select(Video).where(Video.id.in_(e.video_ids)))).scalars().all()
    geaendert = unveraendert = angelegt = abgebrochen = 0
    for v in rows:
        v.auswahl_manuell = True
        if v.ausgewaehlt == e.ausgewaehlt:
            unveraendert += 1
            continue
        v.ausgewaehlt = e.ausgewaehlt
        a, b = await _nach_auswahl(session, v, automatik)
        angelegt += a
        abgebrochen += b
        geaendert += 1
    await session.commit()
    bus.veroeffentliche("video", aktion="auswahl", geaendert=geaendert)
    return AuswahlStapelErgebnis(
        angefragt=len(e.video_ids),
        geaendert=geaendert,
        unveraendert=unveraendert,
        nicht_gefunden=len(e.video_ids) - len(rows),
        auftraege_angelegt=angelegt,
        auftraege_abgebrochen=abgebrochen,
    )


@router.get("/{video_id}", response_model=VideoDetail)
async def detail(video_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> VideoDetail:
    v = await _laden(session, video_id)
    audio_ids, chunks, offene = await _zusatz(session, [v.id])
    basis = _eintrag(v, v.id in audio_ids, chunks.get(v.id, 0), offene.get(v.id))
    audio = (await session.execute(select(Audio).where(Audio.video_id == v.id))).scalar_one_or_none()
    t = (
        await session.execute(
            select(Transkript)
            .where(Transkript.video_id == v.id, Transkript.aktuell.is_(True))
            .order_by(Transkript.erstellt.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    k = (
        await session.execute(
            select(Korrektur).where(Korrektur.video_id == v.id, Korrektur.aktuell.is_(True)).order_by(Korrektur.erstellt.desc()).limit(1)
        )
    ).scalar_one_or_none()
    auftraege = (
        (await session.execute(select(Auftrag).where(Auftrag.video_id == v.id).order_by(Auftrag.erstellt.desc()).limit(10))).scalars().all()
    )
    quelle = await session.get(Quelle, v.quelle_id) if v.quelle_id else None
    quelle_typ = quelle.typ if quelle else ""
    tubevault_url = ""
    if quelle_typ == "tubevault":
        tubevault_url = abgleich.tubevault_videoseite(await einstellungen_dienst.alle(session), v.extern_id)
    return VideoDetail(
        **basis.model_dump(),
        beschreibung=v.beschreibung,
        aufrufe=v.aufrufe,
        schlagworte=list(v.schlagworte or []),
        kanal_name=v.kanal_name,
        quelle_id=v.quelle_id,
        quelle_typ=quelle_typ,
        tubevault_url=tubevault_url,
        quelle_heruntergeladen=v.quelle_heruntergeladen,
        datei_pfad=str((v.metadaten_original or {}).get("pfad") or "") if quelle_typ == lokal.TYP_KENNUNG else "",
        felder_manuell=list(v.felder_manuell or []),
        prioritaet=v.prioritaet,
        notizen=v.notizen,
        metadaten_original=v.metadaten_original or {},
        audio=(
            AudioInfo(
                id=audio.id,
                pfad=audio.pfad,
                format=audio.format,
                dauer_s=audio.dauer_s,
                groesse_bytes=audio.groesse_bytes,
                abtastrate=audio.abtastrate,
                kanaele=audio.kanaele,
                bezugsweg=audio.bezugsweg,
                datei_vorhanden=bezug.pfad_aufloesen(audio.pfad).exists() if audio.pfad else False,
                erstellt=audio.erstellt,
            )
            if audio
            else None
        ),
        transkript=(
            TranskriptMeta(
                id=t.id,
                engine=t.engine,
                modell=t.modell,
                sprache=t.sprache,
                zeichen=len(t.volltext),
                segmente_anzahl=len(t.segmente or []),
                dauer_verarbeitung_s=t.dauer_verarbeitung_s,
                erstellt=t.erstellt,
            )
            if t
            else None
        ),
        korrektur=(
            KorrekturMeta(
                id=k.id,
                transkript_id=k.transkript_id,
                engine=k.engine,
                anbieter=k.anbieter,
                modell=k.modell,
                absaetze_anzahl=len(k.absaetze or []),
                themen=list(k.themen or []),
                zusammenfassung=k.zusammenfassung,
                aehnlichkeit=k.aehnlichkeit,
                bloecke_gesamt=k.bloecke_gesamt,
                bloecke_verworfen=k.bloecke_verworfen,
                dauer_verarbeitung_s=k.dauer_verarbeitung_s,
                manuell_bearbeitet=k.manuell_bearbeitet,
                erstellt=k.erstellt,
            )
            if k
            else None
        ),
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
        erstellt=v.erstellt,
        aktualisiert=v.aktualisiert,
    )


@router.get("/{video_id}/miniatur", include_in_schema=False)
async def miniatur(video_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> FileResponse:
    v = await _laden(session, video_id)
    pfad = Path(v.miniatur_pfad) if v.miniatur_pfad else einstellungen.miniaturen_verzeichnis / f"{v.extern_id}.jpg"
    if not pfad.exists():
        raise HTTPException(404, "Kein Vorschaubild gespeichert")
    return FileResponse(pfad, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


def _metadaten_pflegen(v: Video, e: VideoAenderung) -> None:
    """Überträgt die von Hand gepflegten Metadaten und merkt sie sich als festgehalten."""
    festgehalten = set(v.felder_manuell or [])
    werte: list[tuple[str, Any]] = []
    if e.titel is not None and e.titel.strip():
        werte.append(("titel", e.titel.strip()))
    if e.beschreibung is not None:
        werte.append(("beschreibung", e.beschreibung))
    if e.veroeffentlicht is not None:
        werte.append(("veroeffentlicht", e.veroeffentlicht))
    if e.dauer_s is not None:
        werte.append(("dauer_s", e.dauer_s))
    if e.typ is not None:
        werte.append(("typ", e.typ.strip().lower()))
    if e.original_url is not None:
        werte.append(("original_url", e.original_url.strip()))
    if e.kanal_name is not None:
        werte.append(("kanal_name", e.kanal_name.strip()))
    if e.serie is not None:
        werte.append(("serie", e.serie.strip()))
    if e.folge_nr is not None or e.folge_nr_loeschen:
        werte.append(("folge_nr", None if e.folge_nr_loeschen else e.folge_nr))
    if e.schlagworte is not None:
        werte.append(("schlagworte", [w.strip() for w in e.schlagworte if w.strip()]))
    for attribut, wert in werte:
        setattr(v, attribut, wert)
        festgehalten.add(attribut)
    if e.handpflege_aufheben:
        festgehalten.clear()
    v.felder_manuell = sorted(festgehalten & set(abgleich.PFLEGBARE_FELDER))


@router.put("/{video_id}", response_model=VideoDetail)
async def aendern(video_id: str, e: VideoAenderung, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> VideoDetail:
    v = await _laden(session, video_id)
    _metadaten_pflegen(v, e)
    if e.notizen is not None:
        v.notizen = e.notizen
    if e.prioritaet is not None:
        v.prioritaet = e.prioritaet
    if e.ausgewaehlt is not None:
        v.auswahl_manuell = True
        if v.ausgewaehlt != e.ausgewaehlt:
            v.ausgewaehlt = e.ausgewaehlt
            await _nach_auswahl(session, v, bool(await einstellungen_dienst.wert(session, "band.automatik")))
    await session.commit()
    bus.veroeffentliche("video", aktion="geaendert", video_id=v.id)
    return await detail(video_id, session)


@router.post("/{video_id}/miniatur", response_model=VideoDetail)
async def miniatur_hochladen(
    video_id: str, datei: UploadFile = File(...), session: AsyncSession = Depends(sitzung_abhaengigkeit)
) -> VideoDetail:
    """Eigenes Vorschaubild setzen (JPEG, PNG oder WebP); wird als JPEG abgelegt und bleibt beim Abgleich stehen."""
    v = await _laden(session, video_id)
    roh = await datei.read()
    if not roh:
        raise HTTPException(422, "Die Datei ist leer")
    if len(roh) > 20 * 1024 * 1024:
        raise HTTPException(413, "Das Bild ist größer als 20 Megabyte")
    verzeichnis = einstellungen.miniaturen_verzeichnis
    verzeichnis.mkdir(parents=True, exist_ok=True)
    zwischen = verzeichnis / f"{v.extern_id}.hochgeladen{Path(datei.filename or '').suffix.lower() or '.bin'}"
    zwischen.write_bytes(roh)
    try:
        jpeg = await lokal.bild_als_jpeg(zwischen)
    except QuellenFehler as e:
        raise HTTPException(422, f"Das Bild ist nicht lesbar: {e}") from e
    finally:
        zwischen.unlink(missing_ok=True)
    ziel = abgleich.miniatur_pfad(verzeichnis, v.extern_id)
    ziel.write_bytes(jpeg)
    v.miniatur_pfad = str(ziel)
    await session.commit()
    bus.veroeffentliche("video", aktion="geaendert", video_id=v.id)
    return await detail(video_id, session)


@router.post("/{video_id}/auftrag/{art}", response_model=AuftragAngelegt)
async def auftrag(video_id: str, art: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> AuftragAngelegt:
    v = await _laden(session, video_id)
    try:
        a_art = Auftragsart(art)
    except ValueError as err:
        raise HTTPException(422, f"Unbekannte Auftragsart '{art}'") from err
    if a_art == Auftragsart.QUELLE_ABGLEICH:
        raise HTTPException(422, "Der Abgleich gehört zur Quelle, nicht zum Video")
    noetig = vorstufe(a_art)
    if stufen_index(Stufe(v.stufe)) < stufen_index(noetig):
        raise HTTPException(
            409,
            f"{AUFTRAGSART_TITEL[a_art]} braucht mindestens die Stufe '{STUFEN_TITEL[noetig]}', "
            f"das Video steht auf '{STUFEN_TITEL[Stufe(v.stufe)]}'",
        )
    a = await auftrag_anlegen(session, a_art, v.id, prioritaet=10)
    if a is None:
        raise HTTPException(409, f"Für dieses Video wartet oder läuft bereits ein Auftrag '{AUFTRAGSART_TITEL[a_art]}'")
    await session.commit()
    return AuftragAngelegt(auftrag_id=a.id, video_id=v.id, art=a.art, art_titel=AUFTRAGSART_TITEL[a_art], status=a.status)


async def _artefakte_loeschen(session: AsyncSession, v: Video, ziel: Stufe) -> GeloeschteArtefakte:
    """Löscht alles oberhalb der Zielstufe (Datenbank und Dateien)."""
    g = GeloeschteArtefakte()
    zi = stufen_index(ziel)
    if zi < stufen_index(Stufe.EINGEBETTET):
        chunk_ids = select(Chunk.id).where(Chunk.video_id == v.id)
        g.einbettungen = int(await session.scalar(select(func.count(Einbettung.id)).where(Einbettung.chunk_id.in_(chunk_ids))) or 0)
        await session.execute(delete(Einbettung).where(Einbettung.chunk_id.in_(chunk_ids)))
    if zi < stufen_index(Stufe.GESTUECKELT):
        g.chunks = int(await session.scalar(select(func.count(Chunk.id)).where(Chunk.video_id == v.id)) or 0)
        await session.execute(delete(Chunk).where(Chunk.video_id == v.id))
    if zi < stufen_index(Stufe.KORRIGIERT):
        g.korrekturen = int(await session.scalar(select(func.count(Korrektur.id)).where(Korrektur.video_id == v.id)) or 0)
        await session.execute(delete(Korrektur).where(Korrektur.video_id == v.id))
    if zi < stufen_index(Stufe.TRANSKRIBIERT):
        g.transkripte = int(await session.scalar(select(func.count(Transkript.id)).where(Transkript.video_id == v.id)) or 0)
        await session.execute(delete(Transkript).where(Transkript.video_id == v.id))
    if zi < stufen_index(Stufe.AUDIO):
        audio = (await session.execute(select(Audio).where(Audio.video_id == v.id))).scalar_one_or_none()
        if audio is not None:
            p = bezug.pfad_aufloesen(audio.pfad)
            if p.exists():
                p.unlink()
                g.dateien += 1
            await session.delete(audio)
            g.audios = 1
    return g


@router.post("/{video_id}/zuruecksetzen/{stufe}", response_model=ZuruecksetzErgebnis)
async def zuruecksetzen(video_id: str, stufe: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> ZuruecksetzErgebnis:
    """Setzt das Video auf eine Stufe zurück und löscht die Ergebnisse oberhalb."""
    v = await _laden(session, video_id)
    try:
        ziel = Stufe(stufe)
    except ValueError as err:
        raise HTTPException(422, f"Unbekannte Stufe '{stufe}'") from err
    if stufen_index(ziel) >= stufen_index(Stufe(v.stufe)):
        raise HTTPException(409, f"Das Video steht auf '{STUFEN_TITEL[Stufe(v.stufe)]}' - Zurücksetzen geht nur auf eine niedrigere Stufe")
    abgebrochen = 0
    offene = (await session.execute(select(Auftrag).where(Auftrag.video_id == v.id, Auftrag.status.in_(OFFENE_STATUS)))).scalars().all()
    for a in offene:
        if a.status == Auftragsstatus.LAEUFT:
            await laeufer.abbrechen(a.id)
        a.status = Auftragsstatus.ABGEBROCHEN
        a.fehler = f"Video auf Stufe '{STUFEN_TITEL[ziel]}' zurückgesetzt"
        abgebrochen += 1
    vorher = v.stufe
    geloescht = await _artefakte_loeschen(session, v, ziel)
    v.stufe = ziel
    v.fehler = ""
    folge = None
    if bool(await einstellungen_dienst.wert(session, "band.automatik")):
        folge = await auftrag_fuer_naechste_stufe(session, v)
    await session.commit()
    bus.veroeffentliche("video", aktion="zurueckgesetzt", video_id=v.id, stufe=v.stufe)
    return ZuruecksetzErgebnis(
        video_id=v.id,
        stufe_vorher=vorher,
        stufe_nachher=v.stufe,
        geloescht=geloescht,
        auftraege_abgebrochen=abgebrochen,
        folgeauftrag_id=folge.id if folge else None,
    )


@router.delete("/{video_id}", status_code=204)
async def loeschen(video_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> None:
    v = await _laden(session, video_id)
    offene = (
        (await session.execute(select(Auftrag).where(Auftrag.video_id == v.id, Auftrag.status == Auftragsstatus.LAEUFT))).scalars().all()
    )
    for a in offene:
        await laeufer.abbrechen(a.id)
    await _artefakte_loeschen(session, v, Stufe.ENTDECKT)
    if v.miniatur_pfad and Path(v.miniatur_pfad).exists():
        Path(v.miniatur_pfad).unlink()
    await session.delete(v)
    await session.commit()
    bus.veroeffentliche("video", aktion="geloescht", video_id=video_id)
