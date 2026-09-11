"""TubeVault als Videoquelle: Kanal, Kanalvideos seitenweise, Videodetail, Vorschaubild.

Die Backend-API von TubeVault braucht keinen Schlüssel. Jeder Fehler wird als
`QuellenFehler` mit sprechendem Text gemeldet, nie als nackter HTTP-Code. Die
Übersetzung eines rohen Eintrags in ein `QuellVideo` ist eine reine Funktion und
damit ohne Netz prüfbar.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from .basis import Kanalinfo, QuellenFehler, QuellVideo, Videodetail, Videoseite

TYP_KENNUNG = "tubevault"
TYP_TITEL = "TubeVault"

# Vorgabe, solange die Einstellung 'quelle.zeitgrenze_s' im Register fehlt
# (siehe Bericht, register_ergaenzungen).
ZEITGRENZE_S_VORGABE: float = 60.0
VERBINDUNGSGRENZE_S: float = 10.0

_LISTEN_PARAMETER: dict[str, str] = {
    "include_dismissed": "true",
    "source": "all",
    "video_type": "all",
    "sort": "newest",
}


def datum_parsen(text: Any) -> datetime | None:
    """Zeitangaben der Quelle nach UTC.

    Verstanden werden '2026-09-10 06:16:10' (ohne Zone, gilt als UTC),
    '2020-11-02 15:59:50-08:00' (mit Zone, wird nach UTC umgerechnet) und
    '20201102' (nur der Tag). Alles andere ergibt None statt eines Fehlers, denn ein
    fehlendes Datum darf den Abgleich nicht anhalten.
    """
    if text is None:
        return None
    roh = str(text).strip()
    if not roh:
        return None
    if roh.isdigit() and len(roh) == 8:
        return _tag_parsen(roh)
    try:
        wert = datetime.fromisoformat(roh)
    except ValueError:
        return None
    if wert.tzinfo is None:
        return wert.replace(tzinfo=UTC)
    return wert.astimezone(UTC)


def _tag_parsen(roh: str) -> datetime | None:
    try:
        return datetime.strptime(roh, "%Y%m%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def _ganzzahl(wert: Any) -> int | None:
    if wert is None or wert == "":
        return None
    try:
        return int(float(wert))
    except (TypeError, ValueError):
        return None


def schlagworte_parsen(wert: Any) -> list[str]:
    if not isinstance(wert, list):
        return []
    return [str(w).strip() for w in wert if str(w).strip()]


def video_aus_eintrag(eintrag: dict[str, Any]) -> QuellVideo:
    """Übersetzt einen Listeneintrag der Kanalvideos in ein QuellVideo.

    Titel: `title`, sonst `rss_title`. Datum: `published`, sonst `upload_date`.
    Der rohe Eintrag bleibt vollständig erhalten (Herkunft).
    """
    extern_id = str(eintrag.get("video_id") or "").strip()
    if not extern_id:
        raise QuellenFehler("Ein Videoeintrag der Quelle hat keine Kennung (video_id)")
    titel = str(eintrag.get("title") or eintrag.get("rss_title") or "").strip()
    veroeffentlicht = datum_parsen(eintrag.get("published")) or datum_parsen(eintrag.get("upload_date"))
    return QuellVideo(
        extern_id=extern_id,
        titel=titel,
        beschreibung=str(eintrag.get("description") or ""),
        veroeffentlicht=veroeffentlicht,
        dauer_s=_ganzzahl(eintrag.get("duration")),
        typ=str(eintrag.get("video_type") or "video").strip().lower(),
        aufrufe=_ganzzahl(eintrag.get("view_count")),
        schlagworte=schlagworte_parsen(eintrag.get("tags")),
        kanal_name=str(eintrag.get("channel_name") or ""),
        miniatur_url=str(eintrag.get("thumbnail_url") or ""),
        heruntergeladen=bool(_ganzzahl(eintrag.get("is_downloaded")) or 0),
        roh=dict(eintrag),
    )


def kanal_aus_detail(kanal_id: str, detail: dict[str, Any]) -> Kanalinfo:
    return Kanalinfo(
        kanal_id=str(detail.get("channel_id") or kanal_id),
        name=str(detail.get("channel_name") or ""),
        beschreibung=str(detail.get("channel_description") or ""),
        videos_gesamt=_ganzzahl(detail.get("video_count")),
        videos_heruntergeladen=_ganzzahl(detail.get("downloaded_count")),
        banner_url=str(detail.get("banner_url") or ""),
        roh=dict(detail),
    )


def _fehlertext(resp: httpx.Response) -> str:
    try:
        daten = resp.json()
    except ValueError:
        return resp.text[:300] or f"HTTP {resp.status_code}"
    if isinstance(daten, dict):
        for schluessel in ("detail", "error", "message"):
            if daten.get(schluessel):
                return str(daten[schluessel])[:300]
    return resp.text[:300] or f"HTTP {resp.status_code}"


class TubeVault:
    """Videoquelle über die TubeVault-Backend-API (ein Kanal je Instanz)."""

    def __init__(
        self,
        basis_url: str,
        kanal_id: str,
        zeitgrenze_s: float = ZEITGRENZE_S_VORGABE,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.basis_url = basis_url.rstrip("/")
        self.kanal_id = kanal_id.strip()
        self._client = httpx.AsyncClient(
            base_url=self.basis_url,
            timeout=httpx.Timeout(zeitgrenze_s, connect=VERBINDUNGSGRENZE_S),
            transport=transport,
        )

    async def schliessen(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ Aufrufe
    async def _holen(self, pfad: str, params: dict[str, str] | None = None) -> httpx.Response:
        try:
            return await self._client.get(pfad, params=params)
        except httpx.HTTPError as e:
            raise QuellenFehler(f"{TYP_TITEL} unter {self.basis_url} ist nicht erreichbar ({e.__class__.__name__})") from e

    async def _json(self, pfad: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        resp = await self._holen(pfad, params)
        if resp.status_code != 200:
            raise QuellenFehler(f"{TYP_TITEL} antwortete auf {pfad} mit HTTP {resp.status_code}: {_fehlertext(resp)}")
        try:
            daten = resp.json()
        except ValueError as e:
            raise QuellenFehler(f"{TYP_TITEL} lieferte auf {pfad} keine gültige JSON-Antwort") from e
        if not isinstance(daten, dict):
            raise QuellenFehler(f"{TYP_TITEL} lieferte auf {pfad} eine unerwartete Struktur (kein Objekt)")
        return daten

    # ------------------------------------------------------------------ Schnittstelle
    async def kanal(self) -> Kanalinfo:
        detail = await self._json(f"/api/subscriptions/channel/{self.kanal_id}")
        return kanal_aus_detail(self.kanal_id, detail)

    async def videoseite(self, seite: int, je_seite: int) -> Videoseite:
        if seite < 1:
            raise QuellenFehler("Seiten werden ab 1 gezählt")
        params = {"page": str(seite), "per_page": str(je_seite), **_LISTEN_PARAMETER}
        daten = await self._json(f"/api/subscriptions/channel/{self.kanal_id}/videos", params)
        eintraege = daten.get("videos")
        if not isinstance(eintraege, list):
            raise QuellenFehler(f"{TYP_TITEL} lieferte keine Videoliste (Feld 'videos' fehlt)")
        videos = [video_aus_eintrag(e) for e in eintraege if isinstance(e, dict)]
        gesamt = _ganzzahl(daten.get("total"))
        return Videoseite(
            videos=videos,
            gesamt=gesamt if gesamt is not None else len(videos),
            seite=_ganzzahl(daten.get("page")) or seite,
            je_seite=je_seite,
        )

    async def videodetail(self, extern_id: str) -> Videodetail | None:
        """Nur für heruntergeladene Videos vorhanden; sonst antwortet die Quelle mit 404."""
        resp = await self._holen(f"/api/videos/{extern_id}")
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise QuellenFehler(f"{TYP_TITEL} antwortete auf das Videodetail {extern_id} mit HTTP {resp.status_code}: {_fehlertext(resp)}")
        try:
            daten = resp.json()
        except ValueError as e:
            raise QuellenFehler(f"{TYP_TITEL} lieferte für {extern_id} kein gültiges Videodetail") from e
        if not isinstance(daten, dict):
            return None
        return Videodetail(schlagworte=schlagworte_parsen(daten.get("tags")), roh=dict(daten))

    async def miniatur(self, extern_id: str) -> bytes:
        resp = await self._holen(f"/api/player/{extern_id}/thumbnail")
        if resp.status_code != 200:
            raise QuellenFehler(f"Vorschaubild für {extern_id}: HTTP {resp.status_code} ({_fehlertext(resp)})")
        if not resp.content:
            raise QuellenFehler(f"Vorschaubild für {extern_id}: leere Antwort")
        return resp.content
