"""Der Auftragsläufer: nimmt wartende Aufträge vom Fließband und führt sie aus.

Eine Schleife im Backend-Prozess. Je Auftragsart gelten Parallelität und Pause aus
den Einstellungen. Jeder Auftrag läuft als eigene Task mit Herzschlag; Fehler werden
gespeichert und nach Einstellung wiederholt; nach Erfolg wird bei aktiver Automatik der
Auftrag der nächsten Stufe angelegt. Alle Zustandswechsel gehen als Ereignis an die
Oberfläche.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.engine import sitzung
from ...db.modelle import Auftrag, AuftragProtokoll, Dokument, Video
from ...domaene.fliessband import (
    DOKUMENT_STUFE_JE_AUFTRAG,
    VIDEO_AUFTRAGSARTEN,
    Auftragsart,
    Auftragsstatus,
    Dokumentstufe,
    Stufe,
    dokumentstufen_index,
    naechste_auftragsart,
    naechste_dokumentauftragsart,
    stufen_index,
)
from ..einstellungen import dienst as einstellungen_dienst
from ..ereignisse import bus
from . import stufen

log = logging.getLogger(__name__)


class AuftragKontext:
    """Was ein Stufen-Ausführer bekommt: Auftrag, Video, Einstellungen, Protokoll, Fortschritt."""

    def __init__(self, auftrag_id: str, video_id: str | None, werte: dict[str, Any], art: str, dokument_id: str | None = None) -> None:
        self.auftrag_id = auftrag_id
        self.video_id = video_id
        self.dokument_id = dokument_id
        self.werte = werte
        self.art = art
        self.abbruch = asyncio.Event()

    @property
    def werk_id(self) -> str | None:
        """Das Werk des Auftrags: Video oder Dokument."""
        return self.video_id or self.dokument_id

    def wert(self, schluessel: str) -> Any:
        return self.werte[schluessel]

    async def protokoll(self, text: str, stufe: str = "info") -> None:
        async with sitzung() as s:
            s.add(AuftragProtokoll(auftrag_id=self.auftrag_id, stufe=stufe, text=text))
            await s.commit()
        bus.veroeffentliche(
            "auftrag_protokoll", auftrag_id=self.auftrag_id, video_id=self.video_id, dokument_id=self.dokument_id, stufe=stufe, text=text
        )
        (log.warning if stufe == "fehler" else log.info)("[%s %s] %s", self.art, (self.werk_id or "")[:8], text)

    async def fortschritt(self, anteil: float, meldung: str = "") -> None:
        anteil = max(0.0, min(1.0, anteil))
        async with sitzung() as s:
            await s.execute(
                update(Auftrag)
                .where(Auftrag.id == self.auftrag_id)
                .values(fortschritt=anteil, meldung=meldung, herzschlag=datetime.now(UTC))
            )
            await s.commit()
        bus.veroeffentliche(
            "auftrag_fortschritt",
            auftrag_id=self.auftrag_id,
            video_id=self.video_id,
            dokument_id=self.dokument_id,
            art=self.art,
            fortschritt=anteil,
            meldung=meldung,
        )

    async def herzschlag(self) -> None:
        async with sitzung() as s:
            await s.execute(update(Auftrag).where(Auftrag.id == self.auftrag_id).values(herzschlag=datetime.now(UTC)))
            await s.commit()


class Laeufer:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._laufend: dict[str, asyncio.Task[None]] = {}
        self._kontexte: dict[str, AuftragKontext] = {}
        self._stopp = asyncio.Event()
        self._takt_s = 2.0

    # ------------------------------------------------------------------ Lebenszyklus
    NEUSTART_MELDUNG = "Backend neu gestartet - Auftrag wird erneut ausgeführt"

    async def start(self) -> None:
        if self._task is not None:
            return
        await self._verwaiste_zuruecksetzen()
        self._stopp.clear()
        self._task = asyncio.create_task(self._schleife(), name="auftragslaeufer")
        log.info("Auftragsläufer gestartet")

    async def stopp(self) -> None:
        self._stopp.set()
        for k in self._kontexte.values():
            k.abbruch.set()
        aufgaben = list(self._laufend.values())
        for t in aufgaben:
            t.cancel()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        # Erst die abgebrochenen Aufgaben ihr Zurückstellen schreiben lassen, dann den Rest
        # aufräumen; sonst überschreibt ihr Abschluss das Zurücksetzen (Auftrag blieb "abgebrochen").
        if aufgaben:
            await asyncio.gather(*aufgaben, return_exceptions=True)
        await self._verwaiste_zuruecksetzen()
        log.info("Auftragsläufer gestoppt")

    def laeuft(self) -> bool:
        return self._task is not None and not self._task.done()

    def aktive(self) -> list[str]:
        return list(self._laufend.keys())

    async def abbrechen(self, auftrag_id: str) -> bool:
        k = self._kontexte.get(auftrag_id)
        if k is None:
            return False
        k.abbruch.set()
        t = self._laufend.get(auftrag_id)
        if t is not None:
            t.cancel()
        return True

    async def _verwaiste_zuruecksetzen(self) -> None:
        """Nach einem Neustart: 'laeuft' ohne Prozess -> wieder 'wartend' (ehrlich, nicht fertig).

        Ebenso Aufträge, die ein Neustart als 'abgebrochen' hinterlassen hat (erkennbar an der
        Neustart-Meldung): sie hat kein Nutzer abgebrochen, sie gehören wieder in die Reihe.
        """
        async with sitzung() as s:
            bedingung = or_(
                Auftrag.status == Auftragsstatus.LAEUFT,
                and_(Auftrag.status == Auftragsstatus.ABGEBROCHEN, Auftrag.meldung == self.NEUSTART_MELDUNG),
            )
            rows = (await s.execute(select(Auftrag).where(bedingung))).scalars().all()
            for a in rows:
                text = "Backend beendet, Auftrag zurückgestellt" if a.status == Auftragsstatus.LAEUFT else "Nach Neustart wieder eingereiht"
                a.status = Auftragsstatus.WARTEND
                a.meldung = self.NEUSTART_MELDUNG
                a.fehler = ""
                a.beendet = None
                s.add(AuftragProtokoll(auftrag_id=a.id, stufe="warn", text=text))
            await s.commit()
            if rows:
                log.info("%d Aufträge nach dem Neustart wieder eingereiht", len(rows))

    async def _zurueckstellen(self, k: AuftragKontext) -> None:
        """Beim Herunterfahren: den laufenden Auftrag ohne Zählung eines Versuchs wieder einreihen."""
        async with sitzung() as s:
            a = await s.get(Auftrag, k.auftrag_id)
            if a is None or a.status not in (Auftragsstatus.LAEUFT, Auftragsstatus.WARTEND):
                return
            a.status = Auftragsstatus.WARTEND
            a.meldung = self.NEUSTART_MELDUNG
            a.fehler = ""
            a.beendet = None
            s.add(AuftragProtokoll(auftrag_id=a.id, stufe="warn", text="Backend beendet, Auftrag zurückgestellt"))
            await s.commit()

    # ------------------------------------------------------------------ Schleife
    async def _schleife(self) -> None:
        while not self._stopp.is_set():
            try:
                await self._runde()
            except asyncio.CancelledError:
                raise
            except Exception:  # der Läufer darf nie sterben
                log.exception("Fehler in der Läuferrunde")
            try:
                await asyncio.wait_for(self._stopp.wait(), timeout=self._takt_s)
            except TimeoutError:
                pass

    async def _runde(self) -> None:
        self._laufend = {k: t for k, t in self._laufend.items() if not t.done()}
        for k in list(self._kontexte):
            if k not in self._laufend:
                self._kontexte.pop(k, None)
        async with sitzung() as s:
            werte = await einstellungen_dienst.alle(s)
            await self._haengende_markieren(s, werte)
            for art in stufen.REGISTER:
                if art == Auftragsart.QUELLE_ABGLEICH:
                    grenze = 1
                    pausiert = False
                else:
                    grenze = int(werte.get(f"band.parallel.{art}", 1))
                    pausiert = bool(werte.get(f"band.pause.{art}", False))
                if pausiert:
                    continue
                aktiv = sum(1 for k, t in self._laufend.items() if self._kontexte[k].art == art)
                frei = grenze - aktiv
                if frei <= 0:
                    continue
                kandidaten = await self._naechste(s, art, frei, werte)
                for a in kandidaten:
                    a.status = Auftragsstatus.LAEUFT
                    a.gestartet = datetime.now(UTC)
                    a.herzschlag = a.gestartet
                    a.versuche += 1
                    a.fehler = ""
                    await s.commit()
                    self._starte(a, werte)

    async def _naechste(self, s: AsyncSession, art: str, anzahl: int, werte: dict[str, Any]) -> list[Auftrag]:
        # Ein Werk (Video oder Dokument) hat höchstens einen laufenden Auftrag (Stufen bauen aufeinander auf).
        laufende_werke = {self._kontexte[k].werk_id for k in self._laufend if self._kontexte[k].werk_id}
        q = (
            select(Auftrag)
            .outerjoin(Video, Video.id == Auftrag.video_id)
            .where(Auftrag.art == art, Auftrag.status == Auftragsstatus.WARTEND)
            .order_by(Auftrag.prioritaet.desc(), Video.prioritaet.desc().nulls_last())
        )
        if werte.get("quelle.serie_zuerst", True):
            kennung = str(werte.get("quelle.serien_kennung", "mmM"))
            q = q.order_by((Video.serie == kennung).desc().nulls_last())
        q = q.order_by(Video.veroeffentlicht.desc().nulls_last(), Auftrag.erstellt.asc()).limit(anzahl * 4)
        rows = (await s.execute(q)).scalars().all()
        aus: list[Auftrag] = []
        for a in rows:
            werk = a.video_id or a.dokument_id
            if werk and werk in laufende_werke:
                continue
            aus.append(a)
            if werk:
                laufende_werke.add(werk)
            if len(aus) >= anzahl:
                break
        return aus

    async def _haengende_markieren(self, s: AsyncSession, werte: dict[str, Any]) -> None:
        frist = int(werte.get("band.herzschlag_frist_s", 7200))
        grenze = datetime.now(UTC) - timedelta(seconds=frist)
        rows = (
            (
                await s.execute(
                    select(Auftrag).where(
                        and_(Auftrag.status == Auftragsstatus.LAEUFT, Auftrag.herzschlag.is_not(None), Auftrag.herzschlag < grenze)
                    )
                )
            )
            .scalars()
            .all()
        )
        for a in rows:
            if a.id in self._laufend:
                self._laufend[a.id].cancel()
            a.status = Auftragsstatus.FEHLER
            a.fehler = f"Kein Lebenszeichen seit {frist} Sekunden - als hängend markiert"
            a.beendet = datetime.now(UTC)
            s.add(AuftragProtokoll(auftrag_id=a.id, stufe="fehler", text=a.fehler))
            bus.veroeffentliche("auftrag_status", auftrag_id=a.id, video_id=a.video_id, art=a.art, status=a.status, fehler=a.fehler)
        if rows:
            await s.commit()

    # ------------------------------------------------------------------ Ausführung
    def _starte(self, a: Auftrag, werte: dict[str, Any]) -> None:
        k = AuftragKontext(a.id, a.video_id, werte, a.art, a.dokument_id)
        self._kontexte[a.id] = k
        self._laufend[a.id] = asyncio.create_task(self._ausfuehren(k, a.parameter or {}), name=f"auftrag-{a.art}-{a.id[:8]}")
        bus.veroeffentliche(
            "auftrag_status", auftrag_id=a.id, video_id=a.video_id, dokument_id=a.dokument_id, art=a.art, status=Auftragsstatus.LAEUFT
        )

    async def _ausfuehren(self, k: AuftragKontext, parameter: dict[str, Any]) -> None:
        ausfuehrer = stufen.REGISTER[Auftragsart(k.art)]
        try:
            await k.protokoll(f"Start: {stufen.TITEL[Auftragsart(k.art)]}")
            ergebnis = await ausfuehrer(k, parameter)
        except asyncio.CancelledError:
            if self._stopp.is_set():
                await self._zurueckstellen(k)
            else:
                await self._abschluss(k, Auftragsstatus.ABGEBROCHEN, fehler="Abgebrochen")
            raise
        except Exception as e:
            kurz = f"{e.__class__.__name__}: {e}"[:2000]
            log.debug("Auftrag %s fehlgeschlagen:\n%s", k.auftrag_id, traceback.format_exc())
            await self._abschluss(k, Auftragsstatus.FEHLER, fehler=kurz)
            return
        await self._abschluss(k, Auftragsstatus.FERTIG, ergebnis=ergebnis)

    async def _abschluss(self, k: AuftragKontext, status: Auftragsstatus, fehler: str = "", ergebnis: dict[str, Any] | None = None) -> None:
        async with sitzung() as s:
            a = await s.get(Auftrag, k.auftrag_id)
            if a is None:
                return
            wiederholungen = int(k.werte.get("band.wiederholungen", 2))
            if status == Auftragsstatus.FEHLER and a.versuche <= wiederholungen and not k.abbruch.is_set():
                a.status = Auftragsstatus.WARTEND
                a.fehler = fehler
                a.meldung = f"Fehlgeschlagen (Versuch {a.versuche} von {wiederholungen + 1}), wird wiederholt"
                s.add(AuftragProtokoll(auftrag_id=a.id, stufe="fehler", text=f"{fehler} - Wiederholung folgt"))
                await s.commit()
                bus.veroeffentliche("auftrag_status", auftrag_id=a.id, video_id=a.video_id, art=a.art, status=a.status, fehler=fehler)
                return
            a.status = status
            a.beendet = datetime.now(UTC)
            a.fehler = fehler
            if ergebnis is not None:
                a.ergebnis = ergebnis
            if status == Auftragsstatus.FERTIG:
                a.fortschritt = 1.0
                a.meldung = "Fertig"
                s.add(AuftragProtokoll(auftrag_id=a.id, stufe="info", text="Fertig"))
            else:
                s.add(AuftragProtokoll(auftrag_id=a.id, stufe="fehler", text=fehler or status))
            video = await s.get(Video, a.video_id) if a.video_id else None
            if video is not None:
                if status == Auftragsstatus.FERTIG:
                    neue = stufen.ZIELSTUFE.get(Auftragsart(a.art))
                    if neue is not None and stufen_index(Stufe(neue)) > stufen_index(Stufe(video.stufe)):
                        video.stufe = neue
                    video.fehler = ""
                elif status == Auftragsstatus.FEHLER:
                    video.fehler = f"{stufen.TITEL[Auftragsart(a.art)]}: {fehler}"[:2000]
            dokument = await s.get(Dokument, a.dokument_id) if a.dokument_id else None
            if dokument is not None:
                if status == Auftragsstatus.FERTIG:
                    neue_d = DOKUMENT_STUFE_JE_AUFTRAG.get(Auftragsart(a.art))
                    if neue_d is not None and dokumentstufen_index(neue_d) > dokumentstufen_index(Dokumentstufe(dokument.stufe)):
                        dokument.stufe = neue_d
                    dokument.fehler = ""
                elif status == Auftragsstatus.FEHLER:
                    dokument.fehler = f"{stufen.TITEL[Auftragsart(a.art)]}: {fehler}"[:2000]
            await s.commit()
            bus.veroeffentliche(
                "auftrag_status",
                auftrag_id=a.id,
                video_id=a.video_id,
                dokument_id=a.dokument_id,
                art=a.art,
                status=a.status,
                fehler=fehler,
                video_stufe=video.stufe if video else None,
                dokument_stufe=dokument.stufe if dokument else None,
            )
            if status == Auftragsstatus.FERTIG and k.werte.get("band.automatik", True):
                if video is not None:
                    await auftrag_fuer_naechste_stufe(s, video)
                if dokument is not None:
                    await auftrag_fuer_naechste_dokumentstufe(s, dokument)
                await s.commit()


async def auftrag_fuer_naechste_stufe(s: AsyncSession, video: Video) -> Auftrag | None:
    """Legt den Auftrag der nächsten Stufe an (falls nicht schon offen). Gibt ihn zurück."""
    if not video.ausgewaehlt:
        return None
    art = naechste_auftragsart(Stufe(video.stufe))
    if art is None:
        return None
    return await auftrag_anlegen(s, art, video.id)


async def auftrag_fuer_naechste_dokumentstufe(s: AsyncSession, dokument: Dokument) -> Auftrag | None:
    """Legt den Auftrag der nächsten Dokumentstufe an (falls nicht schon offen). Gibt ihn zurück."""
    art = naechste_dokumentauftragsart(Dokumentstufe(dokument.stufe))
    if art is None:
        return None
    return await auftrag_anlegen(s, art, None, prioritaet=dokument.prioritaet, dokument_id=dokument.id)


async def auftrag_anlegen(
    s: AsyncSession,
    art: Auftragsart,
    video_id: str | None,
    prioritaet: int = 0,
    parameter: dict[str, Any] | None = None,
    dokument_id: str | None = None,
) -> Auftrag | None:
    """Legt einen Auftrag an, wenn für dieses Werk (Video oder Dokument) und diese Art keiner wartet oder läuft."""
    if video_id is not None or dokument_id is not None:
        werk = Auftrag.video_id == video_id if video_id is not None else Auftrag.dokument_id == dokument_id
        offen = await s.scalar(
            select(func.count(Auftrag.id)).where(
                werk, Auftrag.art == art, Auftrag.status.in_([Auftragsstatus.WARTEND, Auftragsstatus.LAEUFT])
            )
        )
        if offen:
            return None
    a = Auftrag(art=art, video_id=video_id, dokument_id=dokument_id, prioritaet=prioritaet, parameter=parameter or {})
    s.add(a)
    await s.flush()
    bus.veroeffentliche("auftrag_status", auftrag_id=a.id, video_id=video_id, dokument_id=dokument_id, art=art, status=a.status)
    return a


async def band_auffuellen(s: AsyncSession) -> int:
    """Für alle ausgewählten Videos und alle Dokumente ohne offenen Auftrag den nächsten Schritt anlegen."""
    videos = (await s.execute(select(Video).where(Video.ausgewaehlt.is_(True)))).scalars().all()
    anzahl = 0
    for v in videos:
        if Stufe(v.stufe) == Stufe.EINGEBETTET:
            continue
        a = await auftrag_fuer_naechste_stufe(s, v)
        if a is not None:
            anzahl += 1
    dokumente = (await s.execute(select(Dokument).where(Dokument.stufe != Dokumentstufe.EINGEBETTET))).scalars().all()
    for d in dokumente:
        if await auftrag_fuer_naechste_dokumentstufe(s, d) is not None:
            anzahl += 1
    return anzahl


ALLE_VIDEO_ARTEN = VIDEO_AUFTRAGSARTEN

laeufer = Laeufer()
