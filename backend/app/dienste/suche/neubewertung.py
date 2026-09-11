"""Neu-Bewertung von Suchkandidaten: aus, lokaler Cross-Encoder oder Sprachmodell.

Ein Neubewerter bekommt die Frage und die Kandidatentexte und liefert je Text eine Zahl;
höher ist besser. Die Suche sortiert danach. Die Werte sind je Art verschieden (Logits beim
Cross-Encoder, 0 bis 10 beim Sprachmodell) und nur innerhalb einer Suche vergleichbar.

Kann eine Neu-Bewertung nicht arbeiten (Modell fehlt, Antwort unlesbar), wirft sie
`NeubewertungFehler`; die Suche behält dann die Vektorreihenfolge und meldet es sichtbar.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from ...config import einstellungen
from ..anbieter import dienst as anbieter_dienst
from ..anbieter.basis import AnbieterFehler, Antwortparameter, Nachricht, SprachmodellAnbieter
from ..einstellungen import dienst as einstellungen_dienst
from ..einstellungen import register

log = logging.getLogger(__name__)

NEUBEWERTUNG_AUS = "aus"
NEUBEWERTUNG_CROSSENCODER = "crossencoder"
NEUBEWERTUNG_SPRACHMODELL = "sprachmodell"

# Die erlaubten Arten stammen aus dem Register (einzige Wahrheit, auch für die Oberfläche).
ARTEN: tuple[str, ...] = tuple(w for w, _ in register.definition("suche.neubewertung").auswahl)

# Modul-Vorgaben, solange das Register diese Werte nicht kennt (siehe Bericht: register_ergaenzungen).
# Vorschlag: suche.crossencoder_modell (text), suche.neubewertung_zeitgrenze_s (ganzzahl, Sekunden),
# suche.neubewertung_zeichen (ganzzahl, Zeichen je Kandidat für das Sprachmodell).
CROSSENCODER_MODELL_VORGABE = "BAAI/bge-reranker-base"
CROSSENCODER_ZEITGRENZE_S_VORGABE = 120.0
SPRACHMODELL_ZEICHEN_JE_KANDIDAT_VORGABE = 1200

BEWERTUNG_MIN = 0.0
BEWERTUNG_MAX = 10.0


class NeubewertungFehler(RuntimeError):
    """Die Neu-Bewertung konnte nicht arbeiten; die Suche behält die Vektorreihenfolge."""


class Neubewerter(Protocol):
    kennung: str

    async def bewerte(self, frage: str, texte: list[str]) -> list[float]:
        """Je Text eine Zahl, höher ist besser. Länge gleich `len(texte)`."""
        ...


# ---------------------------------------------------------------- Aus


class KeineNeubewertung:
    """Behält die Reihenfolge: absteigende Werte in Eingabereihenfolge."""

    kennung = NEUBEWERTUNG_AUS

    async def bewerte(self, frage: str, texte: list[str]) -> list[float]:
        return [float(len(texte) - i) for i in range(len(texte))]


# ---------------------------------------------------------------- Cross-Encoder (fastembed)

_crossencoder: dict[str, Any] = {}
_sperre = threading.Lock()


def _lade_crossencoder(modellname: str) -> Any:
    """Lädt das Modell einmal (Singleton je Name) in das Modellverzeichnis des Projekts."""
    with _sperre:
        if modellname not in _crossencoder:
            try:
                from fastembed.rerank.cross_encoder import TextCrossEncoder
            except ImportError as e:  # pragma: no cover - Abhängigkeit fehlt
                raise NeubewertungFehler("fastembed ist nicht installiert") from e
            einstellungen.modelle_verzeichnis.mkdir(parents=True, exist_ok=True)
            _crossencoder[modellname] = TextCrossEncoder(model_name=modellname, cache_dir=str(einstellungen.modelle_verzeichnis))
        return _crossencoder[modellname]


class CrossEncoderNeubewertung:
    """Lokales Cross-Encoder-Modell; die Werte sind Logits und dienen nur der Sortierung."""

    kennung = NEUBEWERTUNG_CROSSENCODER

    def __init__(self, modellname: str = CROSSENCODER_MODELL_VORGABE, zeitgrenze_s: float = CROSSENCODER_ZEITGRENZE_S_VORGABE) -> None:
        self._modellname = modellname
        self._zeitgrenze_s = zeitgrenze_s

    async def bewerte(self, frage: str, texte: list[str]) -> list[float]:
        if not texte:
            return []

        def _rechne() -> list[float]:
            modell = _lade_crossencoder(self._modellname)
            return [float(w) for w in modell.rerank(frage, texte)]

        try:
            return await asyncio.wait_for(asyncio.to_thread(_rechne), timeout=self._zeitgrenze_s)
        except TimeoutError as e:
            raise NeubewertungFehler(
                f"Cross-Encoder '{self._modellname}' hat die Zeitgrenze von {self._zeitgrenze_s:.0f} Sekunden überschritten"
            ) from e
        except NeubewertungFehler:
            raise
        except Exception as e:  # Modell-Ladefehler, ONNX-Laufzeit
            raise NeubewertungFehler(f"Cross-Encoder '{self._modellname}': {e}") from e


# ---------------------------------------------------------------- Sprachmodell

SPRACHMODELL_ANWEISUNG = (
    "Du bewertest, wie gut Textstellen aus Erklärvideos eine Frage beantworten.\n"
    "Vergib je Stelle eine ganze Zahl von 0 (beantwortet die Frage gar nicht) bis 10 (beantwortet sie "
    "vollständig und genau). Bewerte jede Stelle für sich, ohne die anderen zu vergleichen.\n"
    'Antworte ausschließlich mit JSON in dieser Form: {"bewertungen": [{"nr": 1, "wert": 7}, {"nr": 2, "wert": 2}]}\n'
    "Keine Erklärungen, kein anderer Text."
)


def _kuerze(text: str, zeichen: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= zeichen else text[:zeichen].rstrip() + " ..."


def baue_bewertungsaufforderung(frage: str, texte: list[str], zeichen_je_kandidat: int) -> str:
    zeilen = [f"Frage: {frage}", "", "Stellen:"]
    for i, t in enumerate(texte, start=1):
        zeilen.append(f"[{i}] {_kuerze(t, zeichen_je_kandidat)}")
    zeilen.append("")
    zeilen.append(f"Bewerte alle {len(texte)} Stellen.")
    return "\n".join(zeilen)


_ZAUN = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_PAAR = re.compile(r'"?nr"?\s*:\s*(\d+)\s*,\s*"?wert"?\s*:\s*(-?\d+(?:[.,]\d+)?)')


def _begrenze(wert: Any) -> float:
    try:
        zahl = float(str(wert).replace(",", "."))
    except (TypeError, ValueError):
        return BEWERTUNG_MIN
    return max(BEWERTUNG_MIN, min(BEWERTUNG_MAX, zahl))


def _json_kern(text: str) -> Any | None:
    """Findet das erste JSON-Objekt oder die erste JSON-Liste im Text (auch in Codezäunen)."""
    treffer = _ZAUN.search(text)
    kandidat = treffer.group(1) if treffer else text
    for oeffner, schliesser in (("{", "}"), ("[", "]")):
        start, ende = kandidat.find(oeffner), kandidat.rfind(schliesser)
        if start != -1 and ende > start:
            try:
                return json.loads(kandidat[start : ende + 1])
            except ValueError:
                continue
    return None


def _eintraege_aus_json(daten: Any) -> dict[int, float]:
    """Akzeptiert {"bewertungen": [...]}, eine Liste von Einträgen oder {"1": 7, "2": 3}."""
    if isinstance(daten, dict) and isinstance(daten.get("bewertungen"), list):
        daten = daten["bewertungen"]
    aus: dict[int, float] = {}
    if isinstance(daten, list):
        for eintrag in daten:
            if isinstance(eintrag, dict) and "nr" in eintrag:
                try:
                    aus[int(eintrag["nr"])] = _begrenze(eintrag.get("wert", eintrag.get("score")))
                except (TypeError, ValueError):
                    continue
            elif isinstance(eintrag, (int, float)):
                aus[len(aus) + 1] = _begrenze(eintrag)
    elif isinstance(daten, dict):
        for schluessel, wert in daten.items():
            try:
                aus[int(str(schluessel).strip("[] "))] = _begrenze(wert)
            except ValueError:
                continue
    return aus


def parse_bewertungen(text: str, anzahl: int) -> list[float]:
    """Liest die Bewertungen robust aus der Modellantwort; fehlende Nummern zählen als 0.

    Wirft `NeubewertungFehler`, wenn keine einzige Bewertung lesbar ist.
    """
    je_nr = _eintraege_aus_json(_json_kern(text))
    if not je_nr:
        je_nr = {int(nr): _begrenze(wert) for nr, wert in _PAAR.findall(text)}
    if not je_nr:
        raise NeubewertungFehler("Die Antwort des Sprachmodells enthielt keine lesbaren Bewertungen")
    return [je_nr.get(nr, BEWERTUNG_MIN) for nr in range(1, anzahl + 1)]


class SprachmodellNeubewertung:
    """Das Chat-Modell bewertet jede Stelle 0 bis 10; unlesbare Antworten führen zum Fehler."""

    kennung = NEUBEWERTUNG_SPRACHMODELL

    def __init__(
        self,
        anbieter: SprachmodellAnbieter,
        zeitgrenze_s: float,
        zeichen_je_kandidat: int = SPRACHMODELL_ZEICHEN_JE_KANDIDAT_VORGABE,
    ) -> None:
        self._anbieter = anbieter
        self._zeitgrenze_s = zeitgrenze_s
        self._zeichen_je_kandidat = zeichen_je_kandidat

    async def bewerte(self, frage: str, texte: list[str]) -> list[float]:
        if not texte:
            return []
        nachrichten = [
            Nachricht("system", SPRACHMODELL_ANWEISUNG),
            Nachricht("user", baue_bewertungsaufforderung(frage, texte, self._zeichen_je_kandidat)),
        ]
        parameter = Antwortparameter(
            temperatur=0.0,
            max_tokens=40 * len(texte) + 200,  # je Eintrag etwa ein Dutzend Tokens, plus Rahmen
            zeitgrenze_s=self._zeitgrenze_s,
            json_modus=True,
        )
        try:
            antwort = await self._anbieter.antworte(nachrichten, parameter)
        except AnbieterFehler as e:
            raise NeubewertungFehler(str(e)) from e
        return parse_bewertungen(antwort.text, len(texte))


# ---------------------------------------------------------------- Fabrik


async def neubewerter_fuer(art: str, session: AsyncSession) -> Neubewerter:
    """Baut den Neubewerter zur eingestellten Art; unbekannte Arten sind ein Fehler."""
    if art == NEUBEWERTUNG_AUS:
        return KeineNeubewertung()
    if art == NEUBEWERTUNG_CROSSENCODER:
        return CrossEncoderNeubewertung()
    if art == NEUBEWERTUNG_SPRACHMODELL:
        try:
            anbieter = await anbieter_dienst.sprachmodell_fuer(session, "chat")
        except AnbieterFehler as e:
            raise NeubewertungFehler(str(e)) from e
        zeitgrenze = float(await einstellungen_dienst.wert(session, "chat.zeitgrenze_s"))
        return SprachmodellNeubewertung(anbieter, zeitgrenze_s=zeitgrenze)
    raise NeubewertungFehler(f"Unbekannte Art der Neu-Bewertung '{art}' (erlaubt: {', '.join(ARTEN)})")
