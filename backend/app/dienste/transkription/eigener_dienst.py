"""Transkription über den eigenen Dienst des Projekts (hilfsdienste/transkription).

Der Dienst nimmt die Audiodatei als multipart entgegen (Felder datei, sprache, wortzeiten),
gibt sie einem seiner Arbeiter und blockiert bis zum Ende - bei langen Videos viele
Minuten. Darum: die Datei wird aus dem Dateiobjekt gestreamt, das Lese-Timeout ist gleich
der Zeitgrenze, die Zeitgrenze gilt als Gesamtdauer des Aufrufs. Daneben liefert der Dienst
seinen Stand (Arbeiter, Speicher) und passt die Zahl der Arbeiter auf Wunsch an; das nutzt
die Stufe Transkription vor jedem Auftrag.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx

from .basis import (
    TranskriptErgebnis,
    TranskriptionsFehler,
    audiodatei_pruefen,
    fehlertext_aus_antwort,
    mime_typ_fuer,
    segmente_aus_json,
    volltext_aus_segmenten,
    zeitgrenzen,
)


class EigenerDienst:
    """Engine "morf": der mitgelieferte Transkriptionsdienst (Whisper hinter HTTP, Arbeiterpool)."""

    kennung: str = "morf"

    def __init__(
        self,
        basis_url: str,
        wortzeiten_behalten: bool = True,
        verbindungs_zeitgrenze_s: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._basis = basis_url.rstrip("/")
        self._wortzeiten_behalten = wortzeiten_behalten
        self._verbindung_s = verbindungs_zeitgrenze_s
        self._transport = transport  # nur für Tests (httpx.MockTransport)

    @property
    def basis_url(self) -> str:
        return self._basis

    def _name(self) -> str:
        return f"morf-Transkription ({self._basis})"

    def _client(self, gesamt_s: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=zeitgrenzen(gesamt_s, self._verbindung_s), transport=self._transport)

    # ------------------------------------------------------------------ Transkription
    async def transkribiere(self, pfad: Path, sprache: str, zeitgrenze_s: float) -> TranskriptErgebnis:
        audiodatei_pruefen(pfad)
        daten = await self._sende(pfad, sprache, zeitgrenze_s)
        return self._ergebnis(daten, sprache)

    async def _sende(self, pfad: Path, sprache: str, zeitgrenze_s: float) -> dict[str, Any]:
        felder = {"sprache": sprache, "wortzeiten": "true" if self._wortzeiten_behalten else "false"}
        try:
            async with asyncio.timeout(zeitgrenze_s):
                with pfad.open("rb") as datei:
                    async with self._client(zeitgrenze_s) as client:
                        resp = await client.post(
                            f"{self._basis}/transkription", data=felder, files={"datei": (pfad.name, datei, mime_typ_fuer(pfad))}
                        )
        except (TimeoutError, httpx.TimeoutException) as e:
            raise TranskriptionsFehler(f"{self._name()}: Zeitgrenze von {int(zeitgrenze_s)} Sekunden überschritten") from e
        except httpx.HTTPError as e:
            raise TranskriptionsFehler(f"{self._name()}: nicht erreichbar ({e.__class__.__name__})") from e
        return self._json(resp)

    def _json(self, resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code != 200:
            raise TranskriptionsFehler(f"{self._name()}: {fehlertext_aus_antwort(resp)}")
        try:
            daten = resp.json()
        except ValueError as e:
            raise TranskriptionsFehler(f"{self._name()}: Antwort ist kein JSON") from e
        if not isinstance(daten, dict):
            raise TranskriptionsFehler(f"{self._name()}: unerwartete Antwortform")
        return daten

    def _ergebnis(self, daten: dict[str, Any], sprache: str) -> TranskriptErgebnis:
        if "text" not in daten and "segmente" not in daten:
            raise TranskriptionsFehler(f"{self._name()}: Antwort enthält weder Text noch Segmente")
        segmente = segmente_aus_json(daten.get("segmente"), self._wortzeiten_behalten)
        text = str(daten.get("text") or "").strip() or volltext_aus_segmenten(segmente)
        return TranskriptErgebnis(
            text=text,
            segmente=segmente,
            sprache=str(daten.get("sprache") or sprache),
            modell=str(daten.get("modell") or ""),
            engine=self.kennung,
        )

    # ------------------------------------------------------------------ Zustand und Arbeiter
    async def erreichbar(self) -> tuple[bool, str]:
        try:
            async with self._client(self._verbindung_s) as client:
                resp = await client.get(f"{self._basis}/health")
        except httpx.HTTPError as e:
            return False, f"nicht erreichbar ({e.__class__.__name__})"
        if resp.status_code != 200:
            return False, fehlertext_aus_antwort(resp)
        try:
            daten = resp.json()
        except ValueError:
            return False, "Antwort ist kein JSON"
        status = str(daten.get("status") or "")
        if status == "ok":
            return True, f"erreichbar, {int(daten.get('arbeiter') or 0)} Arbeiter bereit ({daten.get('engine')}, {daten.get('modell')})"
        if status == "laedt":
            return True, "erreichbar, das Modell lädt noch"
        return False, f"meldet Zustand '{status or 'unbekannt'}'"

    async def stand(self) -> dict[str, Any]:
        """Stand des Dienstes: engine, modell, gewuenscht, maximum, arbeiter, wartend, speicher, hinweise."""
        try:
            async with self._client(self._verbindung_s) as client:
                resp = await client.get(f"{self._basis}/stand")
        except httpx.HTTPError as e:
            raise TranskriptionsFehler(f"{self._name()}: nicht erreichbar ({e.__class__.__name__})") from e
        return self._json(resp)

    async def arbeiter_setzen(self, anzahl: int, zeitgrenze_s: float = 1800.0) -> dict[str, Any]:
        """Bringt die Arbeiter des Dienstes auf die gewünschte Zahl (er prüft den Speicher) und gibt den Stand zurück."""
        try:
            async with self._client(zeitgrenze_s) as client:
                resp = await client.post(f"{self._basis}/arbeiter", json={"anzahl": int(anzahl)})
        except httpx.HTTPError as e:
            raise TranskriptionsFehler(f"{self._name()}: nicht erreichbar ({e.__class__.__name__})") from e
        return self._json(resp)
