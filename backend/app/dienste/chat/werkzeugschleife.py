"""Betriebsart "Das Modell wählt": Werkzeuge als Funktionen anbieten, Aufrufe des Modells
ausführen, Ergebnisse zurückgeben, nach höchstens max_runden Runden antworten.

Liefert am Ende die Nachrichtenfolge für den abschließenden Stream (mit allen Werkzeug-
Zwischenschritten) sowie die gesammelten Stellen und Aufrufprotokolle.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from ..anbieter.basis import AnbieterFehler, Antwortparameter, Nachricht, SprachmodellAnbieter
from ..suche.retrieval import Treffer
from ..werkzeuge import ausfuehrung, register
from ..werkzeuge.basis import Werkzeugbeschreibung
from . import prompts

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Schleifenergebnis:
    nachrichten: list[Nachricht]
    stellen: list[Treffer] = field(default_factory=list)
    aufrufe: list[ausfuehrung.Aufrufprotokoll] = field(default_factory=list)
    hinweise: list[str] = field(default_factory=list)
    runden: int = 0
    unterstuetzt: bool = True


async def laufe(
    session: AsyncSession,
    anbieter: SprachmodellAnbieter,
    frage: str,
    bibliothek_stellen: list[Treffer],
    verlauf: list[prompts.Verlaufsnachricht],
    zusammenfassungen: dict[str, str],
    kennungen: list[str],
    *,
    max_runden: int,
    zeitgrenze_s: float,
    werkzeug_zeitgrenze_s: float,
    ergebnis_zeichen: int,
    temperatur: float,
) -> Schleifenergebnis:
    """Führt die Werkzeugrunden aus. Die Stellen der Bibliothek stehen von Anfang an im Kontext;
    Werkzeugstellen werden fortlaufend nummeriert angehängt."""
    gewaehlt = await register.nach_kennungen(session, kennungen)
    je_name: dict[str, tuple[str, Werkzeugbeschreibung]] = {b.name: (b.kennung, b) for _, b in gewaehlt}
    werkzeuge_openai = [b.als_openai() for _, b in gewaehlt]
    alle_stellen = list(bibliothek_stellen)
    nachrichten = prompts.baue_nachrichten(
        frage, alle_stellen, verlauf, zusammenfassungen, system=prompts.SYSTEM_WERKZEUGWAHL if werkzeuge_openai else prompts.SYSTEM_PROMPT
    )
    ergebnis = Schleifenergebnis(nachrichten=nachrichten)
    if not werkzeuge_openai:
        return ergebnis

    for runde in range(1, max_runden + 1):
        try:
            antwort = await anbieter.antworte(
                nachrichten,
                Antwortparameter(temperatur=temperatur, max_tokens=1200, zeitgrenze_s=zeitgrenze_s, werkzeuge=werkzeuge_openai),
            )
        except AnbieterFehler as e:
            # Anbieter kann keine Werkzeugaufrufe: ehrlich melden, ohne Werkzeuge weiter
            ergebnis.hinweise.append(f"Der Anbieter unterstützt keine Werkzeugaufrufe ({e}); Antwort ohne Werkzeuge.")
            ergebnis.unterstuetzt = False
            return ergebnis
        ergebnis.runden = runde
        if not antwort.werkzeugaufrufe:
            # Das Modell will antworten. Die Antwort selbst wird gestreamt (mit dem Kontext).
            return ergebnis
        nachrichten.append(Nachricht("assistant", antwort.text, werkzeugaufrufe=antwort.werkzeugaufrufe))
        for aufruf in antwort.werkzeugaufrufe:
            eintrag = je_name.get(aufruf.name)
            if eintrag is None:
                text = f"Unbekanntes Werkzeug '{aufruf.name}'."
                ergebnis.aufrufe.append(
                    ausfuehrung.Aufrufprotokoll(
                        kennung=aufruf.name, titel=aufruf.name, argumente=aufruf.argumente, herkunft="modellwahl", fehler=text, runde=runde
                    )
                )
                nachrichten.append(Nachricht("tool", text, werkzeugaufruf_id=aufruf.id))
                continue
            kennung, b = eintrag
            stellen, protokoll = await ausfuehrung.einzeln(
                session,
                kennung,
                aufruf.argumente,
                zeitgrenze_s=werkzeug_zeitgrenze_s,
                ergebnis_zeichen=ergebnis_zeichen,
                herkunft="modellwahl",
                runde=runde,
            )
            ergebnis.aufrufe.append(protokoll)
            if protokoll.fehler and not stellen:
                nachrichten.append(Nachricht("tool", f"Fehler: {protokoll.fehler}", werkzeugaufruf_id=aufruf.id))
                ergebnis.hinweise.append(f"Werkzeug {b.titel}: {protokoll.fehler}")
                continue
            # Nummern vergeben und dem Modell die Stellen mit Nummern zeigen
            start_nr = len(alle_stellen) + 1
            alle_stellen.extend(stellen)
            ergebnis.stellen.extend(stellen)
            block = "\n\n".join(prompts.stelle_als_kontext(start_nr + i, s) for i, s in enumerate(stellen))
            nachrichten.append(Nachricht("tool", block or "(kein Text)", werkzeugaufruf_id=aufruf.id))
        if runde == max_runden:
            ergebnis.hinweise.append(f"Höchstzahl von {max_runden} Werkzeugrunden erreicht; jetzt wird geantwortet.")
    return ergebnis
