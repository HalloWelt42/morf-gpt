"""Transkription über die txt2voice-App (POST /api/transcribe/upload).

Anders als der Worker legt die App für jede Datei einen Eintrag in ihrer eigenen
Bibliothek an; das Transkript kommt als Objekt mit `full_text` und `segments`
zurück. Der Aufruf blockiert wie beim Worker bis zum Ende.
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


class Txt2VoiceApp:
    """Engine "txt2voice_api": Upload-Weg über die txt2voice-Oberfläche."""

    kennung: str = "txt2voice_api"

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

    def _name(self) -> str:
        return f"txt2voice-App ({self._basis})"

    async def transkribiere(self, pfad: Path, sprache: str, zeitgrenze_s: float) -> TranskriptErgebnis:
        audiodatei_pruefen(pfad)
        daten = await self._sende(pfad, sprache, zeitgrenze_s)
        return self._ergebnis(daten, sprache)

    async def _sende(self, pfad: Path, sprache: str, zeitgrenze_s: float) -> dict[str, Any]:
        # Der Name erscheint in der Bibliothek der App; der Dateistamm ist die Video-Kennung.
        felder = {"language": sprache, "name": pfad.stem}
        try:
            async with asyncio.timeout(zeitgrenze_s):
                with pfad.open("rb") as datei:
                    async with httpx.AsyncClient(
                        timeout=zeitgrenzen(zeitgrenze_s, self._verbindung_s), transport=self._transport
                    ) as client:
                        resp = await client.post(
                            f"{self._basis}/api/transcribe/upload",
                            data=felder,
                            files={"file": (pfad.name, datei, mime_typ_fuer(pfad))},
                        )
        except (TimeoutError, httpx.TimeoutException) as e:
            raise TranskriptionsFehler(f"{self._name()}: Zeitgrenze von {int(zeitgrenze_s)} Sekunden überschritten") from e
        except httpx.HTTPError as e:
            raise TranskriptionsFehler(f"{self._name()}: nicht erreichbar ({e.__class__.__name__})") from e
        if resp.status_code not in (200, 201):
            raise TranskriptionsFehler(f"{self._name()}: {fehlertext_aus_antwort(resp)}")
        try:
            daten = resp.json()
        except ValueError as e:
            raise TranskriptionsFehler(f"{self._name()}: Antwort ist kein JSON") from e
        if not isinstance(daten, dict):
            raise TranskriptionsFehler(f"{self._name()}: unerwartete Antwortform")
        return daten

    def _ergebnis(self, daten: dict[str, Any], sprache: str) -> TranskriptErgebnis:
        if "full_text" not in daten and "text" not in daten and "segments" not in daten:
            raise TranskriptionsFehler(f"{self._name()}: Antwort enthält weder Text noch Segmente")
        segmente = segmente_aus_json(daten.get("segments"), self._wortzeiten_behalten)
        text = str(daten.get("full_text") or daten.get("text") or "").strip() or volltext_aus_segmenten(segmente)
        return TranskriptErgebnis(
            text=text,
            segmente=segmente,
            sprache=str(daten.get("language") or sprache),
            modell=str(daten.get("model") or ""),
            engine=self.kennung,
        )

    async def erreichbar(self) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=zeitgrenzen(self._verbindung_s, self._verbindung_s), transport=self._transport) as client:
                resp = await client.get(f"{self._basis}/api/system/health")
        except httpx.HTTPError as e:
            return False, f"nicht erreichbar ({e.__class__.__name__})"
        if resp.status_code != 200:
            return False, fehlertext_aus_antwort(resp)
        return True, "erreichbar"
