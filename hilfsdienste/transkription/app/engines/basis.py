"""Schnittstelle der Engines: Datenformen, Protokoll und die Beschreibung, aus der ein
Arbeiterprozess seine Engine baut.

Die Segmentform folgt der Speicherform der Bibliothek: start, end, text, words[{word, start, end}].
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(slots=True)
class Wort:
    wort: str
    start: float
    end: float

    def als_speicherform(self) -> dict[str, Any]:
        return {"word": self.wort, "start": round(self.start, 3), "end": round(self.end, 3)}


@dataclass(slots=True)
class Segment:
    start: float
    end: float
    text: str
    woerter: list[Wort] = field(default_factory=list)

    def als_speicherform(self) -> dict[str, Any]:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "text": self.text,
            "words": [w.als_speicherform() for w in self.woerter],
        }


@dataclass(slots=True)
class Rohtranskript:
    """Was eine Engine liefert, vor der Nachbearbeitung."""

    text: str
    segmente: list[Segment]
    sprache: str
    modell: str


@dataclass(slots=True, frozen=True)
class EngineBeschreibung:
    """Wie ein Arbeiterprozess seine Engine baut: Modul, Klasse, Argumente (alles serialisierbar)."""

    kennung: str
    modul: str
    klasse: str
    argumente: dict[str, Any]


class Engine(Protocol):
    kennung: str
    modell: str

    def laden(self) -> None:
        """Lädt das Modell in den Speicher (einmal je Prozess)."""
        ...

    def groesse_gb(self) -> float:
        """Speicherbedarf des geladenen Modells in Gigabyte, gemessen oder aus den Gewichten."""
        ...

    def speicher_gb(self) -> float:
        """Aktuell belegter Speicher des Prozesses für Modell und Zwischenergebnisse (nach einem Auftrag gemessen)."""
        ...

    def transkribiere(self, pfad: Path, sprache_code: str | None, wortzeiten: bool) -> Rohtranskript:
        """Blockiert bis zum Ende; sprache_code None heißt Spracherkennung durch das Modell."""
        ...


def woerter_aus(roh: Any) -> list[Wort]:
    """Wortliste einer Engine-Antwort; Einträge ohne Text oder Start fallen weg."""
    aus: list[Wort] = []
    for w in roh or []:
        if not isinstance(w, dict):
            continue
        text = str(w.get("word") or w.get("text") or "")
        if not text.strip() or w.get("start") is None:
            continue
        start = float(w["start"])
        aus.append(Wort(text, start, float(w["end"]) if w.get("end") is not None else start))
    return aus
