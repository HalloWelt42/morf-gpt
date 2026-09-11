"""Werkzeugtyp mcp: ein MCP-Server (Streamable HTTP oder SSE), dessen Werkzeuge entdeckt
und einzeln freigeschaltet werden.

Konfiguration: url, transport ("streamable_http" | "sse"), kopfzeilen [{"name","wert","geheim"}].
Jeder Aufruf öffnet eine eigene Sitzung (zustandslos, robust gegen Neustarts des Servers).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from .basis import Quellenangabe, Werkzeugbeschreibung, Werkzeugergebnis, WerkzeugFehler, funktionsname

TRANSPORTE: dict[str, str] = {"streamable_http": "Streamable HTTP", "sse": "SSE (älter)"}


def _kopfzeilen(konfiguration: dict[str, Any]) -> dict[str, str]:
    aus: dict[str, str] = {}
    for k in konfiguration.get("kopfzeilen") or []:
        name = str(k.get("name") or "").strip()
        if name:
            aus[name] = str(k.get("wert") or "")
    return aus


@asynccontextmanager
async def _sitzung(konfiguration: dict[str, Any], zeitgrenze_s: float) -> AsyncIterator[Any]:
    """Öffnet eine MCP-Sitzung zum konfigurierten Server."""
    from mcp import ClientSession

    url = str(konfiguration.get("url") or "").strip()
    if not url:
        raise WerkzeugFehler("MCP-Server: keine Adresse konfiguriert")
    transport = str(konfiguration.get("transport") or "streamable_http")
    kopf = _kopfzeilen(konfiguration)
    if transport == "sse":
        from mcp.client.sse import sse_client

        async with sse_client(url, headers=kopf or None, timeout=min(30.0, zeitgrenze_s), sse_read_timeout=zeitgrenze_s) as (
            lese,
            schreibe,
        ):
            async with ClientSession(lese, schreibe, read_timeout_seconds=zeitgrenze_s) as s:
                await s.initialize()
                yield s
        return
    import httpx2
    from mcp.client.streamable_http import streamable_http_client

    client = httpx2.AsyncClient(headers=kopf, timeout=httpx2.Timeout(zeitgrenze_s, connect=15))
    try:
        async with streamable_http_client(url, http_client=client) as stroeme:
            async with ClientSession(stroeme[0], stroeme[1], read_timeout_seconds=zeitgrenze_s) as s:
                await s.initialize()
                yield s
    finally:
        await client.aclose()


def _fehlertext(e: BaseException) -> str:
    """Ausnahmegruppen (anyio) auf die innerste Meldung reduzieren."""
    if isinstance(e, BaseExceptionGroup):
        teile = [_fehlertext(x) for x in e.exceptions]
        return "; ".join(t for t in teile if t)
    text = str(e).strip()
    return f"{e.__class__.__name__}: {text}" if text else e.__class__.__name__


async def entdecke(konfiguration: dict[str, Any], zeitgrenze_s: float = 60.0) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fragt den Server nach Name, Version und seinen Werkzeugen."""
    try:
        async with asyncio.timeout(zeitgrenze_s):
            async with _sitzung(konfiguration, zeitgrenze_s) as s:
                init = await s.initialize()
                info = getattr(init, "server_info", None)
                antwort = await s.list_tools()
                werkzeuge: list[dict[str, Any]] = []
                for t in antwort.tools:
                    schema = getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {}
                    werkzeuge.append(
                        {
                            "name": t.name,
                            "titel": getattr(t, "title", None) or t.name,
                            "beschreibung": (t.description or "").strip(),
                            "parameter_schema": schema,
                        }
                    )
                server = {
                    "name": getattr(info, "name", "") if info else "",
                    "version": getattr(info, "version", "") if info else "",
                    "protokoll": str(getattr(init, "protocol_version", "") or ""),
                }
                return server, werkzeuge
    except TimeoutError as e:
        raise WerkzeugFehler(f"MCP-Server antwortet nicht innerhalb von {int(zeitgrenze_s)} Sekunden") from e
    except WerkzeugFehler:
        raise
    except BaseException as e:  # anyio liefert Ausnahmegruppen
        if isinstance(e, asyncio.CancelledError | KeyboardInterrupt):
            raise
        raise WerkzeugFehler(f"MCP-Server nicht erreichbar: {_fehlertext(e)}") from e


def _inhalt_als_text(inhalt: Any) -> list[str]:
    aus: list[str] = []
    for c in inhalt or []:
        text = getattr(c, "text", None)
        if isinstance(text, str) and text.strip():
            aus.append(text.strip())
            continue
        typ = getattr(c, "type", "")
        if typ and typ != "text":
            aus.append(f"[{typ}-Inhalt, nicht als Text darstellbar]")
    return aus


class McpWerkzeug:
    """Ein einzelnes Werkzeug eines MCP-Servers."""

    def __init__(self, beschreibung: Werkzeugbeschreibung, konfiguration: dict[str, Any], mcp_name: str) -> None:
        self.beschreibung = beschreibung
        self._k = konfiguration
        self._mcp_name = mcp_name

    async def ausfuehren(self, argumente: dict[str, Any], zeitgrenze_s: float) -> Werkzeugergebnis:
        start = time.monotonic()
        try:
            async with asyncio.timeout(zeitgrenze_s):
                async with _sitzung(self._k, zeitgrenze_s) as s:
                    r = await s.call_tool(self._mcp_name, argumente)
        except TimeoutError as e:
            raise WerkzeugFehler(f"{self.beschreibung.titel}: keine Antwort innerhalb von {int(zeitgrenze_s)} Sekunden") from e
        except WerkzeugFehler:
            raise
        except BaseException as e:
            if isinstance(e, asyncio.CancelledError | KeyboardInterrupt):
                raise
            raise WerkzeugFehler(f"{self.beschreibung.titel}: {_fehlertext(e)}") from e
        dauer = int((time.monotonic() - start) * 1000)
        texte = _inhalt_als_text(getattr(r, "content", None))
        strukturiert = getattr(r, "structured_content", None) or getattr(r, "structuredContent", None)
        if not texte and strukturiert is not None:
            import json

            texte = [json.dumps(strukturiert, ensure_ascii=False, indent=1)]
        text = "\n\n".join(texte)
        if getattr(r, "is_error", False) or getattr(r, "isError", False):
            raise WerkzeugFehler(f"{self.beschreibung.titel}: {text[:300] or 'Fehler ohne Text'}")
        return Werkzeugergebnis(text=text, stellen=[(text, Quellenangabe())] if text else [], dauer_ms=dauer, roh=strukturiert)


def beschreibungen_aus_entdeckt(werkzeug_id: str, titel: str, entdeckt: list[dict[str, Any]]) -> list[Werkzeugbeschreibung]:
    """Die freigeschalteten Werkzeuge eines Servers als Beschreibungen (Kennung server:werkzeug)."""
    aus: list[Werkzeugbeschreibung] = []
    for e in entdeckt:
        if not e.get("aktiv", True):
            continue
        name = str(e.get("name") or "")
        if not name:
            continue
        aus.append(
            Werkzeugbeschreibung(
                kennung=f"{werkzeug_id}:{name}",
                name=funktionsname(f"{titel}_{name}"),
                titel=f"{titel}: {e.get('titel') or name}",
                beschreibung=str(e.get("beschreibung") or ""),
                parameter_schema=dict(e.get("parameter_schema") or {}),
                werkzeug_id=werkzeug_id,
                typ="mcp",
            )
        )
    return aus
