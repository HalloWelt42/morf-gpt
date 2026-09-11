"""Abgleich einer Quelle mit der Tabelle videos.

Holt alle Kanalvideos seitenweise aus der Quelle, legt neue Videos an, frischt bekannte
auf, erkennt Serie und Folge aus dem Titel, lädt fehlende Vorschaubilder und wendet die
Auswahlregel an - nur dort, wo der Nutzer die Auswahl nicht von Hand festgelegt hat.

Die Datenbankzugriffe laufen über die kleine Schnittstelle `Videoablage`; der Ablauf
selbst kennt keine Sitzung und ist damit ohne Datenbank prüfbar. Fortschritt und
Protokoll gehen über übergebene Rückrufe (der Auftragskontext liefert sie).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from math import ceil
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.modelle import Quelle, Video, neue_id
from ...domaene.fliessband import Stufe
from . import lokal, tubevault
from .basis import QuellenFehler, QuellVideo, VideoQuelle, alle_seiten

# Vorgabe, solange die Einstellung 'quelle.seitengroesse' im Register fehlt
# (siehe Bericht, register_ergaenzungen).
SEITENGROESSE_VORGABE = 200

# So viele Kennungen fehlgeschlagener Vorschaubilder nennt eine Protokollzeile je Seite.
_MINIATUR_FEHLER_BEISPIELE = 5

# Serie und Folge am Titelende: "... | mmM#377", "... | gmM#51".
SERIEN_MUSTER = re.compile(r"\|\s*([A-Za-z]+)#(\d+)\s*$")

TYPEN: dict[str, str] = {tubevault.TYP_KENNUNG: tubevault.TYP_TITEL, lokal.TYP_KENNUNG: lokal.TYP_TITEL}

# Felder, die der Abgleich aus der Quelle überträgt und die der Nutzer von Hand
# festhalten kann (Spalte videos.felder_manuell): festgehaltene Felder rührt er nicht an.
PFLEGBARE_FELDER: tuple[str, ...] = (
    "titel",
    "beschreibung",
    "veroeffentlicht",
    "dauer_s",
    "typ",
    "original_url",
    "kanal_name",
    "serie",
    "folge_nr",
    "schlagworte",
)

Fortschrittsmelder = Callable[[float, str], Awaitable[None]]
Protokollant = Callable[[str, str], Awaitable[None]]


# ---------------------------------------------------------------- reine Regeln
def serie_aus_titel(titel: str) -> tuple[str, int | None]:
    """Serie (Buchstabenteil) und Folgennummer aus dem Titelende; ("", None) ohne Treffer."""
    treffer = SERIEN_MUSTER.search(titel or "")
    if treffer is None:
        return "", None
    return treffer.group(1), int(treffer.group(2))


def typen_parsen(text: Any) -> frozenset[str]:
    """'video, live' -> {'video', 'live'}; leere Teile fallen weg."""
    teile = str(text or "").split(",")
    return frozenset(t.strip().lower() for t in teile if t.strip())


@dataclass(frozen=True, slots=True)
class Auswahlregeln:
    """Welche Videos automatisch in den Umfang kommen."""

    mindest_dauer_s: int
    typen: frozenset[str]
    nur_heruntergeladene: bool

    @classmethod
    def aus_werten(cls, werte: Mapping[str, Any], ueberschreibungen: Mapping[str, Any] | None = None) -> Auswahlregeln:
        """Aus den Einstellungen (quelle.*), optional je Quelle überschrieben (Spalte regeln)."""
        eigene = dict(ueberschreibungen or {})

        def wert(schluessel: str) -> Any:
            if eigene.get(schluessel) is not None:
                return eigene[schluessel]
            return werte[f"quelle.{schluessel}"]

        return cls(
            mindest_dauer_s=int(wert("mindest_dauer_s")),
            typen=typen_parsen(wert("typen")),
            nur_heruntergeladene=bool(wert("nur_heruntergeladene")),
        )


def ist_im_umfang(video: QuellVideo, regeln: Auswahlregeln) -> bool:
    """Auswahlregel: länger als die Mindestdauer, erlaubter Typ, bei Bedarf heruntergeladen."""
    if video.dauer_s is None or video.dauer_s <= regeln.mindest_dauer_s:
        return False
    if video.typ not in regeln.typen:
        return False
    if regeln.nur_heruntergeladene and not video.heruntergeladen:
        return False
    return True


def miniatur_pfad(verzeichnis: Path, extern_id: str) -> Path:
    return verzeichnis / f"{extern_id}.jpg"


# ---------------------------------------------------------------- Quelle bauen
def zeitgrenze_aus(werte: Mapping[str, Any]) -> float:
    return float(werte.get("quelle.zeitgrenze_s", tubevault.ZEITGRENZE_S_VORGABE))


def seitengroesse_aus(werte: Mapping[str, Any]) -> int:
    return int(werte.get("quelle.seitengroesse", SEITENGROESSE_VORGABE))


def dateiendungen_aus(werte: Mapping[str, Any]) -> frozenset[str]:
    return lokal.endungen_parsen(werte.get("quelle.dateiendungen", lokal.ENDUNGEN_VORGABE))


def tubevault_adresse(werte: Mapping[str, Any]) -> str:
    """Die eine, zentral eingestellte Adresse der TubeVault-Schnittstelle (Einstellung quelle.tubevault_api)."""
    adresse = str(werte.get("quelle.tubevault_api") or "").strip().rstrip("/")
    if not adresse:
        raise QuellenFehler("Die TubeVault-Adresse fehlt (Einstellungen, Quelle und Auswahl)")
    return adresse


def tubevault_videoseite(werte: Mapping[str, Any], extern_id: str) -> str:
    """Sprung zur Videoseite in der TubeVault-Oberfläche; leer, wenn Adresse oder Kennung fehlt."""
    basis = str(werte.get("quelle.tubevault_oberflaeche") or "").strip().rstrip("/")
    pfad = str(werte.get("quelle.tubevault_videoseite") or "").strip()
    if not basis or not pfad or not extern_id:
        return ""
    return basis + "/" + pfad.replace("{extern_id}", extern_id).lstrip("/")


def baue_quelle(typ: str, basis_url: str, kanal_id: str, werte: Mapping[str, Any]) -> VideoQuelle:
    """Die Umsetzung zum Quellentyp. Unbekannte Typen sind ein sprechender Fehler.

    TubeVault-Quellen nutzen die zentrale Adresse aus den Einstellungen; `basis_url` ist dort
    ohne Bedeutung. Bei lokalen Dateien ist `basis_url` das Verzeichnis; `kanal_id` braucht
    nur TubeVault.
    """
    if typ == tubevault.TYP_KENNUNG:
        if not kanal_id.strip():
            raise QuellenFehler("TubeVault braucht eine Kanalkennung")
        return tubevault.TubeVault(tubevault_adresse(werte), kanal_id, zeitgrenze_s=zeitgrenze_aus(werte))
    if typ == lokal.TYP_KENNUNG:
        return lokal.LokaleDateien(basis_url, dateiendungen_aus(werte))
    raise QuellenFehler(f"Unbekannter Quellentyp '{typ}' (bekannt: {', '.join(TYPEN)})")


# ---------------------------------------------------------------- Ablage
class Videoablage(Protocol):
    """Was der Abgleich von der Datenbank braucht - klein, damit Tests es nachbilden können."""

    async def finde(self, quelle_id: str, extern_id: str) -> Video | None: ...

    def hinzufuegen(self, video: Video) -> None: ...

    async def speichern(self) -> None: ...


class Videobestand:
    """Videoablage über eine SQLAlchemy-Sitzung."""

    def __init__(self, s: AsyncSession) -> None:
        self._s = s

    async def finde(self, quelle_id: str, extern_id: str) -> Video | None:
        """Das Video dieser Quelle; sonst ein verwaistes (Quelle gelöscht) derselben Kennung,
        damit ein neu angelegter Kanal seine alten Videos wieder aufnimmt statt sie zu doppeln."""
        q = select(Video).where(
            Video.extern_id == extern_id,
            or_(Video.quelle_id == quelle_id, Video.quelle_id.is_(None)),
        )
        rows = (await self._s.execute(q)).scalars().all()
        for v in rows:
            if v.quelle_id == quelle_id:
                return v
        return rows[0] if rows else None

    def hinzufuegen(self, video: Video) -> None:
        self._s.add(video)

    async def speichern(self) -> None:
        await self._s.commit()


# ---------------------------------------------------------------- Zähler
@dataclass(slots=True)
class Abgleichzaehler:
    gesamt_quelle: int = 0
    seiten: int = 0
    neu: int = 0
    aktualisiert: int = 0
    unveraendert: int = 0
    ausgewaehlt: int = 0
    neu_ausgewaehlt: int = 0
    miniaturen_geladen: int = 0
    miniaturen_fehler: int = 0
    neu_ausgewaehlt_ids: list[str] = field(default_factory=list)

    def als_dict(self) -> dict[str, Any]:
        """Für Auftragsergebnis und Ereignis (die Kennungsliste bleibt draußen)."""
        daten = asdict(self)
        daten.pop("neu_ausgewaehlt_ids")
        return daten


# ---------------------------------------------------------------- Feldübernahme
def _neues_video(quelle: Quelle, extern_id: str) -> Video:
    """Alle Felder ausdrücklich belegt: Spaltenvorgaben greifen erst beim Einfügen."""
    return Video(
        id=neue_id(),
        quelle_id=quelle.id,
        extern_id=extern_id,
        titel="",
        beschreibung="",
        schlagworte=[],
        kanal_name="",
        serie="",
        miniatur_url="",
        miniatur_pfad="",
        metadaten_original={},
        felder_manuell=[],
        quelle_heruntergeladen=False,
        ausgewaehlt=False,
        auswahl_manuell=False,
        stufe=Stufe.ENTDECKT,
        fehler="",
        prioritaet=0,
        notizen="",
    )


def _setze_wenn_anders(video: Video, attribut: str, wert: Any) -> bool:
    if getattr(video, attribut) == wert:
        return False
    setattr(video, attribut, wert)
    return True


def _metadaten_zusammenfuehren(alt: Mapping[str, Any] | None, neu: Mapping[str, Any]) -> dict[str, Any]:
    """Der Listeneintrag ersetzt den alten; ein früher geholtes Videodetail bleibt erhalten."""
    ergebnis = dict(neu)
    if alt and "detail" in alt and "detail" not in ergebnis:
        ergebnis["detail"] = alt["detail"]
    return ergebnis


def felder_uebernehmen(video: Video, qv: QuellVideo, quelle: Quelle) -> bool:
    """Überträgt die Quellfelder auf das Video. True, wenn sich etwas geändert hat.

    Von Hand gepflegte Felder (videos.felder_manuell) bleiben unangetastet, bis der
    Nutzer die Handpflege aufhebt.
    """
    serie, folge_nr = serie_aus_titel(qv.titel)
    festgehalten = set(video.felder_manuell or [])
    werte: list[tuple[str, Any]] = [
        ("quelle_id", quelle.id),
        ("original_url", qv.original_url),
        ("titel", qv.titel),
        ("beschreibung", qv.beschreibung),
        ("veroeffentlicht", qv.veroeffentlicht),
        ("dauer_s", qv.dauer_s),
        ("typ", qv.typ),
        ("aufrufe", qv.aufrufe),
        ("kanal_name", qv.kanal_name or quelle.kanal_name or ""),
        ("serie", serie),
        ("folge_nr", folge_nr),
        ("miniatur_url", qv.miniatur_url),
        ("quelle_heruntergeladen", qv.heruntergeladen),
        ("metadaten_original", _metadaten_zusammenfuehren(video.metadaten_original, qv.roh)),
    ]
    if qv.schlagworte:
        werte.append(("schlagworte", list(qv.schlagworte)))
    geaendert = False
    for attribut, wert in werte:
        if attribut in festgehalten:
            continue
        if _setze_wenn_anders(video, attribut, wert):
            geaendert = True
    return geaendert


def auswahl_anwenden(video: Video, qv: QuellVideo, regeln: Auswahlregeln) -> bool:
    """Setzt `ausgewaehlt` nach Regel, außer der Nutzer hat entschieden. True = neu aufgenommen."""
    if video.auswahl_manuell:
        return False
    vorher = bool(video.ausgewaehlt)
    nachher = ist_im_umfang(qv, regeln)
    video.ausgewaehlt = nachher
    return nachher and not vorher


# ---------------------------------------------------------------- Ablauf
async def _nichts_melden(_anteil: float, _meldung: str) -> None:
    return None


async def _nichts_protokollieren(_text: str, _stufe: str) -> None:
    return None


def _abbruch_pruefen(abbruch: asyncio.Event | None) -> None:
    if abbruch is not None and abbruch.is_set():
        raise asyncio.CancelledError()


async def _detail_ergaenzen(videoquelle: VideoQuelle, qv: QuellVideo, vorhanden: Video | None) -> None:
    """Holt das Videodetail (Schlagworte, Datei) einmalig für heruntergeladene Videos."""
    if not qv.heruntergeladen:
        return
    if vorhanden is not None and "detail" in (vorhanden.metadaten_original or {}):
        return
    detail = await videoquelle.videodetail(qv.extern_id)
    if detail is None:
        return
    qv.roh["detail"] = detail.roh
    if not qv.schlagworte:
        qv.schlagworte = list(detail.schlagworte)


async def _video_abgleichen(
    quelle: Quelle,
    videoquelle: VideoQuelle,
    bestand: Videoablage,
    qv: QuellVideo,
    regeln: Auswahlregeln,
    zaehler: Abgleichzaehler,
) -> Video:
    vorhanden = await bestand.finde(quelle.id, qv.extern_id)
    await _detail_ergaenzen(videoquelle, qv, vorhanden)
    if vorhanden is None:
        video = _neues_video(quelle, qv.extern_id)
        felder_uebernehmen(video, qv, quelle)
        bestand.hinzufuegen(video)
        zaehler.neu += 1
    else:
        video = vorhanden
        if felder_uebernehmen(video, qv, quelle):
            zaehler.aktualisiert += 1
        else:
            zaehler.unveraendert += 1
    if auswahl_anwenden(video, qv, regeln):
        zaehler.neu_ausgewaehlt += 1
        zaehler.neu_ausgewaehlt_ids.append(video.id)
    if video.ausgewaehlt:
        zaehler.ausgewaehlt += 1
    return video


async def _miniatur_sichern(videoquelle: VideoQuelle, video: Video, verzeichnis: Path) -> bool:
    """Lädt das Vorschaubild, wenn es lokal fehlt. True = neu geladen. Wirft QuellenFehler."""
    ziel = miniatur_pfad(verzeichnis, video.extern_id)
    if ziel.is_file() and ziel.stat().st_size > 0:
        video.miniatur_pfad = str(ziel)
        return False
    daten = await videoquelle.miniatur(video.extern_id)
    verzeichnis.mkdir(parents=True, exist_ok=True)
    ziel.write_bytes(daten)
    video.miniatur_pfad = str(ziel)
    return True


async def _miniaturen_der_seite(
    videoquelle: VideoQuelle,
    videos: list[Video],
    verzeichnis: Path,
    zaehler: Abgleichzaehler,
    protokoll: Protokollant,
    abbruch: asyncio.Event | None,
) -> None:
    """Vorschaubilder einer Seite; Fehler werden gezählt und je Seite gesammelt protokolliert."""
    fehlgeschlagen: list[str] = []
    for video in videos:
        _abbruch_pruefen(abbruch)
        try:
            if await _miniatur_sichern(videoquelle, video, verzeichnis):
                zaehler.miniaturen_geladen += 1
        except (QuellenFehler, OSError) as e:
            zaehler.miniaturen_fehler += 1
            if len(fehlgeschlagen) < _MINIATUR_FEHLER_BEISPIELE:
                fehlgeschlagen.append(f"{video.extern_id} ({e})")
    if fehlgeschlagen:
        rest = zaehler.miniaturen_fehler - len(fehlgeschlagen)
        await protokoll(
            "Vorschaubild nicht ladbar: " + "; ".join(fehlgeschlagen) + (f" und {rest} weitere" if rest > 0 else ""),
            "warn",
        )


async def abgleichen(
    quelle: Quelle,
    videoquelle: VideoQuelle,
    bestand: Videoablage,
    werte: Mapping[str, Any],
    miniaturen_verzeichnis: Path,
    *,
    fortschritt: Fortschrittsmelder | None = None,
    protokoll: Protokollant | None = None,
    abbruch: asyncio.Event | None = None,
) -> Abgleichzaehler:
    """Der vollständige Abgleich einer Quelle. Speichert je Seite; ein Abbruch verliert
    höchstens die laufende Seite, ein erneuter Lauf ist ohne Doppelungen möglich."""
    melde = fortschritt or _nichts_melden
    schreibe = protokoll or _nichts_protokollieren
    regeln = Auswahlregeln.aus_werten(werte, quelle.regeln)
    je_seite = seitengroesse_aus(werte)
    zaehler = Abgleichzaehler()

    kanal = await videoquelle.kanal()
    quelle.kanal_name = kanal.name or quelle.kanal_name
    quelle.kanal_beschreibung = kanal.beschreibung or quelle.kanal_beschreibung
    await schreibe(
        f"Kanal '{quelle.kanal_name}' mit {kanal.videos_gesamt if kanal.videos_gesamt is not None else 'unbekannt vielen'} "
        f"Videos; Regel: länger als {regeln.mindest_dauer_s} Sekunden, Arten {', '.join(sorted(regeln.typen))}"
        + (", nur heruntergeladene" if regeln.nur_heruntergeladene else ""),
        "info",
    )

    gesehen = 0
    seitengroesse_effektiv = je_seite
    async for seite in alle_seiten(videoquelle, je_seite):
        _abbruch_pruefen(abbruch)
        if zaehler.seiten == 0:
            # Die Quelle darf die Seitengröße deckeln; die erste Seite zeigt die echte Größe.
            seitengroesse_effektiv = max(1, len(seite.videos))
        zaehler.gesamt_quelle = seite.gesamt
        zaehler.seiten += 1
        videos: list[Video] = []
        for qv in seite.videos:
            _abbruch_pruefen(abbruch)
            videos.append(await _video_abgleichen(quelle, videoquelle, bestand, qv, regeln, zaehler))
        await _miniaturen_der_seite(videoquelle, videos, miniaturen_verzeichnis, zaehler, schreibe, abbruch)
        await bestand.speichern()
        gesehen += len(seite.videos)
        seiten_gesamt = max(1, ceil(seite.gesamt / seitengroesse_effektiv))
        await melde(
            min(1.0, gesehen / max(1, seite.gesamt)),
            f"Seite {seite.seite} von {seiten_gesamt}: {gesehen} von {seite.gesamt} Videos abgeglichen",
        )

    quelle.zuletzt_abgeglichen = datetime.now(UTC)
    await bestand.speichern()
    await schreibe(
        f"Abgleich fertig: {zaehler.neu} neu, {zaehler.aktualisiert} aktualisiert, {zaehler.unveraendert} unverändert, "
        f"{zaehler.ausgewaehlt} im Umfang ({zaehler.neu_ausgewaehlt} neu aufgenommen), "
        f"{zaehler.miniaturen_geladen} Vorschaubilder geladen, {zaehler.miniaturen_fehler} nicht ladbar",
        "info",
    )
    return zaehler
