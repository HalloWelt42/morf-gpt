"""LM Studio: OpenAI-kompatibel plus Modellzustand über die native REST-API.

`/v1/models` listet bei aktivem JIT alle heruntergeladenen Modelle - als Signal für
"geladen" ungeeignet. Verlässlich ist `/api/v0/models` mit `state` je Modell.
"""

from __future__ import annotations

from typing import Any

import httpx

from .basis import AnbieterInfo
from .openai_kompatibel import OpenAiKompatibel, OpenAiKompatibelEinbettung


def _wurzel(basis_url: str) -> str:
    """Von .../v1 auf die Serverwurzel."""
    b = basis_url.rstrip("/")
    return b[:-3] if b.endswith("/v1") else b


async def modelle_mit_zustand(basis_url: str) -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5)) as client:
            resp = await client.get(f"{_wurzel(basis_url)}/api/v0/models")
    except httpx.HTTPError:
        return []
    if resp.status_code != 200:
        return []
    aus: list[dict[str, Any]] = []
    for m in resp.json().get("data", []):
        if not isinstance(m, dict):
            continue
        aus.append(
            {
                "id": m.get("id", ""),
                "typ": m.get("type", ""),
                "geladen": m.get("state") == "loaded",
                "kontext": m.get("max_context_length"),
                "quantisierung": m.get("quantization"),
            }
        )
    return aus


class LmStudio(OpenAiKompatibel):
    def __init__(self, info: AnbieterInfo, api_schluessel: str = "", zusatz: dict[str, Any] | None = None) -> None:
        super().__init__(info, api_schluessel, zusatz)

    async def modelle(self) -> list[dict[str, Any]]:
        alle = await modelle_mit_zustand(self.info.basis_url)
        if alle:
            return [m for m in alle if m["typ"] in ("llm", "vlm")]
        return await super().modelle()

    async def erreichbar(self) -> tuple[bool, str]:
        ok, hinweis = await super().erreichbar()
        if not ok:
            return ok, hinweis
        alle = await modelle_mit_zustand(self.info.basis_url)
        geladen = [m["id"] for m in alle if m["geladen"] and m["typ"] in ("llm", "vlm")]
        if self.info.modell in geladen:
            return True, "Modell geladen"
        if geladen:
            return True, f"erreichbar, geladen ist: {', '.join(geladen)}"
        return True, "erreichbar, kein Chat-Modell geladen (wird beim ersten Aufruf geladen)"


class LmStudioEinbettung(OpenAiKompatibelEinbettung):
    async def modelle(self) -> list[dict[str, Any]]:
        alle = await modelle_mit_zustand(self.info.basis_url)
        if alle:
            return [m for m in alle if m["typ"] == "embeddings"]
        return await super().modelle()

    async def erreichbar(self) -> tuple[bool, str]:
        ok, hinweis = await super().erreichbar()
        if not ok:
            return ok, hinweis
        alle = await modelle_mit_zustand(self.info.basis_url)
        for m in alle:
            if m["id"] == self.info.modell:
                return True, "Modell geladen" if m["geladen"] else "erreichbar, Modell wird beim ersten Aufruf geladen"
        return True, "erreichbar"
