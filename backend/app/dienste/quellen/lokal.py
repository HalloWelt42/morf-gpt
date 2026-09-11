"""Lokale Dateien als Videoquelle: ein Verzeichnis mit Video- oder Audiodateien.

Die Quelle braucht keinen Dienst: ein Ordner auf dem eigenen Rechner reicht. Jede
Mediendatei darunter ist ein Video der Bibliothek. Die Kennung eines Videos entsteht aus
seinem Pfad relativ zum Ordner (stabil über Abgleiche hinweg, kein Inhaltshash nötig).

Metadaten kommen, in dieser Reihenfolge, aus einem Beiblatt (`<name>.json` oder
`<name>.info.json` neben der Datei, etwa von yt-dlp), aus ffprobe (Dauer) und aus dem
Dateinamen (Titel) samt Änderungsdatum. Ein Bild `<name>.jpg|.png|.webp` daneben ist das
Vorschaubild; fehlt es, wird bei Videodateien ein Einzelbild aus dem Film gezogen.
Alles, was hier unvollständig bleibt, pflegt der Nutzer später von Hand am Video.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..audio import bezug
from .basis import Kanalinfo, QuellenFehler, QuellVideo, Videodetail, Videoseite
from .tubevault import datum_parsen

log = logging.getLogger(__name__)

TYP_KENNUNG = "lokal"
TYP_TITEL = "Lokale Dateien"

# Vorgabe für die Einstellung quelle.dateiendungen (dort änderbar).
ENDUNGEN_VORGABE = "mp4,mkv,webm,mov,m4v,avi,m4a,mp3,wav,flac,ogg,opus,aac"
BILD_ENDUNGEN: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".webp")
AUDIO_ENDUNGEN: frozenset[str] = frozenset({".m4a", ".mp3", ".wav", ".flac", ".ogg", ".opus", ".aac"})
BEIBLATT_ENDUNGEN: tuple[str, ...] = (".info.json", ".json")

# Einzelbild aus dem Film: nach diesem Anteil der Dauer, höchstens so viele Sekunden.
EINZELBILD_ANTEIL = 0.1
EINZELBILD_MAX_S = 30.0
EINZELBILD_BREITE = 480
BILD_ZEITGRENZE_S = 60.0

Dauersonde = Callable[[Path], Awaitable[float | None]]


# ---------------------------------------------------------------- reine Funktionen
def endungen_parsen(text: Any) -> frozenset[str]:
    """'mp4, mkv' -> {'.mp4', '.mkv'}; leer -> Vorgabe."""
    teile = [t.strip().lower().lstrip(".") for t in str(text or "").split(",")]
    endungen = frozenset(f".{t}" for t in teile if t)
    return endungen or endungen_parsen(ENDUNGEN_VORGABE)


def kennung_aus_pfad(relativer_pfad: str) -> str:
    """Stabile Kennung aus dem relativen Pfad (passt in die Spalte extern_id, taugt als Dateiname)."""
    return "datei-" + hashlib.sha1(relativer_pfad.encode("utf-8")).hexdigest()[:20]


def titel_aus_dateiname(name: str) -> str:
    """'2024-03-01_Vortrag_ueber_Zeit.mp4' -> '2024-03-01 Vortrag ueber Zeit'."""
    stamm = Path(name).stem
    return " ".join(stamm.replace("_", " ").split()).strip() or stamm


def ist_versteckt(relativ: Path) -> bool:
    return any(teil.startswith(".") for teil in relativ.parts)


def dateien_auflisten(wurzel: Path, endungen: frozenset[str]) -> list[Path]:
    """Alle Mediendateien unter der Wurzel, nach relativem Pfad sortiert, versteckte ausgelassen."""
    gefunden: list[Path] = []
    for pfad in wurzel.rglob("*"):
        if not pfad.is_file() or pfad.suffix.lower() not in endungen:
            continue
        if ist_versteckt(pfad.relative_to(wurzel)):
            continue
        gefunden.append(pfad)
    return sorted(gefunden, key=lambda p: str(p.relative_to(wurzel)).lower())


def beiblatt_pfad(datei: Path) -> Path | None:
    for endung in BEIBLATT_ENDUNGEN:
        kandidat = datei.with_name(datei.stem + endung)
        if kandidat.is_file():
            return kandidat
    return None


def beiblatt_lesen(datei: Path) -> dict[str, Any]:
    """Das Beiblatt neben der Datei als Objekt; fehlt es oder ist es kaputt, ein leeres Objekt."""
    pfad = beiblatt_pfad(datei)
    if pfad is None:
        return {}
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("Beiblatt %s nicht lesbar: %s", pfad, e)
        return {}
    return daten if isinstance(daten, dict) else {}


def bild_pfad(datei: Path) -> Path | None:
    for endung in BILD_ENDUNGEN:
        kandidat = datei.with_name(datei.stem + endung)
        if kandidat.is_file():
            return kandidat
    return None


def _datum_aus_beiblatt(beiblatt: dict[str, Any]) -> datetime | None:
    for schluessel in ("veroeffentlicht", "published", "upload_date", "release_date", "datum"):
        wert = beiblatt.get(schluessel)
        if wert:
            gelesen = datum_parsen(wert)
            if gelesen is not None:
                return gelesen
    return None


def _schlagworte(beiblatt: dict[str, Any]) -> list[str]:
    for schluessel in ("schlagworte", "tags", "categories"):
        wert = beiblatt.get(schluessel)
        if isinstance(wert, list):
            return [str(w).strip() for w in wert if str(w).strip()]
    return []


def video_aus_datei(wurzel: Path, datei: Path, beiblatt: dict[str, Any], dauer_s: float | None) -> QuellVideo:
    """Übersetzt eine Datei samt Beiblatt in ein QuellVideo. Der Pfad bleibt roh erhalten."""
    relativ = str(datei.relative_to(wurzel))
    stat = datei.stat()
    geaendert = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    titel = str(beiblatt.get("titel") or beiblatt.get("title") or "").strip() or titel_aus_dateiname(datei.name)
    dauer = dauer_s if dauer_s is not None else _als_float(beiblatt.get("dauer_s") or beiblatt_dauer(beiblatt))
    return QuellVideo(
        extern_id=kennung_aus_pfad(relativ),
        titel=titel,
        beschreibung=str(beiblatt.get("beschreibung") or beiblatt.get("description") or ""),
        veroeffentlicht=_datum_aus_beiblatt(beiblatt) or geaendert,
        dauer_s=int(dauer) if dauer is not None else None,
        typ=str(beiblatt.get("typ") or "video").strip().lower() or "video",
        aufrufe=_als_int(beiblatt.get("aufrufe") or beiblatt.get("view_count")),
        schlagworte=_schlagworte(beiblatt),
        kanal_name=str(beiblatt.get("kanal") or beiblatt.get("channel") or beiblatt.get("uploader") or ""),
        miniatur_url="",
        original_url=str(beiblatt.get("original_url") or beiblatt.get("webpage_url") or beiblatt.get("url") or "").strip(),
        heruntergeladen=True,
        roh={
            "pfad": relativ,
            "dateiname": datei.name,
            "groesse_bytes": stat.st_size,
            "geaendert": geaendert.isoformat(),
            "beiblatt": beiblatt,
        },
    )


def beiblatt_dauer(beiblatt: dict[str, Any]) -> Any:
    """Dauer aus einem yt-dlp-Beiblatt (Sekunden)."""
    return beiblatt.get("duration")


def _als_float(wert: Any) -> float | None:
    try:
        return float(wert)
    except (TypeError, ValueError):
        return None


def _als_int(wert: Any) -> int | None:
    try:
        return int(float(wert))
    except (TypeError, ValueError):
        return None


def verzeichnis_pruefen(pfad_text: str) -> Path:
    """Der Ordner als Pfad; fehlt er oder ist er keiner, ein sprechender Fehler."""
    text = str(pfad_text or "").strip()
    if not text:
        raise QuellenFehler("Für lokale Dateien muss ein Verzeichnis angegeben sein")
    pfad = Path(text).expanduser()
    if not pfad.is_dir():
        raise QuellenFehler(f"Das Verzeichnis '{text}' gibt es nicht oder es ist kein Ordner")
    return pfad


def datei_finden(wurzel_text: str, extern_id: str, endungen: Iterable[str]) -> Path:
    """Die Datei zu einer Kennung (für den Audio-Bezug). Wirft QuellenFehler, wenn sie fehlt."""
    wurzel = verzeichnis_pruefen(wurzel_text)
    for datei in dateien_auflisten(wurzel, frozenset(endungen)):
        if kennung_aus_pfad(str(datei.relative_to(wurzel))) == extern_id:
            return datei
    raise QuellenFehler(f"Im Verzeichnis '{wurzel}' liegt keine Datei mehr zur Kennung {extern_id}")


async def dauer_per_ffprobe(pfad: Path) -> float | None:
    try:
        return (await bezug.ffprobe_eigenschaften(pfad)).dauer_s
    except bezug.AudioBezugFehler as e:
        log.warning("Dauer von %s nicht lesbar: %s", pfad.name, e)
        return None


def einzelbild_kommandozeile(ffmpeg: str, datei: Path, sekunde: float) -> list[str]:
    return [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-ss",
        f"{sekunde:.2f}",
        "-i",
        str(datei),
        "-frames:v",
        "1",
        "-vf",
        f"scale={EINZELBILD_BREITE}:-2",
        "-f",
        "image2",
        "-c:v",
        "mjpeg",
        "pipe:1",
    ]


def bild_kommandozeile(ffmpeg: str, bild: Path) -> list[str]:
    """Beliebiges Bild nach JPEG (die Miniaturablage ist einheitlich JPEG)."""
    return [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(bild), "-frames:v", "1", "-f", "image2", "-c:v", "mjpeg", "pipe:1"]


async def _ffmpeg_bytes(kommando: list[str]) -> bytes:
    try:
        prozess = await asyncio.create_subprocess_exec(
            *kommando, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except OSError as e:
        raise QuellenFehler(f"ffmpeg konnte nicht gestartet werden: {e}") from e
    try:
        ausgabe, fehler = await asyncio.wait_for(prozess.communicate(), timeout=BILD_ZEITGRENZE_S)
    except TimeoutError as e:
        prozess.kill()
        raise QuellenFehler("ffmpeg brauchte zu lange für das Vorschaubild") from e
    if prozess.returncode != 0 or not ausgabe:
        text = fehler.decode("utf-8", errors="replace").strip().splitlines()
        raise QuellenFehler("Vorschaubild nicht erzeugbar: " + (text[-1] if text else "keine Ausgabe"))
    return ausgabe


async def bild_als_jpeg(bild: Path, ffmpeg: str | None = None) -> bytes:
    if bild.suffix.lower() in (".jpg", ".jpeg"):
        return bild.read_bytes()
    return await _ffmpeg_bytes(bild_kommandozeile(ffmpeg or bezug.ffmpeg_pfad(), bild))


async def einzelbild(datei: Path, dauer_s: float | None, ffmpeg: str | None = None) -> bytes:
    sekunde = min(EINZELBILD_MAX_S, (dauer_s or 0.0) * EINZELBILD_ANTEIL)
    return await _ffmpeg_bytes(einzelbild_kommandozeile(ffmpeg or bezug.ffmpeg_pfad(), datei, sekunde))


# ---------------------------------------------------------------- die Quelle
class LokaleDateien:
    """Videoquelle über ein Verzeichnis. Die Dateiliste wird je Instanz einmal gelesen."""

    def __init__(self, verzeichnis: str, endungen: frozenset[str], dauersonde: Dauersonde | None = None) -> None:
        self._verzeichnis_text = verzeichnis
        self._endungen = endungen
        self._dauersonde: Dauersonde = dauersonde or dauer_per_ffprobe
        self._dateien: list[Path] | None = None
        self._dauern: dict[Path, float | None] = {}

    @property
    def wurzel(self) -> Path:
        return verzeichnis_pruefen(self._verzeichnis_text)

    def _liste(self) -> list[Path]:
        if self._dateien is None:
            self._dateien = dateien_auflisten(self.wurzel, self._endungen)
        return self._dateien

    async def _dauer(self, datei: Path) -> float | None:
        if datei not in self._dauern:
            self._dauern[datei] = await self._dauersonde(datei)
        return self._dauern[datei]

    async def schliessen(self) -> None:
        return None

    async def kanal(self) -> Kanalinfo:
        wurzel = self.wurzel
        anzahl = len(self._liste())
        return Kanalinfo(
            kanal_id=str(wurzel),
            name=wurzel.name or str(wurzel),
            beschreibung=f"{anzahl} Dateien unter {wurzel}",
            videos_gesamt=anzahl,
            videos_heruntergeladen=anzahl,
            roh={"verzeichnis": str(wurzel), "dateien": anzahl, "endungen": sorted(self._endungen)},
        )

    async def videoseite(self, seite: int, je_seite: int) -> Videoseite:
        if seite < 1:
            raise QuellenFehler("Seiten werden ab 1 gezählt")
        wurzel = self.wurzel
        alle = self._liste()
        ausschnitt = alle[(seite - 1) * je_seite : seite * je_seite]
        videos: list[QuellVideo] = []
        for datei in ausschnitt:
            beiblatt = beiblatt_lesen(datei)
            videos.append(video_aus_datei(wurzel, datei, beiblatt, await self._dauer(datei)))
        return Videoseite(videos=videos, gesamt=len(alle), seite=seite, je_seite=je_seite)

    async def videodetail(self, extern_id: str) -> Videodetail | None:
        return None

    def datei(self, extern_id: str) -> Path:
        wurzel = self.wurzel
        for datei in self._liste():
            if kennung_aus_pfad(str(datei.relative_to(wurzel))) == extern_id:
                return datei
        raise QuellenFehler(f"Keine Datei zur Kennung {extern_id} im Verzeichnis '{wurzel}'")

    async def miniatur(self, extern_id: str) -> bytes:
        datei = self.datei(extern_id)
        bild = bild_pfad(datei)
        if bild is not None:
            return await bild_als_jpeg(bild)
        if datei.suffix.lower() in AUDIO_ENDUNGEN:
            raise QuellenFehler(f"'{datei.name}' ist eine Audiodatei ohne Bild daneben")
        return await einzelbild(datei, await self._dauer(datei))
