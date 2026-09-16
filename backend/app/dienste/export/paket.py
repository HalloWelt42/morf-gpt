"""Export und Import der Bibliothek als Paket (tar.gz).

Ein Paket trägt alles, was die Bibliothek zum Suchen und Antworten braucht: Videos mit
Metadaten, aktuelle Korrekturen, Chunks, Einbettungen, Vorschaubilder, wahlweise die
Rohtranskripte, dazu die Dokumente (zweite Werkart) mit Abschnitten, Stücken und
Originaldateien. Audio bleibt in der Werkstatt (docs/ARCHITEKTUR.md, Abschnitt 8); die
Übergabe (uebergabe.py) legt es als eigene Teile daneben.

Aufbau eines Pakets (die Reihenfolge ist verbindlich, der Leser arbeitet streamend):

    manifest.json            Version, Einbettungsmodelle, Dimension, Zähler
    videos.jsonl             eine Zeile je Video
    transkripte.jsonl        nur mit Schalter, nur aktuelle Transkripte
    korrekturen.jsonl        nur aktuelle Korrekturen
    chunks.jsonl             Stücke der Videos
    dokumente.jsonl          eine Zeile je Dokument (Formatversion 2)
    dokument_abschnitte.jsonl
    dokument_chunks.jsonl    Stücke der Dokumente
    einbettungen.jsonl       chunk_id, modell, anbieter, dimension, vektor (Videos und Dokumente)
    miniaturen/<extern_id>.jpg
    dokumente/<dokument_id>.<endung>   Originaldateien der Dokumente

Die Datenbankzugriffe stecken hinter zwei Schnittstellen (Datenquelle für den Export,
Datenziel für den Import). Schreiben und Lesen des Pakets kennen keine Datenbank und
sind ohne sie prüfbar. Kennungen der Bibliothekszeilen (Videos, Korrekturen, Chunks)
bleiben beim Umzug erhalten, damit gespeicherte Fundstellen in Unterhaltungen weiter
auf dieselben Stücke zeigen.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import tarfile
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Row, Select, delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.engine import sitzung
from ...db.modelle import Chunk, Dokument, DokumentAbschnitt, Einbettung, Korrektur, Transkript, Video, jetzt, neue_id
from ...domaene.fliessband import Dokumentstufe, Stufe, stufen_index

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- Paketaufbau
PAKET_PRAEFIX = "morf-gpt-bibliothek-"
PAKET_ENDUNG = ".tar.gz"
FORMAT_KENNUNG = "morf-gpt-bibliothek"
# 2: Dokumente (dokumente.jsonl, dokument_abschnitte.jsonl, dokument_chunks.jsonl, dokumente/). Ein Leser
# dieser Version liest Pakete der Version 1 unverändert; die Dokumenttabellen fehlen dort einfach.
FORMAT_VERSION = 2

MANIFEST = "manifest.json"
VIDEOS = "videos.jsonl"
TRANSKRIPTE = "transkripte.jsonl"
KORREKTUREN = "korrekturen.jsonl"
CHUNKS = "chunks.jsonl"
DOKUMENTE = "dokumente.jsonl"
DOKUMENT_ABSCHNITTE = "dokument_abschnitte.jsonl"
DOKUMENT_CHUNKS = "dokument_chunks.jsonl"
EINBETTUNGEN = "einbettungen.jsonl"
MINIATUREN_ORDNER = "miniaturen"
DOKUMENTE_ORDNER = "dokumente"
EINGANG_ORDNER = "eingang"

# Technische Vorgaben ohne Nutzerregler (siehe Bericht, Abschnitt "register_ergaenzungen").
# Zeilen je Datenbankstapel beim Import und Abstand der Fortschrittsmeldungen.
STAPEL_ZEILEN = 500
# Kompressionsstufe: 9 ist deutlich langsamer bei kaum kleinerer Datei.
GZIP_STUFE = 6
# Nachkommastellen je Vektorkomponente. pgvector speichert einfache Genauigkeit, mehr
# Stellen würden das Paket nur aufblähen.
VEKTOR_NACHKOMMASTELLEN = 8

# Fortschrittsabschnitte (Anteil von .. bis) je Tabelle, für Export und Import gleich.
ABSCHNITTE: dict[str, tuple[float, float]] = {
    VIDEOS: (0.0, 0.15),
    TRANSKRIPTE: (0.15, 0.3),
    KORREKTUREN: (0.3, 0.42),
    CHUNKS: (0.42, 0.52),
    DOKUMENTE: (0.52, 0.54),
    DOKUMENT_ABSCHNITTE: (0.54, 0.57),
    DOKUMENT_CHUNKS: (0.57, 0.6),
    EINBETTUNGEN: (0.6, 0.9),
}
_DOKUMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_ENDUNG = re.compile(r"^\.[A-Za-z0-9]{1,8}$")

_PAKETNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}\.tar\.gz$")
_EXTERN_ID = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}$")
_UNSICHERE_ZEICHEN = re.compile(r"[^A-Za-z0-9._-]+")

Fortschrittsmelder = Callable[[float, str], Awaitable[None]]


class PaketFehler(RuntimeError):
    """Ein Paket konnte nicht geschrieben oder gelesen werden (sprechende Meldung)."""


# --------------------------------------------------------------------------- Zeilenformate
class Zeile(BaseModel):
    """Grundlage aller JSONL-Zeilen: unbekannte Felder späterer Formate werden überlesen."""

    model_config = ConfigDict(extra="ignore")


class VideoZeile(Zeile):
    """Ein Video mit den Metadaten der Quelle. `metadaten_original` ist die rohe Antwort
    der Quelle und darum bewusst ein freies Wörterbuch."""

    id: str
    extern_id: str
    original_url: str = ""
    titel: str = ""
    beschreibung: str = ""
    veroeffentlicht: datetime | None = None
    dauer_s: int | None = None
    typ: str = "video"
    aufrufe: int | None = None
    schlagworte: list[str] = Field(default_factory=list)
    kanal_name: str = ""
    serie: str = ""
    folge_nr: int | None = None
    miniatur_url: str = ""
    metadaten_original: dict[str, Any] = Field(default_factory=dict)
    ausgewaehlt: bool = False
    auswahl_manuell: bool = False
    notizen: str = ""
    # Zur Information; der Import bestimmt die Stufe aus dem tatsächlichen Inhalt.
    stufe: str = ""
    # Liegt ein Vorschaubild unter miniaturen/<extern_id>.jpg im Paket?
    miniatur: bool = False


class Kindzeile(Zeile):
    """Zeile, die zu einem Video gehört (Kennung des Videos im Quellsystem)."""

    id: str
    video_id: str


class TranskriptZeile(Kindzeile):
    engine: str = ""
    modell: str = ""
    sprache: str = "de"
    volltext: str = ""
    segmente: list[dict[str, Any]] = Field(default_factory=list)
    dauer_verarbeitung_s: float | None = None
    erstellt: datetime


class KorrekturZeile(Kindzeile):
    transkript_id: str | None = None
    engine: str = ""
    anbieter: str = ""
    modell: str = ""
    absaetze: list[dict[str, Any]] = Field(default_factory=list)
    themen: list[dict[str, Any]] = Field(default_factory=list)
    zusammenfassung: str = ""
    aehnlichkeit: float | None = None
    bloecke_gesamt: int = 0
    bloecke_verworfen: int = 0
    dauer_verarbeitung_s: float | None = None
    manuell_bearbeitet: bool = False
    erstellt: datetime


class ChunkZeile(Kindzeile):
    korrektur_id: str | None = None
    reihenfolge: int
    text: str
    start_s: float = 0.0
    end_s: float = 0.0
    zeichen: int = 0
    thema: str = ""
    ueberlappung_vor: int = 0
    ueberlappung_nach: int = 0
    manuell_bearbeitet: bool = False
    erstellt: datetime


class DokumentZeile(Zeile):
    """Ein Dokument (E-Book, Markdown, Text). Die Kennung ist zugleich die Identität beim Import."""

    id: str
    titel: str = ""
    autor: str = ""
    art: str = "text"
    sprache: str = "de"
    beschreibung: str = ""
    veroeffentlicht: datetime | None = None
    dateiname: str = ""
    groesse_bytes: int | None = None
    zeichen: int = 0
    metadaten_original: dict[str, Any] = Field(default_factory=dict)
    felder_manuell: list[str] = Field(default_factory=list)
    notizen: str = ""
    # Zur Information; der Import bestimmt die Stufe aus dem tatsächlichen Inhalt.
    stufe: str = ""
    # Liegt die Originaldatei unter dokumente/<id><endung> im Paket?
    datei: bool = False
    endung: str = ""


class DokumentKindzeile(Zeile):
    id: str
    dokument_id: str


class AbschnittZeile(DokumentKindzeile):
    reihenfolge: int
    ebene: int = 1
    titel: str = ""
    text: str = ""
    zeichen: int = 0
    anker: str = ""
    seite_von: int | None = None
    seite_bis: int | None = None
    position_von: int = 0
    erstellt: datetime


class DokumentChunkZeile(DokumentKindzeile):
    abschnitt_id: str | None = None
    reihenfolge: int
    text: str
    zeichen: int = 0
    thema: str = ""
    ueberlappung_vor: int = 0
    ueberlappung_nach: int = 0
    position_von: int | None = None
    position_bis: int | None = None
    manuell_bearbeitet: bool = False
    erstellt: datetime


class EinbettungZeile(Zeile):
    """Ohne eigene Kennung: (chunk_id, modell) ist eindeutig, die Kennung wird beim Import neu vergeben."""

    chunk_id: str
    modell: str
    anbieter: str = ""
    dimension: int
    vektor: list[float]


class Zaehler(BaseModel):
    videos: int = 0
    transkripte: int = 0
    korrekturen: int = 0
    chunks: int = 0
    einbettungen: int = 0
    miniaturen: int = 0
    dokumente: int = 0
    dokument_abschnitte: int = 0
    dokument_chunks: int = 0
    dokument_dateien: int = 0


class Manifest(Zeile):
    format: str = FORMAT_KENNUNG
    format_version: int = FORMAT_VERSION
    version: str
    erstellt: datetime
    einbettung_modelle: list[str] = Field(default_factory=list)
    dimension: int
    mit_transkripten: bool = False
    zaehler: Zaehler = Field(default_factory=Zaehler)


class ImportErgebnis(BaseModel):
    videos_neu: int = 0
    videos_aktualisiert: int = 0
    transkripte: int = 0
    korrekturen: int = 0
    chunks: int = 0
    einbettungen: int = 0
    miniaturen: int = 0
    dokumente_neu: int = 0
    dokumente_aktualisiert: int = 0
    dokument_abschnitte: int = 0
    dokument_chunks: int = 0
    dokument_dateien: int = 0
    einbettung_modelle: list[str] = Field(default_factory=list)
    paket_version: str = ""
    paket_erstellt: datetime | None = None


@dataclass(slots=True)
class ExportErgebnis:
    datei: Path
    manifest: Manifest
    groesse_bytes: int


# --------------------------------------------------------------------------- Hilfen
def pruefe_paketname(name: str) -> str:
    """Nur einfache Dateinamen mit Paketendung, ohne Pfadanteile. Wirft PaketFehler."""
    if not _PAKETNAME.match(name) or ".." in name:
        raise PaketFehler(f"Ungültiger Paketname '{name}'")
    return name


def sicherer_dateiname(name: str | None, vorgabe: str = "paket.tar.gz") -> str:
    """Bereinigt einen hochgeladenen Dateinamen auf harmlose Zeichen."""
    roh = Path(name or "").name
    bereinigt = _UNSICHERE_ZEICHEN.sub("_", roh).lstrip(".")
    return bereinigt or vorgabe


def vektor_kompakt(vektor: Any) -> list[float]:
    """Vektorkomponenten als gerundete Gleitkommazahlen (siehe VEKTOR_NACHKOMMASTELLEN)."""
    return [round(float(x), VEKTOR_NACHKOMMASTELLEN) for x in vektor]


def _zahl(n: int) -> str:
    """Tausenderpunkte, wie in der Oberfläche üblich."""
    return f"{n:,}".replace(",", ".")


def _groesse(byte: int) -> str:
    megabyte = byte / (1024 * 1024)
    return f"{megabyte:.1f}".replace(".", ",") + " Megabyte"


def _anteil(abschnitt: tuple[float, float], anzahl: int, erwartet: int) -> float:
    von, bis = abschnitt
    if erwartet <= 0:
        return bis
    return von + (bis - von) * min(1.0, anzahl / erwartet)


async def _melde(melde: Fortschrittsmelder | None, anteil: float, meldung: str) -> None:
    if melde is not None:
        await melde(anteil, meldung)


def _pruefe_dokument_id(dokument_id: str) -> str:
    if not _DOKUMENT_ID.match(dokument_id):
        raise PaketFehler(f"Ungültige Dokumentkennung '{dokument_id}'")
    return dokument_id


def _pruefe_endung(endung: str) -> str:
    endung = endung.lower()
    if not _ENDUNG.match(endung):
        raise PaketFehler(f"Ungültige Dateiendung '{endung}' einer Dokumentdatei")
    return endung


def _pruefe_extern_id(extern_id: str) -> str:
    if not _EXTERN_ID.match(extern_id):
        raise PaketFehler(f"Die Videokennung '{extern_id}' taugt nicht als Dateiname für das Vorschaubild")
    return extern_id


def _normaler_name(name: str) -> str:
    return name.removeprefix("./")


# --------------------------------------------------------------------------- JSONL lesen und schreiben
class JsonlSchreiber:
    """Schreibt Zeilen sofort in eine Datei; nichts bleibt im Speicher."""

    def __init__(self, pfad: Path) -> None:
        self._datei = pfad.open("wb")
        self.anzahl = 0

    def schreibe(self, zeile: BaseModel) -> None:
        self._datei.write(zeile.model_dump_json().encode("utf-8"))
        self._datei.write(b"\n")
        self.anzahl += 1

    def schliesse(self) -> None:
        self._datei.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.schliesse()


def lese_jsonl[Z: Zeile](datei: IO[bytes], modell: type[Z], name: str) -> Iterator[Z]:
    """Liest eine JSONL-Datei zeilenweise; Fehler nennen Datei und Zeilennummer."""
    for nummer, roh in enumerate(datei, start=1):
        inhalt = roh.strip()
        if not inhalt:
            continue
        try:
            yield modell.model_validate_json(inhalt)
        except ValidationError as e:
            raise PaketFehler(f"{name}, Zeile {nummer}: {_validierungsfehler(e)}") from e


def _validierungsfehler(e: ValidationError) -> str:
    erster = e.errors()[0]
    if erster.get("type") == "json_invalid":
        return "kein gültiges JSON"
    ort = ".".join(str(t) for t in erster.get("loc", ()))
    return f"Feld '{ort}' - {erster.get('msg', 'ungültig')}"


# --------------------------------------------------------------------------- Paket schreiben
class PaketSchreiber:
    """Sammelt die Dateien in einem Arbeitsverzeichnis und packt sie am Ende in die Reihenfolge,
    die der streamende Leser erwartet (Manifest zuerst, dann Tabellen, dann Vorschaubilder)."""

    def __init__(self, arbeitsverzeichnis: Path) -> None:
        self._arbeit = arbeitsverzeichnis
        self._miniaturen = arbeitsverzeichnis / MINIATUREN_ORDNER
        self._miniaturen.mkdir(parents=True, exist_ok=True)
        self._dokumente = arbeitsverzeichnis / DOKUMENTE_ORDNER
        self._dokumente.mkdir(parents=True, exist_ok=True)
        self._tabellen: list[str] = []
        self.miniaturen = 0
        self.dokument_dateien = 0

    def tabelle(self, name: str) -> JsonlSchreiber:
        self._tabellen.append(name)
        return JsonlSchreiber(self._arbeit / name)

    def miniatur_ablegen(self, extern_id: str, quelle: Path) -> None:
        ziel = self._miniaturen / f"{_pruefe_extern_id(extern_id)}.jpg"
        shutil.copyfile(quelle, ziel)
        self.miniaturen += 1

    def dokument_datei_ablegen(self, dokument_id: str, quelle: Path) -> str:
        """Legt die Originaldatei unter dokumente/<id><endung> ab und gibt die Endung zurück."""
        endung = _pruefe_endung(quelle.suffix)
        ziel = self._dokumente / f"{_pruefe_dokument_id(dokument_id)}{endung}"
        shutil.copyfile(quelle, ziel)
        self.dokument_dateien += 1
        return endung

    def abschliessen(self, manifest: Manifest, ziel: Path) -> Path:
        """Schreibt Manifest und Archiv. Blockierend: im Backend über einen Thread aufrufen."""
        (self._arbeit / MANIFEST).write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        teil = ziel.with_name(ziel.name + ".teil")
        try:
            with tarfile.open(teil, "w:gz", compresslevel=GZIP_STUFE) as tar:
                tar.add(self._arbeit / MANIFEST, arcname=MANIFEST)
                for name in self._tabellen:
                    tar.add(self._arbeit / name, arcname=name)
                for datei in sorted(self._miniaturen.iterdir()):
                    tar.add(datei, arcname=f"{MINIATUREN_ORDNER}/{datei.name}")
                for datei in sorted(self._dokumente.iterdir()):
                    tar.add(datei, arcname=f"{DOKUMENTE_ORDNER}/{datei.name}")
            teil.replace(ziel)
        except BaseException:
            teil.unlink(missing_ok=True)
            raise
        finally:
            self.verwerfen()
        return ziel

    def verwerfen(self) -> None:
        shutil.rmtree(self._arbeit, ignore_errors=True)


# --------------------------------------------------------------------------- Paket lesen
@dataclass(slots=True)
class Paketeintrag:
    name: str
    daten: IO[bytes]


class PaketLeser:
    """Liest ein Paket als Strom: jeder Eintrag wird genau einmal, in Archivreihenfolge, geliefert."""

    def __init__(self, pfad: Path) -> None:
        self._pfad = pfad
        self._tar: tarfile.TarFile | None = None

    def __enter__(self) -> Self:
        try:
            self._tar = tarfile.open(self._pfad, "r|gz")
        except (tarfile.ReadError, OSError) as e:
            raise PaketFehler(f"'{self._pfad.name}' ist kein lesbares Paket (tar.gz): {e}") from e
        return self

    def __exit__(self, *_: object) -> None:
        if self._tar is not None:
            self._tar.close()
            self._tar = None

    def eintraege(self) -> Iterator[Paketeintrag]:
        if self._tar is None:
            raise PaketFehler("Der Paketleser ist nicht geöffnet")
        try:
            for mitglied in self._tar:
                if not mitglied.isfile():
                    continue
                daten = self._tar.extractfile(mitglied)
                if daten is None:
                    continue
                yield Paketeintrag(_normaler_name(mitglied.name), daten)
        except (tarfile.TarError, EOFError) as e:
            raise PaketFehler(f"Das Paket '{self._pfad.name}' ist beschädigt: {e}") from e


def manifest_lesen(daten: IO[bytes]) -> Manifest:
    try:
        return Manifest.model_validate_json(daten.read())
    except (ValidationError, ValueError) as e:
        raise PaketFehler(f"Das Manifest des Pakets ist unlesbar: {e}") from e


def pruefe_manifest(manifest: Manifest, erwartete_dimension: int) -> None:
    """Herkunft, Formatversion und Vektordimension gegen diese Installation prüfen."""
    if manifest.format != FORMAT_KENNUNG:
        raise PaketFehler(f"Das Paket stammt nicht aus morf-gpt (Kennung '{manifest.format}')")
    if manifest.format_version > FORMAT_VERSION:
        raise PaketFehler(
            f"Das Paketformat {manifest.format_version} ist neuer als das dieser Installation "
            f"({FORMAT_VERSION}). Bitte zuerst morf-gpt aktualisieren."
        )
    if manifest.zaehler.einbettungen > 0 and manifest.dimension != erwartete_dimension:
        raise PaketFehler(
            f"Das Paket trägt Einbettungen mit {manifest.dimension} Dimensionen, diese Datenbank "
            f"erwartet {erwartete_dimension}. Ein anderes Einbettungsmodell braucht eine Migration."
        )


# --------------------------------------------------------------------------- Schnittstellen
@dataclass(slots=True)
class Videoexport:
    zeile: VideoZeile
    miniatur_datei: Path | None


@dataclass(slots=True)
class Dokumentexport:
    zeile: DokumentZeile
    datei: Path | None


class Datenquelle(Protocol):
    """Woher der Export seine Zeilen bekommt. Alle Ströme liefern nur aktuelle Ergebnisse."""

    async def zaehler(self) -> Zaehler: ...

    def videos(self) -> AsyncIterator[Videoexport]: ...

    def transkripte(self) -> AsyncIterator[TranskriptZeile]: ...

    def korrekturen(self) -> AsyncIterator[KorrekturZeile]: ...

    def chunks(self) -> AsyncIterator[ChunkZeile]: ...

    def dokumente(self) -> AsyncIterator[Dokumentexport]: ...

    def dokument_abschnitte(self) -> AsyncIterator[AbschnittZeile]: ...

    def dokument_chunks(self) -> AsyncIterator[DokumentChunkZeile]: ...

    def einbettungen(self) -> AsyncIterator[EinbettungZeile]:
        """Einbettungen aller Stücke, Videos wie Dokumente."""
        ...


@dataclass(slots=True)
class VorhandenesVideo:
    id: str
    stufe: str
    auswahl_manuell: bool


@dataclass(slots=True)
class VorhandeneVideos:
    je_extern_id: dict[str, VorhandenesVideo]
    ids: set[str]


class Datenziel(Protocol):
    """Wohin der Import schreibt: Datenbank und Ablage der Vorschaubilder.

    Die übergebenen Zeilen tragen bereits die Kennungen des Ziels (video_id, korrektur_id,
    transkript_id sind umgeschrieben); das Ziel fügt nur noch ein.
    """

    async def vorhandene_videos(self) -> VorhandeneVideos: ...

    async def video_anlegen(self, video_id: str, zeile: VideoZeile) -> None: ...

    async def video_aktualisieren(self, video_id: str, zeile: VideoZeile, ausgewaehlt_uebernehmen: bool) -> None: ...

    async def transkripte_loeschen(self, video_id: str) -> None: ...

    async def korrekturen_loeschen(self, video_id: str) -> None: ...

    async def chunks_loeschen(self, video_id: str) -> None: ...

    async def transkripte_einfuegen(self, zeilen: list[TranskriptZeile]) -> None: ...

    async def korrekturen_einfuegen(self, zeilen: list[KorrekturZeile]) -> None: ...

    async def chunks_einfuegen(self, zeilen: list[ChunkZeile]) -> None: ...

    async def einbettungen_einfuegen(self, zeilen: list[EinbettungZeile]) -> None: ...

    async def miniatur_ablegen(self, video_id: str, daten: IO[bytes]) -> str:
        """Legt das Bild ab und gibt den Pfad zurück, der im Video gespeichert wird."""
        ...

    async def video_abschliessen(self, video_id: str, stufe: Stufe, miniatur_pfad: str | None) -> None: ...

    async def vorhandene_dokumente(self) -> dict[str, str]:
        """Kennung -> Stufe aller Dokumente im Ziel."""
        ...

    async def dokument_anlegen(self, zeile: DokumentZeile) -> None: ...

    async def dokument_aktualisieren(self, zeile: DokumentZeile) -> None: ...

    async def dokument_abschnitte_loeschen(self, dokument_id: str) -> None: ...

    async def dokument_chunks_loeschen(self, dokument_id: str) -> None: ...

    async def dokument_abschnitte_einfuegen(self, zeilen: list[AbschnittZeile]) -> None: ...

    async def dokument_chunks_einfuegen(self, zeilen: list[DokumentChunkZeile]) -> None: ...

    async def dokument_datei_ablegen(self, dokument_id: str, endung: str, daten: IO[bytes]) -> str:
        """Legt die Originaldatei ab und gibt den Pfad zurück, der im Dokument gespeichert wird."""
        ...

    async def dokument_abschliessen(self, dokument_id: str, stufe: Dokumentstufe, datei_pfad: str | None) -> None: ...

    async def abschliessen(self) -> None:
        """Alles festschreiben."""
        ...


# --------------------------------------------------------------------------- Export
async def _tabelle_schreiben[Z: Zeile](
    schreiber: PaketSchreiber,
    name: str,
    titel: str,
    zeilen: AsyncIterator[Z],
    erwartet: int,
    melde: Fortschrittsmelder | None,
) -> int:
    abschnitt = ABSCHNITTE[name]
    with schreiber.tabelle(name) as js:
        async for zeile in zeilen:
            js.schreibe(zeile)
            if js.anzahl % STAPEL_ZEILEN == 0:
                await _melde(melde, _anteil(abschnitt, js.anzahl, erwartet), f"{titel}: {_zahl(js.anzahl)} von {_zahl(erwartet)}")
        await _melde(melde, abschnitt[1], f"{titel}: {_zahl(js.anzahl)} geschrieben")
        return js.anzahl


async def _videos_mit_miniaturen(schreiber: PaketSchreiber, quelle: Datenquelle) -> AsyncIterator[VideoZeile]:
    async for export in quelle.videos():
        zeile = export.zeile
        if export.miniatur_datei is not None:
            schreiber.miniatur_ablegen(zeile.extern_id, export.miniatur_datei)
            zeile = zeile.model_copy(update={"miniatur": True})
        yield zeile


async def _dokumente_mit_dateien(schreiber: PaketSchreiber, quelle: Datenquelle) -> AsyncIterator[DokumentZeile]:
    async for export in quelle.dokumente():
        zeile = export.zeile
        if export.datei is not None and export.datei.is_file():
            endung = schreiber.dokument_datei_ablegen(zeile.id, export.datei)
            zeile = zeile.model_copy(update={"datei": True, "endung": endung})
        yield zeile


async def _einbettungen_geprueft(
    zeilen: AsyncIterator[EinbettungZeile], dimension: int, modelle: set[str]
) -> AsyncIterator[EinbettungZeile]:
    async for zeile in zeilen:
        if len(zeile.vektor) != dimension:
            raise PaketFehler(f"Die Einbettung für Chunk {zeile.chunk_id} hat {len(zeile.vektor)} Dimensionen, erwartet sind {dimension}")
        modelle.add(zeile.modell)
        yield zeile


async def exportiere(
    quelle: Datenquelle,
    ziel_verzeichnis: Path,
    *,
    version: str,
    dimension: int,
    mit_transkripten: bool,
    melde: Fortschrittsmelder | None = None,
) -> ExportErgebnis:
    """Schreibt ein vollständiges Paket nach ziel_verzeichnis und gibt Pfad und Manifest zurück."""
    ziel_verzeichnis.mkdir(parents=True, exist_ok=True)
    stempel = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    ziel = ziel_verzeichnis / f"{PAKET_PRAEFIX}{stempel}{PAKET_ENDUNG}"
    schreiber = PaketSchreiber(ziel_verzeichnis / f".arbeit-{stempel}")
    try:
        erwartet = await quelle.zaehler()
        zaehler = Zaehler()
        zaehler.videos = await _tabelle_schreiben(
            schreiber, VIDEOS, "Videos", _videos_mit_miniaturen(schreiber, quelle), erwartet.videos, melde
        )
        if mit_transkripten:
            zaehler.transkripte = await _tabelle_schreiben(
                schreiber, TRANSKRIPTE, "Transkripte", quelle.transkripte(), erwartet.transkripte, melde
            )
        zaehler.korrekturen = await _tabelle_schreiben(
            schreiber, KORREKTUREN, "Korrekturen", quelle.korrekturen(), erwartet.korrekturen, melde
        )
        zaehler.chunks = await _tabelle_schreiben(schreiber, CHUNKS, "Chunks", quelle.chunks(), erwartet.chunks, melde)
        zaehler.dokumente = await _tabelle_schreiben(
            schreiber, DOKUMENTE, "Dokumente", _dokumente_mit_dateien(schreiber, quelle), erwartet.dokumente, melde
        )
        zaehler.dokument_abschnitte = await _tabelle_schreiben(
            schreiber, DOKUMENT_ABSCHNITTE, "Abschnitte", quelle.dokument_abschnitte(), erwartet.dokument_abschnitte, melde
        )
        zaehler.dokument_chunks = await _tabelle_schreiben(
            schreiber, DOKUMENT_CHUNKS, "Dokumentstücke", quelle.dokument_chunks(), erwartet.dokument_chunks, melde
        )
        modelle: set[str] = set()
        zaehler.einbettungen = await _tabelle_schreiben(
            schreiber,
            EINBETTUNGEN,
            "Einbettungen",
            _einbettungen_geprueft(quelle.einbettungen(), dimension, modelle),
            erwartet.einbettungen,
            melde,
        )
        zaehler.miniaturen = schreiber.miniaturen
        zaehler.dokument_dateien = schreiber.dokument_dateien
        manifest = Manifest(
            version=version,
            erstellt=datetime.now(UTC),
            einbettung_modelle=sorted(modelle),
            dimension=dimension,
            mit_transkripten=mit_transkripten,
            zaehler=zaehler,
        )
        await _melde(melde, ABSCHNITTE[EINBETTUNGEN][1], "Paket wird gepackt")
        pfad = await asyncio.to_thread(schreiber.abschliessen, manifest, ziel)
    except BaseException:
        schreiber.verwerfen()
        raise
    groesse = pfad.stat().st_size
    await _melde(melde, 1.0, f"Fertig: {pfad.name} ({_groesse(groesse)})")
    return ExportErgebnis(datei=pfad, manifest=manifest, groesse_bytes=groesse)


# --------------------------------------------------------------------------- Import
@dataclass(slots=True)
class Videostand:
    """Was der Import für ein Video getan hat; daraus folgt am Ende die Stufe."""

    ziel_id: str
    neu: bool
    bestehende_stufe: Stufe | None
    transkripte: int = 0
    korrekturen: int = 0
    chunks: int = 0
    chunks_eingebettet: int = 0
    miniatur_pfad: str | None = None


def stufe_nach_import(stand: Videostand) -> Stufe:
    """Die Stufe, die der Inhalt des Videos nach dem Import ehrlich belegt.

    Wurden Chunks ersetzt, bestimmt das Paket alles ab der Stückelung (auch ein Abstieg
    von 'eingebettet' auf 'gestueckelt'). Sonst kann die Stufe nur steigen: was das Paket
    nicht mitbringt, bleibt im Ziel erhalten.
    """
    aus_paket: Stufe | None = None
    if stand.chunks > 0 and stand.chunks_eingebettet >= stand.chunks:
        aus_paket = Stufe.EINGEBETTET
    elif stand.chunks > 0:
        aus_paket = Stufe.GESTUECKELT
    elif stand.korrekturen > 0:
        aus_paket = Stufe.KORRIGIERT
    elif stand.transkripte > 0:
        aus_paket = Stufe.TRANSKRIBIERT
    if stand.bestehende_stufe is None:
        return aus_paket or Stufe.ENTDECKT
    if stand.chunks > 0 and aus_paket is not None:
        return aus_paket
    if aus_paket is None or stufen_index(stand.bestehende_stufe) >= stufen_index(aus_paket):
        return stand.bestehende_stufe
    return aus_paket


@dataclass(slots=True)
class Dokumentstand:
    """Was der Import für ein Dokument getan hat; daraus folgt am Ende die Stufe."""

    id: str
    neu: bool
    bestehende_stufe: Dokumentstufe | None
    abschnitte: int = 0
    chunks: int = 0
    chunks_eingebettet: int = 0
    datei_pfad: str | None = None
    abschnitt_ids: set[str] = field(default_factory=set)


def dokumentstufe_nach_import(stand: Dokumentstand) -> Dokumentstufe:
    """Die Stufe, die der Inhalt des Dokuments nach dem Import belegt (analog zu stufe_nach_import)."""
    if stand.chunks > 0 and stand.chunks_eingebettet >= stand.chunks:
        return Dokumentstufe.EINGEBETTET
    if stand.chunks > 0:
        return Dokumentstufe.GESTUECKELT
    return Dokumentstufe.IMPORTIERT


@dataclass(slots=True)
class _Importzustand:
    manifest: Manifest | None = None
    je_quell_id: dict[str, Videostand] = field(default_factory=dict)
    je_extern_id: dict[str, Videostand] = field(default_factory=dict)
    transkript_ids: set[str] = field(default_factory=set)
    korrektur_ids: set[str] = field(default_factory=set)
    chunk_video: dict[str, Videostand] = field(default_factory=dict)
    dokumente: dict[str, Dokumentstand] = field(default_factory=dict)
    chunk_dokument: dict[str, Dokumentstand] = field(default_factory=dict)
    eingebettete_chunks: set[str] = field(default_factory=set)
    modelle: set[str] = field(default_factory=set)
    ergebnis: ImportErgebnis = field(default_factory=ImportErgebnis)

    def manifest_oder_fehler(self) -> Manifest:
        if self.manifest is None:
            raise PaketFehler("Das Manifest fehlt oder liegt nicht am Anfang des Pakets")
        return self.manifest

    def stand_fuer(self, quell_video_id: str, eintrag: str) -> Videostand:
        if not self.je_quell_id:
            raise PaketFehler(f"'{eintrag}' liegt im Paket vor der Videoliste")
        stand = self.je_quell_id.get(quell_video_id)
        if stand is None:
            raise PaketFehler(f"'{eintrag}' verweist auf ein Video ({quell_video_id}), das im Paket fehlt")
        return stand

    def dokumentstand_fuer(self, dokument_id: str, eintrag: str) -> Dokumentstand:
        if not self.dokumente:
            raise PaketFehler(f"'{eintrag}' liegt im Paket vor der Dokumentliste")
        stand = self.dokumente.get(dokument_id)
        if stand is None:
            raise PaketFehler(f"'{eintrag}' verweist auf ein Dokument ({dokument_id}), das im Paket fehlt")
        return stand


class _Stapel[Z: Zeile]:
    """Sammelt Zeilen und reicht sie stapelweise weiter; gibt zwischen Stapeln die Schleife frei."""

    def __init__(self, senden: Callable[[list[Z]], Awaitable[None]]) -> None:
        self._senden = senden
        self._zeilen: list[Z] = []
        self.gesamt = 0

    async def hinzu(self, zeile: Z) -> None:
        self._zeilen.append(zeile)
        if len(self._zeilen) >= STAPEL_ZEILEN:
            await self.leeren()

    async def leeren(self) -> None:
        if not self._zeilen:
            return
        await self._senden(self._zeilen)
        self.gesamt += len(self._zeilen)
        self._zeilen = []
        await asyncio.sleep(0)


async def _videos_importieren(eintrag: Paketeintrag, zustand: _Importzustand, ziel: Datenziel, melde: Fortschrittsmelder | None) -> None:
    vorhandene = await ziel.vorhandene_videos()
    belegt = set(vorhandene.ids)
    erwartet = zustand.manifest_oder_fehler().zaehler.videos
    for zeile in lese_jsonl(eintrag.daten, VideoZeile, eintrag.name):
        bekannt = vorhandene.je_extern_id.get(zeile.extern_id)
        if bekannt is None:
            ziel_id = zeile.id if zeile.id not in belegt else neue_id()
            belegt.add(ziel_id)
            await ziel.video_anlegen(ziel_id, zeile)
            vorhandene.je_extern_id[zeile.extern_id] = VorhandenesVideo(ziel_id, Stufe.ENTDECKT, zeile.auswahl_manuell)
            stand = Videostand(ziel_id=ziel_id, neu=True, bestehende_stufe=None)
            zustand.ergebnis.videos_neu += 1
        else:
            await ziel.video_aktualisieren(bekannt.id, zeile, ausgewaehlt_uebernehmen=not bekannt.auswahl_manuell)
            stand = Videostand(ziel_id=bekannt.id, neu=False, bestehende_stufe=Stufe(bekannt.stufe))
            zustand.ergebnis.videos_aktualisiert += 1
        zustand.je_quell_id[zeile.id] = stand
        zustand.je_extern_id[zeile.extern_id] = stand
        gelesen = len(zustand.je_quell_id)
        if gelesen % STAPEL_ZEILEN == 0:
            await _melde(melde, _anteil(ABSCHNITTE[VIDEOS], gelesen, erwartet), f"Videos: {_zahl(gelesen)} von {_zahl(erwartet)}")
    await _melde(melde, ABSCHNITTE[VIDEOS][1], f"Videos: {_zahl(len(zustand.je_quell_id))} abgeglichen")


async def _kinder_importieren[Z: Kindzeile](
    eintrag: Paketeintrag,
    modell: type[Z],
    titel: str,
    erwartet: int,
    zustand: _Importzustand,
    loeschen: Callable[[str], Awaitable[None]],
    einfuegen: Callable[[list[Z]], Awaitable[None]],
    umschreiben: Callable[[Z, Videostand], Z],
    melde: Fortschrittsmelder | None,
) -> int:
    """Gemeinsamer Ablauf für Transkripte, Korrekturen und Chunks: je Video zuerst die alten
    Zeilen löschen, dann die des Pakets mit den Kennungen des Ziels einfügen."""
    abschnitt = ABSCHNITTE[eintrag.name]
    geleert: set[str] = set()
    stapel: _Stapel[Z] = _Stapel(einfuegen)
    for zeile in lese_jsonl(eintrag.daten, modell, eintrag.name):
        stand = zustand.stand_fuer(zeile.video_id, eintrag.name)
        if stand.ziel_id not in geleert:
            await loeschen(stand.ziel_id)
            geleert.add(stand.ziel_id)
        await stapel.hinzu(umschreiben(zeile, stand))
        if stapel.gesamt and stapel.gesamt % STAPEL_ZEILEN == 0:
            await _melde(melde, _anteil(abschnitt, stapel.gesamt, erwartet), f"{titel}: {_zahl(stapel.gesamt)} von {_zahl(erwartet)}")
    await stapel.leeren()
    await _melde(melde, abschnitt[1], f"{titel}: {_zahl(stapel.gesamt)} übernommen")
    return stapel.gesamt


async def _transkripte_importieren(
    eintrag: Paketeintrag, zustand: _Importzustand, ziel: Datenziel, melde: Fortschrittsmelder | None
) -> None:
    def umschreiben(zeile: TranskriptZeile, stand: Videostand) -> TranskriptZeile:
        stand.transkripte += 1
        zustand.transkript_ids.add(zeile.id)
        return zeile.model_copy(update={"video_id": stand.ziel_id})

    zustand.ergebnis.transkripte = await _kinder_importieren(
        eintrag,
        TranskriptZeile,
        "Transkripte",
        zustand.manifest_oder_fehler().zaehler.transkripte,
        zustand,
        ziel.transkripte_loeschen,
        ziel.transkripte_einfuegen,
        umschreiben,
        melde,
    )


async def _korrekturen_importieren(
    eintrag: Paketeintrag, zustand: _Importzustand, ziel: Datenziel, melde: Fortschrittsmelder | None
) -> None:
    def umschreiben(zeile: KorrekturZeile, stand: Videostand) -> KorrekturZeile:
        stand.korrekturen += 1
        zustand.korrektur_ids.add(zeile.id)
        transkript_id = zeile.transkript_id if zeile.transkript_id in zustand.transkript_ids else None
        return zeile.model_copy(update={"video_id": stand.ziel_id, "transkript_id": transkript_id})

    zustand.ergebnis.korrekturen = await _kinder_importieren(
        eintrag,
        KorrekturZeile,
        "Korrekturen",
        zustand.manifest_oder_fehler().zaehler.korrekturen,
        zustand,
        ziel.korrekturen_loeschen,
        ziel.korrekturen_einfuegen,
        umschreiben,
        melde,
    )


async def _chunks_importieren(eintrag: Paketeintrag, zustand: _Importzustand, ziel: Datenziel, melde: Fortschrittsmelder | None) -> None:
    def umschreiben(zeile: ChunkZeile, stand: Videostand) -> ChunkZeile:
        stand.chunks += 1
        zustand.chunk_video[zeile.id] = stand
        korrektur_id = zeile.korrektur_id if zeile.korrektur_id in zustand.korrektur_ids else None
        return zeile.model_copy(update={"video_id": stand.ziel_id, "korrektur_id": korrektur_id})

    zustand.ergebnis.chunks = await _kinder_importieren(
        eintrag,
        ChunkZeile,
        "Chunks",
        zustand.manifest_oder_fehler().zaehler.chunks,
        zustand,
        ziel.chunks_loeschen,
        ziel.chunks_einfuegen,
        umschreiben,
        melde,
    )


async def _einbettungen_importieren(
    eintrag: Paketeintrag, zustand: _Importzustand, ziel: Datenziel, melde: Fortschrittsmelder | None
) -> None:
    manifest = zustand.manifest_oder_fehler()
    abschnitt = ABSCHNITTE[EINBETTUNGEN]
    stapel: _Stapel[EinbettungZeile] = _Stapel(ziel.einbettungen_einfuegen)
    for nummer, zeile in enumerate(lese_jsonl(eintrag.daten, EinbettungZeile, eintrag.name), start=1):
        if zeile.chunk_id not in zustand.chunk_video and zeile.chunk_id not in zustand.chunk_dokument:
            raise PaketFehler(f"{eintrag.name}, Zeile {nummer}: Chunk {zeile.chunk_id} fehlt im Paket")
        if len(zeile.vektor) != manifest.dimension:
            raise PaketFehler(f"{eintrag.name}, Zeile {nummer}: Vektor mit {len(zeile.vektor)} statt {manifest.dimension} Dimensionen")
        zustand.eingebettete_chunks.add(zeile.chunk_id)
        zustand.modelle.add(zeile.modell)
        await stapel.hinzu(zeile)
        if stapel.gesamt and stapel.gesamt % STAPEL_ZEILEN == 0:
            await _melde(
                melde,
                _anteil(abschnitt, stapel.gesamt, manifest.zaehler.einbettungen),
                f"Einbettungen: {_zahl(stapel.gesamt)} von {_zahl(manifest.zaehler.einbettungen)}",
            )
    await stapel.leeren()
    zustand.ergebnis.einbettungen = stapel.gesamt
    await _melde(melde, abschnitt[1], f"Einbettungen: {_zahl(stapel.gesamt)} übernommen")


async def _dokumente_importieren(eintrag: Paketeintrag, zustand: _Importzustand, ziel: Datenziel, melde: Fortschrittsmelder | None) -> None:
    vorhandene = await ziel.vorhandene_dokumente()
    erwartet = zustand.manifest_oder_fehler().zaehler.dokumente
    for zeile in lese_jsonl(eintrag.daten, DokumentZeile, eintrag.name):
        _pruefe_dokument_id(zeile.id)
        stufe = vorhandene.get(zeile.id)
        if stufe is None:
            await ziel.dokument_anlegen(zeile)
            zustand.dokumente[zeile.id] = Dokumentstand(id=zeile.id, neu=True, bestehende_stufe=None)
            zustand.ergebnis.dokumente_neu += 1
        else:
            await ziel.dokument_aktualisieren(zeile)
            zustand.dokumente[zeile.id] = Dokumentstand(id=zeile.id, neu=False, bestehende_stufe=Dokumentstufe(stufe))
            zustand.ergebnis.dokumente_aktualisiert += 1
        gelesen = len(zustand.dokumente)
        if gelesen % STAPEL_ZEILEN == 0:
            await _melde(melde, _anteil(ABSCHNITTE[DOKUMENTE], gelesen, erwartet), f"Dokumente: {_zahl(gelesen)} von {_zahl(erwartet)}")
    await _melde(melde, ABSCHNITTE[DOKUMENTE][1], f"Dokumente: {_zahl(len(zustand.dokumente))} abgeglichen")


async def _dokumentkinder_importieren[Z: DokumentKindzeile](
    eintrag: Paketeintrag,
    modell: type[Z],
    titel: str,
    erwartet: int,
    zustand: _Importzustand,
    loeschen: Callable[[str], Awaitable[None]],
    einfuegen: Callable[[list[Z]], Awaitable[None]],
    merken: Callable[[Z, Dokumentstand], Z],
    melde: Fortschrittsmelder | None,
) -> int:
    """Abschnitte und Stücke eines Dokuments: alte Zeilen löschen, dann die des Pakets einfügen."""
    abschnitt = ABSCHNITTE[eintrag.name]
    geleert: set[str] = set()
    stapel: _Stapel[Z] = _Stapel(einfuegen)
    for zeile in lese_jsonl(eintrag.daten, modell, eintrag.name):
        stand = zustand.dokumentstand_fuer(zeile.dokument_id, eintrag.name)
        if stand.id not in geleert:
            await loeschen(stand.id)
            geleert.add(stand.id)
        await stapel.hinzu(merken(zeile, stand))
        if stapel.gesamt and stapel.gesamt % STAPEL_ZEILEN == 0:
            await _melde(melde, _anteil(abschnitt, stapel.gesamt, erwartet), f"{titel}: {_zahl(stapel.gesamt)} von {_zahl(erwartet)}")
    await stapel.leeren()
    await _melde(melde, abschnitt[1], f"{titel}: {_zahl(stapel.gesamt)} übernommen")
    return stapel.gesamt


async def _dokument_abschnitte_importieren(
    eintrag: Paketeintrag, zustand: _Importzustand, ziel: Datenziel, melde: Fortschrittsmelder | None
) -> None:
    def merken(zeile: AbschnittZeile, stand: Dokumentstand) -> AbschnittZeile:
        stand.abschnitte += 1
        stand.abschnitt_ids.add(zeile.id)
        return zeile

    zustand.ergebnis.dokument_abschnitte = await _dokumentkinder_importieren(
        eintrag,
        AbschnittZeile,
        "Abschnitte",
        zustand.manifest_oder_fehler().zaehler.dokument_abschnitte,
        zustand,
        ziel.dokument_abschnitte_loeschen,
        ziel.dokument_abschnitte_einfuegen,
        merken,
        melde,
    )


async def _dokument_chunks_importieren(
    eintrag: Paketeintrag, zustand: _Importzustand, ziel: Datenziel, melde: Fortschrittsmelder | None
) -> None:
    def merken(zeile: DokumentChunkZeile, stand: Dokumentstand) -> DokumentChunkZeile:
        stand.chunks += 1
        zustand.chunk_dokument[zeile.id] = stand
        abschnitt_id = zeile.abschnitt_id if zeile.abschnitt_id in stand.abschnitt_ids else None
        return zeile.model_copy(update={"abschnitt_id": abschnitt_id})

    zustand.ergebnis.dokument_chunks = await _dokumentkinder_importieren(
        eintrag,
        DokumentChunkZeile,
        "Dokumentstücke",
        zustand.manifest_oder_fehler().zaehler.dokument_chunks,
        zustand,
        ziel.dokument_chunks_loeschen,
        ziel.dokument_chunks_einfuegen,
        merken,
        melde,
    )


async def _dokument_datei_importieren(eintrag: Paketeintrag, zustand: _Importzustand, ziel: Datenziel) -> None:
    name = Path(eintrag.name)
    stand = zustand.dokumente.get(name.stem)
    if stand is None:
        raise PaketFehler(f"Die Dokumentdatei '{eintrag.name}' gehört zu keinem Dokument im Paket")
    stand.datei_pfad = await ziel.dokument_datei_ablegen(stand.id, _pruefe_endung(name.suffix), eintrag.daten)
    zustand.ergebnis.dokument_dateien += 1


async def _miniatur_importieren(eintrag: Paketeintrag, zustand: _Importzustand, ziel: Datenziel) -> None:
    extern_id = Path(eintrag.name).stem
    stand = zustand.je_extern_id.get(extern_id)
    if stand is None:
        raise PaketFehler(f"Das Vorschaubild '{eintrag.name}' gehört zu keinem Video im Paket")
    stand.miniatur_pfad = await ziel.miniatur_ablegen(stand.ziel_id, eintrag.daten)
    zustand.ergebnis.miniaturen += 1


async def _eintrag_verarbeiten(
    eintrag: Paketeintrag,
    zustand: _Importzustand,
    ziel: Datenziel,
    erwartete_dimension: int,
    melde: Fortschrittsmelder | None,
) -> None:
    if eintrag.name == MANIFEST:
        zustand.manifest = manifest_lesen(eintrag.daten)
        pruefe_manifest(zustand.manifest, erwartete_dimension)
        return
    zustand.manifest_oder_fehler()
    if eintrag.name == VIDEOS:
        await _videos_importieren(eintrag, zustand, ziel, melde)
    elif eintrag.name == TRANSKRIPTE:
        await _transkripte_importieren(eintrag, zustand, ziel, melde)
    elif eintrag.name == KORREKTUREN:
        await _korrekturen_importieren(eintrag, zustand, ziel, melde)
    elif eintrag.name == CHUNKS:
        await _chunks_importieren(eintrag, zustand, ziel, melde)
    elif eintrag.name == DOKUMENTE:
        await _dokumente_importieren(eintrag, zustand, ziel, melde)
    elif eintrag.name == DOKUMENT_ABSCHNITTE:
        await _dokument_abschnitte_importieren(eintrag, zustand, ziel, melde)
    elif eintrag.name == DOKUMENT_CHUNKS:
        await _dokument_chunks_importieren(eintrag, zustand, ziel, melde)
    elif eintrag.name == EINBETTUNGEN:
        await _einbettungen_importieren(eintrag, zustand, ziel, melde)
    elif eintrag.name.startswith(MINIATUREN_ORDNER + "/"):
        _miniatur_stand_pruefen(zustand, eintrag.name)
        await _miniatur_importieren(eintrag, zustand, ziel)
    elif eintrag.name.startswith(DOKUMENTE_ORDNER + "/"):
        if not zustand.dokumente:
            raise PaketFehler(f"'{eintrag.name}' liegt im Paket vor der Dokumentliste")
        await _dokument_datei_importieren(eintrag, zustand, ziel)
    else:
        log.warning("Unbekannter Paketeintrag übersprungen: %s", eintrag.name)


def _miniatur_stand_pruefen(zustand: _Importzustand, name: str) -> None:
    if not zustand.je_quell_id:
        raise PaketFehler(f"'{name}' liegt im Paket vor der Videoliste")


async def _videos_abschliessen(zustand: _Importzustand, ziel: Datenziel) -> None:
    for chunk_id in zustand.eingebettete_chunks:
        if chunk_id in zustand.chunk_video:
            zustand.chunk_video[chunk_id].chunks_eingebettet += 1
        else:
            zustand.chunk_dokument[chunk_id].chunks_eingebettet += 1
    for stand in zustand.je_quell_id.values():
        await ziel.video_abschliessen(stand.ziel_id, stufe_nach_import(stand), stand.miniatur_pfad)
    for dokument in zustand.dokumente.values():
        await ziel.dokument_abschliessen(dokument.id, dokumentstufe_nach_import(dokument), dokument.datei_pfad)


async def importiere(
    pfad: Path,
    ziel: Datenziel,
    *,
    erwartete_dimension: int,
    melde: Fortschrittsmelder | None = None,
) -> ImportErgebnis:
    """Liest ein Paket streamend in das Ziel. Videos werden über extern_id abgeglichen; Korrekturen,
    Chunks und Einbettungen (und Transkripte, falls enthalten) eines Videos werden ersetzt."""
    zustand = _Importzustand()
    with PaketLeser(pfad) as leser:
        for eintrag in leser.eintraege():
            await _eintrag_verarbeiten(eintrag, zustand, ziel, erwartete_dimension, melde)
    manifest = zustand.manifest_oder_fehler()
    await _melde(melde, 0.95, "Stufen und Vorschaubilder werden eingetragen")
    await _videos_abschliessen(zustand, ziel)
    await ziel.abschliessen()
    zustand.ergebnis.einbettung_modelle = sorted(zustand.modelle)
    zustand.ergebnis.paket_version = manifest.version
    zustand.ergebnis.paket_erstellt = manifest.erstellt
    fertig = f"Fertig: {_zahl(len(zustand.je_quell_id))} Videos übernommen"
    if zustand.dokumente:
        fertig += f", {_zahl(len(zustand.dokumente))} Dokumente"
    await _melde(melde, 1.0, fertig)
    return zustand.ergebnis


# --------------------------------------------------------------------------- Datenbank: Quelle
def _video_zeile(v: Video) -> VideoZeile:
    return VideoZeile(
        id=v.id,
        extern_id=v.extern_id,
        original_url=v.original_url,
        titel=v.titel,
        beschreibung=v.beschreibung,
        veroeffentlicht=v.veroeffentlicht,
        dauer_s=v.dauer_s,
        typ=v.typ,
        aufrufe=v.aufrufe,
        schlagworte=list(v.schlagworte or []),
        kanal_name=v.kanal_name,
        serie=v.serie,
        folge_nr=v.folge_nr,
        miniatur_url=v.miniatur_url,
        metadaten_original=dict(v.metadaten_original or {}),
        ausgewaehlt=v.ausgewaehlt,
        auswahl_manuell=v.auswahl_manuell,
        notizen=v.notizen,
        stufe=v.stufe,
    )


def _dokument_zeile(d: Dokument) -> DokumentZeile:
    return DokumentZeile(
        id=d.id,
        titel=d.titel,
        autor=d.autor,
        art=d.art,
        sprache=d.sprache,
        beschreibung=d.beschreibung,
        veroeffentlicht=d.veroeffentlicht,
        dateiname=d.dateiname,
        groesse_bytes=d.groesse_bytes,
        zeichen=d.zeichen,
        metadaten_original=dict(d.metadaten_original or {}),
        felder_manuell=list(d.felder_manuell or []),
        notizen=d.notizen,
        stufe=d.stufe,
    )


def _aus_spalten[Z: Zeile](modell: type[Z]) -> Callable[[Row[Any]], Z]:
    def wandle(row: Row[Any]) -> Z:
        return modell.model_validate(dict(row._mapping))

    return wandle


def _einbettung_zeile(row: Row[Any]) -> EinbettungZeile:
    return EinbettungZeile(
        chunk_id=row.chunk_id,
        modell=row.modell,
        anbieter=row.anbieter,
        dimension=row.dimension,
        vektor=vektor_kompakt(row.vektor),
    )


async def _streame[Z: Zeile](stmt: Select[Any], wandle: Callable[[Row[Any]], Z]) -> AsyncIterator[Z]:
    """Serverseitiger Cursor: Zeilen kommen stapelweise, nichts wird komplett geladen."""
    async with sitzung() as s:
        ergebnis = await s.stream(stmt.execution_options(yield_per=STAPEL_ZEILEN))
        async for row in ergebnis:
            yield wandle(row)


async def _anzahl(s: AsyncSession, stmt: Select[Any]) -> int:
    return int(await s.scalar(stmt) or 0)


class DatenbankQuelle:
    """Export aus der Datenbank; Vorschaubilder aus der lokalen Ablage."""

    def __init__(self, daten_verzeichnis: Path, miniaturen_verzeichnis: Path) -> None:
        self._daten = daten_verzeichnis
        self._miniaturen = miniaturen_verzeichnis

    async def zaehler(self) -> Zaehler:
        async with sitzung() as s:
            return Zaehler(
                videos=await _anzahl(s, select(func.count(Video.id))),
                transkripte=await _anzahl(s, select(func.count(Transkript.id)).where(Transkript.aktuell.is_(True))),
                korrekturen=await _anzahl(s, select(func.count(Korrektur.id)).where(Korrektur.aktuell.is_(True))),
                chunks=await _anzahl(s, select(func.count(Chunk.id)).where(Chunk.video_id.is_not(None))),
                einbettungen=await _anzahl(s, select(func.count(Einbettung.id))),
                dokumente=await _anzahl(s, select(func.count(Dokument.id))),
                dokument_abschnitte=await _anzahl(s, select(func.count(DokumentAbschnitt.id))),
                dokument_chunks=await _anzahl(s, select(func.count(Chunk.id)).where(Chunk.dokument_id.is_not(None))),
            )

    def _miniatur_datei(self, video: Video) -> Path | None:
        kandidaten: list[Path] = []
        if video.miniatur_pfad:
            p = Path(video.miniatur_pfad)
            kandidaten.append(p if p.is_absolute() else self._daten / p)
        kandidaten.append(self._miniaturen / f"{video.id}.jpg")
        for k in kandidaten:
            if k.is_file():
                return k
        return None

    async def videos(self) -> AsyncIterator[Videoexport]:
        stmt = select(Video).order_by(Video.veroeffentlicht.desc().nulls_last(), Video.id)
        async with sitzung() as s:
            ergebnis = await s.stream_scalars(stmt.execution_options(yield_per=STAPEL_ZEILEN))
            async for video in ergebnis:
                yield Videoexport(zeile=_video_zeile(video), miniatur_datei=self._miniatur_datei(video))

    def transkripte(self) -> AsyncIterator[TranskriptZeile]:
        stmt = (
            select(
                Transkript.id,
                Transkript.video_id,
                Transkript.engine,
                Transkript.modell,
                Transkript.sprache,
                Transkript.volltext,
                Transkript.segmente,
                Transkript.dauer_verarbeitung_s,
                Transkript.erstellt,
            )
            .where(Transkript.aktuell.is_(True))
            .order_by(Transkript.video_id, Transkript.erstellt)
        )
        return _streame(stmt, _aus_spalten(TranskriptZeile))

    def korrekturen(self) -> AsyncIterator[KorrekturZeile]:
        stmt = (
            select(
                Korrektur.id,
                Korrektur.video_id,
                Korrektur.transkript_id,
                Korrektur.engine,
                Korrektur.anbieter,
                Korrektur.modell,
                Korrektur.absaetze,
                Korrektur.themen,
                Korrektur.zusammenfassung,
                Korrektur.aehnlichkeit,
                Korrektur.bloecke_gesamt,
                Korrektur.bloecke_verworfen,
                Korrektur.dauer_verarbeitung_s,
                Korrektur.manuell_bearbeitet,
                Korrektur.erstellt,
            )
            .where(Korrektur.aktuell.is_(True))
            .order_by(Korrektur.video_id, Korrektur.erstellt)
        )
        return _streame(stmt, _aus_spalten(KorrekturZeile))

    def chunks(self) -> AsyncIterator[ChunkZeile]:
        stmt = (
            select(
                Chunk.id,
                Chunk.video_id,
                Chunk.korrektur_id,
                Chunk.reihenfolge,
                Chunk.text,
                Chunk.start_s,
                Chunk.end_s,
                Chunk.zeichen,
                Chunk.thema,
                Chunk.ueberlappung_vor,
                Chunk.ueberlappung_nach,
                Chunk.manuell_bearbeitet,
                Chunk.erstellt,
            )
            .where(Chunk.video_id.is_not(None))
            .order_by(Chunk.video_id, Chunk.reihenfolge)
        )
        return _streame(stmt, _aus_spalten(ChunkZeile))

    def _dokument_datei(self, d: Dokument) -> Path | None:
        if not d.datei_pfad:
            return None
        p = Path(d.datei_pfad)
        pfad = p if p.is_absolute() else self._daten / p
        return pfad if pfad.is_file() else None

    async def dokumente(self) -> AsyncIterator[Dokumentexport]:
        stmt = select(Dokument).order_by(Dokument.erstellt, Dokument.id)
        async with sitzung() as s:
            ergebnis = await s.stream_scalars(stmt.execution_options(yield_per=STAPEL_ZEILEN))
            async for d in ergebnis:
                yield Dokumentexport(zeile=_dokument_zeile(d), datei=self._dokument_datei(d))

    def dokument_abschnitte(self) -> AsyncIterator[AbschnittZeile]:
        stmt = select(
            DokumentAbschnitt.id,
            DokumentAbschnitt.dokument_id,
            DokumentAbschnitt.reihenfolge,
            DokumentAbschnitt.ebene,
            DokumentAbschnitt.titel,
            DokumentAbschnitt.text,
            DokumentAbschnitt.zeichen,
            DokumentAbschnitt.anker,
            DokumentAbschnitt.seite_von,
            DokumentAbschnitt.seite_bis,
            DokumentAbschnitt.position_von,
            DokumentAbschnitt.erstellt,
        ).order_by(DokumentAbschnitt.dokument_id, DokumentAbschnitt.reihenfolge)
        return _streame(stmt, _aus_spalten(AbschnittZeile))

    def dokument_chunks(self) -> AsyncIterator[DokumentChunkZeile]:
        stmt = (
            select(
                Chunk.id,
                Chunk.dokument_id,
                Chunk.abschnitt_id,
                Chunk.reihenfolge,
                Chunk.text,
                Chunk.zeichen,
                Chunk.thema,
                Chunk.ueberlappung_vor,
                Chunk.ueberlappung_nach,
                Chunk.position_von,
                Chunk.position_bis,
                Chunk.manuell_bearbeitet,
                Chunk.erstellt,
            )
            .where(Chunk.dokument_id.is_not(None))
            .order_by(Chunk.dokument_id, Chunk.reihenfolge)
        )
        return _streame(stmt, _aus_spalten(DokumentChunkZeile))

    def einbettungen(self) -> AsyncIterator[EinbettungZeile]:
        stmt = select(Einbettung.chunk_id, Einbettung.modell, Einbettung.anbieter, Einbettung.dimension, Einbettung.vektor).order_by(
            Einbettung.chunk_id, Einbettung.modell
        )
        return _streame(stmt, _einbettung_zeile)


# --------------------------------------------------------------------------- Datenbank: Ziel
def _video_werte(zeile: VideoZeile) -> dict[str, Any]:
    """Metadaten der Quelle, die bei Neuanlage und Aktualisierung gleichermaßen gelten."""
    return {
        "extern_id": zeile.extern_id,
        "original_url": zeile.original_url,
        "titel": zeile.titel,
        "beschreibung": zeile.beschreibung,
        "veroeffentlicht": zeile.veroeffentlicht,
        "dauer_s": zeile.dauer_s,
        "typ": zeile.typ,
        "aufrufe": zeile.aufrufe,
        "schlagworte": zeile.schlagworte,
        "kanal_name": zeile.kanal_name,
        "serie": zeile.serie,
        "folge_nr": zeile.folge_nr,
        "miniatur_url": zeile.miniatur_url,
        "metadaten_original": zeile.metadaten_original,
    }


def _dokument_werte(zeile: DokumentZeile) -> dict[str, Any]:
    return {
        "titel": zeile.titel,
        "autor": zeile.autor,
        "art": zeile.art,
        "sprache": zeile.sprache,
        "beschreibung": zeile.beschreibung,
        "veroeffentlicht": zeile.veroeffentlicht,
        "dateiname": zeile.dateiname,
        "groesse_bytes": zeile.groesse_bytes,
        "zeichen": zeile.zeichen,
        "metadaten_original": zeile.metadaten_original,
        "felder_manuell": zeile.felder_manuell,
    }


class DatenbankZiel:
    """Import in die Datenbank innerhalb einer Sitzung; festgeschrieben wird erst in `abschliessen`.

    Einfügen läuft über Core-Anweisungen in Stapeln, damit die Sitzung bei zehntausenden
    Einbettungen keine Objekte im Speicher hält.
    """

    def __init__(
        self, session: AsyncSession, daten_verzeichnis: Path, miniaturen_verzeichnis: Path, dokumente_verzeichnis: Path | None = None
    ) -> None:
        self._s = session
        self._daten = daten_verzeichnis
        self._miniaturen = miniaturen_verzeichnis
        self._dokumente = dokumente_verzeichnis or (daten_verzeichnis / "dokumente")

    async def vorhandene_videos(self) -> VorhandeneVideos:
        rows = (await self._s.execute(select(Video.id, Video.extern_id, Video.stufe, Video.auswahl_manuell))).all()
        return VorhandeneVideos(
            je_extern_id={r.extern_id: VorhandenesVideo(r.id, r.stufe, bool(r.auswahl_manuell)) for r in rows},
            ids={r.id for r in rows},
        )

    async def video_anlegen(self, video_id: str, zeile: VideoZeile) -> None:
        await self._s.execute(
            insert(Video).values(
                id=video_id,
                quelle_id=None,
                ausgewaehlt=zeile.ausgewaehlt,
                auswahl_manuell=zeile.auswahl_manuell,
                notizen=zeile.notizen,
                stufe=Stufe.ENTDECKT.value,
                **_video_werte(zeile),
            )
        )

    async def video_aktualisieren(self, video_id: str, zeile: VideoZeile, ausgewaehlt_uebernehmen: bool) -> None:
        werte = _video_werte(zeile)
        werte["aktualisiert"] = jetzt()
        if ausgewaehlt_uebernehmen:
            werte["ausgewaehlt"] = zeile.ausgewaehlt
        await self._s.execute(update(Video).where(Video.id == video_id).values(**werte))

    async def transkripte_loeschen(self, video_id: str) -> None:
        await self._s.execute(delete(Transkript).where(Transkript.video_id == video_id))

    async def korrekturen_loeschen(self, video_id: str) -> None:
        await self._s.execute(delete(Korrektur).where(Korrektur.video_id == video_id))

    async def chunks_loeschen(self, video_id: str) -> None:
        # Einbettungen hängen per Fremdschlüssel (ON DELETE CASCADE) an den Chunks.
        await self._s.execute(delete(Chunk).where(Chunk.video_id == video_id))

    async def transkripte_einfuegen(self, zeilen: list[TranskriptZeile]) -> None:
        await self._s.execute(insert(Transkript), [{**z.model_dump(), "aktuell": True} for z in zeilen])

    async def korrekturen_einfuegen(self, zeilen: list[KorrekturZeile]) -> None:
        await self._s.execute(insert(Korrektur), [{**z.model_dump(), "aktuell": True} for z in zeilen])

    async def chunks_einfuegen(self, zeilen: list[ChunkZeile]) -> None:
        await self._s.execute(insert(Chunk), [z.model_dump() for z in zeilen])

    async def einbettungen_einfuegen(self, zeilen: list[EinbettungZeile]) -> None:
        await self._s.execute(insert(Einbettung), [{"id": neue_id(), **z.model_dump()} for z in zeilen])

    async def miniatur_ablegen(self, video_id: str, daten: IO[bytes]) -> str:
        self._miniaturen.mkdir(parents=True, exist_ok=True)
        ziel = self._miniaturen / f"{video_id}.jpg"
        with ziel.open("wb") as f:
            shutil.copyfileobj(daten, f)
        try:
            return str(ziel.relative_to(self._daten))
        except ValueError:
            return str(ziel)

    async def video_abschliessen(self, video_id: str, stufe: Stufe, miniatur_pfad: str | None) -> None:
        werte: dict[str, Any] = {"stufe": stufe.value, "aktualisiert": jetzt()}
        if miniatur_pfad:
            werte["miniatur_pfad"] = miniatur_pfad
        await self._s.execute(update(Video).where(Video.id == video_id).values(**werte))

    async def vorhandene_dokumente(self) -> dict[str, str]:
        rows = (await self._s.execute(select(Dokument.id, Dokument.stufe))).all()
        return {r.id: r.stufe for r in rows}

    async def dokument_anlegen(self, zeile: DokumentZeile) -> None:
        await self._s.execute(
            insert(Dokument).values(id=zeile.id, stufe=Dokumentstufe.IMPORTIERT.value, notizen=zeile.notizen, **_dokument_werte(zeile))
        )

    async def dokument_aktualisieren(self, zeile: DokumentZeile) -> None:
        werte = _dokument_werte(zeile)
        werte["aktualisiert"] = jetzt()
        await self._s.execute(update(Dokument).where(Dokument.id == zeile.id).values(**werte))

    async def dokument_abschnitte_loeschen(self, dokument_id: str) -> None:
        await self._s.execute(delete(DokumentAbschnitt).where(DokumentAbschnitt.dokument_id == dokument_id))

    async def dokument_chunks_loeschen(self, dokument_id: str) -> None:
        await self._s.execute(delete(Chunk).where(Chunk.dokument_id == dokument_id))

    async def dokument_abschnitte_einfuegen(self, zeilen: list[AbschnittZeile]) -> None:
        await self._s.execute(insert(DokumentAbschnitt), [z.model_dump() for z in zeilen])

    async def dokument_chunks_einfuegen(self, zeilen: list[DokumentChunkZeile]) -> None:
        await self._s.execute(insert(Chunk), [{**z.model_dump(), "video_id": None, "korrektur_id": None} for z in zeilen])

    async def dokument_datei_ablegen(self, dokument_id: str, endung: str, daten: IO[bytes]) -> str:
        self._dokumente.mkdir(parents=True, exist_ok=True)
        ziel = self._dokumente / f"{dokument_id}{endung}"
        with ziel.open("wb") as f:
            shutil.copyfileobj(daten, f)
        # Dokumente speichern den vollen Pfad (so legt sie auch der Hochlade-Import ab)
        return str(ziel)

    async def dokument_abschliessen(self, dokument_id: str, stufe: Dokumentstufe, datei_pfad: str | None) -> None:
        werte: dict[str, Any] = {"stufe": stufe.value, "aktualisiert": jetzt()}
        if datei_pfad:
            werte["datei_pfad"] = datei_pfad
        await self._s.execute(update(Dokument).where(Dokument.id == dokument_id).values(**werte))

    async def abschliessen(self) -> None:
        await self._s.commit()
