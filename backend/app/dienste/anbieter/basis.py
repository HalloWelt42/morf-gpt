"""Schnittstellen der Anbieter: Sprachmodelle und Einbettungen.

Aufrufer programmieren nur gegen diese Protokolle. Welche Umsetzung dahintersteht
(LM Studio, ein OpenAI-kompatibler Dienst wie Hetzner, lokales fastembed), entscheidet
das Register zur Laufzeit anhand der Anbieter-Einträge in der Datenbank.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Rolle = Literal["system", "user", "assistant", "tool"]


@dataclass(slots=True)
class Werkzeugaufruf:
    """Ein vom Modell gewünschter Werkzeugaufruf (OpenAI 'tool_calls')."""

    id: str
    name: str
    argumente: dict[str, Any]


@dataclass(slots=True)
class Nachricht:
    rolle: Rolle
    inhalt: str
    # Nur bei rolle="assistant": gewünschte Werkzeugaufrufe; bei rolle="tool": die Antwort auf einen Aufruf.
    werkzeugaufrufe: list[Werkzeugaufruf] = field(default_factory=list)
    werkzeugaufruf_id: str = ""

    def als_openai(self) -> dict[str, Any]:
        daten: dict[str, Any] = {"role": self.rolle, "content": self.inhalt}
        if self.rolle == "assistant" and self.werkzeugaufrufe:
            daten["tool_calls"] = [
                {
                    "id": w.id,
                    "type": "function",
                    "function": {"name": w.name, "arguments": json.dumps(w.argumente, ensure_ascii=False)},
                }
                for w in self.werkzeugaufrufe
            ]
            if not self.inhalt:
                daten["content"] = None
        if self.rolle == "tool":
            daten["tool_call_id"] = self.werkzeugaufruf_id
        return daten


@dataclass(slots=True)
class Antwortparameter:
    temperatur: float = 0.2
    max_tokens: int = 4000
    zeitgrenze_s: float = 1800.0
    json_modus: bool = False
    # Strukturierte Ausgabe nach Schema (OpenAI 'json_schema'); hat Vorrang vor json_modus.
    json_schema: dict[str, Any] | None = None
    stopp: list[str] = field(default_factory=list)
    # Werkzeuge im OpenAI-Format ({"type":"function","function":{name,description,parameters}});
    # leer = keine Werkzeugaufrufe anbieten.
    werkzeuge: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class Antwort:
    text: str
    modell: str
    tokens_ein: int | None = None
    tokens_aus: int | None = None
    roh: dict[str, Any] = field(default_factory=dict)
    werkzeugaufrufe: list[Werkzeugaufruf] = field(default_factory=list)


@dataclass(slots=True)
class Delta:
    """Ein Stück einer gestreamten Antwort. `fertig=True` trägt die Abschlussdaten."""

    text: str = ""
    fertig: bool = False
    modell: str = ""
    tokens_ein: int | None = None
    tokens_aus: int | None = None


@dataclass(slots=True)
class AnbieterInfo:
    kennung: str
    name: str
    typ: str
    modell: str
    basis_url: str = ""
    dimension: int | None = None


class AnbieterFehler(RuntimeError):
    """Ein Anbieter konnte nicht antworten (Netz, Modell nicht geladen, Fehlerkörper)."""


class SprachmodellAnbieter(Protocol):
    info: AnbieterInfo

    async def antworte(self, nachrichten: list[Nachricht], parameter: Antwortparameter) -> Antwort: ...

    def streame(self, nachrichten: list[Nachricht], parameter: Antwortparameter) -> AsyncIterator[Delta]: ...

    async def erreichbar(self) -> tuple[bool, str]:
        """(erreichbar, Hinweis) - für die Anzeige in der Oberfläche."""
        ...

    async def modelle(self) -> list[dict[str, Any]]:
        """Verfügbare Modelle beim Anbieter (Kennung, Zustand), sofern abfragbar."""
        ...


class EinbettungsAnbieter(Protocol):
    info: AnbieterInfo

    async def einbetten(self, texte: list[str], zeitgrenze_s: float = 600.0, instanz: str | None = None) -> list[list[float]]:
        """`instanz`: Kennung einer geladenen Modellinstanz beim Dienst; None heißt das eingestellte Modell."""
        ...

    async def erreichbar(self) -> tuple[bool, str]: ...

    async def modelle(self) -> list[dict[str, Any]]: ...
