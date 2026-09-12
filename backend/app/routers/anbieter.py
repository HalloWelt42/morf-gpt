"""Anbieter verwalten: anlegen, ändern, prüfen, Modelle auflisten, Rollen zuweisen."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.engine import sitzung_abhaengigkeit
from ..db.modelle import Anbieter
from ..dienste.anbieter import dienst
from ..dienste.anbieter.basis import AnbieterFehler, Antwortparameter, Nachricht
from ..dienste.einstellungen import dienst as einstellungen_dienst
from ..dienste.ereignisse import bus

router = APIRouter(prefix="/anbieter", tags=["anbieter"])


class AnbieterEingabe(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    typ: str
    art: str
    basis_url: str = ""
    api_schluessel: str | None = None  # None = unverändert lassen
    modell: str = ""
    parameter: dict[str, Any] = Field(default_factory=dict)
    aktiv: bool = True


class RollenEingabe(BaseModel):
    rolle: str
    anbieter_id: str


class Pruefung(BaseModel):
    erreichbar: bool
    hinweis: str
    modelle: list[dict[str, Any]]


class Probe(BaseModel):
    text: str
    modell: str
    dauer_ms: int


def _validiere(e: AnbieterEingabe) -> None:
    if e.typ not in dienst.TYPEN:
        raise HTTPException(422, f"Unbekannter Typ '{e.typ}'")
    if e.art not in ("sprachmodell", "einbettung"):
        raise HTTPException(422, "Art muss 'sprachmodell' oder 'einbettung' sein")
    if e.typ == "fastembed" and e.art != "einbettung":
        raise HTTPException(422, "fastembed kann nur Einbettung")
    if e.typ != "fastembed" and not e.basis_url:
        raise HTTPException(422, "Basisadresse fehlt")


@router.get("", response_model=dict[str, Any])
async def alle(session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> dict[str, Any]:
    rows = await dienst.alle(session)
    rollen = {r: await einstellungen_dienst.wert(session, f"anbieter.{r}") for r in dienst.ROLLEN}
    return {
        "anbieter": [dienst.oeffentlich(a, schluessel_zeigen=True) for a in rows],
        "rollen": rollen,
        "rollen_titel": dienst.ROLLEN,
        "typen": dienst.TYPEN,
    }


@router.post("", response_model=dict[str, Any], status_code=201)
async def anlegen(e: AnbieterEingabe, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> dict[str, Any]:
    _validiere(e)
    a = Anbieter(
        name=e.name,
        typ=e.typ,
        art=e.art,
        basis_url=e.basis_url.strip(),
        api_schluessel=(e.api_schluessel or "").strip(),
        modell=e.modell.strip(),
        parameter=e.parameter,
        aktiv=e.aktiv,
    )
    session.add(a)
    await session.commit()
    bus.veroeffentliche("anbieter", aktion="angelegt", anbieter_id=a.id)
    return dienst.oeffentlich(a, schluessel_zeigen=True)


# Feste Pfade vor den Pfaden mit Kennung: sonst fängt PUT /{anbieter_id} den Pfad /rollen ab und verlangt die Felder
# eines Anbieters ("Field required").
@router.put("/rollen", response_model=dict[str, str])
async def rolle_setzen(e: RollenEingabe, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> dict[str, str]:
    if e.rolle not in dienst.ROLLEN:
        raise HTTPException(422, f"Unbekannte Rolle '{e.rolle}'")
    a = await session.get(Anbieter, e.anbieter_id)
    if a is None:
        raise HTTPException(404, "Anbieter nicht gefunden")
    erwartet = "einbettung" if e.rolle == "einbettung" else "sprachmodell"
    if a.art != erwartet:
        raise HTTPException(422, f"Die Rolle '{dienst.ROLLEN[e.rolle]}' braucht einen Anbieter der Art '{erwartet}'")
    await einstellungen_dienst.setze(session, f"anbieter.{e.rolle}", a.id)
    await session.commit()
    bus.veroeffentliche("anbieter", aktion="rolle", rolle=e.rolle, anbieter_id=a.id)
    return {r: str(await einstellungen_dienst.wert(session, f"anbieter.{r}")) for r in dienst.ROLLEN}


@router.put("/{anbieter_id}", response_model=dict[str, Any])
async def aendern(anbieter_id: str, e: AnbieterEingabe, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> dict[str, Any]:
    _validiere(e)
    a = await session.get(Anbieter, anbieter_id)
    if a is None:
        raise HTTPException(404, "Anbieter nicht gefunden")
    a.name, a.typ, a.art, a.basis_url, a.modell, a.parameter, a.aktiv = (
        e.name,
        e.typ,
        e.art,
        e.basis_url.strip(),
        e.modell.strip(),
        e.parameter,
        e.aktiv,
    )
    if e.api_schluessel is not None:
        a.api_schluessel = e.api_schluessel.strip()
    await session.commit()
    bus.veroeffentliche("anbieter", aktion="geaendert", anbieter_id=a.id)
    return dienst.oeffentlich(a, schluessel_zeigen=True)


@router.delete("/{anbieter_id}", status_code=204)
async def loeschen(anbieter_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> None:
    a = await session.get(Anbieter, anbieter_id)
    if a is None:
        raise HTTPException(404, "Anbieter nicht gefunden")
    for rolle in dienst.ROLLEN:
        if await einstellungen_dienst.wert(session, f"anbieter.{rolle}") == anbieter_id:
            raise HTTPException(409, f"Anbieter ist der Rolle '{dienst.ROLLEN[rolle]}' zugewiesen - zuerst umstellen")
    await session.delete(a)
    await session.commit()
    bus.veroeffentliche("anbieter", aktion="geloescht", anbieter_id=anbieter_id)


@router.post("/{anbieter_id}/pruefen", response_model=Pruefung)
async def pruefen(anbieter_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> Pruefung:
    a = await session.get(Anbieter, anbieter_id)
    if a is None:
        raise HTTPException(404, "Anbieter nicht gefunden")
    try:
        umsetzung = dienst.baue_einbettung(a) if a.art == "einbettung" else dienst.baue_sprachmodell(a)
    except AnbieterFehler as e:
        return Pruefung(erreichbar=False, hinweis=str(e), modelle=[])
    ok, hinweis = await umsetzung.erreichbar()
    modelle = await umsetzung.modelle() if ok else []
    return Pruefung(erreichbar=ok, hinweis=hinweis, modelle=modelle)


@router.post("/{anbieter_id}/probe", response_model=Probe)
async def probe(anbieter_id: str, session: AsyncSession = Depends(sitzung_abhaengigkeit)) -> Probe:
    """Kurzer Echtaufruf: eine Frage an das Sprachmodell oder ein Satz an die Einbettung."""
    import time

    a = await session.get(Anbieter, anbieter_id)
    if a is None:
        raise HTTPException(404, "Anbieter nicht gefunden")
    start = time.monotonic()
    try:
        if a.art == "einbettung":
            v = await dienst.baue_einbettung(a).einbetten(["Probe: morf-gpt"], zeitgrenze_s=300)
            text = f"Vektor mit {len(v[0])} Dimensionen"
            modell = a.modell
        else:
            antwort = await dienst.baue_sprachmodell(a).antworte(
                [Nachricht("user", "Antworte mit genau einem kurzen deutschen Satz: Bist du bereit?")],
                Antwortparameter(temperatur=0.0, max_tokens=60, zeitgrenze_s=600),
            )
            text, modell = antwort.text.strip(), antwort.modell
    except AnbieterFehler as e:
        raise HTTPException(502, str(e)) from e
    return Probe(text=text, modell=modell, dauer_ms=int((time.monotonic() - start) * 1000))
