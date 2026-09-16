"""Einbettungsdienst: Einbettungstext mit Kontextkopf, Stapelverarbeitung, Frage einbetten.

Der Index gehört zu genau einer Modellfamilie (siehe familie.py); die Suche fragt mit einem
Modell derselben Familie, auch wenn ein anderer Anbieter es anders nennt. Die Dimension
wird gegen die Konfiguration geprüft (Spalte vector(N)).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import einstellungen
from ...db.engine import sitzung
from ...db.modelle import Chunk, Dokument, Einbettung, Video
from ..anbieter import dienst as anbieter_dienst
from ..anbieter.basis import AnbieterFehler, EinbettungsAnbieter
from ..einstellungen import dienst as einstellungen_dienst
from .familie import gleiche_familie

Fortschrittsmelder = Callable[[float, str], Awaitable[None]]


@dataclass(slots=True)
class Einbettungsergebnis:
    anzahl: int
    modell: str
    anbieter: str
    dimension: int


def einbettungstext(titel: str, thema: str, text: str, kontextkopf: bool, werk: str = "Video") -> str:
    """Der Text, der eingebettet wird: bei Kontextkopf mit Werk (Video oder Dokument), Titel und Thema davor."""
    if not kontextkopf:
        return text
    kopf = f"{werk}: {titel.strip()}" if titel.strip() else werk
    if thema.strip():
        kopf = f"{kopf} | Thema: {thema.strip()}"
    return f"{kopf}\n{text}"


def dimension_pruefen(vektoren: list[list[float]], anbieter_name: str) -> int:
    erwartet = einstellungen.einbettung_dimension
    for v in vektoren:
        if len(v) != erwartet:
            raise AnbieterFehler(
                f"{anbieter_name} liefert Vektoren mit {len(v)} Dimensionen, der Index erwartet {erwartet}. "
                "Anbieter oder Modell passen nicht zur Datenbankspalte."
            )
    return erwartet


async def frage_einbetten(session: AsyncSession, text: str) -> tuple[list[float], str]:
    """Bettet eine Frage mit dem aktiven Anbieter ein: (Vektor, Modellname)."""
    zeile = await anbieter_dienst.anbieter_fuer_rolle(session, "einbettung")
    anbieter = anbieter_dienst.baue_einbettung(zeile)
    zeitgrenze = float(await einstellungen_dienst.wert(session, "einbettung.zeitgrenze_s"))
    vektoren = await anbieter.einbetten([text], zeitgrenze_s=zeitgrenze)
    dimension_pruefen(vektoren, zeile.name)
    return vektoren[0], anbieter.info.modell


async def aktiver_einbetter(session: AsyncSession) -> tuple[EinbettungsAnbieter, str]:
    zeile = await anbieter_dienst.anbieter_fuer_rolle(session, "einbettung")
    return anbieter_dienst.baue_einbettung(zeile), zeile.name


def _stapel(liste: list[Chunk], groesse: int) -> list[list[Chunk]]:
    groesse = max(1, groesse)
    return [liste[i : i + groesse] for i in range(0, len(liste), groesse)]


def instanzen_verteilung(stapel: list[list[Chunk]], kennungen: list[str | None]) -> list[tuple[list[Chunk], str | None]]:
    """Stapel im Wechsel auf die Instanzkennungen verteilen (None = eingestelltes Modell)."""
    return [(s, kennungen[i % len(kennungen)]) for i, s in enumerate(stapel)]


async def chunks_einbetten(
    video_id: str | None,
    werte: dict[str, Any],
    *,
    dokument_id: str | None = None,
    nur_chunk_ids: list[str] | None = None,
    instanzen: list[str] | None = None,
    fortschritt: Fortschrittsmelder | None = None,
    abbruch: asyncio.Event | None = None,
) -> Einbettungsergebnis:
    """Bettet die Chunks eines Werks (oder eine Auswahl) ein und schreibt die Vektoren.

    Stapel gehen gleichzeitig an die übergebenen Instanzen (Kennungen beim Dienst; leer heißt
    nur das eingestellte Modell). Vorhandene Vektoren desselben Modells werden ersetzt; jeder
    Stapel wird sofort gespeichert, damit ein Abbruch nichts Fertiges verliert.
    """
    async with sitzung() as s:
        anbieter, anbieter_name = await aktiver_einbetter(s)
        if dokument_id:
            dokument = await s.get(Dokument, dokument_id)
            titel = dokument.titel if dokument else ""
            werk = "Dokument"
            q = select(Chunk).where(Chunk.dokument_id == dokument_id).order_by(Chunk.reihenfolge)
        else:
            video = await s.get(Video, video_id) if video_id else None
            titel = video.titel if video else ""
            werk = "Video"
            q = select(Chunk).where(Chunk.video_id == video_id).order_by(Chunk.reihenfolge)
        if nur_chunk_ids:
            q = q.where(Chunk.id.in_(nur_chunk_ids))
        chunks = list((await s.execute(q)).scalars().all())
    if not chunks:
        raise RuntimeError("Keine Stücke zum Einbetten vorhanden - erst stückeln")

    kontextkopf = bool(werte["stueckelung.kontextkopf"])
    stapelgroesse = int(werte["einbettung.stapel"])
    zeitgrenze = float(werte["einbettung.zeitgrenze_s"])
    modell = anbieter.info.modell
    async with sitzung() as s:
        vorhandene = (await s.execute(select(Einbettung.modell).distinct())).scalars().all()
    familie_namen = [n for n in vorhandene if gleiche_familie(n, modell)] + [modell]
    dimension = einstellungen.einbettung_dimension
    stapel = _stapel(chunks, stapelgroesse)
    # Instanzen (nur LM Studio) und gleichzeitige Anfragen: Stapel werden im Wechsel verteilt
    # und je Instanz bis zur eingestellten Zahl gleichzeitig geschickt.
    instanzen_kennungen = instanzen or [None]
    gleichzeitig = max(1, int(werte.get("einbettung.anfragen_je_instanz", 1))) * len(instanzen_kennungen)
    schleuse = asyncio.Semaphore(gleichzeitig)
    fertig = 0
    fortschritt_sperre = asyncio.Lock()

    async def _ein_stapel(nr: int, gruppe: list[Chunk], kennung: str | None) -> None:
        nonlocal fertig, dimension
        async with schleuse:
            if abbruch is not None and abbruch.is_set():
                raise asyncio.CancelledError()
            texte = [einbettungstext(titel, c.thema, c.text, kontextkopf, werk) for c in gruppe]
            vektoren = await anbieter.einbetten(texte, zeitgrenze_s=zeitgrenze, instanz=kennung)
            if len(vektoren) != len(gruppe):
                raise AnbieterFehler(f"{anbieter_name}: {len(vektoren)} Vektoren für {len(gruppe)} Stücke")
            dimension = dimension_pruefen(vektoren, anbieter_name)
            async with sitzung() as s:
                # Alte Vektoren derselben Familie weichen (auch unter dem Namen eines anderen Anbieters)
                kennungen = [c.id for c in gruppe]
                await s.execute(delete(Einbettung).where(Einbettung.chunk_id.in_(kennungen), Einbettung.modell.in_(familie_namen)))
                for c, v in zip(gruppe, vektoren, strict=True):
                    s.add(Einbettung(chunk_id=c.id, anbieter=anbieter_name, modell=modell, dimension=dimension, vektor=v))
                await s.commit()
            async with fortschritt_sperre:
                fertig += len(gruppe)
                if fortschritt is not None:
                    await fortschritt(
                        0.05 + 0.9 * (fertig / len(chunks)),
                        f"Stapel {nr} von {len(stapel)}: {fertig} von {len(chunks)} Stücken eingebettet"
                        + (f" ({len(instanzen_kennungen)} Instanzen)" if len(instanzen_kennungen) > 1 else ""),
                    )

    verteilt = [
        (nr, gruppe, kennung)
        for nr, (gruppe, kennung) in enumerate(
            zip(stapel, [k for _, k in instanzen_verteilung(stapel, instanzen_kennungen)], strict=True), start=1
        )
    ]
    await asyncio.gather(*(_ein_stapel(nr, gruppe, kennung) for nr, gruppe, kennung in verteilt))
    return Einbettungsergebnis(anzahl=fertig, modell=modell, anbieter=anbieter_name, dimension=dimension)
