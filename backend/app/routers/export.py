"""Umzug der Bibliothek: Paket schreiben (Hintergrund), Pakete verwalten, Paket einlesen.

Der Export läuft als Hintergrund-Task im Backend und meldet seinen Fortschritt über den
Ereignisbus (Ereignisart "export"); es läuft höchstens ein Export zugleich. Der Import
nimmt ein hochgeladenes Paket entgegen, legt es unter export/eingang ab, liest es in die
Datenbank und antwortet mit den Zählern.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import einstellungen
from ..db.engine import sitzung_abhaengigkeit
from ..dienste.ereignisse import bus
from ..dienste.export import paket
from ..version import version_lesen

log = logging.getLogger(__name__)

router = APIRouter(prefix="/export", tags=["export"])

# Stückgröße beim Ablegen eines hochgeladenen Pakets (technische Vorgabe, kein Nutzerregler).
UPLOAD_STUECK_BYTES = 1024 * 1024


class ExportStart(BaseModel):
    mit_transkripten: bool = False


class ExportStatus(BaseModel):
    laeuft: bool
    gestartet: datetime | None
    mit_transkripten: bool
    fortschritt: float
    meldung: str
    letzte_datei: str | None
    fehler: str


class PaketInfo(BaseModel):
    name: str
    groesse_bytes: int
    erstellt: datetime


class _Exportlauf:
    """Zustand des höchstens einen laufenden Exports (lebt im Backend-Prozess)."""

    def __init__(self) -> None:
        self.task: asyncio.Task[None] | None = None
        self.gestartet: datetime | None = None
        self.mit_transkripten = False
        self.fortschritt = 0.0
        self.meldung = ""
        self.letzte_datei: str | None = None
        self.fehler = ""

    def laeuft(self) -> bool:
        return self.task is not None and not self.task.done()

    def starten(self, mit_transkripten: bool) -> None:
        self.gestartet = datetime.now(UTC)
        self.mit_transkripten = mit_transkripten
        self.fortschritt = 0.0
        self.meldung = "Export gestartet"
        self.fehler = ""
        self.task = asyncio.create_task(_export_ausfuehren(mit_transkripten), name="export-bibliothek")

    def status(self) -> ExportStatus:
        return ExportStatus(
            laeuft=self.laeuft(),
            gestartet=self.gestartet,
            mit_transkripten=self.mit_transkripten,
            fortschritt=self.fortschritt,
            meldung=self.meldung,
            letzte_datei=self.letzte_datei,
            fehler=self.fehler,
        )


_lauf = _Exportlauf()


async def _melde_export(anteil: float, meldung: str) -> None:
    _lauf.fortschritt = anteil
    _lauf.meldung = meldung
    bus.veroeffentliche("export", status="laeuft", fortschritt=anteil, meldung=meldung)


async def _melde_import(anteil: float, meldung: str) -> None:
    bus.veroeffentliche("import", status="laeuft", fortschritt=anteil, meldung=meldung)


async def _export_ausfuehren(mit_transkripten: bool) -> None:
    quelle = paket.DatenbankQuelle(einstellungen.daten_verzeichnis, einstellungen.miniaturen_verzeichnis)
    try:
        ergebnis = await paket.exportiere(
            quelle,
            einstellungen.export_verzeichnis,
            version=version_lesen()["version"],
            dimension=einstellungen.einbettung_dimension,
            mit_transkripten=mit_transkripten,
            melde=_melde_export,
        )
    except Exception as e:  # Hintergrund-Task: jeder Fehler muss sichtbar werden, nicht still enden
        _lauf.fehler = f"{e.__class__.__name__}: {e}"[:2000]
        _lauf.meldung = "Export fehlgeschlagen"
        log.exception("Export der Bibliothek fehlgeschlagen")
        bus.veroeffentliche("export", status="fehler", fehler=_lauf.fehler)
        return
    _lauf.letzte_datei = ergebnis.datei.name
    bus.veroeffentliche(
        "export",
        status="fertig",
        datei=ergebnis.datei.name,
        groesse_bytes=ergebnis.groesse_bytes,
        zaehler=ergebnis.manifest.zaehler.model_dump(),
    )


def _paketpfad(name: str) -> Path:
    try:
        paket.pruefe_paketname(name)
    except paket.PaketFehler as e:
        raise HTTPException(422, str(e)) from e
    pfad = einstellungen.export_verzeichnis / name
    if not pfad.is_file():
        raise HTTPException(404, f"Paket '{name}' nicht gefunden")
    return pfad


def _paket_info(pfad: Path) -> PaketInfo:
    stat = pfad.stat()
    return PaketInfo(name=pfad.name, groesse_bytes=stat.st_size, erstellt=datetime.fromtimestamp(stat.st_mtime, UTC))


async def _upload_ablegen(datei: UploadFile) -> Path:
    """Schreibt den Upload stückweise nach export/eingang; der Name bleibt eindeutig."""
    eingang = einstellungen.export_verzeichnis / paket.EINGANG_ORDNER
    eingang.mkdir(parents=True, exist_ok=True)
    stempel = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    ziel = eingang / f"{stempel}-{paket.sicherer_dateiname(datei.filename)}"
    with ziel.open("wb") as f:
        while stueck := await datei.read(UPLOAD_STUECK_BYTES):
            f.write(stueck)
    return ziel


@router.post("/bibliothek", response_model=ExportStatus, status_code=202)
async def export_starten(eingabe: ExportStart) -> ExportStatus:
    if _lauf.laeuft():
        raise HTTPException(409, "Es läuft bereits ein Export der Bibliothek")
    _lauf.starten(eingabe.mit_transkripten)
    bus.veroeffentliche("export", status="laeuft", fortschritt=0.0, meldung=_lauf.meldung)
    return _lauf.status()


@router.get("/status", response_model=ExportStatus)
async def export_status() -> ExportStatus:
    return _lauf.status()


@router.get("/pakete", response_model=list[PaketInfo])
async def pakete() -> list[PaketInfo]:
    verzeichnis = einstellungen.export_verzeichnis
    if not verzeichnis.is_dir():
        return []
    dateien = [p for p in verzeichnis.glob(f"*{paket.PAKET_ENDUNG}") if p.is_file()]
    eintraege = [_paket_info(p) for p in dateien]
    eintraege.sort(key=lambda e: e.erstellt, reverse=True)
    return eintraege


@router.get("/pakete/{name}", response_class=FileResponse)
async def paket_laden(name: str) -> FileResponse:
    """Liefert die Paketdatei; kein Antwortmodell, weil der Körper die Datei selbst ist."""
    pfad = _paketpfad(name)
    return FileResponse(pfad, media_type="application/gzip", filename=pfad.name)


@router.delete("/pakete/{name}", status_code=204)
async def paket_loeschen(name: str) -> None:
    pfad = _paketpfad(name)
    pfad.unlink()
    bus.veroeffentliche("export", status="geloescht", datei=name)


@router.post("/import", response_model=paket.ImportErgebnis)
async def importieren(datei: UploadFile = File(...), session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> paket.ImportErgebnis:
    pfad = await _upload_ablegen(datei)
    ziel = paket.DatenbankZiel(session, einstellungen.daten_verzeichnis, einstellungen.miniaturen_verzeichnis)
    try:
        ergebnis = await paket.importiere(pfad, ziel, erwartete_dimension=einstellungen.einbettung_dimension, melde=_melde_import)
    except paket.PaketFehler as e:
        bus.veroeffentliche("import", status="fehler", fehler=str(e))
        raise HTTPException(422, str(e)) from e
    finally:
        pfad.unlink(missing_ok=True)
    bus.veroeffentliche("import", status="fertig", zaehler=ergebnis.model_dump(mode="json"))
    return ergebnis
