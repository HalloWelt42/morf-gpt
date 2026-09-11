"""Audio-Bezug: die Audiodatei eines Videos beschaffen.

Zwei Wege hinter einer Schnittstelle (`AudioBezug`):

- `VideostromFfmpeg`: das Video wird von der Quelle in eine temporäre Datei gestreamt
  und hier mit ffmpeg zu Mono-AAC gewandelt. Auf dem Quellrechner bleibt nichts zurück.
- `QuellExtraktion`: die Quelle extrahiert das Audio selbst (blockierend, hinterlässt
  dort eine Kopie), danach wird die fertige Datei gestreamt.

Welcher Weg gilt, entscheidet die Einstellung `audio.bezugsweg` (siehe `waehle_bezug`).
Nach dem Bezug liest ffprobe Dauer, Abtastrate und Kanäle der fertigen Datei.

Ablage: Audiodateien liegen unter `data/audio/<video_id>.m4a`; in der Datenbank steht
der Pfad relativ zum Datenverzeichnis, damit das Verzeichnis umziehen kann.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import anyio
import httpx

from ...config import einstellungen

log = logging.getLogger(__name__)

BEZUGSWEG_VIDEOSTROM = "videostrom_ffmpeg"
BEZUGSWEG_QUELLE = "quelle_extraktion"
BEZUGSWEG_DATEI = "lokale_datei"  # nicht wählbar: gilt immer für Quellen vom Typ lokal
BEZUGSWEGE: tuple[str, ...] = (BEZUGSWEG_VIDEOSTROM, BEZUGSWEG_QUELLE)
AUDIO_FORMAT = "m4a"

# Vorgabewerte ohne Eintrag im Einstellungsregister (Vorschlag im Bericht: audio.ffmpeg_pfad,
# audio.ffprobe_pfad, audio.zeitgrenze_s). Sobald das Register sie kennt, werden sie hier
# von außen hereingereicht; die Konstanten bleiben nur als letzte Rückfallebene.
FFMPEG_FALLBACK = "/opt/homebrew/bin/ffmpeg"
FFPROBE_FALLBACK = "/opt/homebrew/bin/ffprobe"
ZEITGRENZE_S_VORGABE = 3600.0

# Technische Konstanten (keine Nutzerentscheidung)
LESEBLOCK = 256 * 1024
FORTSCHRITT_SCHRITT = 0.01
MELDE_BYTES_OHNE_GESAMT = 8 * 1024 * 1024
PROZESS_ENDE_FRIST_S = 5.0

Fortschrittsmelder = Callable[[float, str], Awaitable[None]]


class AudioBezugFehler(RuntimeError):
    """Die Audiodatei konnte nicht beschafft oder gelesen werden."""


@dataclass(slots=True)
class Wandlung:
    """Zielparameter der Audiowandlung (aus den Einstellungen audio.*)."""

    abtastrate: int
    bitrate_kbit: int


@dataclass(slots=True)
class AudioEigenschaften:
    """Was ffprobe über eine fertige Audiodatei weiß."""

    dauer_s: float | None
    abtastrate: int | None
    kanaele: int | None
    groesse_bytes: int


@dataclass(slots=True)
class AudioErgebnis:
    pfad: Path
    bezugsweg: str
    eigenschaften: AudioEigenschaften


Sonde = Callable[[Path], Awaitable[AudioEigenschaften]]


class AudioBezug(Protocol):
    """Ein Bezugsweg: beschafft die Audiodatei eines Videos an den Zielpfad."""

    kennung: str

    async def beschaffe(
        self,
        basis_url: str,
        extern_id: str,
        ziel: Path,
        fortschritt: Fortschrittsmelder,
        abbruch: asyncio.Event,
        erwartete_dauer_s: float | None = None,
    ) -> AudioErgebnis: ...


# ------------------------------------------------------------------ Ablage und Adressen


def ziel_pfad(video_id: str) -> Path:
    return einstellungen.audio_verzeichnis / f"{video_id}.{AUDIO_FORMAT}"


def temp_verzeichnis() -> Path:
    """Zwischenablage für Videoströme; unter dem Datenverzeichnis, nie im System-Temp."""
    return einstellungen.daten_verzeichnis / "tmp"


def teil_pfad(ziel: Path) -> Path:
    """Halbfertige Datei neben dem Ziel; erst nach Erfolg wird sie an den Zielnamen verschoben."""
    return ziel.with_name(f"{ziel.stem}.teil{ziel.suffix}")


def pfad_speicherform(pfad: Path) -> str:
    """Pfad, wie er in der Datenbank steht: relativ zum Datenverzeichnis, sonst absolut."""
    try:
        return str(pfad.resolve().relative_to(einstellungen.daten_verzeichnis.resolve()))
    except ValueError:
        return str(pfad)


def pfad_aufloesen(gespeichert: str) -> Path:
    p = Path(gespeichert)
    if p.is_absolute():
        return p
    return einstellungen.daten_verzeichnis / p


def video_url(basis_url: str, extern_id: str) -> str:
    return f"{basis_url.rstrip('/')}/api/player/{extern_id}"


def extraktions_url(basis_url: str, extern_id: str) -> str:
    return f"{video_url(basis_url, extern_id)}/audio/extract"


def audio_url(basis_url: str, extern_id: str) -> str:
    return f"{video_url(basis_url, extern_id)}/audio"


# ------------------------------------------------------------------ Werkzeuge (ffmpeg, ffprobe)


def werkzeug_pfad(name: str, fallback: str) -> str:
    """Sucht ein Kommandozeilenwerkzeug im PATH; sonst der bekannte Homebrew-Pfad."""
    gefunden = shutil.which(name)
    return gefunden or fallback


def ffmpeg_pfad() -> str:
    return werkzeug_pfad("ffmpeg", FFMPEG_FALLBACK)


def ffprobe_pfad() -> str:
    return werkzeug_pfad("ffprobe", FFPROBE_FALLBACK)


def ffmpeg_kommandozeile(ffmpeg: str, quelle: Path, ziel: Path, wandlung: Wandlung) -> list[str]:
    """Mono-AAC mit gewünschter Abtastrate und Bitrate, Kopf am Dateianfang (faststart).

    `-progress pipe:1` liefert Zeilen wie `out_time_us=...` auf stdout, daraus entsteht
    der Fortschritt; Fehler und Warnungen landen auf stderr.
    """
    return [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-nostats",
        "-progress",
        "pipe:1",
        "-y",
        "-i",
        str(quelle),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(wandlung.abtastrate),
        "-c:a",
        "aac",
        "-b:a",
        f"{wandlung.bitrate_kbit}k",
        "-movflags",
        "+faststart",
        str(ziel),
    ]


def ffprobe_kommandozeile(ffprobe: str, pfad: Path) -> list[str]:
    return [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(pfad),
    ]


def eigenschaften_aus_ffprobe(daten: dict[str, Any], groesse_bytes: int) -> AudioEigenschaften:
    """Liest Dauer, Abtastrate und Kanäle aus der JSON-Ausgabe von ffprobe."""
    format_teil = daten.get("format") if isinstance(daten.get("format"), dict) else {}
    dauer = _als_float(format_teil.get("duration"))
    abtastrate: int | None = None
    kanaele: int | None = None
    for strom in daten.get("streams") or []:
        if not isinstance(strom, dict) or strom.get("codec_type") != "audio":
            continue
        abtastrate = _als_int(strom.get("sample_rate"))
        kanaele = _als_int(strom.get("channels"))
        if dauer is None:
            dauer = _als_float(strom.get("duration"))
        break
    return AudioEigenschaften(dauer_s=dauer, abtastrate=abtastrate, kanaele=kanaele, groesse_bytes=groesse_bytes)


async def ffprobe_eigenschaften(pfad: Path, ffprobe: str | None = None) -> AudioEigenschaften:
    """Fragt ffprobe nach der Datei. Wirft AudioBezugFehler, wenn die Datei unlesbar ist."""
    kommando = ffprobe_kommandozeile(ffprobe or ffprobe_pfad(), pfad)
    prozess = await _prozess_starten(kommando)
    ausgabe, fehler = await prozess.communicate()
    if prozess.returncode != 0:
        raise AudioBezugFehler(f"ffprobe kann '{pfad.name}' nicht lesen: {_letzte_zeilen(fehler)}")
    try:
        daten = json.loads(ausgabe.decode("utf-8", errors="replace"))
    except ValueError as e:
        raise AudioBezugFehler(f"ffprobe lieferte für '{pfad.name}' kein gültiges JSON") from e
    return eigenschaften_aus_ffprobe(daten, pfad.stat().st_size)


async def ffmpeg_ausfuehren(
    kommando: list[str],
    abbruch: asyncio.Event,
    fortschritt: Fortschrittsmelder | None = None,
    erwartete_dauer_s: float | None = None,
    von: float = 0.0,
    bis: float = 1.0,
) -> None:
    """Führt ffmpeg aus. Abbruch (Ereignis oder Task-Abbruch) beendet den Prozess sicher."""
    prozess = await _prozess_starten(kommando)
    leser = asyncio.gather(
        _stderr_sammeln(prozess),
        _ffmpeg_fortschritt_lesen(prozess, fortschritt, erwartete_dauer_s, von, bis),
    )
    try:
        await _warten_oder_abbrechen(prozess, abbruch)
    except BaseException:
        await _prozess_beenden(prozess)
        leser.cancel()
        # Aufräumen im Abbruchfall: die Leser dürfen den eigentlichen Abbruch nicht verdecken.
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await leser
        raise
    fehlertext, _ = await leser
    if prozess.returncode != 0:
        raise AudioBezugFehler(f"ffmpeg endete mit Code {prozess.returncode}: {_letzte_zeilen(fehlertext)}")


async def _prozess_starten(kommando: list[str]) -> asyncio.subprocess.Process:
    try:
        return await asyncio.create_subprocess_exec(
            *kommando,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as e:
        raise AudioBezugFehler(f"Werkzeug '{kommando[0]}' konnte nicht gestartet werden: {e}") from e


async def _warten_oder_abbrechen(prozess: asyncio.subprocess.Process, abbruch: asyncio.Event) -> None:
    """Wartet auf das Prozessende; ist vorher das Abbruch-Ereignis gesetzt, wird abgebrochen."""
    abbruch_warten = asyncio.create_task(abbruch.wait())
    prozess_warten = asyncio.create_task(prozess.wait())
    try:
        fertig, _ = await asyncio.wait({abbruch_warten, prozess_warten}, return_when=asyncio.FIRST_COMPLETED)
        if prozess_warten not in fertig:
            raise asyncio.CancelledError()
    finally:
        for aufgabe in (abbruch_warten, prozess_warten):
            if not aufgabe.done():
                aufgabe.cancel()


async def _prozess_beenden(prozess: asyncio.subprocess.Process) -> None:
    """Freundlich beenden, nach Frist hart beenden. Ein schon beendeter Prozess ist kein Fehler."""
    if prozess.returncode is not None:
        return
    try:
        prozess.terminate()
        try:
            await asyncio.wait_for(prozess.wait(), timeout=PROZESS_ENDE_FRIST_S)
        except TimeoutError:
            prozess.kill()
            await prozess.wait()
    except ProcessLookupError:
        pass


async def _stderr_sammeln(prozess: asyncio.subprocess.Process) -> bytes:
    if prozess.stderr is None:
        return b""
    return await prozess.stderr.read()


async def _ffmpeg_fortschritt_lesen(
    prozess: asyncio.subprocess.Process,
    fortschritt: Fortschrittsmelder | None,
    erwartete_dauer_s: float | None,
    von: float,
    bis: float,
) -> None:
    """Liest `out_time_us=` aus der Fortschrittsausgabe und meldet den Anteil an der Dauer."""
    if prozess.stdout is None:
        return
    zuletzt = -1.0
    while True:
        zeile = await prozess.stdout.readline()
        if not zeile:
            return
        sekunden = ffmpeg_zeit_aus_zeile(zeile.decode("utf-8", errors="replace"))
        if sekunden is None or fortschritt is None or not erwartete_dauer_s or erwartete_dauer_s <= 0:
            continue
        anteil = min(1.0, sekunden / erwartete_dauer_s)
        if anteil - zuletzt < FORTSCHRITT_SCHRITT:
            continue
        zuletzt = anteil
        meldung = f"Wandle in Audio: {zeit_text(sekunden)} von {zeit_text(erwartete_dauer_s)}"
        await fortschritt(von + (bis - von) * anteil, meldung)


def ffmpeg_zeit_aus_zeile(zeile: str) -> float | None:
    """`out_time_us=12345678` -> 12.345678 Sekunden; andere Zeilen -> None."""
    zeile = zeile.strip()
    if not zeile.startswith("out_time_us="):
        return None
    wert = _als_int(zeile.split("=", 1)[1])
    if wert is None or wert < 0:
        return None
    return wert / 1_000_000


# ------------------------------------------------------------------ Strom in Datei


async def stream_zu_datei(
    client: httpx.AsyncClient,
    url: str,
    ziel: Path,
    fortschritt: Fortschrittsmelder,
    abbruch: asyncio.Event,
    von: float = 0.0,
    bis: float = 1.0,
    meldung: str = "Lade",
) -> int:
    """Lädt `url` nach `ziel`; Fortschritt aus Content-Length zwischen `von` und `bis`.

    Gibt die geschriebene Bytezahl zurück. Bei Abbruch oder Fehler wird die Teildatei
    gelöscht und der Fehler weitergereicht.
    """
    ziel.parent.mkdir(parents=True, exist_ok=True)
    drossel = _Fortschrittsdrossel(fortschritt, von, bis, meldung)
    geschrieben = 0
    vollstaendig = False
    try:
        async with client.stream("GET", url) as antwort:
            if antwort.status_code != 200:
                await antwort.aread()
                raise AudioBezugFehler(f"Quelle antwortet mit HTTP {antwort.status_code} auf {url}")
            gesamt = _content_length(antwort)
            async with await anyio.open_file(ziel, "wb") as datei:
                async for stueck in antwort.aiter_bytes(LESEBLOCK):
                    if abbruch.is_set():
                        raise asyncio.CancelledError()
                    await datei.write(stueck)
                    geschrieben += len(stueck)
                    await drossel.melde(geschrieben, gesamt)
            if gesamt is not None and geschrieben != gesamt:
                raise AudioBezugFehler(f"Übertragung unvollständig: {geschrieben} von {gesamt} Bytes von {url}")
        vollstaendig = True
    except httpx.HTTPError as e:
        raise AudioBezugFehler(f"Übertragung von {url} fehlgeschlagen ({e.__class__.__name__}: {e})") from e
    finally:
        if not vollstaendig:
            loesche_leise(ziel)
    return geschrieben


class _Fortschrittsdrossel:
    """Meldet nur, wenn sich genug getan hat (schont Datenbank und Ereignisbus)."""

    def __init__(self, melder: Fortschrittsmelder, von: float, bis: float, meldung: str) -> None:
        self._melder = melder
        self._von = von
        self._bis = bis
        self._meldung = meldung
        self._zuletzt_anteil = -1.0
        self._zuletzt_bytes = -MELDE_BYTES_OHNE_GESAMT

    async def melde(self, geschrieben: int, gesamt: int | None) -> None:
        anteil = _anteil(geschrieben, gesamt)
        if anteil is None:
            if geschrieben - self._zuletzt_bytes < MELDE_BYTES_OHNE_GESAMT:
                return
            self._zuletzt_bytes = geschrieben
            wert = self._von
        else:
            if anteil - self._zuletzt_anteil < FORTSCHRITT_SCHRITT:
                return
            self._zuletzt_anteil = anteil
            wert = self._von + (self._bis - self._von) * anteil
        await self._melder(wert, bytes_meldung(self._meldung, geschrieben, gesamt))


def _content_length(antwort: httpx.Response) -> int | None:
    wert = _als_int(antwort.headers.get("content-length"))
    return wert if wert and wert > 0 else None


def _anteil(geschrieben: int, gesamt: int | None) -> float | None:
    if not gesamt:
        return None
    return min(1.0, geschrieben / gesamt)


def bytes_meldung(praefix: str, geschrieben: int, gesamt: int | None) -> str:
    if gesamt is None:
        return f"{praefix}: {megabyte_text(geschrieben)} Megabyte"
    return f"{praefix}: {megabyte_text(geschrieben)} von {megabyte_text(gesamt)} Megabyte"


def megabyte_text(anzahl_bytes: int) -> str:
    return f"{anzahl_bytes / (1024 * 1024):.1f}".replace(".", ",")


def zeit_text(sekunden: float) -> str:
    ganz = int(max(0.0, sekunden))
    minuten, rest = divmod(ganz, 60)
    return f"{minuten}:{rest:02d}"


def loesche_leise(pfad: Path) -> None:
    """Entfernt eine Datei, wenn sie existiert; ein fehlender Pfad ist kein Fehler."""
    try:
        pfad.unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("Datei %s konnte nicht gelöscht werden: %s", pfad, e)


# ------------------------------------------------------------------ Bezugswege


def _client(zeitgrenze_s: float, transport: httpx.AsyncBaseTransport | None) -> httpx.AsyncClient:
    zeit = httpx.Timeout(zeitgrenze_s, connect=20)
    if transport is None:
        return httpx.AsyncClient(timeout=zeit, follow_redirects=True)
    return httpx.AsyncClient(timeout=zeit, follow_redirects=True, transport=transport)


class VideostromFfmpeg:
    """Video von der Quelle streamen, hier mit ffmpeg zu Mono-AAC wandeln."""

    kennung = BEZUGSWEG_VIDEOSTROM

    def __init__(
        self,
        wandlung: Wandlung,
        tmp_verzeichnis: Path | None = None,
        ffmpeg: str | None = None,
        sonde: Sonde | None = None,
        zeitgrenze_s: float = ZEITGRENZE_S_VORGABE,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._wandlung = wandlung
        self._tmp = tmp_verzeichnis or temp_verzeichnis()
        self._ffmpeg = ffmpeg or ffmpeg_pfad()
        self._sonde: Sonde = sonde or ffprobe_eigenschaften
        self._zeitgrenze_s = zeitgrenze_s
        self._transport = transport

    async def beschaffe(
        self,
        basis_url: str,
        extern_id: str,
        ziel: Path,
        fortschritt: Fortschrittsmelder,
        abbruch: asyncio.Event,
        erwartete_dauer_s: float | None = None,
    ) -> AudioErgebnis:
        zwischen = self._tmp / f"{extern_id}-{uuid.uuid4().hex}.mp4"
        teil = teil_pfad(ziel)
        try:
            async with _client(self._zeitgrenze_s, self._transport) as client:
                await stream_zu_datei(
                    client,
                    video_url(basis_url, extern_id),
                    zwischen,
                    fortschritt,
                    abbruch,
                    von=0.0,
                    bis=0.7,
                    meldung="Hole Video",
                )
            await fortschritt(0.7, "Wandle in Audio")
            ziel.parent.mkdir(parents=True, exist_ok=True)
            await ffmpeg_ausfuehren(
                ffmpeg_kommandozeile(self._ffmpeg, zwischen, teil, self._wandlung),
                abbruch,
                fortschritt,
                erwartete_dauer_s,
                von=0.7,
                bis=0.95,
            )
            os.replace(teil, ziel)
        except BaseException:
            loesche_leise(teil)
            raise
        finally:
            loesche_leise(zwischen)
        return AudioErgebnis(pfad=ziel, bezugsweg=self.kennung, eigenschaften=await self._sonde(ziel))


class QuellExtraktion:
    """Die Quelle extrahiert selbst (blockierend), dann wird die fertige Datei geholt."""

    kennung = BEZUGSWEG_QUELLE

    def __init__(
        self,
        sonde: Sonde | None = None,
        zeitgrenze_s: float = ZEITGRENZE_S_VORGABE,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._sonde: Sonde = sonde or ffprobe_eigenschaften
        self._zeitgrenze_s = zeitgrenze_s
        self._transport = transport

    async def beschaffe(
        self,
        basis_url: str,
        extern_id: str,
        ziel: Path,
        fortschritt: Fortschrittsmelder,
        abbruch: asyncio.Event,
        erwartete_dauer_s: float | None = None,
    ) -> AudioErgebnis:
        teil = teil_pfad(ziel)
        try:
            async with _client(self._zeitgrenze_s, self._transport) as client:
                await fortschritt(0.05, "Quelle extrahiert das Audio")
                await self._extraktion_anstossen(client, basis_url, extern_id)
                if abbruch.is_set():
                    raise asyncio.CancelledError()
                await stream_zu_datei(
                    client,
                    audio_url(basis_url, extern_id),
                    teil,
                    fortschritt,
                    abbruch,
                    von=0.3,
                    bis=0.95,
                    meldung="Hole Audio",
                )
            os.replace(teil, ziel)
        except BaseException:
            loesche_leise(teil)
            raise
        return AudioErgebnis(pfad=ziel, bezugsweg=self.kennung, eigenschaften=await self._sonde(ziel))

    async def _extraktion_anstossen(self, client: httpx.AsyncClient, basis_url: str, extern_id: str) -> None:
        url = extraktions_url(basis_url, extern_id)
        try:
            antwort = await client.post(url, params={"format": AUDIO_FORMAT})
        except httpx.HTTPError as e:
            raise AudioBezugFehler(f"Extraktion in der Quelle fehlgeschlagen ({e.__class__.__name__}: {e})") from e
        if antwort.status_code != 200:
            raise AudioBezugFehler(f"Quelle antwortet mit HTTP {antwort.status_code} auf die Extraktion ({url})")


Dateifinder = Callable[[str, str], Path]


class LokaleDatei:
    """Eine Datei vom eigenen Rechner mit ffmpeg zu Mono-AAC wandeln (Quellentyp lokal).

    `basis_url` ist hier das Verzeichnis der Quelle, `extern_id` die Kennung der Datei;
    der übergebene Finder löst beides zur Datei auf (er gehört zur Quelle, nicht hierher).
    """

    kennung = BEZUGSWEG_DATEI

    def __init__(self, wandlung: Wandlung, finder: Dateifinder, ffmpeg: str | None = None, sonde: Sonde | None = None) -> None:
        self._wandlung = wandlung
        self._finder = finder
        self._ffmpeg = ffmpeg or ffmpeg_pfad()
        self._sonde: Sonde = sonde or ffprobe_eigenschaften

    async def beschaffe(
        self,
        basis_url: str,
        extern_id: str,
        ziel: Path,
        fortschritt: Fortschrittsmelder,
        abbruch: asyncio.Event,
        erwartete_dauer_s: float | None = None,
    ) -> AudioErgebnis:
        try:
            quelle = self._finder(basis_url, extern_id)
        except Exception as e:  # der Finder meldet mit eigenem Fehlertyp; hier zählt nur der Text
            raise AudioBezugFehler(str(e)) from e
        await fortschritt(0.02, f"Wandle '{quelle.name}' in Audio")
        teil = teil_pfad(ziel)
        ziel.parent.mkdir(parents=True, exist_ok=True)
        try:
            await ffmpeg_ausfuehren(
                ffmpeg_kommandozeile(self._ffmpeg, quelle, teil, self._wandlung),
                abbruch,
                fortschritt,
                erwartete_dauer_s,
                von=0.02,
                bis=0.95,
            )
            os.replace(teil, ziel)
        except BaseException:
            loesche_leise(teil)
            raise
        return AudioErgebnis(pfad=ziel, bezugsweg=self.kennung, eigenschaften=await self._sonde(ziel))


def waehle_bezug(
    bezugsweg: str,
    wandlung: Wandlung,
    zeitgrenze_s: float = ZEITGRENZE_S_VORGABE,
    ffmpeg: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AudioBezug:
    """Baut die Umsetzung zur Einstellung `audio.bezugsweg`."""
    if bezugsweg == BEZUGSWEG_VIDEOSTROM:
        return VideostromFfmpeg(wandlung, ffmpeg=ffmpeg, zeitgrenze_s=zeitgrenze_s, transport=transport)
    if bezugsweg == BEZUGSWEG_QUELLE:
        return QuellExtraktion(zeitgrenze_s=zeitgrenze_s, transport=transport)
    raise AudioBezugFehler(f"Unbekannter Bezugsweg '{bezugsweg}' (bekannt: {', '.join(BEZUGSWEGE)})")


# ------------------------------------------------------------------ Kleinkram


def _als_int(wert: Any) -> int | None:
    try:
        return int(wert)
    except (TypeError, ValueError):
        return None


def _als_float(wert: Any) -> float | None:
    try:
        return float(wert)
    except (TypeError, ValueError):
        return None


def _letzte_zeilen(ausgabe: bytes, anzahl: int = 3) -> str:
    zeilen = [z.strip() for z in ausgabe.decode("utf-8", errors="replace").splitlines() if z.strip()]
    return " | ".join(zeilen[-anzahl:]) if zeilen else "keine Fehlerausgabe"
