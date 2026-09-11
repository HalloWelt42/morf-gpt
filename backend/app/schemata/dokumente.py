"""Ein- und Ausgabemodelle der Dokumentverwaltung (Router /dokumente)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .videos import AuftragKurz, OffenerAuftrag


class AbschnittEintrag(BaseModel):
    id: str
    reihenfolge: int
    ebene: int
    titel: str
    zeichen: int
    anker: str
    seite_von: int | None
    seite_bis: int | None
    chunks_anzahl: int


class AbschnittText(AbschnittEintrag):
    text: str


class DokumentEintrag(BaseModel):
    id: str
    titel: str
    autor: str
    art: str
    art_titel: str
    sprache: str
    veroeffentlicht: datetime | None
    dateiname: str
    groesse_bytes: int | None
    zeichen: int
    abschnitte_anzahl: int
    chunks_anzahl: int
    stufe: str
    stufe_titel: str
    fehler: str
    offener_auftrag: OffenerAuftrag | None
    erstellt: datetime
    aktualisiert: datetime


class DokumentSeite(BaseModel):
    eintraege: list[DokumentEintrag]
    gesamt: int
    seite: int
    je_seite: int


class DokumentDetail(DokumentEintrag):
    beschreibung: str
    notizen: str
    prioritaet: int
    felder_manuell: list[str]
    metadaten_original: dict[str, Any]
    abschnitte: list[AbschnittEintrag]
    auftraege: list[AuftragKurz]


class DokumentInhalt(BaseModel):
    """Der volle Text in Abschnitten (Leseansicht)."""

    id: str
    titel: str
    abschnitte: list[AbschnittText]


class DokumentAenderung(BaseModel):
    """Von Hand gepflegte Felder; gesetzte Metadaten gelten danach als festgehalten."""

    titel: str | None = Field(default=None, min_length=1)
    autor: str | None = Field(default=None, max_length=300)
    sprache: str | None = Field(default=None, max_length=16)
    beschreibung: str | None = None
    veroeffentlicht: datetime | None = None
    notizen: str | None = None
    prioritaet: int | None = Field(default=None, ge=-1000, le=1000)
    handpflege_aufheben: bool = False


class EigenerText(BaseModel):
    titel: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1)
    autor: str = ""
    art: str = "markdown"


class ArtEintrag(BaseModel):
    kennung: str
    titel: str
    endungen: list[str]
