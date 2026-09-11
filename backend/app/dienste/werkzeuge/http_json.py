"""Werkzeugtyp http_json: ein beliebiger HTTP-Dienst mit JSON- (oder Text-) Antwort.

Konfiguration (Tabelle werkzeuge, Spalte konfiguration):
  url            Adresse, Platzhalter {frage} und {parametername}
  methode        GET oder POST
  kopfzeilen     [{"name", "wert", "geheim"}]
  rumpf          Vorlage des Rumpfes (POST), Platzhalter wie bei url; leer = kein Rumpf
  antwort_text   Pfad zum Text, z. B. "antwort" oder "ergebnisse[].text" (leer = ganze Antwort)
  antwort_titel  Pfad zum Titel je Fundstück (optional)
  antwort_url    Pfad zur Quelladresse je Fundstück (optional)
  parameter      [{"name", "beschreibung", "pflicht"}] - Vorgabe: nur "frage"

Pfadsprache: Schlüssel mit Punkten, "[]" sammelt über alle Listenelemente, "[0]" wählt eins.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import quote

import httpx

from .basis import Quellenangabe, Werkzeugbeschreibung, Werkzeugergebnis, WerkzeugFehler

_PLATZHALTER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_PFADTEIL = re.compile(r"([^.\[\]]+)|\[(\d*)\]")


def pfad_werte(daten: Any, pfad: str) -> list[Any]:
    """Alle Werte unter einem Pfad; '[]' fächert Listen auf, fehlende Schlüssel ergeben nichts."""
    pfad = pfad.strip()
    if not pfad:
        return [daten]
    aktuell: list[Any] = [daten]
    for schluessel, index in _PFADTEIL.findall(pfad):
        naechste: list[Any] = []
        for wert in aktuell:
            if schluessel:
                if isinstance(wert, dict) and schluessel in wert:
                    naechste.append(wert[schluessel])
            elif index == "":
                if isinstance(wert, list):
                    naechste.extend(wert)
            else:
                i = int(index)
                if isinstance(wert, list) and -len(wert) <= i < len(wert):
                    naechste.append(wert[i])
        aktuell = naechste
        if not aktuell:
            break
    return aktuell


def _als_text(wert: Any) -> str:
    if wert is None:
        return ""
    if isinstance(wert, str):
        return wert
    if isinstance(wert, int | float | bool):
        return str(wert)
    return json.dumps(wert, ensure_ascii=False, indent=1)


def platzhalter_fuellen(vorlage: str, argumente: dict[str, Any], *, url: bool) -> str:
    """Setzt {name} ein; in Adressen wird der Wert kodiert, im Rumpf JSON-sicher eingefügt."""

    def ersetze(m: re.Match[str]) -> str:
        wert = argumente.get(m.group(1), "")
        text = _als_text(wert)
        if url:
            return quote(text, safe="")
        return json.dumps(text, ensure_ascii=False)[1:-1]  # Anführungszeichen der Vorlage bleiben

    return _PLATZHALTER.sub(ersetze, vorlage)


def parameter_schema(konfiguration: dict[str, Any]) -> dict[str, Any]:
    parameter = konfiguration.get("parameter") or [{"name": "frage", "beschreibung": "Die Suchanfrage oder Frage", "pflicht": True}]
    props: dict[str, Any] = {}
    pflicht: list[str] = []
    for p in parameter:
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        props[name] = {"type": "string", "description": str(p.get("beschreibung") or "")}
        if p.get("pflicht", True):
            pflicht.append(name)
    return {"type": "object", "properties": props, "required": pflicht}


def kopfzeilen(konfiguration: dict[str, Any]) -> dict[str, str]:
    aus: dict[str, str] = {}
    for k in konfiguration.get("kopfzeilen") or []:
        name = str(k.get("name") or "").strip()
        if name:
            aus[name] = str(k.get("wert") or "")
    return aus


def ergebnis_aus_antwort(konfiguration: dict[str, Any], daten: Any, text_roh: str) -> Werkzeugergebnis:
    """Baut aus der Antwort die Fundstücke nach den konfigurierten Pfaden."""
    pfad_text = str(konfiguration.get("antwort_text") or "").strip()
    if daten is None:
        return Werkzeugergebnis(text=text_roh.strip(), roh=text_roh)
    texte = [_als_text(w).strip() for w in pfad_werte(daten, pfad_text)]
    texte = [t for t in texte if t]
    if not texte:
        return Werkzeugergebnis(text="", roh=daten, fehler="Unter dem Pfad für den Antworttext stand nichts")
    titel = (
        [_als_text(w) for w in pfad_werte(daten, str(konfiguration.get("antwort_titel") or ""))]
        if konfiguration.get("antwort_titel")
        else []
    )
    urls = (
        [_als_text(w) for w in pfad_werte(daten, str(konfiguration.get("antwort_url") or ""))] if konfiguration.get("antwort_url") else []
    )
    stellen: list[tuple[str, Quellenangabe]] = []
    for i, t in enumerate(texte):
        q = Quellenangabe(
            titel=titel[i] if len(titel) == len(texte) else (titel[0] if len(titel) == 1 else ""),
            url=urls[i] if len(urls) == len(texte) else (urls[0] if len(urls) == 1 else ""),
        )
        stellen.append((t, q))
    return Werkzeugergebnis(text="\n\n".join(texte), stellen=stellen, roh=daten)


class HttpJsonWerkzeug:
    def __init__(self, beschreibung: Werkzeugbeschreibung, konfiguration: dict[str, Any]) -> None:
        self.beschreibung = beschreibung
        self._k = konfiguration

    async def ausfuehren(self, argumente: dict[str, Any], zeitgrenze_s: float) -> Werkzeugergebnis:
        url_vorlage = str(self._k.get("url") or "").strip()
        if not url_vorlage:
            raise WerkzeugFehler(f"{self.beschreibung.titel}: keine Adresse konfiguriert")
        methode = str(self._k.get("methode") or "GET").upper()
        url = platzhalter_fuellen(url_vorlage, argumente, url=True)
        rumpf_vorlage = str(self._k.get("rumpf") or "")
        rumpf = platzhalter_fuellen(rumpf_vorlage, argumente, url=False) if rumpf_vorlage.strip() else ""
        kopf = kopfzeilen(self._k)
        if rumpf and "content-type" not in {k.lower() for k in kopf}:
            kopf["Content-Type"] = "application/json"
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(zeitgrenze_s, connect=15), follow_redirects=True) as client:
                resp = await client.request(methode, url, headers=kopf, content=rumpf.encode("utf-8") if rumpf else None)
        except httpx.HTTPError as e:
            raise WerkzeugFehler(f"{self.beschreibung.titel}: nicht erreichbar ({e.__class__.__name__})") from e
        dauer = int((time.monotonic() - start) * 1000)
        if resp.status_code >= 400:
            raise WerkzeugFehler(f"{self.beschreibung.titel}: HTTP {resp.status_code} - {resp.text[:300]}")
        daten: Any = None
        text_roh = resp.text
        if "json" in (resp.headers.get("content-type") or "") or text_roh.lstrip().startswith(("{", "[")):
            try:
                daten = resp.json()
            except ValueError:
                daten = None
        ergebnis = ergebnis_aus_antwort(self._k, daten, text_roh)
        ergebnis.dauer_ms = dauer
        return ergebnis
