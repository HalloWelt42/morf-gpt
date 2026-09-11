"""Ein- und Ausgabemodelle der Auftragsverwaltung (Router /auftraege)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuftragEintrag(BaseModel):
    id: str
    art: str
    art_titel: str
    video_id: str | None
    video_titel: str
    video_serie: str
    video_folge_nr: int | None
    status: str
    prioritaet: int
    versuche: int
    fortschritt: float
    meldung: str
    fehler: str
    gestartet: datetime | None
    beendet: datetime | None
    herzschlag: datetime | None
    erstellt: datetime
    laufzeit_s: float | None


class AuftragSeite(BaseModel):
    eintraege: list[AuftragEintrag]
    gesamt: int
    seite: int
    je_seite: int


class AuftragDetail(AuftragEintrag):
    parameter: dict[str, Any]
    ergebnis: dict[str, Any]
    protokoll_anzahl: int


class ProtokollZeile(BaseModel):
    id: int
    zeit: datetime
    stufe: str
    text: str


class ProtokollSeite(BaseModel):
    """Protokollzeilen, neueste zuerst; `ab` ist der Versatz ab der neuesten Zeile."""

    eintraege: list[ProtokollZeile]
    gesamt: int
    ab: int
    anzahl: int


class ArtUebersicht(BaseModel):
    art: str
    titel: str
    wartend: int
    laufend: int
    fertig: int
    fehler: int
    abgebrochen: int
    pausiert: bool
    pausierbar: bool
    parallel: int
    durchsatz_fenster: int
    mittlere_dauer_s: float | None
    restzeit_s: float | None


class BandUebersicht(BaseModel):
    arten: list[ArtUebersicht]
    automatik: bool
    laeufer_aktiv: bool
    durchsatz_fenster_s: int
    wartend_gesamt: int
    laufend_gesamt: int
    fehler_gesamt: int


class PauseEingabe(BaseModel):
    art: str
    pausiert: bool


class PauseErgebnis(BaseModel):
    art: str
    art_titel: str
    pausiert: bool


class AbbruchErgebnis(BaseModel):
    auftrag_id: str
    status: str
    hinweis: str


class WiederholenErgebnis(BaseModel):
    anzahl: int
    auftrag_ids: list[str]


class AufraeumErgebnis(BaseModel):
    geloescht: int
    tage: int


class AuffuellErgebnis(BaseModel):
    angelegt: int
