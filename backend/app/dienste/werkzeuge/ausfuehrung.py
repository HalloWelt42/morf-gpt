"""Werkzeuge ausführen und ihre Ergebnisse zu Stellen machen (Art 'werkzeug').

Wird von beiden Betriebsarten genutzt: "Der Nutzer wählt" ruft alle gewählten Werkzeuge mit
abgeleiteten Argumenten; "Das Modell wählt" ruft einzelne Werkzeuge mit den Argumenten
des Modells. Jeder Aufruf wird protokolliert (Argumente, Dauer, Ergebnis oder Fehler).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..anbieter.basis import SprachmodellAnbieter
from ..suche.retrieval import Treffer
from ..text import bereinige
from . import argumente as argumente_modul
from . import register
from .basis import Werkzeugbeschreibung, WerkzeugFehler

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Aufrufprotokoll:
    """Ein Werkzeugaufruf, wie er in der Nachricht gespeichert wird."""

    kennung: str
    titel: str
    argumente: dict[str, Any]
    herkunft: str  # direkt, modell, notloesung, modellwahl
    dauer_ms: int = 0
    stellen: int = 0
    text: str = ""  # gekürzte Vorschau des Ergebnisses
    fehler: str = ""
    runde: int = 0

    def als_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Werkzeuglauf:
    stellen: list[Treffer] = field(default_factory=list)
    aufrufe: list[Aufrufprotokoll] = field(default_factory=list)
    hinweise: list[str] = field(default_factory=list)


def _kuerze(text: str, zeichen: int) -> str:
    text = text.strip()
    if len(text) <= zeichen:
        return text
    return text[: max(0, zeichen - 20)].rstrip() + " ... [gekürzt]"


def stellen_aus_ergebnis(b: Werkzeugbeschreibung, texte_und_quellen: list[tuple[str, Any]], ergebnis_zeichen: int) -> list[Treffer]:
    aus: list[Treffer] = []
    for i, (text, quelle) in enumerate(texte_und_quellen):
        text = bereinige(text)
        if not text.strip():
            continue
        aus.append(
            Treffer(
                chunk_id=f"werkzeug:{b.kennung}:{i}",
                video_id="",
                titel=(getattr(quelle, "titel", "") or "").strip(),
                serie="",
                folge_nr=None,
                start_s=0.0,
                end_s=0.0,
                text=_kuerze(text, ergebnis_zeichen),
                wert=0.0,
                reihenfolge=i,
                thema="",
                original_url="",
                miniatur="",
                art="werkzeug",
                werkzeug=b.titel,
                quelle_url=(getattr(quelle, "url", "") or "").strip(),
            )
        )
    return aus


async def einzeln(
    session: AsyncSession,
    kennung: str,
    argumente: dict[str, Any],
    *,
    zeitgrenze_s: float,
    ergebnis_zeichen: int,
    herkunft: str,
    runde: int = 0,
) -> tuple[list[Treffer], Aufrufprotokoll]:
    """Ein Werkzeug mit fertigen Argumenten ausführen."""
    passende = await register.nach_kennungen(session, [kennung])
    if not passende:
        p = Aufrufprotokoll(
            kennung=kennung, titel=kennung, argumente=argumente, herkunft=herkunft, fehler="Werkzeug nicht (mehr) vorhanden", runde=runde
        )
        return [], p
    zeile, b = passende[0]
    werkzeug = register.baue(zeile, b)
    start = time.monotonic()
    try:
        ergebnis = await werkzeug.ausfuehren(argumente, zeitgrenze_s)
    except WerkzeugFehler as e:
        return [], Aufrufprotokoll(
            kennung=kennung,
            titel=b.titel,
            argumente=argumente,
            herkunft=herkunft,
            dauer_ms=int((time.monotonic() - start) * 1000),
            fehler=str(e),
            runde=runde,
        )
    stellen = stellen_aus_ergebnis(b, ergebnis.als_stellen(), ergebnis_zeichen)
    p = Aufrufprotokoll(
        kennung=kennung,
        titel=b.titel,
        argumente=argumente,
        herkunft=herkunft,
        dauer_ms=ergebnis.dauer_ms or int((time.monotonic() - start) * 1000),
        stellen=len(stellen),
        text=_kuerze(bereinige(ergebnis.text), 400),
        fehler=ergebnis.fehler,
        runde=runde,
    )
    return stellen, p


async def fuer_frage(
    session: AsyncSession,
    kennungen: list[str],
    frage: str,
    *,
    anbieter: SprachmodellAnbieter | None,
    argumente_per_modell: bool,
    zeitgrenze_s: float,
    ergebnis_zeichen: int,
) -> Werkzeuglauf:
    """Betriebsart 'Der Nutzer wählt': alle gewählten Werkzeuge mit abgeleiteten Argumenten, parallel."""
    lauf = Werkzeuglauf()
    gewaehlt = await register.nach_kennungen(session, kennungen)
    fehlend = set(kennungen) - {b.kennung for _, b in gewaehlt}
    if fehlend:
        lauf.hinweise.append(f"{len(fehlend)} gewählte Werkzeuge sind nicht (mehr) vorhanden oder deaktiviert.")
    if not gewaehlt:
        return lauf

    async def _eins(zeile: Any, b: Werkzeugbeschreibung) -> tuple[list[Treffer], Aufrufprotokoll]:
        argumente, herkunft = await argumente_modul.ableiten(b, frage, anbieter, per_modell=argumente_per_modell, zeitgrenze_s=zeitgrenze_s)
        werkzeug = register.baue(zeile, b)
        start = time.monotonic()
        try:
            ergebnis = await werkzeug.ausfuehren(argumente, zeitgrenze_s)
        except WerkzeugFehler as e:
            return [], Aufrufprotokoll(
                kennung=b.kennung,
                titel=b.titel,
                argumente=argumente,
                herkunft=herkunft,
                dauer_ms=int((time.monotonic() - start) * 1000),
                fehler=str(e),
            )
        stellen = stellen_aus_ergebnis(b, ergebnis.als_stellen(), ergebnis_zeichen)
        return stellen, Aufrufprotokoll(
            kennung=b.kennung,
            titel=b.titel,
            argumente=argumente,
            herkunft=herkunft,
            dauer_ms=ergebnis.dauer_ms or int((time.monotonic() - start) * 1000),
            stellen=len(stellen),
            text=_kuerze(bereinige(ergebnis.text), 400),
            fehler=ergebnis.fehler,
        )

    ergebnisse = await asyncio.gather(*(_eins(z, b) for z, b in gewaehlt), return_exceptions=True)
    for (_z, b), r in zip(gewaehlt, ergebnisse, strict=True):
        if isinstance(r, BaseException):
            log.warning("Werkzeug %s scheiterte: %s", b.titel, r)
            lauf.aufrufe.append(Aufrufprotokoll(kennung=b.kennung, titel=b.titel, argumente={}, herkunft="fehler", fehler=str(r)[:300]))
            continue
        stellen, protokoll = r
        lauf.stellen.extend(stellen)
        lauf.aufrufe.append(protokoll)
        if protokoll.fehler:
            lauf.hinweise.append(f"Werkzeug {b.titel}: {protokoll.fehler}")
    return lauf
