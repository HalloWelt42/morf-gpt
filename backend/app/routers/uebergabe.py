"""Übergabe: einen Übergabeordner erstellen (Hintergrund), vorhandene Übergaben verwalten und ihre
Dateien ausliefern, eine Übergabe von einer Adresse holen (Hintergrund).

Beide Hintergrundläufe (erstellen, holen) melden ihren Fortschritt über den Ereignisbus
(Ereignisart "uebergabe"); je Richtung läuft höchstens einer zugleich.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..config import einstellungen
from ..db.engine import sitzungsfabrik
from ..dienste.ereignisse import bus
from ..dienste.export import holen, paket, uebergabe
from ..version import version_lesen

log = logging.getLogger(__name__)
router = APIRouter(prefix="/uebergabe", tags=["uebergabe"])


class ErstellenStart(BaseModel):
    mit_audio: bool = True
    mit_modellen: bool = True


class HolenStart(BaseModel):
    adresse: str = Field(min_length=1, max_length=2000)
    aufraeumen: bool = True


class Laufstatus(BaseModel):
    laeuft: bool
    gestartet: datetime | None
    fortschritt: float
    meldung: str
    fehler: str
    ergebnis: dict[str, Any] | None


class UebergabeInfo(BaseModel):
    kennung: str
    erstellt: datetime
    version: str
    gesamt_bytes: int
    teile: list[uebergabe.Teil]
    audio_dateien: int
    audio_bytes: int
    modelle: list[str]
    zaehler: paket.Zaehler
    ordner: str


class _Lauf:
    """Zustand eines Hintergrundlaufs (erstellen oder holen); lebt im Backend-Prozess."""

    def __init__(self, richtung: str) -> None:
        self.richtung = richtung
        self.task: asyncio.Task[None] | None = None
        self.gestartet: datetime | None = None
        self.fortschritt = 0.0
        self.meldung = ""
        self.fehler = ""
        self.ergebnis: dict[str, Any] | None = None

    def laeuft(self) -> bool:
        return self.task is not None and not self.task.done()

    def starten(self, arbeit: Callable[[], Awaitable[dict[str, Any]]], startmeldung: str) -> None:
        self.gestartet = datetime.now(UTC)
        self.fortschritt = 0.0
        self.meldung = startmeldung
        self.fehler = ""
        self.ergebnis = None
        self.task = asyncio.create_task(self._ausfuehren(arbeit), name=f"uebergabe-{self.richtung}")
        bus.veroeffentliche("uebergabe", richtung=self.richtung, status="laeuft", fortschritt=0.0, meldung=startmeldung)

    async def _ausfuehren(self, arbeit: Callable[[], Awaitable[dict[str, Any]]]) -> None:
        try:
            self.ergebnis = await arbeit()
        except Exception as e:  # Hintergrund-Task: jeder Fehler muss sichtbar werden, nicht still enden
            sprechend = isinstance(e, uebergabe.UebergabeFehler | paket.PaketFehler)
            self.fehler = str(e) if sprechend else f"{e.__class__.__name__}: {e}"[:2000]
            self.meldung = "Fehlgeschlagen"
            log.exception("Übergabe (%s) fehlgeschlagen", self.richtung)
            bus.veroeffentliche("uebergabe", richtung=self.richtung, status="fehler", fehler=self.fehler)
            return
        bus.veroeffentliche("uebergabe", richtung=self.richtung, status="fertig", ergebnis=self.ergebnis)

    async def melde(self, anteil: float, meldung: str) -> None:
        self.fortschritt = anteil
        self.meldung = meldung
        bus.veroeffentliche("uebergabe", richtung=self.richtung, status="laeuft", fortschritt=anteil, meldung=meldung)

    def status(self) -> Laufstatus:
        return Laufstatus(
            laeuft=self.laeuft(),
            gestartet=self.gestartet,
            fortschritt=self.fortschritt,
            meldung=self.meldung,
            fehler=self.fehler,
            ergebnis=self.ergebnis,
        )


_erstellen = _Lauf("erstellen")
_holen = _Lauf("holen")


def _eingang() -> Path:
    return einstellungen.uebergabe_verzeichnis / "eingang"


def _info(m: uebergabe.Uebergabemanifest) -> UebergabeInfo:
    return UebergabeInfo(
        kennung=m.kennung,
        erstellt=m.erstellt,
        version=m.version,
        gesamt_bytes=m.gesamt_bytes,
        teile=m.teile,
        audio_dateien=m.audio_dateien,
        audio_bytes=m.audio_bytes,
        modelle=m.modelle,
        zaehler=m.zaehler,
        ordner=str(einstellungen.uebergabe_verzeichnis / m.kennung),
    )


def _ordner(kennung: str) -> Path:
    try:
        kennung = uebergabe.pruefe_kennung(kennung)
    except uebergabe.UebergabeFehler as e:
        raise HTTPException(422, str(e)) from e
    ordner = einstellungen.uebergabe_verzeichnis / kennung
    if not (ordner / uebergabe.MANIFEST).is_file():
        raise HTTPException(404, f"Übergabe {kennung} nicht gefunden")
    return ordner


# --------------------------------------------------------------------------- Erstellen
@router.post("/erstellen", response_model=Laufstatus, status_code=202)
async def erstellen(eingabe: ErstellenStart) -> Laufstatus:
    if _erstellen.laeuft():
        raise HTTPException(409, "Es wird bereits eine Übergabe erstellt")

    async def arbeit() -> dict[str, Any]:
        quelle = paket.DatenbankQuelle(einstellungen.daten_verzeichnis, einstellungen.miniaturen_verzeichnis)
        ergebnis = await uebergabe.erstelle(
            quelle,
            einstellungen.uebergabe_verzeichnis,
            version=version_lesen()["version"],
            dimension=einstellungen.einbettung_dimension,
            mit_audio=eingabe.mit_audio,
            mit_modellen=eingabe.mit_modellen,
            modelle_verzeichnis=einstellungen.modelle_verzeichnis,
            melde=_erstellen.melde,
        )
        return _info(ergebnis.manifest).model_dump(mode="json")

    _erstellen.starten(arbeit, "Übergabe wird erstellt")
    return _erstellen.status()


@router.get("/erstellen/status", response_model=Laufstatus)
async def erstellen_status() -> Laufstatus:
    return _erstellen.status()


# --------------------------------------------------------------------------- Holen
@router.post("/holen", response_model=Laufstatus, status_code=202)
async def holen_starten(eingabe: HolenStart) -> Laufstatus:
    if _holen.laeuft():
        raise HTTPException(409, "Es wird bereits eine Übergabe geholt")
    try:
        herkunft = holen.herkunft_fuer(eingabe.adresse, _eingang())
    except uebergabe.UebergabeFehler as e:
        raise HTTPException(422, str(e)) from e

    async def ziel_bauen() -> tuple[paket.Datenziel, Callable[[], Awaitable[None]]]:
        session = sitzungsfabrik()()
        ziel = paket.DatenbankZiel(
            session, einstellungen.daten_verzeichnis, einstellungen.miniaturen_verzeichnis, einstellungen.dokumente_verzeichnis
        )

        async def schliessen() -> None:
            await session.close()

        return ziel, schliessen

    async def arbeit() -> dict[str, Any]:
        ergebnis = await holen.hole(
            herkunft,
            ziel_bauen=ziel_bauen,
            erwartete_dimension=einstellungen.einbettung_dimension,
            audio_verzeichnis=einstellungen.audio_verzeichnis,
            modelle_verzeichnis=einstellungen.modelle_verzeichnis,
            aufraeumen=eingabe.aufraeumen,
            melde=_holen.melde,
        )
        return ergebnis.model_dump(mode="json")

    _holen.starten(arbeit, f"Übergabe wird geholt: {herkunft.beschreibung()}")
    return _holen.status()


@router.get("/holen/status", response_model=Laufstatus)
async def holen_status() -> Laufstatus:
    return _holen.status()


# --------------------------------------------------------------------------- Vorhandene (feste Pfade oben, Kennungen unten)
@router.get("", response_model=list[UebergabeInfo])
async def liste() -> list[UebergabeInfo]:
    return [_info(m) for m in uebergabe.vorhandene(einstellungen.uebergabe_verzeichnis)]


@router.delete("/{kennung}", status_code=204)
async def loeschen(kennung: str) -> None:
    ordner = _ordner(kennung)
    await asyncio.to_thread(shutil.rmtree, ordner, True)
    bus.veroeffentliche("uebergabe", richtung="erstellen", status="geloescht", kennung=kennung)


@router.get("/{kennung}/{name}", response_class=FileResponse)
async def datei(kennung: str, name: str) -> FileResponse:
    """Liefert eine Datei der Übergabe (Manifest, Anleitung, Teile); damit lässt sich eine Übergabe auch
    direkt von diesem Rechner holen (Adresse: .../api/uebergabe/<kennung>/)."""
    ordner = _ordner(kennung)
    try:
        name = holen.pruefe_teilname(name)
    except uebergabe.UebergabeFehler as e:
        raise HTTPException(422, str(e)) from e
    pfad = ordner / name
    if not pfad.is_file():
        raise HTTPException(404, f"Datei '{name}' nicht gefunden")
    return FileResponse(pfad, filename=pfad.name)
