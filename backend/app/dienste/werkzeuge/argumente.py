"""Argumente für einen Werkzeugaufruf aus der Frage ableiten (Betriebsart "Der Nutzer wählt").

Regeln, in dieser Reihenfolge:
1. Keine Parameter -> leere Argumente.
2. Genau ein Pflichtparameter vom Typ Text (oder genau ein Parameter überhaupt) -> die Frage.
3. Sonst leitet das Sprachmodell die Argumente mit dem Parameterschema als json_schema ab;
   ist das abgeschaltet oder scheitert es, bekommt der erste Textparameter die Frage.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..anbieter.basis import AnbieterFehler, Antwortparameter, Nachricht, SprachmodellAnbieter
from .basis import Werkzeugbeschreibung

log = logging.getLogger(__name__)

SYSTEM = (
    "Du füllst die Argumente eines Werkzeugs aus einer Nutzerfrage. Antworte nur mit dem JSON-Objekt "
    "der Argumente. Nimm nur Werte, die aus der Frage hervorgehen; lass optionale Felder weg, wenn die "
    "Frage nichts dazu sagt. Suchanfragen knapp und treffend formulieren."
)


def _textparameter(b: Werkzeugbeschreibung) -> list[str]:
    return [n for n, p in b.parameter.items() if isinstance(p, dict) and p.get("type", "string") == "string"]


# Parameternamen, die eine freie Suchanfrage oder Frage meinen - hier passt die Frage 1:1.
FREITEXT_NAMEN: frozenset[str] = frozenset(
    {"query", "q", "frage", "text", "suche", "suchanfrage", "anfrage", "prompt", "input", "eingabe", "frage_text", "thema"}
)


def direkt(b: Werkzeugbeschreibung, frage: str) -> dict[str, Any] | None:
    """Argumente ohne Modell, wenn die Form es hergibt; sonst None (dann leitet das Modell ab).

    Direkt geht es nur, wenn genau ein Text-Parameter eine freie Frage meint (query, frage ...)
    und alle anderen Parameter optional sind. Ein Parameter wie `ort` bekommt nicht die ganze
    Frage, sondern wird vom Modell aus der Frage herausgelesen.
    """
    if not b.parameter:
        return {}
    pflicht = b.pflichtparameter
    texte = _textparameter(b)
    frei = [n for n in texte if n.lower() in FREITEXT_NAMEN]
    if len(frei) == 1 and all(p == frei[0] for p in pflicht):
        return {frei[0]: frage}
    return None


def notloesung(b: Werkzeugbeschreibung, frage: str) -> dict[str, Any]:
    """Wenn nichts anderes geht: der erste Textparameter bekommt die Frage."""
    texte = _textparameter(b)
    pflicht = [p for p in b.pflichtparameter if p in texte]
    if pflicht:
        return {pflicht[0]: frage}
    if texte:
        return {texte[0]: frage}
    return {}


def _schema_fuer_modell(b: Werkzeugbeschreibung) -> dict[str, Any]:
    schema = dict(b.parameter_schema or {})
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    return schema


async def ableiten(
    b: Werkzeugbeschreibung,
    frage: str,
    anbieter: SprachmodellAnbieter | None,
    *,
    per_modell: bool,
    zeitgrenze_s: float,
) -> tuple[dict[str, Any], str]:
    """(Argumente, Herkunft) mit Herkunft 'direkt', 'modell' oder 'notloesung'."""
    d = direkt(b, frage)
    if d is not None:
        return d, "direkt"
    if per_modell and anbieter is not None:
        try:
            nachrichten = [
                Nachricht("system", SYSTEM),
                Nachricht(
                    "user",
                    f"Werkzeug: {b.titel}\nZweck: {b.beschreibung[:600]}\n"
                    f"Parameter (JSON-Schema): {json.dumps(_schema_fuer_modell(b), ensure_ascii=False)[:3000]}\n\n"
                    f"Frage: {frage}",
                ),
            ]
            antwort = await anbieter.antworte(
                nachrichten,
                Antwortparameter(temperatur=0.0, max_tokens=600, zeitgrenze_s=zeitgrenze_s, json_schema=_schema_fuer_modell(b)),
            )
            daten = json.loads(antwort.text)
            if isinstance(daten, dict):
                # Pflichtfelder sicherstellen
                for p in b.pflichtparameter:
                    if p not in daten and p in _textparameter(b):
                        daten[p] = frage
                return daten, "modell"
        except (AnbieterFehler, ValueError) as e:
            log.warning("Argumente für %s nicht ableitbar: %s", b.titel, e)
    return notloesung(b, frage), "notloesung"
