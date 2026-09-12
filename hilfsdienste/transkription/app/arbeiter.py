"""Arbeiterpool: Prozesse, die je ein geladenes Modell halten und Dateien nacheinander
transkribieren. Mehrere Arbeiter arbeiten gleichzeitig; Aufträge über der Zahl der
Arbeiter warten in der Reihenfolge ihres Eintreffens.

Warum Prozesse: die Engines rechnen blockierend und halten Zustand auf der Grafikeinheit
oder im Prozessorspeicher. Ein eigener Prozess je Arbeiter hält den HTTP-Prozess
antwortfähig, trennt die Modelle sauber und überlebt den Absturz eines Arbeiters.

Anpassen der Zahl: aufwärts nur, wenn nach dem Laden die Speicherreserve frei bleibt
(Größe des Modells gemessen am ersten Arbeiter); abwärts beendet freie Arbeiter sofort
und beschäftigte nach ihrem laufenden Auftrag.

Abbruch: Wird ein laufender Auftrag abgebrochen (der Aufrufer hat aufgelegt), wird sein
Arbeiter beendet und ersetzt, damit die Grafikeinheit nicht minutenlang für niemanden
rechnet. Das kostet nur das erneute Laden des Modells.
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing as mp
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

from . import speicher
from .engines import wahl
from .engines.basis import EngineBeschreibung, Rohtranskript

log = logging.getLogger(__name__)

# Bis die Größe gemessen ist (erster Arbeiter lädt gerade), gilt diese Schätzung für große Modelle.
GROESSE_SCHAETZUNG_GB = 3.5


class ArbeiterFehler(RuntimeError):
    """Ein Arbeiter konnte nicht laden oder die Transkription schlug fehl."""


def _arbeiter_lauf(verbindung: Connection, beschreibung: EngineBeschreibung) -> None:
    """Hauptschleife eines Arbeiterprozesses: Modell laden, dann Aufträge abarbeiten bis None kommt."""
    try:
        engine = wahl.baue(beschreibung)
        engine.laden()
        verbindung.send(("bereit", engine.groesse_gb()))
    except Exception as e:  # noqa: BLE001 - alles zum Elternprozess melden
        verbindung.send(("fehler", f"{e.__class__.__name__}: {e}"))
        return
    while True:
        try:
            auftrag = verbindung.recv()
        except EOFError:
            return
        if auftrag is None:
            return
        pfad, sprache_code, wortzeiten = auftrag
        try:
            ergebnis = engine.transkribiere(Path(pfad), sprache_code, wortzeiten)
            verbindung.send(("ergebnis", ergebnis, engine.speicher_gb()))
        except Exception as e:  # noqa: BLE001
            verbindung.send(("fehler", f"{e.__class__.__name__}: {e}", engine.speicher_gb()))


@dataclass(slots=True)
class Arbeiter:
    nummer: int
    prozess: Any
    verbindung: Connection
    zustand: str = "laedt"  # laedt | bereit | beschaeftigt | beendet
    groesse_gb: float = 0.0  # Modell nach dem Laden
    speicher_gb: float = 0.0  # nach dem letzten Auftrag: Modell plus behaltene Puffer
    auftraege: int = 0
    aktuell: str | None = None  # Datei des laufenden Auftrags
    seit: float | None = None  # Beginn des laufenden Auftrags (Uhrzeit)
    zuletzt: dict[str, Any] | None = None  # letzter Auftrag: datei, dauer_s, audio_s, fehler
    soll_enden: bool = False
    gestartet: float = field(default_factory=time.monotonic)
    gestartet_uhr: float = field(default_factory=time.time)

    def als_dict(self) -> dict[str, Any]:
        return {
            "nummer": self.nummer,
            "zustand": self.zustand,
            "groesse_gb": round(self.groesse_gb, 2),
            "speicher_gb": round(self.speicher_gb or self.groesse_gb, 2),
            "auftraege": self.auftraege,
            "pid": self.prozess.pid,
            "gestartet": datetime.fromtimestamp(self.gestartet_uhr, UTC).isoformat(timespec="seconds"),
            "aktuell": (
                {
                    "datei": self.aktuell,
                    "seit": datetime.fromtimestamp(self.seit, UTC).isoformat(timespec="seconds"),
                    "laeuft_s": round(time.time() - self.seit, 1),
                }
                if self.aktuell and self.seit
                else None
            ),
            "zuletzt": self.zuletzt,
        }


class Arbeiterpool:
    def __init__(self, beschreibung: EngineBeschreibung, *, maximum: int, reserve_gb: float, ladefrist_s: float) -> None:
        self.beschreibung = beschreibung
        self._maximum = max(1, maximum)
        self._reserve_gb = reserve_gb
        self._ladefrist_s = ladefrist_s
        self._ctx = mp.get_context("spawn")
        self._alle: list[Arbeiter] = []
        self._naechste_nummer = 1
        self._gewuenscht = 1
        self._wartend = 0
        self._hinweise: list[str] = []
        self._bedingung = asyncio.Condition()
        self._anpass_sperre = asyncio.Lock()
        self._ersatz: asyncio.Task[list[str]] | None = None

    # ------------------------------------------------------------------ Stand
    @property
    def engine_kennung(self) -> str:
        return self.beschreibung.kennung

    @property
    def modell(self) -> str:
        return str(self.beschreibung.argumente.get("modell", ""))

    def lebendige(self) -> list[Arbeiter]:
        return [a for a in self._alle if a.zustand != "beendet" and not a.soll_enden]

    def bereite(self) -> int:
        return sum(1 for a in self.lebendige() if a.zustand in ("bereit", "beschaeftigt"))

    def groesse_gb(self) -> float:
        gemessen = [a.groesse_gb for a in self._alle if a.groesse_gb > 0]
        return max(gemessen) if gemessen else GROESSE_SCHAETZUNG_GB

    def stand(self) -> dict[str, Any]:
        return {
            "engine": self.engine_kennung,
            "modell": self.modell,
            "gewuenscht": self._gewuenscht,
            "maximum": self._maximum,
            "arbeiter": [a.als_dict() for a in self._alle if a.zustand != "beendet"],
            "wartend": self._wartend,
            "modell_groesse_gb": round(self.groesse_gb(), 2),
            "speicher": speicher.speicherstand().als_dict(),
            "hinweise": list(self._hinweise),
        }

    # ------------------------------------------------------------------ Anpassen
    async def anpassen(self, anzahl: int) -> list[str]:
        """Bringt die Zahl der Arbeiter auf anzahl (1 bis Maximum), soweit Speicher und Laden es erlauben."""
        async with self._anpass_sperre:
            anzahl = max(1, min(anzahl, self._maximum))
            self._gewuenscht = anzahl
            hinweise: list[str] = []
            while len(self.lebendige()) < anzahl:
                if self.lebendige():
                    erlaubt, hinweis = speicher.darf_laden(speicher.speicherstand(), self.groesse_gb(), self._reserve_gb)
                    if hinweis:
                        hinweise.append(hinweis)
                    if not erlaubt:
                        break
                arbeiter = await self._neuer_arbeiter()
                if arbeiter.zustand != "bereit":
                    hinweise.append(f"Arbeiter {arbeiter.nummer} konnte nicht laden: {self._letzter_fehler}")
                    break
            zu_viele = self.lebendige()[anzahl:]
            for arbeiter in reversed(zu_viele):
                await self._abbauen(arbeiter)
            self._hinweise = hinweise
            for h in hinweise:
                log.warning(h)
            return hinweise

    async def _neuer_arbeiter(self) -> Arbeiter:
        eltern, kind = self._ctx.Pipe(duplex=True)
        prozess = self._ctx.Process(target=_arbeiter_lauf, args=(kind, self.beschreibung), daemon=True, name="transkription-arbeiter")
        arbeiter = Arbeiter(nummer=self._naechste_nummer, prozess=prozess, verbindung=eltern)
        self._naechste_nummer += 1
        self._alle.append(arbeiter)
        prozess.start()
        kind.close()
        log.info("Arbeiter %d lädt %s (%s)", arbeiter.nummer, self.modell, self.engine_kennung)
        self._letzter_fehler = ""
        try:
            art, wert = await asyncio.wait_for(asyncio.to_thread(eltern.recv), self._ladefrist_s)
        except TimeoutError:
            art, wert = "fehler", f"Laden dauerte länger als {int(self._ladefrist_s)} Sekunden"
        except (EOFError, OSError) as e:
            art, wert = "fehler", f"Prozess endete beim Laden ({e.__class__.__name__})"
        if art != "bereit":
            self._letzter_fehler = str(wert)
            await self._beenden(arbeiter)
            return arbeiter
        arbeiter.groesse_gb = float(wert)
        async with self._bedingung:
            arbeiter.zustand = "bereit"
            self._bedingung.notify_all()
        ladezeit = time.monotonic() - arbeiter.gestartet
        log.info("Arbeiter %d bereit, Modell %.2f GB, Ladezeit %.1f s", arbeiter.nummer, arbeiter.groesse_gb, ladezeit)
        return arbeiter

    async def _abbauen(self, arbeiter: Arbeiter) -> None:
        async with self._bedingung:
            arbeiter.soll_enden = True
            frei = arbeiter.zustand == "bereit"
        if frei:
            await self._beenden(arbeiter)

    async def _beenden(self, arbeiter: Arbeiter) -> None:
        async with self._bedingung:
            arbeiter.zustand = "beendet"
        try:
            arbeiter.verbindung.send(None)
        except (OSError, ValueError):
            pass
        await asyncio.to_thread(arbeiter.prozess.join, 5)
        if arbeiter.prozess.is_alive():
            arbeiter.prozess.terminate()
        arbeiter.verbindung.close()
        log.info("Arbeiter %d beendet", arbeiter.nummer)

    async def beenden_alle(self) -> None:
        if self._ersatz is not None and not self._ersatz.done():
            self._ersatz.cancel()
        for arbeiter in list(self._alle):
            if arbeiter.zustand != "beendet":
                await self._beenden(arbeiter)

    # ------------------------------------------------------------------ Aufträge
    async def transkribiere(
        self, pfad: Path, sprache_code: str | None, wortzeiten: bool, anzeige: str | None = None
    ) -> tuple[Rohtranskript, Arbeiter]:
        """Transkribiert mit dem nächsten freien Arbeiter; gibt Ergebnis und Arbeiter (für die Herkunft) zurück.

        `anzeige` ist der Name, unter dem der Auftrag im Stand erscheint (Vorgabe: Dateiname).
        """
        name = anzeige or pfad.name
        if not self.lebendige():
            await self.anpassen(self._gewuenscht)
            if not self.lebendige():
                raise ArbeiterFehler("Kein Arbeiter verfügbar: " + "; ".join(self._hinweise or ["Modell konnte nicht geladen werden"]))
        arbeiter = await self._nehmen()
        arbeiter.aktuell, arbeiter.seit = name, time.time()
        start = time.monotonic()
        try:
            art, wert, speicher = await asyncio.to_thread(self._auftrag, arbeiter, pfad, sprache_code, wortzeiten)
            if speicher:
                arbeiter.speicher_gb = float(speicher)
        except asyncio.CancelledError:
            arbeiter.zuletzt = {"datei": name, "dauer_s": round(time.monotonic() - start, 1), "audio_s": None, "fehler": "abgebrochen"}
            await self._ersetzen(arbeiter)
            raise
        finally:
            arbeiter.aktuell, arbeiter.seit = None, None
            await self._zurueckgeben(arbeiter)
        dauer = round(time.monotonic() - start, 1)
        if art != "ergebnis":
            arbeiter.zuletzt = {"datei": name, "dauer_s": dauer, "audio_s": None, "fehler": str(wert)[:200]}
            raise ArbeiterFehler(str(wert))
        audio_s = round(wert.segmente[-1].end) if wert.segmente else 0
        arbeiter.zuletzt = {"datei": name, "dauer_s": dauer, "audio_s": audio_s, "fehler": ""}
        return wert, arbeiter

    async def _ersetzen(self, arbeiter: Arbeiter) -> None:
        """Beendet einen Arbeiter mitten im Auftrag (Abbruch) und ersetzt ihn im Hintergrund."""
        log.warning("Arbeiter %d wird abgebrochen und ersetzt", arbeiter.nummer)
        async with self._bedingung:
            arbeiter.zustand = "beendet"
        arbeiter.prozess.terminate()
        arbeiter.verbindung.close()
        self._ersatz = asyncio.create_task(self.anpassen(self._gewuenscht))

    async def _nehmen(self) -> Arbeiter:
        async with self._bedingung:
            self._wartend += 1
            try:
                while True:
                    for arbeiter in self._alle:
                        if arbeiter.zustand == "bereit" and not arbeiter.soll_enden:
                            arbeiter.zustand = "beschaeftigt"
                            return arbeiter
                    if not self.lebendige():
                        raise ArbeiterFehler("Kein Arbeiter verfügbar")
                    await self._bedingung.wait()
            finally:
                self._wartend -= 1

    @staticmethod
    def _auftrag(arbeiter: Arbeiter, pfad: Path, sprache_code: str | None, wortzeiten: bool) -> tuple[str, Any, float]:
        try:
            arbeiter.verbindung.send((str(pfad), sprache_code, wortzeiten))
            antwort = arbeiter.verbindung.recv()
            return antwort[0], antwort[1], float(antwort[2]) if len(antwort) > 2 else 0.0
        except (EOFError, OSError) as e:
            arbeiter.zustand = "beendet"
            return "fehler", f"Arbeiter {arbeiter.nummer} ist während der Transkription ausgefallen ({e.__class__.__name__})", 0.0

    async def _zurueckgeben(self, arbeiter: Arbeiter) -> None:
        arbeiter.auftraege += 1
        if arbeiter.zustand == "beendet":
            arbeiter.verbindung.close()
            async with self._bedingung:
                self._bedingung.notify_all()
            return
        if arbeiter.soll_enden:
            await self._beenden(arbeiter)
            async with self._bedingung:
                self._bedingung.notify_all()
            return
        async with self._bedingung:
            arbeiter.zustand = "bereit"
            self._bedingung.notify_all()
