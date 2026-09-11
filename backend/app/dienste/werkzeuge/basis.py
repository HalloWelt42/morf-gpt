"""Schnittstelle der Werkzeuge: fremde Dienste, die der Chat neben der Bibliothek befragt.

Ein Werkzeug beschreibt sich (Name, Zweck, Parameterschema) und führt einen Aufruf mit
Argumenten aus. Was dahinter steht (HTTP-Dienst, MCP-Server ...), entscheidet das Register.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class WerkzeugFehler(RuntimeError):
    """Ein Werkzeug konnte nicht ausgeführt werden (Netz, Fehlerantwort, Konfiguration)."""


@dataclass(slots=True)
class Werkzeugbeschreibung:
    """Was das Sprachmodell (und die Oberfläche) über ein Werkzeug wissen."""

    kennung: str  # eindeutig im Chat: "<werkzeug_id>" oder "<werkzeug_id>:<name>"
    name: str  # Funktionsname für das Modell (ASCII, ohne Leerzeichen)
    titel: str  # Anzeige in der Oberfläche
    beschreibung: str
    parameter_schema: dict[str, Any] = field(default_factory=dict)  # JSON-Schema (type object)
    werkzeug_id: str = ""
    typ: str = ""

    @property
    def pflichtparameter(self) -> list[str]:
        return [str(p) for p in (self.parameter_schema.get("required") or [])]

    @property
    def parameter(self) -> dict[str, Any]:
        props = self.parameter_schema.get("properties")
        return props if isinstance(props, dict) else {}

    def als_openai(self) -> dict[str, Any]:
        schema = self.parameter_schema or {"type": "object", "properties": {}}
        if "type" not in schema:
            schema = {"type": "object", **schema}
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.beschreibung[:1000], "parameters": schema},
        }


@dataclass(slots=True)
class Quellenangabe:
    titel: str = ""
    url: str = ""


@dataclass(slots=True)
class Werkzeugergebnis:
    """Ergebnis eines Aufrufs. `stellen` sind die einzelnen Fundstücke (mindestens eines)."""

    text: str
    stellen: list[tuple[str, Quellenangabe]] = field(default_factory=list)  # (Text, Quelle)
    dauer_ms: int = 0
    roh: Any = None
    fehler: str = ""

    def als_stellen(self) -> list[tuple[str, Quellenangabe]]:
        if self.stellen:
            return self.stellen
        return [(self.text, Quellenangabe())] if self.text else []


class Werkzeug(Protocol):
    beschreibung: Werkzeugbeschreibung

    async def ausfuehren(self, argumente: dict[str, Any], zeitgrenze_s: float) -> Werkzeugergebnis: ...


def funktionsname(text: str) -> str:
    """Macht aus einem Titel einen Funktionsnamen für das Modell (a-z, 0-9, Unterstrich)."""
    ersatz = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"}
    aus: list[str] = []
    for zeichen in text:
        zeichen = ersatz.get(zeichen, zeichen)
        if zeichen.isalnum() and zeichen.isascii():
            aus.append(zeichen.lower())
        elif aus and aus[-1] != "_":
            aus.append("_")
    name = "".join(aus).strip("_")
    return name[:60] or "werkzeug"
