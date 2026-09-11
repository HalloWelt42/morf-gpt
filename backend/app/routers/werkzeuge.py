"""Werkzeuge verwalten: anlegen, ändern, prüfen (MCP-Werkzeuge entdecken), Probelauf, Liste
der im Chat einsetzbaren Werkzeuge."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ..db.engine import sitzung_abhaengigkeit
from ..db.modelle import Werkzeug
from ..dienste.anbieter import dienst as anbieter_dienst
from ..dienste.anbieter.basis import AnbieterFehler
from ..dienste.einstellungen import dienst as einstellungen_dienst
from ..dienste.ereignisse import bus
from ..dienste.werkzeuge import argumente as argumente_modul
from ..dienste.werkzeuge import mcp_server, register
from ..dienste.werkzeuge.basis import WerkzeugFehler

router = APIRouter(prefix="/werkzeuge", tags=["werkzeuge"])


class WerkzeugEingabe(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    typ: str
    beschreibung: str = ""
    konfiguration: dict[str, Any] = Field(default_factory=dict)
    aktiv: bool = True
    vorausgewaehlt: bool = False


class EntdecktSchalter(BaseModel):
    name: str
    aktiv: bool


class Pruefung(BaseModel):
    ok: bool
    hinweis: str
    entdeckt: list[dict[str, Any]]


class ProbeEingabe(BaseModel):
    kennung: str | None = None  # bei MCP: "<id>:<name>", sonst die Werkzeug-Kennung
    frage: str = "Was ist morf-gpt?"
    argumente: dict[str, Any] | None = None


class ProbeAusgabe(BaseModel):
    argumente: dict[str, Any]
    herkunft: str
    dauer_ms: int
    stellen: int
    text: str
    fehler: str


class Einsetzbar(BaseModel):
    kennung: str
    titel: str
    name: str
    beschreibung: str
    typ: str
    werkzeug_id: str
    parameter: list[str]
    pflicht: list[str]
    vorausgewaehlt: bool


def _validiere(e: WerkzeugEingabe) -> None:
    if e.typ not in register.TYPEN:
        raise HTTPException(422, f"Unbekannter Typ '{e.typ}'")
    if e.typ == "http_json" and not str(e.konfiguration.get("url") or "").strip():
        raise HTTPException(422, "HTTP-Dienst: die Adresse fehlt")
    if e.typ == "mcp" and not str(e.konfiguration.get("url") or "").strip():
        raise HTTPException(422, "MCP-Server: die Adresse fehlt")


async def _laden(session: AsyncSession, werkzeug_id: str) -> Werkzeug:
    z = await session.get(Werkzeug, werkzeug_id)
    if z is None:
        raise HTTPException(404, "Werkzeug nicht gefunden")
    return z


def _kopfzeilen_uebernehmen(alt: dict[str, Any], neu: dict[str, Any]) -> dict[str, Any]:
    """Verdeckte Werte (nur Sternchen) aus der Oberfläche behalten den alten Klartext."""
    alte = {k.get("name"): k.get("wert") for k in alt.get("kopfzeilen") or []}
    kopf = []
    for k in neu.get("kopfzeilen") or []:
        wert = str(k.get("wert") or "")
        if wert.startswith("********") and k.get("name") in alte:
            wert = str(alte[k.get("name")] or "")
        kopf.append({"name": k.get("name", ""), "wert": wert, "geheim": bool(k.get("geheim", False))})
    ergebnis = dict(neu)
    ergebnis["kopfzeilen"] = kopf
    return ergebnis


@router.get("", response_model=dict[str, Any])
async def alle(session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> dict[str, Any]:
    rows = (await session.execute(select(Werkzeug).order_by(Werkzeug.erstellt))).scalars().all()
    return {
        "werkzeuge": [register.oeffentlich(z, schluessel_zeigen=True) for z in rows],
        "typen": register.TYPEN,
        "transporte": mcp_server.TRANSPORTE,
    }


@router.get("/einsetzbar", response_model=list[Einsetzbar])
async def einsetzbar(session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> list[Einsetzbar]:
    """Was der Chat als zusätzliche Quelle anbieten kann."""
    aus: list[Einsetzbar] = []
    for z, b in await register.einsetzbare(session):
        aus.append(
            Einsetzbar(
                kennung=b.kennung,
                titel=b.titel,
                name=b.name,
                beschreibung=b.beschreibung,
                typ=z.typ,
                werkzeug_id=z.id,
                parameter=list(b.parameter.keys()),
                pflicht=b.pflichtparameter,
                vorausgewaehlt=z.vorausgewaehlt,
            )
        )
    return aus


@router.post("", response_model=dict[str, Any], status_code=201)
async def anlegen(e: WerkzeugEingabe, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> dict[str, Any]:
    _validiere(e)
    z = Werkzeug(
        name=e.name.strip(),
        typ=e.typ,
        beschreibung=e.beschreibung.strip(),
        konfiguration=e.konfiguration,
        aktiv=e.aktiv,
        vorausgewaehlt=e.vorausgewaehlt,
    )
    session.add(z)
    await session.commit()
    bus.veroeffentliche("werkzeug", aktion="angelegt", werkzeug_id=z.id)
    return register.oeffentlich(z, schluessel_zeigen=True)


@router.put("/{werkzeug_id}", response_model=dict[str, Any])
async def aendern(werkzeug_id: str, e: WerkzeugEingabe, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> dict[str, Any]:
    _validiere(e)
    z = await _laden(session, werkzeug_id)
    z.name, z.typ, z.beschreibung, z.aktiv, z.vorausgewaehlt = e.name.strip(), e.typ, e.beschreibung.strip(), e.aktiv, e.vorausgewaehlt
    z.konfiguration = _kopfzeilen_uebernehmen(z.konfiguration or {}, e.konfiguration)
    flag_modified(z, "konfiguration")
    await session.commit()
    bus.veroeffentliche("werkzeug", aktion="geaendert", werkzeug_id=z.id)
    return register.oeffentlich(z, schluessel_zeigen=True)


@router.delete("/{werkzeug_id}", status_code=204)
async def loeschen(werkzeug_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> None:
    z = await _laden(session, werkzeug_id)
    await session.delete(z)
    await session.commit()
    bus.veroeffentliche("werkzeug", aktion="geloescht", werkzeug_id=werkzeug_id)


@router.post("/{werkzeug_id}/pruefen", response_model=Pruefung)
async def pruefen(werkzeug_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> Pruefung:
    """Erreichbarkeit prüfen; bei MCP-Servern die Werkzeuge entdecken (Freischaltungen bleiben erhalten)."""
    z = await _laden(session, werkzeug_id)
    zeitgrenze = float(await einstellungen_dienst.wert(session, "werkzeuge.zeitgrenze_s"))
    ok, hinweis = True, "erreichbar"
    if z.typ == "mcp":
        try:
            server, gefunden = await mcp_server.entdecke(z.konfiguration or {}, min(zeitgrenze, 60.0))
        except WerkzeugFehler as e:
            ok, hinweis = False, str(e)
        else:
            alt = {str(x.get("name")): x for x in (z.entdeckt or [])}
            neu: list[dict[str, Any]] = []
            for g in gefunden:
                vorher = alt.get(g["name"])
                neu.append({**g, "aktiv": bool(vorher.get("aktiv", True)) if vorher else True})
            z.entdeckt = neu
            flag_modified(z, "entdeckt")
            hinweis = f"{server.get('name') or 'Server'} {server.get('version') or ''}: {len(neu)} Werkzeuge".strip()
    else:
        beschreibungen = register.beschreibungen_fuer_zeile(z)
        try:
            werkzeug = register.baue(z, beschreibungen[0])
            argumente = argumente_modul.notloesung(beschreibungen[0], "Probe")
            ergebnis = await werkzeug.ausfuehren(argumente, min(zeitgrenze, 60.0))
            hinweis = f"erreichbar, {len(ergebnis.als_stellen())} Fundstücke bei der Probe" if not ergebnis.fehler else ergebnis.fehler
            ok = not ergebnis.fehler
        except WerkzeugFehler as e:
            ok, hinweis = False, str(e)
    z.zuletzt_geprueft = datetime.now(UTC)
    z.pruefung = {"ok": ok, "hinweis": hinweis}
    flag_modified(z, "pruefung")
    await session.commit()
    bus.veroeffentliche("werkzeug", aktion="geprueft", werkzeug_id=z.id, ok=ok)
    return Pruefung(ok=ok, hinweis=hinweis, entdeckt=z.entdeckt or [])


@router.put("/{werkzeug_id}/entdeckt", response_model=dict[str, Any])
async def entdeckt_schalten(
    werkzeug_id: str, e: EntdecktSchalter, session: AsyncSession = Depends(sitzung_abhaengigkeit)
) -> dict[str, Any]:
    """Ein entdecktes Werkzeug eines MCP-Servers frei- oder abschalten."""
    z = await _laden(session, werkzeug_id)
    getroffen = False
    for x in z.entdeckt or []:
        if x.get("name") == e.name:
            x["aktiv"] = e.aktiv
            getroffen = True
    if not getroffen:
        raise HTTPException(404, "Entdecktes Werkzeug nicht gefunden - erst prüfen")
    flag_modified(z, "entdeckt")
    await session.commit()
    bus.veroeffentliche("werkzeug", aktion="geaendert", werkzeug_id=z.id)
    return register.oeffentlich(z, schluessel_zeigen=True)


@router.post("/{werkzeug_id}/probe", response_model=ProbeAusgabe)
async def probe(werkzeug_id: str, e: ProbeEingabe, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> ProbeAusgabe:
    """Echter Aufruf mit einer Frage: Argumente ableiten (oder übergeben), ausführen, Ergebnis zeigen."""
    z = await _laden(session, werkzeug_id)
    beschreibungen = register.beschreibungen_fuer_zeile(z)
    if not beschreibungen:
        raise HTTPException(409, "Keine einsetzbaren Werkzeuge - bei MCP-Servern erst prüfen und freischalten")
    b = next((x for x in beschreibungen if x.kennung == e.kennung), beschreibungen[0])
    werte = await einstellungen_dienst.werte(session, "werkzeuge.zeitgrenze_s", "werkzeuge.argumente_per_modell", "chat.zeitgrenze_s")
    if e.argumente is not None:
        argumente, herkunft = e.argumente, "vorgegeben"
    else:
        anbieter = None
        if werte["werkzeuge.argumente_per_modell"]:
            try:
                anbieter = await anbieter_dienst.sprachmodell_fuer(session, "chat")
            except AnbieterFehler:
                anbieter = None
        argumente, herkunft = await argumente_modul.ableiten(
            b, e.frage, anbieter, per_modell=bool(werte["werkzeuge.argumente_per_modell"]), zeitgrenze_s=float(werte["chat.zeitgrenze_s"])
        )
    werkzeug = register.baue(z, b)
    try:
        ergebnis = await werkzeug.ausfuehren(argumente, float(werte["werkzeuge.zeitgrenze_s"]))
    except WerkzeugFehler as err:
        return ProbeAusgabe(argumente=argumente, herkunft=herkunft, dauer_ms=0, stellen=0, text="", fehler=str(err))
    return ProbeAusgabe(
        argumente=argumente,
        herkunft=herkunft,
        dauer_ms=ergebnis.dauer_ms,
        stellen=len(ergebnis.als_stellen()),
        text=ergebnis.text[:4000],
        fehler=ergebnis.fehler,
    )
