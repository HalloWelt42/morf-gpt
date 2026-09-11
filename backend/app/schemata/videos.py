"""Ein- und Ausgabemodelle der Videoverwaltung (Router /videos).

Listeneinträge sind bewusst schlank (was die Tabelle zeigt), das Detail trägt alles,
was die Videoseite braucht: Audio, Transkript- und Korrektur-Meta ohne Nutzlast,
die letzten Aufträge und die Original-Metadaten der Quelle.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class OffenerAuftrag(BaseModel):
    """Der laufende oder wartende Auftrag eines Videos (höchstens einer wird gezeigt)."""

    id: str
    art: str
    art_titel: str
    status: str
    fortschritt: float
    meldung: str


class VideoEintrag(BaseModel):
    id: str
    extern_id: str
    titel: str
    serie: str
    folge_nr: int | None
    veroeffentlicht: datetime | None
    dauer_s: int | None
    typ: str
    stufe: str
    stufe_titel: str
    ausgewaehlt: bool
    auswahl_manuell: bool
    fehler: str
    original_url: str
    miniatur_url: str | None
    hat_audio: bool
    chunks_anzahl: int
    offener_auftrag: OffenerAuftrag | None


class VideoSeite(BaseModel):
    eintraege: list[VideoEintrag]
    gesamt: int
    seite: int
    je_seite: int


class SerieEintrag(BaseModel):
    """Eine Serie (leerer Name = Videos ohne Serie)."""

    serie: str
    anzahl: int
    ausgewaehlt: int
    min_folge: int | None
    max_folge: int | None


class AudioInfo(BaseModel):
    id: str
    pfad: str
    format: str
    dauer_s: float | None
    groesse_bytes: int | None
    abtastrate: int | None
    kanaele: int | None
    bezugsweg: str
    datei_vorhanden: bool
    erstellt: datetime


class TranskriptMeta(BaseModel):
    """Aktuelles Rohtranskript ohne Volltext und Segmente."""

    id: str
    engine: str
    modell: str
    sprache: str
    zeichen: int
    segmente_anzahl: int
    dauer_verarbeitung_s: float | None
    erstellt: datetime


class KorrekturMeta(BaseModel):
    """Aktuelle Korrektur ohne Absätze."""

    id: str
    transkript_id: str | None
    engine: str
    anbieter: str
    modell: str
    absaetze_anzahl: int
    themen: list[dict[str, Any]]
    zusammenfassung: str
    aehnlichkeit: float | None
    bloecke_gesamt: int
    bloecke_verworfen: int
    dauer_verarbeitung_s: float | None
    manuell_bearbeitet: bool
    erstellt: datetime


class AuftragKurz(BaseModel):
    id: str
    art: str
    art_titel: str
    status: str
    fortschritt: float
    meldung: str
    fehler: str
    versuche: int
    gestartet: datetime | None
    beendet: datetime | None
    erstellt: datetime


class VideoDetail(VideoEintrag):
    beschreibung: str
    aufrufe: int | None
    schlagworte: list[str]
    kanal_name: str
    quelle_id: str | None
    quelle_typ: str  # tubevault, lokal oder leer (ohne Quelle)
    quelle_heruntergeladen: bool
    datei_pfad: str  # bei lokalen Quellen der Pfad relativ zum Verzeichnis, sonst leer
    felder_manuell: list[str]  # von Hand gepflegte Felder, die der Abgleich nicht mehr überschreibt
    prioritaet: int
    notizen: str
    metadaten_original: dict[str, Any]
    audio: AudioInfo | None
    transkript: TranskriptMeta | None
    korrektur: KorrekturMeta | None
    auftraege: list[AuftragKurz]
    erstellt: datetime
    aktualisiert: datetime


class VideoAenderung(BaseModel):
    """Felder, die der Nutzer an einem Video ändert. Nicht gesetzte Felder bleiben unverändert.

    Metadatenfelder (Titel, Beschreibung, Datum, Dauer, Art, Originaladresse, Kanal, Serie,
    Folge, Schlagworte) gelten danach als von Hand gepflegt: der Abgleich mit der Quelle
    lässt sie stehen, bis `handpflege_aufheben` gesetzt wird.
    """

    ausgewaehlt: bool | None = None
    prioritaet: int | None = Field(default=None, ge=-1000, le=1000)
    notizen: str | None = None
    titel: str | None = Field(default=None, min_length=1)
    beschreibung: str | None = None
    veroeffentlicht: datetime | None = None
    dauer_s: int | None = Field(default=None, ge=0)
    typ: str | None = Field(default=None, min_length=1, max_length=16)
    original_url: str | None = Field(default=None, max_length=500)
    kanal_name: str | None = Field(default=None, max_length=200)
    serie: str | None = Field(default=None, max_length=32)
    folge_nr: int | None = Field(default=None, ge=0)
    folge_nr_loeschen: bool = False
    schlagworte: list[str] | None = None
    handpflege_aufheben: bool = False


class AuswahlregelAusgabe(BaseModel):
    mindest_dauer_s: int
    typen: list[str]
    nur_heruntergeladene: bool


class AuswahlRegelErgebnis(BaseModel):
    regel: AuswahlregelAusgabe
    geprueft: int
    aufgenommen: int
    entfernt: int
    unveraendert: int
    auftraege_angelegt: int
    auftraege_abgebrochen: int


class AuswahlStapelEingabe(BaseModel):
    video_ids: list[str] = Field(min_length=1)
    ausgewaehlt: bool


class AuswahlStapelErgebnis(BaseModel):
    angefragt: int
    geaendert: int
    unveraendert: int
    nicht_gefunden: int
    auftraege_angelegt: int
    auftraege_abgebrochen: int


class AuftragAngelegt(BaseModel):
    auftrag_id: str
    video_id: str
    art: str
    art_titel: str
    status: str


class GeloeschteArtefakte(BaseModel):
    einbettungen: int = 0
    chunks: int = 0
    korrekturen: int = 0
    transkripte: int = 0
    audios: int = 0
    dateien: int = 0


class ZuruecksetzErgebnis(BaseModel):
    video_id: str
    stufe_vorher: str
    stufe_nachher: str
    geloescht: GeloeschteArtefakte
    auftraege_abgebrochen: int
    folgeauftrag_id: str | None
