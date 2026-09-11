"""Aufträge des Fließbands verwalten: Liste, Übersicht je Art, Detail, Protokoll,
abbrechen, wiederholen, aufräumen, Band auffüllen und Stufen pausieren.

Die reinen Helfer (Prüfung von Art und Status, Restzeit, Laufzeit, Abbruch eines
Auftrags) liegen hier, damit der Videos-Router dieselbe Logik nutzt.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import ColumnElement, delete, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.engine import sitzung_abhaengigkeit
from ..db.modelle import Auftrag, AuftragProtokoll, Video, jetzt
from ..dienste.auftraege.laeufer import band_auffuellen, laeufer
from ..dienste.einstellungen import dienst as einstellungen_dienst
from ..dienste.ereignisse import bus
from ..domaene.fliessband import (
    AUFTRAGSART_TITEL,
    STUFEN_TITEL,
    Auftragsart,
    Auftragsstatus,
    Stufe,
    stufen_index,
    vorstufe,
)
from ..schemata.auftraege import (
    AbbruchErgebnis,
    ArtUebersicht,
    AuffuellErgebnis,
    AufraeumErgebnis,
    AuftragDetail,
    AuftragEintrag,
    AuftragSeite,
    BandUebersicht,
    PauseEingabe,
    PauseErgebnis,
    ProtokollSeite,
    ProtokollZeile,
    WiederholenErgebnis,
)

router = APIRouter(prefix="/auftraege", tags=["auftraege"])

# Modul-Vorgaben, solange das Register keine eigene Einstellung dafür kennt
# (Vorschlag: band.durchsatz_fenster_s und band.aufraeumen_tage, siehe Bericht).
DURCHSATZ_FENSTER_S: int = 3600
AUFRAEUM_TAGE_VORGABE: int = 7

WIEDERHOLBARE_STATUS: tuple[Auftragsstatus, ...] = (Auftragsstatus.FEHLER, Auftragsstatus.ABGEBROCHEN)
OFFENE_STATUS: tuple[Auftragsstatus, ...] = (Auftragsstatus.WARTEND, Auftragsstatus.LAEUFT)
ERLEDIGTE_STATUS: tuple[Auftragsstatus, ...] = (Auftragsstatus.FERTIG, Auftragsstatus.ABGEBROCHEN)


# ------------------------------------------------------------------ reine Helfer
def auftragsart_pruefen(art: str) -> Auftragsart:
    """Auftragsart aus dem Pfad oder Filter; unbekannte Werte sind ein 422."""
    try:
        return Auftragsart(art)
    except ValueError as e:
        erlaubt = ", ".join(a.value for a in Auftragsart)
        raise HTTPException(422, f"Unbekannte Auftragsart '{art}' (erlaubt: {erlaubt})") from e


def status_pruefen(status: str) -> Auftragsstatus:
    try:
        return Auftragsstatus(status)
    except ValueError as e:
        erlaubt = ", ".join(s.value for s in Auftragsstatus)
        raise HTTPException(422, f"Unbekannter Status '{status}' (erlaubt: {erlaubt})") from e


def seiten_versatz(seite: int, je_seite: int) -> int:
    """Versatz der ersten Zeile einer Seite (Seiten zählen ab 1)."""
    return (seite - 1) * je_seite


def laufzeit_s(gestartet: datetime | None, beendet: datetime | None, bezug: datetime) -> float | None:
    """Sekunden zwischen Start und Ende; für laufende Aufträge bis zum Bezugszeitpunkt."""
    if gestartet is None:
        return None
    ende = beendet if beendet is not None else bezug
    return max(0.0, (ende - gestartet).total_seconds())


def restzeit_schaetzen(mittlere_dauer_s: float | None, wartend: int, parallel: int, laufend_rest: float = 0.0) -> float | None:
    """Geschätzte Restzeit einer Art: mittlere Dauer mal offene Arbeit geteilt durch Parallelität.

    `laufend_rest` ist die Summe der noch fehlenden Anteile laufender Aufträge (1 minus
    Fortschritt je Auftrag). Ohne Erfahrungswert oder ohne offene Arbeit gibt es keine Schätzung.
    """
    if mittlere_dauer_s is None or mittlere_dauer_s <= 0:
        return None
    offen = wartend + max(0.0, laufend_rest)
    if offen <= 0:
        return None
    return mittlere_dauer_s * offen / max(1, parallel)


def vorstufe_erfuellt(video_stufe: Stufe, art: Auftragsart) -> bool:
    """Ob ein Video weit genug ist, damit ein Auftrag dieser Art laufen kann."""
    if art == Auftragsart.QUELLE_ABGLEICH:
        return True
    return stufen_index(video_stufe) >= stufen_index(vorstufe(art))


def vorstufe_erklaerung(video_stufe: Stufe, art: Auftragsart) -> str:
    return (
        f"Das Video steht auf '{STUFEN_TITEL[video_stufe]}'; für '{AUFTRAGSART_TITEL[art]}' "
        f"muss es mindestens '{STUFEN_TITEL[vorstufe(art)]}' sein."
    )


# ------------------------------------------------------------------ Datenbank-Helfer
async def auftrag_abbrechen(s: AsyncSession, a: Auftrag, grund: str) -> bool:
    """Bricht einen wartenden oder laufenden Auftrag ab.

    Läuft der Auftrag in diesem Prozess, stößt der Läufer den Abbruch an und schreibt
    Abschluss, Protokoll und Ereignis selbst; der Status wird hier trotzdem sofort gesetzt,
    damit Folgeaufträge nicht an einem scheinbar noch offenen Auftrag scheitern.
    Gibt True zurück, wenn der Läufer den Abschluss übernimmt.
    """
    if a.status == Auftragsstatus.LAEUFT and await laeufer.abbrechen(a.id):
        a.status = Auftragsstatus.ABGEBROCHEN
        return True
    a.status = Auftragsstatus.ABGEBROCHEN
    a.beendet = jetzt()
    a.meldung = grund
    s.add(AuftragProtokoll(auftrag_id=a.id, stufe="warn", text=grund))
    bus.veroeffentliche("auftrag_status", auftrag_id=a.id, video_id=a.video_id, art=a.art, status=a.status, fehler=grund)
    return False


async def offene_auftraege_abbrechen(s: AsyncSession, video_id: str, grund: str, nur_wartende: bool) -> int:
    """Bricht die offenen Aufträge eines Videos ab und gibt die Anzahl zurück."""
    status = (Auftragsstatus.WARTEND,) if nur_wartende else OFFENE_STATUS
    rows = (await s.execute(select(Auftrag).where(Auftrag.video_id == video_id, Auftrag.status.in_(status)))).scalars().all()
    for a in rows:
        await auftrag_abbrechen(s, a, grund)
    return len(rows)


async def _auftrag_laden(s: AsyncSession, auftrag_id: str) -> Auftrag:
    a = await s.get(Auftrag, auftrag_id)
    if a is None:
        raise HTTPException(404, "Auftrag nicht gefunden")
    return a


def _wieder_einreihen(s: AsyncSession, a: Auftrag) -> None:
    a.status = Auftragsstatus.WARTEND
    a.versuche = 0
    a.fehler = ""
    a.meldung = "Erneut eingereiht"
    a.fortschritt = 0.0
    a.gestartet = None
    a.beendet = None
    a.herzschlag = None
    s.add(AuftragProtokoll(auftrag_id=a.id, stufe="info", text="Vom Nutzer erneut eingereiht"))
    bus.veroeffentliche("auftrag_status", auftrag_id=a.id, video_id=a.video_id, art=a.art, status=a.status)


def _eintrag(a: Auftrag, titel: str | None, serie: str | None, folge_nr: int | None, bezug: datetime) -> AuftragEintrag:
    return AuftragEintrag(
        id=a.id,
        art=a.art,
        art_titel=AUFTRAGSART_TITEL.get(Auftragsart(a.art), a.art),
        video_id=a.video_id,
        video_titel=titel or "",
        video_serie=serie or "",
        video_folge_nr=folge_nr,
        status=a.status,
        prioritaet=a.prioritaet,
        versuche=a.versuche,
        fortschritt=a.fortschritt,
        meldung=a.meldung,
        fehler=a.fehler,
        gestartet=a.gestartet,
        beendet=a.beendet,
        herzschlag=a.herzschlag,
        erstellt=a.erstellt,
        laufzeit_s=laufzeit_s(a.gestartet, a.beendet, bezug),
    )


async def _eintrag_mit_video(s: AsyncSession, a: Auftrag) -> AuftragEintrag:
    titel, serie, folge = "", "", None
    if a.video_id:
        video = await s.get(Video, a.video_id)
        if video is not None:
            titel, serie, folge = video.titel, video.serie, video.folge_nr
    return _eintrag(a, titel, serie, folge, jetzt())


# ------------------------------------------------------------------ Routen (feste Pfade zuerst)
@router.get("", response_model=AuftragSeite)
async def liste(
    status: str | None = None,
    art: str | None = None,
    video_id: str | None = None,
    seite: int = Query(1, ge=1),
    je_seite: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(sitzung_abhaengigkeit),
) -> AuftragSeite:
    """Aufträge seitenweise, neueste zuerst, mit Titel, Serie und Folge des Videos."""
    bedingungen: list[ColumnElement[bool]] = []
    if status:
        bedingungen.append(Auftrag.status == status_pruefen(status).value)
    if art:
        bedingungen.append(Auftrag.art == auftragsart_pruefen(art).value)
    if video_id:
        bedingungen.append(Auftrag.video_id == video_id)
    gesamt = int(await session.scalar(select(func.count(Auftrag.id)).where(*bedingungen)) or 0)
    q = (
        select(Auftrag, Video.titel, Video.serie, Video.folge_nr)
        .outerjoin(Video, Video.id == Auftrag.video_id)
        .where(*bedingungen)
        .order_by(Auftrag.erstellt.desc(), Auftrag.id.asc())
        .offset(seiten_versatz(seite, je_seite))
        .limit(je_seite)
    )
    rows = (await session.execute(q)).all()
    bezug = jetzt()
    eintraege = [_eintrag(a, titel, serie, folge, bezug) for a, titel, serie, folge in rows]
    return AuftragSeite(eintraege=eintraege, gesamt=gesamt, seite=seite, je_seite=je_seite)


@router.get("/uebersicht", response_model=BandUebersicht)
async def uebersicht(session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> BandUebersicht:
    """Je Auftragsart: Zähler je Status, Pause und Parallelität, Durchsatz im Fenster, Restzeit."""
    werte = await einstellungen_dienst.alle(session)
    grenze = jetzt() - timedelta(seconds=DURCHSATZ_FENSTER_S)

    zaehler: dict[tuple[str, str], int] = {
        (a, st): int(n)
        for a, st, n in (
            await session.execute(select(Auftrag.art, Auftrag.status, func.count(Auftrag.id)).group_by(Auftrag.art, Auftrag.status))
        ).all()
    }
    laufend_rest: dict[str, float] = {
        a: float(r or 0.0)
        for a, r in (
            await session.execute(
                select(Auftrag.art, func.sum(1.0 - Auftrag.fortschritt))
                .where(Auftrag.status == Auftragsstatus.LAEUFT)
                .group_by(Auftrag.art)
            )
        ).all()
    }
    durchsatz: dict[str, int] = {
        a: int(n)
        for a, n in (
            await session.execute(
                select(Auftrag.art, func.count(Auftrag.id))
                .where(Auftrag.status == Auftragsstatus.FERTIG, Auftrag.beendet.is_not(None), Auftrag.beendet >= grenze)
                .group_by(Auftrag.art)
            )
        ).all()
    }
    dauer_ausdruck = extract("epoch", Auftrag.beendet - Auftrag.gestartet)
    mittlere_dauer: dict[str, float] = {
        a: float(d)
        for a, d in (
            await session.execute(
                select(Auftrag.art, func.avg(dauer_ausdruck))
                .where(
                    Auftrag.status == Auftragsstatus.FERTIG,
                    Auftrag.gestartet.is_not(None),
                    Auftrag.beendet.is_not(None),
                )
                .group_by(Auftrag.art)
            )
        ).all()
        if d is not None
    }

    arten: list[ArtUebersicht] = []
    for art in Auftragsart:
        pausierbar = f"band.pause.{art.value}" in werte
        parallel = int(werte.get(f"band.parallel.{art.value}", 1))
        wartend = zaehler.get((art.value, Auftragsstatus.WARTEND.value), 0)
        laufend = zaehler.get((art.value, Auftragsstatus.LAEUFT.value), 0)
        dauer = mittlere_dauer.get(art.value)
        arten.append(
            ArtUebersicht(
                art=art.value,
                titel=AUFTRAGSART_TITEL[art],
                wartend=wartend,
                laufend=laufend,
                fertig=zaehler.get((art.value, Auftragsstatus.FERTIG.value), 0),
                fehler=zaehler.get((art.value, Auftragsstatus.FEHLER.value), 0),
                abgebrochen=zaehler.get((art.value, Auftragsstatus.ABGEBROCHEN.value), 0),
                pausiert=bool(werte.get(f"band.pause.{art.value}", False)),
                pausierbar=pausierbar,
                parallel=parallel,
                durchsatz_fenster=durchsatz.get(art.value, 0),
                mittlere_dauer_s=dauer,
                restzeit_s=restzeit_schaetzen(dauer, wartend, parallel, laufend_rest.get(art.value, 0.0)),
            )
        )
    return BandUebersicht(
        arten=arten,
        automatik=bool(werte.get("band.automatik", True)),
        laeufer_aktiv=laeufer.laeuft(),
        durchsatz_fenster_s=DURCHSATZ_FENSTER_S,
        wartend_gesamt=sum(a.wartend for a in arten),
        laufend_gesamt=sum(a.laufend for a in arten),
        fehler_gesamt=sum(a.fehler for a in arten),
    )


@router.post("/fehler/wiederholen", response_model=WiederholenErgebnis)
async def fehler_wiederholen(art: str | None = None, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> WiederholenErgebnis:
    """Alle fehlgeschlagenen Aufträge (wahlweise nur einer Art) erneut einreihen."""
    bedingungen: list[ColumnElement[bool]] = [Auftrag.status == Auftragsstatus.FEHLER]
    if art:
        bedingungen.append(Auftrag.art == auftragsart_pruefen(art).value)
    rows = (await session.execute(select(Auftrag).where(*bedingungen).order_by(Auftrag.erstellt))).scalars().all()
    for a in rows:
        _wieder_einreihen(session, a)
    await session.commit()
    return WiederholenErgebnis(anzahl=len(rows), auftrag_ids=[a.id for a in rows])


@router.delete("/erledigte", response_model=AufraeumErgebnis)
async def erledigte_loeschen(
    tage: int = Query(AUFRAEUM_TAGE_VORGABE, ge=0, le=3650),
    session: AsyncSession = Depends(sitzung_abhaengigkeit),
) -> AufraeumErgebnis:
    """Fertige und abgebrochene Aufträge löschen, die älter als `tage` Tage sind (0 = alle)."""
    grenze = jetzt() - timedelta(days=tage)
    zeitpunkt = func.coalesce(Auftrag.beendet, Auftrag.erstellt)
    ergebnis = await session.execute(
        delete(Auftrag).where(Auftrag.status.in_(ERLEDIGTE_STATUS), zeitpunkt < grenze).execution_options(synchronize_session=False)
    )
    await session.commit()
    geloescht = int(ergebnis.rowcount or 0)
    bus.veroeffentliche("auftraege", aktion="aufgeraeumt", anzahl=geloescht, tage=tage)
    return AufraeumErgebnis(geloescht=geloescht, tage=tage)


@router.post("/band/auffuellen", response_model=AuffuellErgebnis)
async def band_auffuellen_route(session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> AuffuellErgebnis:
    """Für alle ausgewählten Videos ohne offenen Auftrag den nächsten Schritt anlegen."""
    angelegt = await band_auffuellen(session)
    await session.commit()
    bus.veroeffentliche("auftraege", aktion="aufgefuellt", anzahl=angelegt)
    return AuffuellErgebnis(angelegt=angelegt)


@router.post("/band/pause", response_model=PauseErgebnis)
async def band_pause(e: PauseEingabe, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> PauseErgebnis:
    """Eine Stufe pausieren oder fortsetzen (Einstellung band.pause.<art>)."""
    art = auftragsart_pruefen(e.art)
    schluessel = f"band.pause.{art.value}"
    try:
        wert = await einstellungen_dienst.setze(session, schluessel, e.pausiert)
    except KeyError as fehler:
        raise HTTPException(422, f"Die Stufe '{AUFTRAGSART_TITEL[art]}' lässt sich nicht pausieren.") from fehler
    await session.commit()
    bus.veroeffentliche("einstellung", schluessel=schluessel, wert=wert)
    return PauseErgebnis(art=art.value, art_titel=AUFTRAGSART_TITEL[art], pausiert=bool(wert))


# ------------------------------------------------------------------ Routen mit Kennung
@router.get("/{auftrag_id}", response_model=AuftragDetail)
async def detail(auftrag_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> AuftragDetail:
    a = await _auftrag_laden(session, auftrag_id)
    eintrag = await _eintrag_mit_video(session, a)
    protokoll_anzahl = int(await session.scalar(select(func.count(AuftragProtokoll.id)).where(AuftragProtokoll.auftrag_id == a.id)) or 0)
    return AuftragDetail(**eintrag.model_dump(), parameter=a.parameter or {}, ergebnis=a.ergebnis or {}, protokoll_anzahl=protokoll_anzahl)


@router.get("/{auftrag_id}/protokoll", response_model=ProtokollSeite)
async def protokoll(
    auftrag_id: str,
    ab: int = Query(0, ge=0),
    anzahl: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(sitzung_abhaengigkeit),
) -> ProtokollSeite:
    """Protokollzeilen eines Auftrags, neueste zuerst."""
    await _auftrag_laden(session, auftrag_id)
    gesamt = int(await session.scalar(select(func.count(AuftragProtokoll.id)).where(AuftragProtokoll.auftrag_id == auftrag_id)) or 0)
    rows = (
        (
            await session.execute(
                select(AuftragProtokoll)
                .where(AuftragProtokoll.auftrag_id == auftrag_id)
                .order_by(AuftragProtokoll.zeit.desc(), AuftragProtokoll.id.desc())
                .offset(ab)
                .limit(anzahl)
            )
        )
        .scalars()
        .all()
    )
    eintraege = [ProtokollZeile(id=z.id, zeit=z.zeit, stufe=z.stufe, text=z.text) for z in rows]
    return ProtokollSeite(eintraege=eintraege, gesamt=gesamt, ab=ab, anzahl=anzahl)


@router.post("/{auftrag_id}/abbrechen", response_model=AbbruchErgebnis)
async def abbrechen(auftrag_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> AbbruchErgebnis:
    a = await _auftrag_laden(session, auftrag_id)
    if Auftragsstatus(a.status) not in OFFENE_STATUS:
        raise HTTPException(409, f"Der Auftrag ist bereits '{a.status}' und kann nicht abgebrochen werden.")
    ueber_laeufer = await auftrag_abbrechen(session, a, "Vom Nutzer abgebrochen")
    await session.commit()
    hinweis = "Abbruch angefordert; der Läufer beendet den Auftrag." if ueber_laeufer else "Auftrag abgebrochen."
    return AbbruchErgebnis(auftrag_id=a.id, status=a.status, hinweis=hinweis)


@router.post("/{auftrag_id}/wiederholen", response_model=AuftragEintrag)
async def wiederholen(auftrag_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> AuftragEintrag:
    """Fehlgeschlagenen oder abgebrochenen Auftrag erneut einreihen (Versuche auf 0)."""
    a = await _auftrag_laden(session, auftrag_id)
    if Auftragsstatus(a.status) not in WIEDERHOLBARE_STATUS:
        raise HTTPException(409, f"Nur fehlgeschlagene oder abgebrochene Aufträge lassen sich wiederholen (Status: '{a.status}').")
    art = Auftragsart(a.art)
    if a.video_id:
        video = await session.get(Video, a.video_id)
        if video is None:
            raise HTTPException(409, "Das Video dieses Auftrags existiert nicht mehr.")
        if not vorstufe_erfuellt(Stufe(video.stufe), art):
            raise HTTPException(409, vorstufe_erklaerung(Stufe(video.stufe), art))
    _wieder_einreihen(session, a)
    await session.commit()
    return await _eintrag_mit_video(session, a)
