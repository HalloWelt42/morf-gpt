"""Korrektur-Engine: Rohsegmente blockweise durch das Sprachmodell, Wächter, Absätze
mit Zeitfenstern, danach Themenaufschlüsselung und Kurzzusammenfassung.

Reine Verarbeitung ohne Datenbank; die Stufe (stufen/korrektur.py) lädt und speichert.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from math import ceil
from typing import Any

from ..anbieter.basis import AnbieterFehler, Antwortparameter, SprachmodellAnbieter
from ..text import gerade
from . import bloecke as blockmodul
from . import prompts, waechter

log = logging.getLogger(__name__)

Fortschrittsmelder = Callable[[float, str], Awaitable[None]]
Protokollant = Callable[[str, str], Awaitable[None]]

# Grobe Schätzung: ein Token je 2,5 Zeichen deutschen Textes, plus Reserve. Bewusst
# großzügig, damit kein Block am Tokenlimit abgeschnitten wird.
ZEICHEN_JE_TOKEN: float = 2.5
TOKEN_RESERVE: int = 300
THEMEN_MAX_TOKENS: int = 4000

# Schema der Themenantwort (strukturierte Ausgabe, damit das Modell kein Beiwerk liefert).
THEMEN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "themen": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "titel": {"type": "string"},
                    "start_s": {"type": "number"},
                    "end_s": {"type": "number"},
                    "kurz": {"type": "string"},
                },
                "required": ["titel", "start_s", "end_s", "kurz"],
            },
        },
        "zusammenfassung": {"type": "string"},
    },
    "required": ["themen", "zusammenfassung"],
}


@dataclass(slots=True)
class Absatz:
    start_s: float
    end_s: float
    text: str
    block: int
    verworfen: bool = False

    def als_dict(self) -> dict[str, Any]:
        return {
            "start_s": round(self.start_s, 3),
            "end_s": round(self.end_s, 3),
            "text": self.text,
            "block": self.block,
            "verworfen": self.verworfen,
        }


@dataclass(slots=True)
class Blockergebnis:
    index: int
    start_s: float
    end_s: float
    roh: str
    text: str
    aehnlichkeit: float
    verworfen: bool
    grund: str = ""
    vorschlag: str = ""  # bereinigte Modellantwort eines verworfenen Blocks

    def als_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "start_s": round(self.start_s, 3),
            "end_s": round(self.end_s, 3),
            "aehnlichkeit": round(self.aehnlichkeit, 4),
            "verworfen": self.verworfen,
            "grund": self.grund,
            "vorschlag": self.vorschlag,
        }


@dataclass(slots=True)
class Thema:
    titel: str
    start_s: float
    end_s: float
    kurz: str = ""

    def als_dict(self) -> dict[str, Any]:
        return {"titel": self.titel, "start_s": round(self.start_s, 3), "end_s": round(self.end_s, 3), "kurz": self.kurz}


@dataclass(slots=True)
class Korrekturergebnis:
    absaetze: list[Absatz] = field(default_factory=list)
    bloecke: list[Blockergebnis] = field(default_factory=list)
    themen: list[Thema] = field(default_factory=list)
    zusammenfassung: str = ""
    themen_fehler: str = ""

    @property
    def aehnlichkeit(self) -> float | None:
        if not self.bloecke:
            return None
        return sum(b.aehnlichkeit for b in self.bloecke) / len(self.bloecke)

    @property
    def verworfen(self) -> int:
        return sum(1 for b in self.bloecke if b.verworfen)


@dataclass(slots=True)
class Korrekturparameter:
    block_zeichen: int = 2500
    mindest_aehnlichkeit: float = 0.8
    temperatur: float = 0.0
    zeitgrenze_s: float = 1800.0
    themen: bool = True

    @classmethod
    def aus_werten(cls, werte: dict[str, Any]) -> Korrekturparameter:
        return cls(
            block_zeichen=int(werte["korrektur.block_zeichen"]),
            mindest_aehnlichkeit=float(werte["korrektur.mindest_aehnlichkeit"]),
            temperatur=float(werte["korrektur.temperatur"]),
            zeitgrenze_s=float(werte["korrektur.zeitgrenze_s"]),
            themen=bool(werte["korrektur.themen"]),
        )


async def _nichts(*_: Any) -> None:
    return None


def max_tokens_fuer(zeichen: int) -> int:
    return int(ceil(zeichen / ZEICHEN_JE_TOKEN)) + TOKEN_RESERVE


# ---------------------------------------------------------------- Absätze aus einem Block


def absaetze_aus_block(block: blockmodul.Block, text: str, verworfen: bool) -> list[Absatz]:
    """Teilt den Blocktext an Leerzeilen in Absätze und verteilt das Zeitfenster anteilig
    nach Zeichen. Der letzte Absatz endet genau am Blockende."""
    teile = [t.strip() for t in re.split(r"\n\s*\n", text.strip()) if t.strip()]
    if not teile:
        return []
    gesamt = sum(len(t) for t in teile) or 1
    dauer = block.dauer_s
    aus: list[Absatz] = []
    lauf = 0
    start = block.start_s
    for i, t in enumerate(teile):
        lauf += len(t)
        ende = block.end_s if i == len(teile) - 1 else block.start_s + dauer * (lauf / gesamt)
        aus.append(Absatz(start_s=start, end_s=ende, text=t, block=block.index, verworfen=verworfen))
        start = ende
    return aus


# ---------------------------------------------------------------- Themen


_ZAUN = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _json_objekt(text: str) -> dict[str, Any] | None:
    """Erstes JSON-Objekt aus einer Modellantwort, auch wenn Text oder Zäune drumherum stehen."""
    kandidaten = [text]
    zaun = _ZAUN.search(text)
    if zaun:
        kandidaten.insert(0, zaun.group(1))
    anfang = text.find("{")
    ende = text.rfind("}")
    if anfang >= 0 and ende > anfang:
        kandidaten.append(text[anfang : ende + 1])
    for k in kandidaten:
        try:
            daten = json.loads(k)
        except ValueError:
            continue
        if isinstance(daten, dict):
            return daten
    return None


def themen_aus_antwort(text: str, start_s: float, end_s: float) -> tuple[list[Thema], str]:
    """Themen und Zusammenfassung aus der Modellantwort; Zeiten werden auf das Video geklemmt
    und in Reihenfolge gebracht. Wirft ValueError bei unbrauchbarer Antwort."""
    daten = _json_objekt(text)
    if daten is None:
        raise ValueError("Die Themenantwort enthält kein JSON-Objekt")
    roh = daten.get("themen")
    if not isinstance(roh, list):
        raise ValueError("Die Themenantwort enthält keine Liste 'themen'")
    themen: list[Thema] = []
    for eintrag in roh:
        if not isinstance(eintrag, dict):
            continue
        titel = str(eintrag.get("titel") or "").strip()
        if not titel:
            continue
        try:
            a = float(eintrag.get("start_s", start_s))
            b = float(eintrag.get("end_s", end_s))
        except (TypeError, ValueError):
            continue
        a = min(max(a, start_s), end_s)
        b = min(max(b, a), end_s)
        themen.append(Thema(titel=titel, start_s=a, end_s=b, kurz=str(eintrag.get("kurz") or "").strip()))
    themen.sort(key=lambda t: t.start_s)
    # Lücken und Überschneidungen glätten: jedes Thema endet, wo das nächste beginnt.
    for i in range(len(themen) - 1):
        themen[i].end_s = max(themen[i].start_s, themen[i + 1].start_s)
    if themen:
        themen[0].start_s = start_s
        themen[-1].end_s = end_s
    zusammenfassung = " ".join(str(daten.get("zusammenfassung") or "").split())
    return themen, zusammenfassung


# ---------------------------------------------------------------- Der Ablauf


def _abbruch_pruefen(abbruch: asyncio.Event | None) -> None:
    if abbruch is not None and abbruch.is_set():
        raise asyncio.CancelledError()


async def korrigiere(
    anbieter: SprachmodellAnbieter,
    rohsegmente: list[dict[str, Any]],
    p: Korrekturparameter,
    *,
    video_titel: str = "",
    fortschritt: Fortschrittsmelder | None = None,
    protokoll: Protokollant | None = None,
    abbruch: asyncio.Event | None = None,
) -> Korrekturergebnis:
    """Korrigiert alle Blöcke, dann (optional) die Themenaufschlüsselung."""
    melde = fortschritt or _nichts
    schreibe = protokoll or _nichts
    segmente = blockmodul.segmente_lesen(rohsegmente)
    if not segmente:
        raise RuntimeError("Das Transkript hat keine Segmente")
    liste = blockmodul.bilde_bloecke(segmente, p.block_zeichen)
    ergebnis = Korrekturergebnis()
    await schreibe(f"{len(liste)} Blöcke zu je etwa {p.block_zeichen} Zeichen, Wächter-Schwelle {p.mindest_aehnlichkeit:.2f}", "info")

    for block in liste:
        _abbruch_pruefen(abbruch)
        await melde(0.05 + 0.85 * (block.index / len(liste)), f"Block {block.index + 1} von {len(liste)} beim Sprachmodell")
        antwort = await anbieter.antworte(
            prompts.korrektur_nachrichten(block.text),
            Antwortparameter(temperatur=p.temperatur, max_tokens=max_tokens_fuer(block.zeichen), zeitgrenze_s=p.zeitgrenze_s),
        )
        pruefung = waechter.pruefe_block(block.text, gerade(antwort.text), p.mindest_aehnlichkeit)
        vorschlag = waechter.bereinige_antwort(gerade(antwort.text)) if pruefung.verworfen else ""
        ergebnis.bloecke.append(
            Blockergebnis(
                index=block.index,
                start_s=block.start_s,
                end_s=block.end_s,
                roh=block.text,
                text=pruefung.text,
                aehnlichkeit=pruefung.aehnlichkeit,
                verworfen=pruefung.verworfen,
                grund=pruefung.grund,
                vorschlag=vorschlag,
            )
        )
        if pruefung.verworfen:
            await schreibe(f"Block {block.index + 1}: {pruefung.grund} - Rohtext bleibt", "warn")
        ergebnis.absaetze.extend(absaetze_aus_block(block, pruefung.text, pruefung.verworfen))

    if p.themen and ergebnis.absaetze:
        _abbruch_pruefen(abbruch)
        await melde(0.92, "Themenaufschlüsselung und Zusammenfassung")
        try:
            antwort = await anbieter.antworte(
                prompts.themen_nachrichten(ergebnis.absaetze, video_titel),
                Antwortparameter(
                    temperatur=p.temperatur, max_tokens=THEMEN_MAX_TOKENS, zeitgrenze_s=p.zeitgrenze_s, json_schema=THEMEN_SCHEMA
                ),
            )
            ergebnis.themen, ergebnis.zusammenfassung = themen_aus_antwort(
                gerade(antwort.text), ergebnis.absaetze[0].start_s, ergebnis.absaetze[-1].end_s
            )
            await schreibe(f"{len(ergebnis.themen)} Themen, Zusammenfassung mit {len(ergebnis.zusammenfassung)} Zeichen", "info")
        except (AnbieterFehler, ValueError) as e:
            # Die Themen sind Beiwerk; die Korrektur bleibt gültig.
            ergebnis.themen_fehler = str(e)
            await schreibe(f"Themenaufschlüsselung nicht möglich: {e}", "warn")
    return ergebnis
