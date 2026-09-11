"""Schnittstelle einer Videoquelle und ihre Datenträger.

Abgleich und Oberfläche programmieren nur gegen `VideoQuelle`. Welche Umsetzung
dahintersteht (TubeVault, später andere), entscheidet `abgleich.baue_quelle` anhand
des Typs der Quelle in der Datenbank. Die Datenträger tragen die Felder, die die
Tabelle videos braucht, plus den rohen Eintrag der Quelle (Herkunft bleibt vollständig).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


class QuellenFehler(RuntimeError):
    """Die Quelle konnte nicht antworten (Netz, Fehlerkörper, unerwartete Struktur)."""


@dataclass(slots=True)
class Kanalinfo:
    """Kanaldetail der Quelle."""

    kanal_id: str
    name: str
    beschreibung: str = ""
    videos_gesamt: int | None = None
    videos_heruntergeladen: int | None = None
    banner_url: str = ""
    roh: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class QuellVideo:
    """Ein Video, wie die Quelle es liefert - bereits in unsere Feldnamen übersetzt."""

    extern_id: str
    titel: str
    beschreibung: str = ""
    veroeffentlicht: datetime | None = None
    dauer_s: int | None = None
    typ: str = "video"
    aufrufe: int | None = None
    schlagworte: list[str] = field(default_factory=list)
    kanal_name: str = ""
    miniatur_url: str = ""
    heruntergeladen: bool = False
    roh: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Videodetail:
    """Volles Video-Objekt der Quelle, gedeutet plus roh."""

    schlagworte: list[str] = field(default_factory=list)
    roh: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Videoseite:
    """Eine Seite der Kanalvideos samt Gesamtzahl."""

    videos: list[QuellVideo]
    gesamt: int
    seite: int
    je_seite: int


class VideoQuelle(Protocol):
    """Was eine Videoquelle können muss."""

    async def kanal(self) -> Kanalinfo:
        """Kanaldetail (Name, Beschreibung, Zähler). Wirft QuellenFehler."""
        ...

    async def videoseite(self, seite: int, je_seite: int) -> Videoseite:
        """Eine Seite der Kanalvideos, Seiten ab 1. Wirft QuellenFehler."""
        ...

    async def videodetail(self, extern_id: str) -> Videodetail | None:
        """Volles Video-Objekt der Quelle oder None, wenn die Quelle keines hat."""
        ...

    async def miniatur(self, extern_id: str) -> bytes:
        """Vorschaubild als Bilddaten. Wirft QuellenFehler."""
        ...

    async def schliessen(self) -> None:
        """Verbindungen freigeben."""
        ...


async def alle_seiten(quelle: VideoQuelle, je_seite: int) -> AsyncIterator[Videoseite]:
    """Läuft alle Seiten der Kanalvideos durch.

    Bricht nach der Zahl der gesehenen Videos ab, nicht nach Seitenarithmetik: so bleibt
    der Lauf richtig, wenn die Quelle die Seitengröße stillschweigend deckelt. Liefert
    eine Seite keine neue Kennung, ist die Seitenzählung der Quelle kaputt - dann lieber
    ein Fehler als eine Endlosschleife.
    """
    gesehen: set[str] = set()
    seite_nr = 1
    while True:
        seite = await quelle.videoseite(seite_nr, je_seite)
        if not seite.videos:
            return
        neue = {v.extern_id for v in seite.videos} - gesehen
        if not neue:
            raise QuellenFehler(f"Die Quelle liefert auf Seite {seite_nr} nur bereits bekannte Videos - Seitenlauf abgebrochen")
        gesehen.update(neue)
        yield seite
        if len(gesehen) >= seite.gesamt:
            return
        seite_nr += 1
