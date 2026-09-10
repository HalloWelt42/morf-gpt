"""Ereignisstrom (SSE) für die Oberfläche: Aufträge, Fortschritt, Protokoll, Einstellungen."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from ..dienste.ereignisse import bus

router = APIRouter(prefix="/ereignisse", tags=["ereignisse"])


@router.get("/stream")
async def stream(request: Request, verlauf: int = 30) -> EventSourceResponse:
    async def _gen() -> AsyncIterator[dict[str, str]]:
        for e in bus.letzte(verlauf):
            yield e.als_sse()
        async for e in bus.abonniere():
            if await request.is_disconnected():
                break
            yield e.als_sse()

    return EventSourceResponse(_gen(), ping=20)
