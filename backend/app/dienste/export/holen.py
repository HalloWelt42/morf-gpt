"""Übergabe holen: Manifest lesen (Webadresse oder Ordner), Teile laden und gegen die Prüfsummen
prüfen, Bibliothekspaket importieren, Audio und Modelle ablegen.

Der Empfänger gibt nur eine Adresse an. Bei einer Webadresse werden die Teile in den Eingang
unter data/uebergabe/eingang/<kennung> geladen (abgebrochene Downloads setzen dort fort, weil
der Server Bereiche liefert); bei einem Ordner auf dem Rechner werden die Dateien an Ort und
Stelle geprüft und gelesen, nichts wird kopiert.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import tarfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

import httpx
from pydantic import BaseModel
from sqlalchemy import select

from ...db.engine import sitzung
from ...db.modelle import Audio, Video
from ..audio import bezug
from . import paket
from .uebergabe import (
    AUDIO_ORDNER,
    FORMAT_KENNUNG,
    FORMAT_VERSION,
    MANIFEST,
    Teil,
    UebergabeFehler,
    Uebergabemanifest,
    sha256_datei,
)

log = logging.getLogger(__name__)

LESE_BLOCK = 4 * 1024 * 1024
VERBINDUNG_S = 20.0
LESEN_S = 120.0
_AUDIO_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}\.[a-z0-9]{1,5}$")
_TEILNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")

Fortschrittsmelder = Callable[[float, str], Awaitable[None]]


class Holergebnis(BaseModel):
    kennung: str
    version: str
    geladen_bytes: int = 0
    bibliothek: paket.ImportErgebnis
    audio_dateien: int = 0
    audio_neu: int = 0
    modelle_dateien: int = 0
    modelle: list[str] = []


async def _melde(melde: Fortschrittsmelder | None, anteil: float, meldung: str) -> None:
    if melde is not None:
        await melde(anteil, meldung)


def _groesse(byte: int) -> str:
    if byte >= 1024**3:
        return f"{byte / 1024**3:.2f} GB".replace(".", ",")
    return f"{byte / 1024**2:.1f} MB".replace(".", ",")


def pruefe_teilname(name: str) -> str:
    if not _TEILNAME.match(name) or ".." in name:
        raise UebergabeFehler(f"Ungültiger Dateiname im Manifest: '{name}'")
    return name


# --------------------------------------------------------------------------- Herkunft
class Herkunft(Protocol):
    """Woher die Übergabe kommt: liefert das Manifest und jede Datei als Pfad auf diesem Rechner."""

    def beschreibung(self) -> str: ...

    async def manifest(self) -> Uebergabemanifest: ...

    async def datei(self, teil: Teil, melde: Fortschrittsmelder | None, von: float, bis: float) -> Path: ...

    def aufraeumen(self) -> None: ...


class OrdnerHerkunft:
    """Ein Ordner auf diesem Rechner (etwa von einem Datenträger); Dateien bleiben liegen."""

    def __init__(self, ordner: Path) -> None:
        self._ordner = ordner

    def beschreibung(self) -> str:
        return str(self._ordner)

    async def manifest(self) -> Uebergabemanifest:
        datei = self._ordner / MANIFEST
        if not datei.is_file():
            raise UebergabeFehler(f"Im Ordner {self._ordner} liegt kein {MANIFEST}")
        try:
            return Uebergabemanifest.model_validate_json(datei.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise UebergabeFehler(f"Das Manifest ist unlesbar: {e}") from e

    async def datei(self, teil: Teil, melde: Fortschrittsmelder | None, von: float, bis: float) -> Path:
        pfad = self._ordner / pruefe_teilname(teil.name)
        if not pfad.is_file():
            raise UebergabeFehler(f"Die Datei {teil.name} fehlt im Ordner")
        return pfad

    def aufraeumen(self) -> None:
        return None


class WebHerkunft:
    """Eine Webadresse, unter der der Übergabeordner liegt; Teile werden in den Eingang geladen."""

    def __init__(self, adresse: str, eingang: Path, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._basis = adresse if adresse.endswith("/") else adresse + "/"
        self._eingang_wurzel = eingang
        self._eingang: Path | None = None
        self._transport = transport

    def beschreibung(self) -> str:
        return self._basis

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=httpx.Timeout(LESEN_S, connect=VERBINDUNG_S), transport=self._transport, follow_redirects=True)

    async def manifest(self) -> Uebergabemanifest:
        try:
            async with self._client() as client:
                resp = await client.get(self._basis + MANIFEST)
        except httpx.HTTPError as e:
            raise UebergabeFehler(f"Die Adresse {self._basis} ist nicht erreichbar ({e.__class__.__name__})") from e
        if resp.status_code != 200:
            raise UebergabeFehler(f"Unter {self._basis} liegt kein {MANIFEST} (HTTP {resp.status_code})")
        try:
            manifest = Uebergabemanifest.model_validate_json(resp.content)
        except ValueError as e:
            raise UebergabeFehler(f"Das Manifest unter {self._basis} ist unlesbar: {e}") from e
        self._eingang = self._eingang_wurzel / manifest.kennung
        self._eingang.mkdir(parents=True, exist_ok=True)
        return manifest

    async def datei(self, teil: Teil, melde: Fortschrittsmelder | None, von: float, bis: float) -> Path:
        if self._eingang is None:
            raise UebergabeFehler("Erst das Manifest lesen")
        ziel = self._eingang / pruefe_teilname(teil.name)
        if ziel.is_file() and ziel.stat().st_size == teil.bytes:
            return ziel  # schon vollständig geladen; die Prüfsumme prüft der Aufrufer
        teilweise = ziel.with_name(ziel.name + ".teil")
        vorhanden = teilweise.stat().st_size if teilweise.is_file() else 0
        kopf = {"Range": f"bytes={vorhanden}-"} if vorhanden else {}
        try:
            async with self._client() as client, client.stream("GET", self._basis + teil.name, headers=kopf) as resp:
                if resp.status_code == 200:
                    vorhanden = 0
                    modus = "wb"
                elif resp.status_code == 206:
                    modus = "ab"
                else:
                    raise UebergabeFehler(f"{teil.name}: HTTP {resp.status_code}")
                geladen = vorhanden
                with teilweise.open(modus) as f:
                    async for block in resp.aiter_bytes(LESE_BLOCK):
                        f.write(block)
                        geladen += len(block)
                        anteil = von + (bis - von) * min(1.0, geladen / max(1, teil.bytes))
                        await _melde(melde, anteil, f"{teil.name}: {_groesse(geladen)} von {_groesse(teil.bytes)}")
        except httpx.HTTPError as e:
            raise UebergabeFehler(f"{teil.name}: Laden abgebrochen ({e.__class__.__name__}); ein neuer Versuch setzt fort") from e
        if teilweise.stat().st_size != teil.bytes:
            teilweise.unlink(missing_ok=True)
            raise UebergabeFehler(f"{teil.name}: {teilweise.stat().st_size if teilweise.exists() else 0} statt {teil.bytes} Byte geladen")
        teilweise.replace(ziel)
        return ziel

    def aufraeumen(self) -> None:
        if self._eingang is not None:
            shutil.rmtree(self._eingang, ignore_errors=True)


def herkunft_fuer(adresse: str, eingang: Path) -> Herkunft:
    adresse = adresse.strip()
    if adresse.startswith(("http://", "https://")):
        return WebHerkunft(adresse, eingang)
    pfad = Path(adresse).expanduser()
    if pfad.is_dir():
        return OrdnerHerkunft(pfad)
    raise UebergabeFehler("Die Adresse muss eine Webadresse (http:// oder https://) oder ein vorhandener Ordner sein")


# --------------------------------------------------------------------------- Ablegen
@dataclass(slots=True)
class Audioablage:
    dateien: int = 0
    neu: int = 0


def _sicherer_mitgliedsname(name: str, erwarteter_ordner: str | None) -> PurePosixPath:
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise UebergabeFehler(f"Unzulässiger Pfad im Archiv: {name}")
    if erwarteter_ordner is not None and (len(p.parts) != 2 or p.parts[0] != erwarteter_ordner):
        raise UebergabeFehler(f"Unerwarteter Eintrag im Audioarchiv: {name}")
    return p


def _audio_entpacken(archiv: Path, audio_verzeichnis: Path) -> list[Path]:
    audio_verzeichnis.mkdir(parents=True, exist_ok=True)
    abgelegt: list[Path] = []
    with tarfile.open(archiv, "r") as tar:
        for mitglied in tar:
            if not mitglied.isfile():
                continue
            p = _sicherer_mitgliedsname(mitglied.name, AUDIO_ORDNER)
            if not _AUDIO_NAME.match(p.name):
                raise UebergabeFehler(f"Unerwarteter Dateiname im Audioarchiv: {mitglied.name}")
            daten = tar.extractfile(mitglied)
            if daten is None:
                continue
            ziel = audio_verzeichnis / p.name
            with ziel.open("wb") as f:
                shutil.copyfileobj(daten, f, LESE_BLOCK)
            abgelegt.append(ziel)
    return abgelegt


async def _audio_eintragen(dateien: list[Path]) -> Audioablage:
    """Legt je abgelegter Datei die Audiozeile des Videos an oder frischt sie auf; Dateien ohne Video bleiben liegen."""
    ablage = Audioablage()
    async with sitzung() as s:
        for pfad in dateien:
            video_id = pfad.stem
            video = await s.get(Video, video_id)
            if video is None:
                continue
            zeile = await s.scalar(select(Audio).where(Audio.video_id == video_id))
            if zeile is None:
                zeile = Audio(video_id=video_id, pfad=bezug.pfad_speicherform(pfad))
                s.add(zeile)
                ablage.neu += 1
            zeile.pfad = bezug.pfad_speicherform(pfad)
            zeile.format = pfad.suffix.lstrip(".").lower()
            zeile.groesse_bytes = pfad.stat().st_size
            if zeile.dauer_s is None and video.dauer_s is not None:
                zeile.dauer_s = float(video.dauer_s)
            zeile.bezugsweg = "uebergabe"
            ablage.dateien += 1
        await s.commit()
    return ablage


def _modelle_entpacken(archiv: Path, modelle_verzeichnis: Path) -> int:
    modelle_verzeichnis.mkdir(parents=True, exist_ok=True)
    anzahl = 0
    with tarfile.open(archiv, "r") as tar:
        for mitglied in tar:
            if not mitglied.isfile():
                continue
            p = _sicherer_mitgliedsname(mitglied.name, None)
            ziel = modelle_verzeichnis.joinpath(*p.parts)
            ziel.parent.mkdir(parents=True, exist_ok=True)
            daten = tar.extractfile(mitglied)
            if daten is None:
                continue
            with ziel.open("wb") as f:
                shutil.copyfileobj(daten, f, LESE_BLOCK)
            anzahl += 1
    return anzahl


# --------------------------------------------------------------------------- Ablauf
async def hole(
    herkunft: Herkunft,
    *,
    ziel_bauen: Callable[[], Awaitable[tuple[paket.Datenziel, Callable[[], Awaitable[None]]]]],
    erwartete_dimension: int,
    audio_verzeichnis: Path,
    modelle_verzeichnis: Path,
    aufraeumen: bool = True,
    melde: Fortschrittsmelder | None = None,
) -> Holergebnis:
    """Holt eine Übergabe vollständig: Manifest, Teile (geprüft), Bibliothek, Audio, Modelle.

    `ziel_bauen` liefert das Datenziel des Imports und eine Funktion, die dessen Sitzung schließt.
    """
    await _melde(melde, 0.0, f"Manifest wird gelesen: {herkunft.beschreibung()}")
    manifest = await herkunft.manifest()
    if manifest.format != FORMAT_KENNUNG:
        raise UebergabeFehler(f"Unter der Adresse liegt keine Übergabe von morf-gpt (Kennung '{manifest.format}')")
    if manifest.format_version > FORMAT_VERSION:
        raise UebergabeFehler(f"Die Übergabe hat Formatversion {manifest.format_version}, diese Installation kennt {FORMAT_VERSION}")
    if not manifest.teile:
        raise UebergabeFehler("Die Übergabe enthält keine Teile")

    # Teile laden und prüfen: Anteil 0 bis 0,6, gewichtet nach Größe
    gesamt = max(1, manifest.gesamt_bytes)
    pfade: dict[str, Path] = {}
    geladen = 0
    for teil in manifest.teile:
        von = 0.6 * geladen / gesamt
        bis = 0.6 * (geladen + teil.bytes) / gesamt
        pfad = await herkunft.datei(teil, melde, von, bis)
        await _melde(melde, bis, f"{teil.name}: Prüfsumme wird geprüft")
        summe = await asyncio.to_thread(sha256_datei, pfad)
        if summe != teil.sha256:
            if isinstance(herkunft, WebHerkunft):
                pfad.unlink(missing_ok=True)
            raise UebergabeFehler(f"{teil.name}: Prüfsumme stimmt nicht (Datei beschädigt oder unvollständig); bitte erneut holen")
        pfade[teil.name] = pfad
        geladen += teil.bytes

    # Bibliothek importieren: 0,6 bis 0,85
    bibliothek = next((t for t in manifest.teile if t.art == "bibliothek"), None)
    if bibliothek is None:
        raise UebergabeFehler("Die Übergabe enthält kein Bibliothekspaket")

    async def melde_import(anteil: float, meldung: str) -> None:
        await _melde(melde, 0.6 + 0.25 * anteil, f"Bibliothek: {meldung}")

    ziel, schliessen = await ziel_bauen()
    try:
        ergebnis = await paket.importiere(pfade[bibliothek.name], ziel, erwartete_dimension=erwartete_dimension, melde=melde_import)
    finally:
        await schliessen()

    # Audio: 0,85 bis 0,95
    audio = Audioablage()
    audio_teile = [t for t in manifest.teile if t.art == "audio"]
    for nr, teil in enumerate(audio_teile, start=1):
        await _melde(melde, 0.85 + 0.1 * (nr - 1) / len(audio_teile), f"Audio: {teil.name} wird abgelegt ({nr} von {len(audio_teile)})")
        dateien = await asyncio.to_thread(_audio_entpacken, pfade[teil.name], audio_verzeichnis)
        stand = await _audio_eintragen(dateien)
        audio.dateien += stand.dateien
        audio.neu += stand.neu

    # Modelle: 0,95 bis 0,99
    modelle_dateien = 0
    for teil in (t for t in manifest.teile if t.art == "modelle"):
        await _melde(melde, 0.95, f"Modelle werden abgelegt: {', '.join(manifest.modelle)}")
        modelle_dateien += await asyncio.to_thread(_modelle_entpacken, pfade[teil.name], modelle_verzeichnis)

    if aufraeumen:
        herkunft.aufraeumen()
    await _melde(
        melde,
        1.0,
        f"Fertig: {ergebnis.videos_neu + ergebnis.videos_aktualisiert} Videos, {audio.dateien} Audiodateien, "
        f"{modelle_dateien} Modelldateien übernommen",
    )
    return Holergebnis(
        kennung=manifest.kennung,
        version=manifest.version,
        geladen_bytes=geladen,
        bibliothek=ergebnis,
        audio_dateien=audio.dateien,
        audio_neu=audio.neu,
        modelle_dateien=modelle_dateien,
        modelle=manifest.modelle,
    )
