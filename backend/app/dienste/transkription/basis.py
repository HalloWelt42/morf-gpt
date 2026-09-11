"""Schnittstelle der Transkription: Engine-Protokoll, Ergebnisformen, Fehler.

Aufrufer (die Stufe Transkription, der Router) programmieren nur gegen dieses Modul.
Welche Umsetzung dahintersteht (txt2voice-Worker oder txt2voice-App), entscheidet
`register.py` anhand der Einstellung `transkription.engine`.

Die Segmentform in der Datenbank (Spalte transkripte.segmente) folgt den Schlüsseln
des Whisper-Dienstes: start, end, text, words[{word, start, end}]. `Segment` ist die
typisierte Sicht darauf; `als_speicherform` und `aus_speicherform` übersetzen. Beide
Engines liefern dieselbe Rohform, darum liegen Parser und Wortzeiten-Filter hier.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx


class TranskriptionsFehler(RuntimeError):
    """Die Transkription konnte nicht durchgeführt werden (Datei, Netz, Dienst, Antwort)."""


# ---------------------------------------------------------------- Datenformen


@dataclass(slots=True)
class Wortzeit:
    """Zeitmarke eines einzelnen Wortes innerhalb eines Segments."""

    wort: str
    start: float
    end: float

    def als_speicherform(self) -> dict[str, Any]:
        return {"word": self.wort, "start": self.start, "end": self.end}

    @classmethod
    def aus_speicherform(cls, roh: dict[str, Any]) -> Wortzeit:
        return cls(wort=str(roh.get("word") or ""), start=_zahl(roh.get("start")), end=_zahl(roh.get("end")))


@dataclass(slots=True)
class Segment:
    """Ein zeitlich abgegrenztes Stück gesprochenen Textes."""

    start: float
    end: float
    text: str
    woerter: list[Wortzeit] = field(default_factory=list)

    def als_speicherform(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "words": [w.als_speicherform() for w in self.woerter],
        }

    @classmethod
    def aus_speicherform(cls, roh: dict[str, Any], wortzeiten_behalten: bool = True) -> Segment:
        woerter: list[Wortzeit] = []
        if wortzeiten_behalten:
            woerter = [Wortzeit.aus_speicherform(w) for w in roh.get("words") or [] if isinstance(w, dict)]
        return cls(
            start=_zahl(roh.get("start")),
            end=_zahl(roh.get("end")),
            text=str(roh.get("text") or "").strip(),
            woerter=woerter,
        )


@dataclass(slots=True)
class SegmentKorrektur:
    """Neuer Text für das Segment an einer Stelle der Segmentliste."""

    index: int
    text: str


@dataclass(slots=True)
class TranskriptErgebnis:
    """Was eine Engine liefert: Volltext, Segmente und Herkunft."""

    text: str
    segmente: list[Segment]
    sprache: str
    modell: str
    engine: str

    @property
    def zeichen(self) -> int:
        return len(self.text)

    def segmente_speicherform(self) -> list[dict[str, Any]]:
        return [s.als_speicherform() for s in self.segmente]


class TranskriptionsEngine(Protocol):
    """Eine Umsetzung der Transkription. `kennung` ist der Wert der Einstellung transkription.engine."""

    kennung: str

    async def transkribiere(self, pfad: Path, sprache: str, zeitgrenze_s: float) -> TranskriptErgebnis:
        """Transkribiert die Audiodatei. Blockiert bis zum Ende; wirft TranskriptionsFehler."""
        ...

    async def erreichbar(self) -> tuple[bool, str]:
        """(erreichbar, Hinweis) - für die Anzeige in der Oberfläche."""
        ...


# ---------------------------------------------------------------- Antworten lesen


def _zahl(wert: Any) -> float:
    try:
        return float(wert)
    except (TypeError, ValueError):
        return 0.0


def segmente_aus_json(roh: Any, wortzeiten_behalten: bool) -> list[Segment]:
    """Liest die Segmentliste einer Dienstantwort. Einträge, die keine Objekte sind, werden übersprungen."""
    if not isinstance(roh, list):
        return []
    return [Segment.aus_speicherform(eintrag, wortzeiten_behalten) for eintrag in roh if isinstance(eintrag, dict)]


def volltext_aus_segmenten(segmente: list[Segment]) -> str:
    """Der Volltext als Folge der Segmenttexte, getrennt durch ein Leerzeichen."""
    return " ".join(s.text.strip() for s in segmente if s.text.strip())


def segmente_korrigieren(segmente: list[Segment], korrekturen: list[SegmentKorrektur]) -> list[Segment]:
    """Setzt neue Texte je Segmentindex und gibt eine neue Liste zurück.

    Ein tatsächlich geänderter Text verliert seine Wortzeiten, weil sie nicht mehr zum
    Text passen. Wirft ValueError bei einem Index außerhalb der Liste.
    """
    neue = [Segment(s.start, s.end, s.text, list(s.woerter)) for s in segmente]
    for k in korrekturen:
        if k.index < 0 or k.index >= len(neue):
            raise ValueError(f"Segment {k.index} gibt es nicht (das Transkript hat {len(neue)} Segmente)")
        text = k.text.strip()
        if text == neue[k.index].text:
            continue
        neue[k.index] = Segment(neue[k.index].start, neue[k.index].end, text, [])
    return neue


def fehlertext_aus_antwort(resp: httpx.Response) -> str:
    """Liest die Fehlermeldung aus dem Antwortkörper statt nur den HTTP-Code zu melden."""
    try:
        daten = resp.json()
    except ValueError:
        daten = None
    if isinstance(daten, dict):
        for schluessel in ("detail", "error", "message"):
            wert = daten.get(schluessel)
            if isinstance(wert, dict) and wert.get("message"):
                return str(wert["message"])
            if isinstance(wert, str) and wert:
                return wert
    return resp.text[:400] or f"HTTP {resp.status_code}"


# ---------------------------------------------------------------- Dateien hochladen

# Endungen, die mimetypes je nach System anders oder gar nicht kennt.
MIME_JE_ENDUNG: dict[str, str] = {
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".aac": "audio/aac",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".webm": "audio/webm",
}


def mime_typ_fuer(pfad: Path) -> str:
    """MIME-Typ nach Dateiendung; unbekannte Endungen gehen als Binärstrom."""
    endung = pfad.suffix.lower()
    if endung in MIME_JE_ENDUNG:
        return MIME_JE_ENDUNG[endung]
    geraten, _ = mimetypes.guess_type(pfad.name)
    return geraten or "application/octet-stream"


def audiodatei_pruefen(pfad: Path) -> None:
    """Wirft TranskriptionsFehler, wenn die Datei fehlt oder leer ist."""
    if not pfad.is_file():
        raise TranskriptionsFehler(f"Audiodatei nicht gefunden: {pfad}")
    if pfad.stat().st_size == 0:
        raise TranskriptionsFehler(f"Audiodatei ist leer: {pfad}")


def zeitgrenzen(zeitgrenze_s: float, verbindung_s: float) -> httpx.Timeout:
    """Zeitgrenzen für einen blockierenden Dienst: Lesen und Schreiben dürfen so lange wie die Transkription dauern."""
    return httpx.Timeout(connect=verbindung_s, read=zeitgrenze_s, write=zeitgrenze_s, pool=verbindung_s)
