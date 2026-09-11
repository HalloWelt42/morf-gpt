"""Chat-Orchestrierung: Frage speichern, Stellen suchen (oder bestätigte laden), Stellen
melden, Antwort streamen, Antwort speichern. Ein Generator liefert die Ereignisse
(treffer, delta, fertig, fehler) für die SSE-Route.

Die Datenbank wird nur kurz gehalten (vor und nach dem Streamen), damit eine lange
Antwort keine Verbindung blockiert.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import select

from ...db.engine import sitzung
from ...db.modelle import Korrektur, Nachricht, Unterhaltung
from ..anbieter import dienst as anbieter_dienst
from ..anbieter.basis import AnbieterFehler, Antwortparameter
from ..einstellungen import dienst as einstellungen_dienst
from ..suche.retrieval import Suche, Suchergebnis, Suchparameter
from ..suche.retrieval import suche as standard_suche
from ..text import bereinige
from ..werkzeuge import ausfuehrung
from . import prompts, werkzeugschleife

log = logging.getLogger(__name__)

TITEL_ZEICHEN = 60


def titel_aus_frage(frage: str) -> str:
    t = " ".join(frage.split())
    return t if len(t) <= TITEL_ZEICHEN else t[: TITEL_ZEICHEN - 1].rstrip() + "…".replace("…", "...")


class ChatFehler(RuntimeError):
    pass


class Orchestrierung:
    def __init__(self, suche: Suche = standard_suche) -> None:
        self._suche = suche

    async def frage_stellen(
        self,
        unterhaltung_id: str,
        frage: str,
        parameter: dict[str, Any] | None = None,
        chunk_ids: list[str] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Ereignisse: {"art": "treffer"|"delta"|"fertig"|"fehler", ...}."""
        frage = frage.strip()
        if not frage:
            yield {"art": "fehler", "text": "Die Frage ist leer."}
            return
        start = time.monotonic()
        nutzer_id = ""
        try:
            async with sitzung() as s:
                u = await s.get(Unterhaltung, unterhaltung_id)
                if u is None:
                    raise ChatFehler("Die Unterhaltung existiert nicht")
                werte = await einstellungen_dienst.alle(s)
                p = Suchparameter.aus_einstellungen(werte, u.suchparameter, parameter or {})
                anzahl = await s.scalar(select(Nachricht.id).where(Nachricht.unterhaltung_id == u.id).limit(1))
                if anzahl is None and u.titel == "Neue Unterhaltung":
                    u.titel = titel_aus_frage(frage)
                u.suchparameter = {
                    **p.als_dict(),
                    "werkzeuge": self._werkzeug_kennungen(parameter, u.suchparameter),
                    "werkzeugwahl": (parameter or {}).get("werkzeugwahl") or (u.suchparameter or {}).get("werkzeugwahl"),
                }
                nutzer = Nachricht(unterhaltung_id=u.id, rolle="nutzer", inhalt=frage, parameter=p.als_dict())
                s.add(nutzer)
                await s.flush()
                nutzer_id = nutzer.id

                if chunk_ids:
                    ergebnis: Suchergebnis = await self._suche.laden(s, chunk_ids, p)
                else:
                    ergebnis = await self._suche.suchen(s, frage, p)

                verlauf = await self._verlauf(s, u.id, int(werte["chat.verlauf_nachrichten"]), ohne=nutzer_id)
                zusammenfassungen = (
                    await self._zusammenfassungen(s, [t.video_id for t in ergebnis.stellen]) if werte["chat.videoebene"] else {}
                )
                anbieter_zeile = await anbieter_dienst.anbieter_fuer_rolle(s, "chat")
                anbieter = anbieter_dienst.baue_sprachmodell(anbieter_zeile)
                antwortparameter = Antwortparameter(
                    temperatur=float(werte["chat.temperatur"]),
                    max_tokens=int(werte["chat.max_tokens"]),
                    zeitgrenze_s=float(werte["chat.zeitgrenze_s"]),
                )
                await s.commit()

                # Werkzeuge: gewählte Kennungen aus der Anfrage (Vorrang) oder der Unterhaltung
                kennungen = self._werkzeug_kennungen(parameter, u.suchparameter)
                werkzeugwahl = str((parameter or {}).get("werkzeugwahl") or werte["chat.werkzeugwahl"])
                aufrufe: list[dict[str, Any]] = []
                alle_stellen = list(ergebnis.stellen)
                schleife: werkzeugschleife.Schleifenergebnis | None = None
                if kennungen and werkzeugwahl == "nutzer":
                    lauf = await ausfuehrung.fuer_frage(
                        s,
                        kennungen,
                        frage,
                        anbieter=anbieter,
                        argumente_per_modell=bool(werte["werkzeuge.argumente_per_modell"]),
                        zeitgrenze_s=float(werte["werkzeuge.zeitgrenze_s"]),
                        ergebnis_zeichen=int(werte["werkzeuge.ergebnis_zeichen"]),
                    )
                    alle_stellen.extend(lauf.stellen)
                    ergebnis.hinweise.extend(lauf.hinweise)
                    aufrufe = [a.als_dict() for a in lauf.aufrufe]
                elif kennungen and werkzeugwahl == "modell":
                    schleife = await werkzeugschleife.laufe(
                        s,
                        anbieter,
                        frage,
                        ergebnis.stellen,
                        verlauf,
                        zusammenfassungen,
                        kennungen,
                        max_runden=int(werte["werkzeuge.max_runden"]),
                        zeitgrenze_s=float(werte["chat.zeitgrenze_s"]),
                        werkzeug_zeitgrenze_s=float(werte["werkzeuge.zeitgrenze_s"]),
                        ergebnis_zeichen=int(werte["werkzeuge.ergebnis_zeichen"]),
                        temperatur=float(werte["chat.temperatur"]),
                    )
                    alle_stellen.extend(schleife.stellen)
                    ergebnis.hinweise.extend(schleife.hinweise)
                    aufrufe = [a.als_dict() for a in schleife.aufrufe]

            stellen_dicts = [t.als_dict() for t in alle_stellen]
            yield {
                "art": "treffer",
                "nachricht_id": nutzer_id,
                "stellen": stellen_dicts,
                "hinweise": ergebnis.hinweise,
                "einbettungsmodell": ergebnis.einbettungsmodell,
                "neubewertung": ergebnis.neubewertung,
                "parameter": p.als_dict(),
                "werkzeugaufrufe": aufrufe,
                "werkzeugwahl": werkzeugwahl,
                "unterhaltung_titel": None,
            }

            if schleife is not None and schleife.unterstuetzt and schleife.aufrufe:
                # Antwort mit allen Werkzeug-Zwischenschritten im Kontext streamen
                nachrichten = schleife.nachrichten
            else:
                nachrichten = prompts.baue_nachrichten(frage, alle_stellen, verlauf, zusammenfassungen)
            text_teile: list[str] = []
            modell = anbieter.info.modell
            tokens_ein: int | None = None
            tokens_aus: int | None = None
            async for delta in anbieter.streame(nachrichten, antwortparameter):
                if delta.fertig:
                    modell = delta.modell or modell
                    tokens_ein, tokens_aus = delta.tokens_ein, delta.tokens_aus
                    break
                stueck = bereinige(delta.text)
                text_teile.append(stueck)
                yield {"art": "delta", "text": stueck}

            inhalt = "".join(text_teile).strip()
            dauer_ms = int((time.monotonic() - start) * 1000)
            async with sitzung() as s:
                antwort = Nachricht(
                    unterhaltung_id=unterhaltung_id,
                    rolle="assistent",
                    inhalt=inhalt,
                    stellen=stellen_dicts,
                    parameter={
                        **p.als_dict(),
                        "chunk_ids": chunk_ids or [],
                        "hinweise": ergebnis.hinweise,
                        "werkzeuge": kennungen,
                        "werkzeugwahl": werkzeugwahl,
                        "werkzeugaufrufe": aufrufe,
                    },
                    modell=modell,
                    dauer_ms=dauer_ms,
                    tokens_ein=tokens_ein,
                    tokens_aus=tokens_aus,
                )
                s.add(antwort)
                u = await s.get(Unterhaltung, unterhaltung_id)
                titel = u.titel if u else ""
                await s.commit()
                antwort_id = antwort.id
            yield {
                "art": "fertig",
                "nachricht_id": antwort_id,
                "modell": modell,
                "dauer_ms": dauer_ms,
                "tokens_ein": tokens_ein,
                "tokens_aus": tokens_aus,
                "unterhaltung_titel": titel,
            }
        except (AnbieterFehler, ChatFehler, ValueError, RuntimeError) as e:
            log.warning("Chat-Fehler: %s", e)
            async with sitzung() as s:
                s.add(Nachricht(unterhaltung_id=unterhaltung_id, rolle="assistent", inhalt="", fehler=str(e), parameter=(parameter or {})))
                await s.commit()
            yield {"art": "fehler", "text": str(e)}

    @staticmethod
    def _werkzeug_kennungen(parameter: dict[str, Any] | None, gespeichert: dict[str, Any] | None) -> list[str]:
        """Gewählte Werkzeuge: aus der Anfrage, sonst aus der Unterhaltung; immer eine Liste von Texten."""
        quelle: Any = None
        if parameter is not None and "werkzeuge" in parameter:
            quelle = parameter.get("werkzeuge")
        elif gespeichert:
            quelle = gespeichert.get("werkzeuge")
        if not isinstance(quelle, list):
            return []
        return [str(k) for k in quelle if str(k).strip()]

    async def _verlauf(self, s: Any, unterhaltung_id: str, anzahl: int, ohne: str) -> list[prompts.Verlaufsnachricht]:
        if anzahl <= 0:
            return []
        rows = (
            (
                await s.execute(
                    select(Nachricht)
                    .where(Nachricht.unterhaltung_id == unterhaltung_id, Nachricht.id != ohne, Nachricht.fehler == "")
                    .order_by(Nachricht.erstellt.desc())
                    .limit(anzahl)
                )
            )
            .scalars()
            .all()
        )
        aus: list[prompts.Verlaufsnachricht] = []
        for n in reversed(rows):
            if not n.inhalt.strip():
                continue
            aus.append(prompts.Verlaufsnachricht("user" if n.rolle == "nutzer" else "assistant", n.inhalt))
        return aus

    async def _zusammenfassungen(self, s: Any, video_ids: list[str]) -> dict[str, str]:
        ids = list({v for v in video_ids if v})
        if not ids:
            return {}
        rows = (
            await s.execute(
                select(Korrektur.video_id, Korrektur.zusammenfassung).where(Korrektur.video_id.in_(ids), Korrektur.aktuell.is_(True))
            )
        ).all()
        return {vid: zf for vid, zf in rows if zf}


orchestrierung = Orchestrierung()
