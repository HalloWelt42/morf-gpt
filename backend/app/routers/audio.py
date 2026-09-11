"""Audio ausliefern: Datei mit HTTP-Range (Sprünge im Spieler), Auskunft, Löschen.

Der Spieler in der Oberfläche springt per Range-Anfrage an eine Stelle; das Backend
antwortet mit 206 und Content-Range. Ungültige Bereiche ergeben 416, eine fehlende
oder unverständliche Range-Angabe die ganze Datei (200). Nur der erste Bereich einer
Mehrfachangabe wird bedient (Spieler fragen immer einen Bereich).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.engine import sitzung_abhaengigkeit
from ..db.modelle import Audio
from ..dienste.audio import bezug
from ..dienste.ereignisse import bus

router = APIRouter(prefix="/audio", tags=["audio"])

# Technische Konstanten der Auslieferung
LESEBLOCK = 64 * 1024
MIME_JE_FORMAT: dict[str, str] = {
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "opus": "audio/ogg",
    "flac": "audio/flac",
}
MIME_VORGABE = "application/octet-stream"


class AudioInfo(BaseModel):
    audio_id: str
    video_id: str
    pfad: str
    format: str
    mime: str
    dauer_s: float | None
    groesse_bytes: int | None
    abtastrate: int | None
    kanaele: int | None
    bezugsweg: str
    vorhanden: bool
    erstellt: datetime | None


class LoeschErgebnis(BaseModel):
    video_id: str
    datei_geloescht: bool
    meldung: str


# ------------------------------------------------------------------ Bytebereiche


class BereichNichtErfuellbar(ValueError):
    """Der angefragte Bereich liegt außerhalb der Datei (HTTP 416)."""


@dataclass(frozen=True, slots=True)
class Bytebereich:
    start: int
    ende: int  # einschließlich
    gesamt: int

    @property
    def laenge(self) -> int:
        return self.ende - self.start + 1

    def content_range(self) -> str:
        return f"bytes {self.start}-{self.ende}/{self.gesamt}"


def bereich_parsen(kopf: str | None, gesamt: int) -> Bytebereich | None:
    """Liest den Range-Kopf. None: kein oder unverständlicher Bereich (ganze Datei liefern).

    Wirft BereichNichtErfuellbar, wenn der Bereich syntaktisch gültig ist, aber außerhalb
    der Datei liegt.
    """
    if not kopf:
        return None
    einheit, _, angaben = kopf.strip().partition("=")
    if einheit.strip().lower() != "bytes" or not angaben.strip():
        return None
    erste = angaben.split(",", 1)[0].strip()
    start_text, trenner, ende_text = erste.partition("-")
    start_text, ende_text = start_text.strip(), ende_text.strip()
    if not trenner or (not start_text and not ende_text):
        return None
    if not start_text.isdigit() and start_text != "":
        return None
    if not ende_text.isdigit() and ende_text != "":
        return None
    if start_text == "":
        return _suffix_bereich(int(ende_text), gesamt)
    return _bereich_ab(int(start_text), int(ende_text) if ende_text else None, gesamt)


def _suffix_bereich(anzahl: int, gesamt: int) -> Bytebereich:
    """`bytes=-500`: die letzten 500 Bytes."""
    if anzahl <= 0 or gesamt <= 0:
        raise BereichNichtErfuellbar(f"Bereich der letzten {anzahl} Bytes ist nicht erfüllbar")
    return Bytebereich(start=max(0, gesamt - anzahl), ende=gesamt - 1, gesamt=gesamt)


def _bereich_ab(start: int, ende: int | None, gesamt: int) -> Bytebereich:
    """`bytes=start-ende` oder `bytes=start-` (bis zum Dateiende)."""
    if start >= gesamt:
        raise BereichNichtErfuellbar(f"Bereich ab Byte {start} liegt außerhalb der Datei ({gesamt} Bytes)")
    letztes = gesamt - 1
    if ende is None or ende > letztes:
        ende = letztes
    if ende < start:
        raise BereichNichtErfuellbar(f"Bereichsende {ende} liegt vor dem Anfang {start}")
    return Bytebereich(start=start, ende=ende, gesamt=gesamt)


# ------------------------------------------------------------------ Datei streamen


async def _datei_stueckweise(pfad: Path, start: int, laenge: int) -> AsyncIterator[bytes]:
    rest = laenge
    async with await anyio.open_file(pfad, "rb") as datei:
        await datei.seek(start)
        while rest > 0:
            stueck = await datei.read(min(LESEBLOCK, rest))
            if not stueck:
                return
            rest -= len(stueck)
            yield stueck


def _etag(stat: os.stat_result) -> str:
    return f'"{stat.st_size:x}-{int(stat.st_mtime):x}"'


def _mime(audio: Audio) -> str:
    return MIME_JE_FORMAT.get((audio.format or "").lower(), MIME_VORGABE)


def _grundkoepfe(stat: os.stat_result, mime: str) -> dict[str, str]:
    return {
        "Accept-Ranges": "bytes",
        "Content-Type": mime,
        "ETag": _etag(stat),
        "Last-Modified": format_datetime(datetime.fromtimestamp(stat.st_mtime, UTC), usegmt=True),
        "Cache-Control": "private, max-age=0",
    }


def _range_anwenden(request: Request, stat: os.stat_result) -> Bytebereich | None:
    """Range gilt nur, wenn If-Range (falls gesetzt) noch zur Datei passt."""
    if_range = request.headers.get("if-range")
    if if_range and if_range.strip() != _etag(stat):
        return None
    return bereich_parsen(request.headers.get("range"), stat.st_size)


# ------------------------------------------------------------------ Routen


async def _audio_zeile(session: AsyncSession, video_id: str) -> Audio:
    zeile = (await session.execute(select(Audio).where(Audio.video_id == video_id))).scalar_one_or_none()
    if zeile is None:
        raise HTTPException(404, "Für dieses Video gibt es keine Audiodatei")
    return zeile


def _datei_pruefen(zeile: Audio) -> tuple[Path, os.stat_result]:
    pfad = bezug.pfad_aufloesen(zeile.pfad)
    try:
        stat = pfad.stat()
    except FileNotFoundError as e:
        raise HTTPException(404, "Die Audiodatei fehlt auf der Platte; bitte Audio erneut beschaffen") from e
    if not pfad.is_file():
        raise HTTPException(404, "Der Audiopfad ist keine Datei")
    return pfad, stat


@router.api_route("/{video_id}", methods=["GET", "HEAD"], response_class=StreamingResponse)
async def datei(video_id: str, request: Request, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> Response:
    """Die Audiodatei, ganz (200) oder als Bereich (206). Binärantwort, darum kein Pydantic-Modell."""
    zeile = await _audio_zeile(session, video_id)
    pfad, stat = _datei_pruefen(zeile)
    koepfe = _grundkoepfe(stat, _mime(zeile))
    try:
        bereich = _range_anwenden(request, stat)
    except BereichNichtErfuellbar as e:
        koepfe["Content-Range"] = f"bytes */{stat.st_size}"
        raise HTTPException(416, str(e), headers=koepfe) from e

    if bereich is None:
        status, start, laenge = 200, 0, stat.st_size
    else:
        status, start, laenge = 206, bereich.start, bereich.laenge
        koepfe["Content-Range"] = bereich.content_range()
    koepfe["Content-Length"] = str(laenge)

    if request.method == "HEAD":
        return Response(status_code=status, headers=koepfe)
    return StreamingResponse(_datei_stueckweise(pfad, start, laenge), status_code=status, headers=koepfe)


@router.get("/{video_id}/info", response_model=AudioInfo)
async def info(video_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> AudioInfo:
    zeile = await _audio_zeile(session, video_id)
    return AudioInfo(
        audio_id=zeile.id,
        video_id=zeile.video_id,
        pfad=zeile.pfad,
        format=zeile.format,
        mime=_mime(zeile),
        dauer_s=zeile.dauer_s,
        groesse_bytes=zeile.groesse_bytes,
        abtastrate=zeile.abtastrate,
        kanaele=zeile.kanaele,
        bezugsweg=zeile.bezugsweg,
        vorhanden=bezug.pfad_aufloesen(zeile.pfad).is_file(),
        erstellt=zeile.erstellt,
    )


@router.delete("/{video_id}", response_model=LoeschErgebnis)
async def loeschen(video_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> LoeschErgebnis:
    """Entfernt Datei und Zeile. Die Stufe des Videos bleibt unverändert (siehe Meldung)."""
    zeile = await _audio_zeile(session, video_id)
    pfad = bezug.pfad_aufloesen(zeile.pfad)
    datei_geloescht = pfad.is_file()
    bezug.loesche_leise(pfad)
    await session.delete(zeile)
    await session.commit()
    bus.veroeffentliche("audio", aktion="geloescht", video_id=video_id)
    return LoeschErgebnis(
        video_id=video_id,
        datei_geloescht=datei_geloescht,
        meldung=(
            "Audiodatei und Eintrag gelöscht. Die Stufe des Videos bleibt unverändert; ein neuer Audio-Auftrag beschafft die Datei wieder."
        ),
    )
