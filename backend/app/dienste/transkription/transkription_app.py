"""Transkription über die App Transkription (Dienstweg über die Kellerwolke).

Ablauf je Datei, wie andere Apps im Verbund es tun: die Aufnahme kommt in den Durchgangsordner der eigenen App
(`Apps/<App>/Dienst`), die Kellerwolke gibt die Anfrage "transkribieren" an die Transkription weiter, und das
Transkript (`transkript/1`) erscheint als Begleitdatei neben der Aufnahme. Danach wandern Aufnahme und Transkript in den
Papierkorb der Kellerwolke (wiederherstellbar); das Ergebnis behält morf-gpt in der eigenen Datenbank.

Angemeldet wird mit dem App-Schlüssel der Kellerwolke (`MORF_KELLERWOLKE_SCHLUESSEL`), nie über die Oberfläche.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from .basis import (
    Segment,
    TranskriptErgebnis,
    TranskriptionsFehler,
    Wortzeit,
    audiodatei_pruefen,
    fehlertext_aus_antwort,
    mime_typ_fuer,
    volltext_aus_segmenten,
)

# Whisper-Sprachnamen (Einstellung transkription.sprache) auf die Kürzel der Transkription
SPRACHEN = {"german": "de", "english": "en", "french": "fr", "spanish": "es", "italian": "it", "dutch": "nl"}
KUERZEL = set(SPRACHEN.values()) | {"auto"}
TAKT_S = 5.0


def sprachkuerzel(sprache: str) -> str:
    s = (sprache or "").strip().lower()
    return s if s in KUERZEL else SPRACHEN.get(s, "auto")


def ergebnis_aus_transkript(t: dict[str, Any], wortzeiten_behalten: bool, engine: str) -> TranskriptErgebnis:
    """Ein Transkript im Format `transkript/1` in die Form von morf-gpt."""
    if t.get("format") != "transkript/1":
        raise TranskriptionsFehler(f"Transkription: unbekanntes Format {t.get('format')!r}")
    segmente: list[Segment] = []
    for s in t.get("segmente") or []:
        text = str(s.get("text") or "").strip()
        if not text:
            continue
        woerter = [Wortzeit(wort=str(w.get("wort") or ""), start=float(w.get("start") or 0), end=float(w.get("ende") or 0))
                   for w in s.get("woerter") or []] if wortzeiten_behalten else []
        segmente.append(Segment(start=float(s.get("start") or 0), end=float(s.get("ende") or 0), text=text, woerter=woerter))
    erzeugt = t.get("erzeugt_mit") or {}
    return TranskriptErgebnis(text=volltext_aus_segmenten(segmente), segmente=segmente, sprache=str(t.get("sprache") or ""),
                              modell=str(erzeugt.get("modell") or erzeugt.get("dienst") or ""), engine=engine)


class TranskriptionApp:
    """Engine "transkription": die App Transkription über die Kellerwolke."""

    kennung: str = "transkription"

    def __init__(
        self,
        kellerwolke_url: str,
        schluessel: str,
        app: str = "Transkription",
        ca: str = "",
        wortzeiten_behalten: bool = True,
        verbindungs_zeitgrenze_s: float = 20.0,
        takt_s: float = TAKT_S,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._basis = kellerwolke_url.rstrip("/") + "/api/v1/ablage"
        self._schluessel = schluessel
        self._app = app
        self._ca = ca
        self._wortzeiten_behalten = wortzeiten_behalten
        self._verbindung_s = verbindungs_zeitgrenze_s
        self._takt_s = takt_s
        self._transport = transport  # nur für Tests (httpx.MockTransport)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._basis, transport=self._transport, verify=self._ca or True,
                                 timeout=httpx.Timeout(300.0, connect=self._verbindung_s),
                                 headers={"Authorization": f"Bearer {self._schluessel}"})

    @staticmethod
    def _pruefen(antwort: httpx.Response, was: str) -> httpx.Response:
        if antwort.status_code >= 400:
            raise TranskriptionsFehler(f"Kellerwolke ({was}): {fehlertext_aus_antwort(antwort)}")
        return antwort

    async def transkribiere(self, pfad: Path, sprache: str, zeitgrenze_s: float) -> TranskriptErgebnis:
        audiodatei_pruefen(pfad)
        if not self._schluessel:
            raise TranskriptionsFehler("Transkription: kein App-Schlüssel der Kellerwolke (MORF_KELLERWOLKE_SCHLUESSEL in der .env)")
        frist = time.monotonic() + zeitgrenze_s
        try:
            async with self._client() as c:
                ich = self._pruefen(await c.get("/ich"), "anmelden").json()
                ordner = f"Apps/{ich['app']}/Dienst"
                self._pruefen(await c.post("/ordner", json={"pfad": ordner}), "Ordner anlegen")
                ziel = f"{ordner}/{pfad.stem}-{uuid.uuid4().hex[:8]}{pfad.suffix}"
                haupt = self._pruefen(await c.put("/datei", params={"pfad": ziel}, content=pfad.read_bytes(),
                                                  headers={"Content-Type": mime_typ_fuer(pfad), "If-None-Match": "*"}),
                                      "hochladen").json()
                try:
                    return await self._abwarten(c, haupt["id"], sprachkuerzel(sprache), frist, zeitgrenze_s)
                finally:
                    try:
                        await c.delete(f"/knoten/{haupt['id']}")   # Papierkorb, Begleiter ziehen mit
                    except httpx.HTTPError:
                        pass
        except httpx.HTTPError as e:
            raise TranskriptionsFehler(f"Kellerwolke nicht erreichbar ({e.__class__.__name__})") from e

    async def _abwarten(self, c: httpx.AsyncClient, haupt_id: str, sprache: str, frist: float,
                        zeitgrenze_s: float) -> TranskriptErgebnis:
        neu = self._pruefen(await c.post("/anfragen", json={"app": self._app, "aktion": "transkribieren",
                                                            "knoten_id": haupt_id, "optionen": {"sprache": sprache}}),
                            "an die Transkription weitergeben").json()
        anfrage_id = neu["anfrage"]["id"]
        while True:
            begleiter = self._pruefen(await c.get(f"/knoten/{haupt_id}/begleiter"), "Begleiter").json()
            transkript = next((b for b in begleiter if b.get("rolle") == "transkript"), None)
            if transkript is not None:
                inhalt = self._pruefen(await c.get(f"/knoten/{transkript['id']}/inhalt"), "Transkript lesen").content
                try:
                    return ergebnis_aus_transkript(json.loads(inhalt), self._wortzeiten_behalten, self.kennung)
                except ValueError as e:
                    raise TranskriptionsFehler("Transkription: Transkript ist kein JSON") from e
            anfrage = self._pruefen(await c.get(f"/anfragen/{anfrage_id}"), "Anfrage").json()
            if anfrage.get("zustand") in ("fehler", "abgebrochen"):
                raise TranskriptionsFehler(f"Transkription: {anfrage.get('meldung') or anfrage.get('zustand')}")
            if time.monotonic() >= frist:
                raise TranskriptionsFehler(f"Transkription: Zeitgrenze von {int(zeitgrenze_s)} Sekunden überschritten")
            await asyncio.sleep(self._takt_s)

    async def erreichbar(self) -> tuple[bool, str]:
        if not self._schluessel:
            return False, "kein App-Schlüssel (MORF_KELLERWOLKE_SCHLUESSEL)"
        try:
            async with self._client() as c:
                antwort = await c.get("/ich")
        except httpx.HTTPError as e:
            return False, f"nicht erreichbar ({e.__class__.__name__})"
        if antwort.status_code != 200:
            return False, fehlertext_aus_antwort(antwort)
        return True, f"angemeldet als App {antwort.json().get('app')}"
