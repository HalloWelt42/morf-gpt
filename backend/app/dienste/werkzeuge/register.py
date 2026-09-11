"""Register der Werkzeuge: aus den Zeilen der Tabelle werkzeuge die einsetzbaren Werkzeuge bauen.

Ein HTTP-Dienst ist genau ein Werkzeug; ein MCP-Server liefert je freigeschaltetem
entdeckten Werkzeug eines. Kennungen: "<werkzeug_id>" bzw. "<werkzeug_id>:<mcp_name>".
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.modelle import Werkzeug as WerkzeugZeile
from . import http_json, mcp_server
from .basis import Werkzeug, Werkzeugbeschreibung, WerkzeugFehler, funktionsname

TYPEN: dict[str, str] = {
    "http_json": "HTTP-Dienst (JSON)",
    "mcp": "MCP-Server",
}


def beschreibungen_fuer_zeile(z: WerkzeugZeile) -> list[Werkzeugbeschreibung]:
    if z.typ == "http_json":
        return [
            Werkzeugbeschreibung(
                kennung=z.id,
                name=funktionsname(z.name),
                titel=z.name,
                beschreibung=z.beschreibung or f"Fremder Dienst {z.name}",
                parameter_schema=http_json.parameter_schema(z.konfiguration or {}),
                werkzeug_id=z.id,
                typ=z.typ,
            )
        ]
    if z.typ == "mcp":
        return mcp_server.beschreibungen_aus_entdeckt(z.id, z.name, z.entdeckt or [])
    return []


def baue(z: WerkzeugZeile, beschreibung: Werkzeugbeschreibung) -> Werkzeug:
    if z.typ == "http_json":
        return http_json.HttpJsonWerkzeug(beschreibung, z.konfiguration or {})
    if z.typ == "mcp":
        mcp_name = beschreibung.kennung.split(":", 1)[1] if ":" in beschreibung.kennung else beschreibung.name
        return mcp_server.McpWerkzeug(beschreibung, z.konfiguration or {}, mcp_name)
    raise WerkzeugFehler(f"Unbekannter Werkzeugtyp '{z.typ}'")


async def aktive_zeilen(session: AsyncSession) -> list[WerkzeugZeile]:
    return list(
        (await session.execute(select(WerkzeugZeile).where(WerkzeugZeile.aktiv.is_(True)).order_by(WerkzeugZeile.erstellt))).scalars().all()
    )


async def einsetzbare(session: AsyncSession) -> list[tuple[WerkzeugZeile, Werkzeugbeschreibung]]:
    """Alle einsetzbaren Werkzeuge (Zeile plus Beschreibung), Funktionsnamen eindeutig gemacht."""
    aus: list[tuple[WerkzeugZeile, Werkzeugbeschreibung]] = []
    gesehen: dict[str, int] = {}
    for z in await aktive_zeilen(session):
        for b in beschreibungen_fuer_zeile(z):
            n = gesehen.get(b.name, 0)
            gesehen[b.name] = n + 1
            if n:
                b.name = f"{b.name}_{n + 1}"
            aus.append((z, b))
    return aus


async def nach_kennungen(session: AsyncSession, kennungen: list[str]) -> list[tuple[WerkzeugZeile, Werkzeugbeschreibung]]:
    """Die gewünschten Werkzeuge in der Reihenfolge der Kennungen; unbekannte werden übergangen."""
    alle = {b.kennung: (z, b) for z, b in await einsetzbare(session)}
    return [alle[k] for k in kennungen if k in alle]


def oeffentlich(z: WerkzeugZeile, schluessel_zeigen: bool = False) -> dict[str, Any]:
    """Darstellung für die API. Geheime Kopfzeilen werden nur im Verwaltungsbereich gezeigt."""
    k = dict(z.konfiguration or {})
    kopf: list[dict[str, Any]] = []
    for e in k.get("kopfzeilen") or []:
        wert = str(e.get("wert") or "")
        kopf.append(
            {
                "name": e.get("name", ""),
                "wert": wert if (schluessel_zeigen or not e.get("geheim")) else ("*" * 8 + wert[-4:] if wert else ""),
                "geheim": bool(e.get("geheim", False)),
            }
        )
    k["kopfzeilen"] = kopf
    return {
        "id": z.id,
        "name": z.name,
        "typ": z.typ,
        "typ_titel": TYPEN.get(z.typ, z.typ),
        "beschreibung": z.beschreibung,
        "konfiguration": k,
        "entdeckt": z.entdeckt or [],
        "aktiv": z.aktiv,
        "vorausgewaehlt": z.vorausgewaehlt,
        "zuletzt_geprueft": z.zuletzt_geprueft.isoformat() if z.zuletzt_geprueft else None,
        "pruefung": z.pruefung or {},
        "einsetzbar": [
            {
                "kennung": b.kennung,
                "titel": b.titel,
                "name": b.name,
                "beschreibung": b.beschreibung,
                "parameter": list(b.parameter.keys()),
                "pflicht": b.pflichtparameter,
            }
            for b in beschreibungen_fuer_zeile(z)
        ],
        "erstellt": z.erstellt.isoformat() if z.erstellt else None,
    }
