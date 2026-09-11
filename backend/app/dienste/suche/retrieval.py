"""Suche über die Bibliothek: Frage einbetten, Kandidaten holen, sieben, ordnen, Nachbarn anfügen.

Ablauf (docs/ARCHITEKTUR.md, Abschnitt 7):

1. Die Frage wird mit demselben Modell eingebettet, das den Index gebaut hat.
2. Cosinus-Suche in pgvector mit Filtern (Serie, Zeitraum, einzelne Videos), dann
   Mindestähnlichkeit und Vielfaltsgrenze je Video.
3. Optional eine Neu-Bewertung der Kandidaten, danach Kürzung auf die gewünschte Trefferzahl.
4. Nachbarstücke werden angefügt und an den Überlappungen entdoppelt.

Alle Datenbankzugriffe liegen hinter kleinen, austauschbaren Funktionen (`FrageEinbetter`,
`KandidatenLader`, `NachbarnLader`, `ChunkLader`), damit die Logik ohne Datenbank prüfbar bleibt.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.modelle import Chunk, Einbettung, Video
from ..einstellungen import register
from .neubewertung import (
    NEUBEWERTUNG_AUS,
    Neubewerter,
    NeubewertungFehler,
    neubewerter_fuer,
)

log = logging.getLogger(__name__)

# Adresse, unter der die Oberfläche ein lokal gespeichertes Vorschaubild abruft. Einziger Ort,
# an dem die Suche diese Route kennt; liefert der Video-Router sie anders, nur hier anpassen.
MINIATUR_ROUTE: str = "/api/videos/{video_id}/miniatur"

# Welches Feld der Suchparameter aus welcher Einstellung seine Vorgabe bezieht.
EINSTELLUNG_JE_FELD: dict[str, str] = {
    "treffer": "suche.treffer",
    "nachbarn": "suche.nachbarn",
    "max_je_video": "suche.max_je_video",
    "mindest_aehnlichkeit": "suche.mindest_aehnlichkeit",
    "neubewertung": "suche.neubewertung",
    "kandidaten_faktor": "suche.kandidaten_faktor",
}

FILTER_FELDER: tuple[str, ...] = ("serie", "von", "bis", "video_ids")


def _vorgabe(feld: str) -> Any:
    """Die Vorgabe eines Suchfelds aus dem Einstellungs-Register (einzige Wahrheit)."""
    return register.definition(EINSTELLUNG_JE_FELD[feld]).vorgabe


def _als_zeitpunkt(wert: Any) -> datetime | None:
    if wert is None or wert == "":
        return None
    if isinstance(wert, datetime):
        return wert
    if isinstance(wert, str):
        return datetime.fromisoformat(wert)
    raise ValueError(f"Ungültiger Zeitpunkt für die Suche: {wert!r}")


@dataclass(slots=True)
class Suchparameter:
    """Die beiden Achsen der Suche (Breite, Genauigkeit) und die Filter.

    Vorgaben kommen aus den Einstellungen `suche.*`; die Felder hier tragen die
    Register-Vorgaben nur, damit ein Objekt auch ohne Datenbank gebaut werden kann.
    """

    treffer: int = field(default_factory=lambda: int(_vorgabe("treffer")))
    nachbarn: int = field(default_factory=lambda: int(_vorgabe("nachbarn")))
    max_je_video: int = field(default_factory=lambda: int(_vorgabe("max_je_video")))
    mindest_aehnlichkeit: float = field(default_factory=lambda: float(_vorgabe("mindest_aehnlichkeit")))
    neubewertung: str = field(default_factory=lambda: str(_vorgabe("neubewertung")))
    kandidaten_faktor: int = field(default_factory=lambda: int(_vorgabe("kandidaten_faktor")))
    serie: str = ""
    von: datetime | None = None
    bis: datetime | None = None
    video_ids: list[str] = field(default_factory=list)

    @classmethod
    def aus_einstellungen(cls, werte: Mapping[str, Any], *ueberschreibungen: Mapping[str, Any] | None) -> Suchparameter:
        """Vorgaben aus den Einstellungen, darüber der Reihe nach die Überschreibungen.

        Ein Wert `None` in einer Überschreibung gilt als "nicht gesetzt" und lässt die
        darunterliegende Ebene stehen (Anfrage über Unterhaltung über Einstellungen).
        """
        roh: dict[str, Any] = {feld: werte[schluessel] for feld, schluessel in EINSTELLUNG_JE_FELD.items()}
        for schicht in ueberschreibungen:
            if not schicht:
                continue
            for feld, wert in schicht.items():
                if wert is not None and (feld in EINSTELLUNG_JE_FELD or feld in FILTER_FELDER):
                    roh[feld] = wert
        return cls.aus_dict(roh)

    @classmethod
    def aus_dict(cls, roh: Mapping[str, Any]) -> Suchparameter:
        """Baut Parameter aus einem JSON-nahen Dict (Zeiten als ISO-Text erlaubt)."""
        p = cls()
        if "treffer" in roh:
            p.treffer = int(roh["treffer"])
        if "nachbarn" in roh:
            p.nachbarn = int(roh["nachbarn"])
        if "max_je_video" in roh:
            p.max_je_video = int(roh["max_je_video"])
        if "mindest_aehnlichkeit" in roh:
            p.mindest_aehnlichkeit = float(roh["mindest_aehnlichkeit"])
        if "neubewertung" in roh:
            p.neubewertung = str(roh["neubewertung"])
        if "kandidaten_faktor" in roh:
            p.kandidaten_faktor = int(roh["kandidaten_faktor"])
        p.serie = str(roh.get("serie") or "")
        p.von = _als_zeitpunkt(roh.get("von"))
        p.bis = _als_zeitpunkt(roh.get("bis"))
        p.video_ids = [str(v) for v in (roh.get("video_ids") or [])]
        return p

    def als_dict(self) -> dict[str, Any]:
        """JSON-fähige Darstellung (für Unterhaltung.suchparameter und Nachricht.parameter)."""
        daten = asdict(self)
        daten["von"] = self.von.isoformat() if self.von else None
        daten["bis"] = self.bis.isoformat() if self.bis else None
        return daten

    @property
    def kandidaten_grenze(self) -> int:
        return max(1, self.treffer * self.kandidaten_faktor)


@dataclass(slots=True)
class Treffer:
    """Eine Textstelle mit Herkunft. `wert` ist die Cosinus-Ähnlichkeit (0 bis 1).

    `bewertung` trägt nach einer Neu-Bewertung deren Wert (Logit oder 0 bis 10), sonst None.
    Wurden Nachbarn angefügt, umfasst `text` den zusammengefügten Abschnitt; `chunk_id` und
    `reihenfolge` zeigen dann auf das Stück mit dem höchsten Wert (den Anker).
    """

    chunk_id: str
    video_id: str
    titel: str
    serie: str
    folge_nr: int | None
    start_s: float
    end_s: float
    text: str
    wert: float
    reihenfolge: int
    thema: str
    original_url: str
    miniatur: str
    ueberlappung_vor: int = 0
    bewertung: float | None = None

    def als_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def aus_dict(cls, roh: Mapping[str, Any]) -> Treffer:
        felder = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in roh.items() if k in felder})


@dataclass(slots=True)
class Suchergebnis:
    """Was die Suche liefert: Stellen in Rangfolge plus Hinweise für die Oberfläche."""

    stellen: list[Treffer]
    einbettungsmodell: str = ""
    neubewertung: str = NEUBEWERTUNG_AUS
    hinweise: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- Schnittstellen der Zugriffe

FrageEinbetter = Callable[[AsyncSession, str], Awaitable[tuple[list[float], str]]]
KandidatenLader = Callable[[AsyncSession, list[float], str, Suchparameter, int], Awaitable[list[Treffer]]]
NachbarnLader = Callable[[AsyncSession, str, set[int]], Awaitable[list[Treffer]]]
ChunkLader = Callable[[AsyncSession, list[str]], Awaitable[list[Treffer]]]
NeubewerterFabrik = Callable[[str, AsyncSession], Awaitable[Neubewerter]]


# ---------------------------------------------------------------- Zeile -> Treffer


def miniatur_adresse(video: Video) -> str:
    """Lokales Vorschaubild über die eigene Route, sonst die Originaladresse der Quelle."""
    if video.miniatur_pfad:
        return MINIATUR_ROUTE.format(video_id=video.id)
    return ""


def treffer_aus_zeile(chunk: Chunk, video: Video, wert: float) -> Treffer:
    return Treffer(
        chunk_id=chunk.id,
        video_id=video.id,
        titel=video.titel,
        serie=video.serie or "",
        folge_nr=video.folge_nr,
        start_s=float(chunk.start_s),
        end_s=float(chunk.end_s),
        text=chunk.text,
        wert=wert,
        reihenfolge=int(chunk.reihenfolge),
        thema=chunk.thema or "",
        original_url=video.original_url or "",
        miniatur=miniatur_adresse(video),
        ueberlappung_vor=int(chunk.ueberlappung_vor or 0),
    )


# ---------------------------------------------------------------- Datenbankzugriffe (Vorgabe)


async def frage_einbetten_standard(session: AsyncSession, text: str) -> tuple[list[float], str]:
    """Bettet die Frage über den Einbettungsdienst ein (Vektor, Modellname).

    Der Import geschieht erst hier: das Einbettungsmodul ist ein eigener Baustein, und die
    Suche bleibt auch dann importierbar, wenn er in einer Umgebung fehlt.
    """
    from ..einbettung.dienst import frage_einbetten

    return await frage_einbetten(session, text)


def _mit_videofiltern(q: Select[Any], p: Suchparameter) -> Select[Any]:
    if p.serie:
        q = q.where(Video.serie == p.serie)
    if p.von is not None:
        q = q.where(Video.veroeffentlicht >= p.von)
    if p.bis is not None:
        q = q.where(Video.veroeffentlicht <= p.bis)
    if p.video_ids:
        q = q.where(Video.id.in_(p.video_ids))
    return q


async def kandidaten_aus_datenbank(session: AsyncSession, vektor: list[float], modell: str, p: Suchparameter, grenze: int) -> list[Treffer]:
    """Cosinus-Suche in pgvector: die `grenze` nächsten Stücke desselben Einbettungsmodells."""
    abstand = Einbettung.vektor.cosine_distance(vektor)
    aehnlichkeit = (1 - abstand).label("aehnlichkeit")
    q: Select[Any] = (
        select(Chunk, Video, aehnlichkeit)
        .join(Einbettung, Einbettung.chunk_id == Chunk.id)
        .join(Video, Video.id == Chunk.video_id)
        .where(Einbettung.modell == modell)
    )
    q = _mit_videofiltern(q, p).order_by(abstand).limit(grenze)
    zeilen = (await session.execute(q)).all()
    return [treffer_aus_zeile(chunk, video, float(wert)) for chunk, video, wert in zeilen]


async def nachbarn_aus_datenbank(session: AsyncSession, video_id: str, reihenfolgen: set[int]) -> list[Treffer]:
    """Stücke eines Videos mit den genannten Reihenfolge-Nummern (ohne Ähnlichkeitswert)."""
    if not reihenfolgen:
        return []
    q = (
        select(Chunk, Video)
        .join(Video, Video.id == Chunk.video_id)
        .where(Chunk.video_id == video_id, Chunk.reihenfolge.in_(sorted(reihenfolgen)))
        .order_by(Chunk.reihenfolge)
    )
    zeilen = (await session.execute(q)).all()
    return [treffer_aus_zeile(chunk, video, 0.0) for chunk, video in zeilen]


async def chunks_aus_datenbank(session: AsyncSession, chunk_ids: list[str]) -> list[Treffer]:
    """Stücke nach Kennung, in der Reihenfolge der übergebenen Liste (fehlende werden übergangen)."""
    if not chunk_ids:
        return []
    q = select(Chunk, Video).join(Video, Video.id == Chunk.video_id).where(Chunk.id.in_(chunk_ids))
    je_id = {chunk.id: treffer_aus_zeile(chunk, video, 0.0) for chunk, video in (await session.execute(q)).all()}
    return [je_id[k] for k in chunk_ids if k in je_id]


# ---------------------------------------------------------------- Reine Siebschritte


def filtere_mindest_aehnlichkeit(kandidaten: Iterable[Treffer], mindest: float) -> list[Treffer]:
    """Behält nur Stellen, deren Cosinus-Wert die Schwelle erreicht."""
    return [k for k in kandidaten if k.wert >= mindest]


def begrenze_je_video(kandidaten: Iterable[Treffer], max_je_video: int) -> list[Treffer]:
    """Vielfalt: höchstens `max_je_video` Stellen je Video, Reihenfolge bleibt (0 = keine Grenze)."""
    if max_je_video <= 0:
        return list(kandidaten)
    zaehler: dict[str, int] = {}
    aus: list[Treffer] = []
    for k in kandidaten:
        if zaehler.get(k.video_id, 0) >= max_je_video:
            continue
        zaehler[k.video_id] = zaehler.get(k.video_id, 0) + 1
        aus.append(k)
    return aus


def verbinde_texte(stuecke: list[Treffer]) -> str:
    """Fügt aufeinanderfolgende Stücke zusammen; die Überlappung am Anfang jedes Folgestücks fällt weg."""
    if not stuecke:
        return ""
    text = stuecke[0].text.strip()
    for folge in stuecke[1:]:
        schnitt = min(max(folge.ueberlappung_vor, 0), len(folge.text))
        rest = folge.text[schnitt:].strip()
        if rest:
            text = f"{text} {rest}" if text else rest
    return text


def _zusammenhaengende_laeufe(stuecke: list[Treffer]) -> list[list[Treffer]]:
    """Teilt nach Reihenfolge sortierte Stücke in Läufe ohne Lücke."""
    laeufe: list[list[Treffer]] = []
    for s in stuecke:
        if laeufe and laeufe[-1][-1].reihenfolge + 1 == s.reihenfolge:
            laeufe[-1].append(s)
        else:
            laeufe.append([s])
    return laeufe


def _verschmelze_lauf(lauf: list[Treffer], anker_ids: set[str]) -> Treffer | None:
    anker = [s for s in lauf if s.chunk_id in anker_ids]
    if not anker:
        return None
    bester = max(anker, key=lambda s: s.wert)
    return Treffer(
        chunk_id=bester.chunk_id,
        video_id=bester.video_id,
        titel=bester.titel,
        serie=bester.serie,
        folge_nr=bester.folge_nr,
        start_s=lauf[0].start_s,
        end_s=lauf[-1].end_s,
        text=verbinde_texte(lauf),
        wert=bester.wert,
        reihenfolge=bester.reihenfolge,
        thema=bester.thema,
        original_url=bester.original_url,
        miniatur=bester.miniatur,
        ueberlappung_vor=lauf[0].ueberlappung_vor,
        bewertung=bester.bewertung,
    )


def fuege_nachbarn_zusammen(anker: list[Treffer], nachbarn: Iterable[Treffer]) -> list[Treffer]:
    """Baut aus Ankern und ihren Nachbarn zusammenhängende Abschnitte, entdoppelt an den Überlappungen.

    Anker desselben Videos, deren Fenster sich berühren, verschmelzen zu einem Abschnitt. Die
    Rangfolge der Anker bleibt erhalten: ein Abschnitt steht dort, wo sein bester Anker stand.
    """
    anker_ids = {a.chunk_id for a in anker}
    rang = {a.chunk_id: i for i, a in enumerate(anker)}
    je_video: dict[str, dict[int, Treffer]] = {}
    for n in nachbarn:
        je_video.setdefault(n.video_id, {})[n.reihenfolge] = n
    for a in anker:  # Anker gewinnen gegen Nachbarn mit gleicher Nummer (sie tragen den Wert)
        je_video.setdefault(a.video_id, {})[a.reihenfolge] = a
    abschnitte: list[Treffer] = []
    for stuecke in je_video.values():
        sortiert = [stuecke[r] for r in sorted(stuecke)]
        for lauf in _zusammenhaengende_laeufe(sortiert):
            abschnitt = _verschmelze_lauf(lauf, anker_ids)
            if abschnitt is not None:
                abschnitte.append(abschnitt)
    abschnitte.sort(key=lambda t: rang[t.chunk_id])
    return abschnitte


def nachbar_nummern(anker: list[Treffer], nachbarn: int) -> dict[str, set[int]]:
    """Je Video die Reihenfolge-Nummern, die als Nachbarn geladen werden müssen (ohne die Anker selbst)."""
    gewuenscht: dict[str, set[int]] = {}
    vorhanden = {(a.video_id, a.reihenfolge) for a in anker}
    for a in anker:
        for r in range(a.reihenfolge - nachbarn, a.reihenfolge + nachbarn + 1):
            if r >= 0 and (a.video_id, r) not in vorhanden:
                gewuenscht.setdefault(a.video_id, set()).add(r)
    return gewuenscht


def _reihenfolge_nach_bewertung(kandidaten: list[Treffer], bewertungen: list[float]) -> list[Treffer]:
    reihenfolge = sorted(range(len(kandidaten)), key=lambda i: bewertungen[i], reverse=True)
    aus: list[Treffer] = []
    for i in reihenfolge:
        k = kandidaten[i]
        k.bewertung = float(bewertungen[i])
        aus.append(k)
    return aus


# ---------------------------------------------------------------- Die Suche


class Suche:
    """Führt eine Suche aus. Alle Zugriffe sind austauschbar (Tests ohne Datenbank)."""

    def __init__(
        self,
        einbetter: FrageEinbetter = frage_einbetten_standard,
        kandidaten: KandidatenLader = kandidaten_aus_datenbank,
        nachbarn: NachbarnLader = nachbarn_aus_datenbank,
        chunks: ChunkLader = chunks_aus_datenbank,
        neubewerter: NeubewerterFabrik = neubewerter_fuer,
    ) -> None:
        self._einbetter = einbetter
        self._kandidaten = kandidaten
        self._nachbarn = nachbarn
        self._chunks = chunks
        self._neubewerter = neubewerter

    async def suchen(self, session: AsyncSession, frage: str, p: Suchparameter) -> Suchergebnis:
        """Der volle Ablauf: einbetten, holen, sieben, neu bewerten, kürzen, Nachbarn anfügen."""
        frage = frage.strip()
        if not frage:
            raise ValueError("Die Frage ist leer.")
        vektor, modell = await self._einbetter(session, frage)
        kandidaten = await self._kandidaten(session, vektor, modell, p, p.kandidaten_grenze)
        ergebnis = Suchergebnis(stellen=[], einbettungsmodell=modell, neubewertung=p.neubewertung)
        if not kandidaten:
            ergebnis.hinweise.append("Keine eingebetteten Stellen für dieses Modell und diese Filter gefunden.")
            return ergebnis
        gesiebt = begrenze_je_video(filtere_mindest_aehnlichkeit(kandidaten, p.mindest_aehnlichkeit), p.max_je_video)
        if not gesiebt:
            ergebnis.hinweise.append(f"Alle {len(kandidaten)} Kandidaten liegen unter der Mindestähnlichkeit {p.mindest_aehnlichkeit:.2f}.")
            return ergebnis
        geordnet = await self._neu_bewerten(session, frage, gesiebt, p.neubewertung, ergebnis.hinweise)
        ausgewaehlt = geordnet[: p.treffer]
        ergebnis.stellen = await self._mit_nachbarn(session, ausgewaehlt, p.nachbarn)
        return ergebnis

    async def laden(self, session: AsyncSession, chunk_ids: list[str], p: Suchparameter) -> Suchergebnis:
        """Vom Nutzer bestätigte Stellen laden, ohne neue Suche; Nachbarn nach Parameter anfügen."""
        anker = await self._chunks(session, chunk_ids)
        ergebnis = Suchergebnis(stellen=[], neubewertung=NEUBEWERTUNG_AUS)
        fehlend = len(chunk_ids) - len(anker)
        if fehlend > 0:
            ergebnis.hinweise.append(f"{fehlend} bestätigte Stellen existieren nicht mehr (Video neu gestückelt?).")
        ergebnis.stellen = await self._mit_nachbarn(session, anker, p.nachbarn)
        return ergebnis

    async def _neu_bewerten(
        self, session: AsyncSession, frage: str, kandidaten: list[Treffer], art: str, hinweise: list[str]
    ) -> list[Treffer]:
        if art == NEUBEWERTUNG_AUS or len(kandidaten) < 2:
            return kandidaten
        try:
            bewerter = await self._neubewerter(art, session)
            bewertungen = await bewerter.bewerte(frage, [kontexttext(k) for k in kandidaten])
        except NeubewertungFehler as e:
            log.warning("Neu-Bewertung '%s' nicht möglich: %s", art, e)
            hinweise.append(f"Neu-Bewertung ({art}) nicht möglich, Vektorreihenfolge behalten: {e}")
            return kandidaten
        if len(bewertungen) != len(kandidaten):
            hinweise.append(
                f"Neu-Bewertung ({art}) lieferte {len(bewertungen)} Werte für {len(kandidaten)} Kandidaten, Vektorreihenfolge behalten."
            )
            return kandidaten
        return _reihenfolge_nach_bewertung(kandidaten, bewertungen)

    async def _mit_nachbarn(self, session: AsyncSession, anker: list[Treffer], nachbarn: int) -> list[Treffer]:
        if nachbarn <= 0 or not anker:
            return anker
        geladen: list[Treffer] = []
        for video_id, nummern in nachbar_nummern(anker, nachbarn).items():
            geladen.extend(await self._nachbarn(session, video_id, nummern))
        return fuege_nachbarn_zusammen(anker, geladen)


def kontexttext(t: Treffer) -> str:
    """Text mit Kontextkopf, wie ihn auch die Einbettung sieht (Architektur, Abschnitt 6)."""
    kopf = f"Video: {t.titel}"
    if t.thema:
        kopf = f"{kopf} | Thema: {t.thema}"
    return f"{kopf}\n{t.text}"


suche = Suche()
