"""Ereignisbus für die Oberfläche (SSE).

Dienste veröffentlichen Ereignisse (Auftrag gestartet, Fortschritt, Protokollzeile,
Video-Stufe geändert). Jede offene SSE-Verbindung hat eine eigene Warteschlange;
langsame Verbindungen verlieren alte Ereignisse statt den Bus zu blockieren.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

_MAX_WARTESCHLANGE = 500


@dataclass(slots=True)
class Ereignis:
    art: str
    daten: dict[str, Any]
    zeit: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def als_sse(self) -> dict[str, str]:
        return {"event": self.art, "data": json.dumps({"zeit": self.zeit, **self.daten}, ensure_ascii=False)}


class Bus:
    def __init__(self) -> None:
        self._abonnenten: set[asyncio.Queue[Ereignis]] = set()
        self._letzte: list[Ereignis] = []

    def veroeffentliche(self, art: str, **daten: Any) -> None:
        e = Ereignis(art, daten)
        self._letzte.append(e)
        if len(self._letzte) > 200:
            del self._letzte[: len(self._letzte) - 200]
        for q in list(self._abonnenten):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(e)
            except asyncio.QueueFull:
                pass

    def letzte(self, anzahl: int = 50) -> list[Ereignis]:
        return self._letzte[-anzahl:]

    async def abonniere(self) -> AsyncIterator[Ereignis]:
        q: asyncio.Queue[Ereignis] = asyncio.Queue(maxsize=_MAX_WARTESCHLANGE)
        self._abonnenten.add(q)
        try:
            while True:
                try:
                    e = await asyncio.wait_for(q.get(), timeout=15)
                except TimeoutError:
                    yield Ereignis("herzschlag", {})
                    continue
                yield e
        finally:
            self._abonnenten.discard(q)


bus = Bus()
