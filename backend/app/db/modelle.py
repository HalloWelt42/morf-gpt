"""ORM-Modelle. Kennungen sind UUID-Hex-Strings, Zeiten UTC.

Die Tabellen bilden Werkstatt (Quellen, Audios, Transkripte, Aufträge) und Bibliothek
(Videos, Korrekturen, Chunks, Einbettungen, Unterhaltungen) ab. Die Bibliothek ist ohne
Werkstatt-Tabellen vollständig nutzbar (siehe docs/ARCHITEKTUR.md, Abschnitt 1 und 8).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ..config import einstellungen


def neue_id() -> str:
    return uuid.uuid4().hex


def jetzt() -> datetime:
    return datetime.now(UTC)


class Basis(DeclarativeBase):
    pass


class Quelle(Basis):
    __tablename__ = "quellen"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=neue_id)
    typ: Mapped[str] = mapped_column(String(32))  # tubevault
    name: Mapped[str] = mapped_column(String(200))
    basis_url: Mapped[str] = mapped_column(String(500))
    kanal_id: Mapped[str] = mapped_column(String(100))
    kanal_name: Mapped[str] = mapped_column(String(200), default="")
    kanal_beschreibung: Mapped[str] = mapped_column(Text, default="")
    # Filterregeln: mindest_dauer_s, typen (video/live/short), nur_heruntergeladene
    regeln: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
    zuletzt_abgeglichen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    erstellt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)

    videos: Mapped[list[Video]] = relationship(back_populates="quelle")


class Video(Basis):
    __tablename__ = "videos"
    __table_args__ = (
        UniqueConstraint("quelle_id", "extern_id", name="uq_video_quelle_extern"),
        Index("ix_videos_stufe", "stufe"),
        Index("ix_videos_serie_folge", "serie", "folge_nr"),
        Index("ix_videos_veroeffentlicht", "veroeffentlicht"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=neue_id)
    quelle_id: Mapped[str | None] = mapped_column(ForeignKey("quellen.id", ondelete="SET NULL"))
    extern_id: Mapped[str] = mapped_column(String(64))  # YouTube-Kennung
    original_url: Mapped[str] = mapped_column(String(500), default="")
    titel: Mapped[str] = mapped_column(Text, default="")
    beschreibung: Mapped[str] = mapped_column(Text, default="")
    veroeffentlicht: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dauer_s: Mapped[int | None] = mapped_column(Integer)
    typ: Mapped[str] = mapped_column(String(16), default="video")  # video, short, live
    aufrufe: Mapped[int | None] = mapped_column(Integer)
    schlagworte: Mapped[list[str]] = mapped_column(JSONB, default=list)
    kanal_name: Mapped[str] = mapped_column(String(200), default="")
    serie: Mapped[str] = mapped_column(String(32), default="")  # z. B. mmM
    folge_nr: Mapped[int | None] = mapped_column(Integer)
    miniatur_url: Mapped[str] = mapped_column(String(600), default="")
    miniatur_pfad: Mapped[str] = mapped_column(String(500), default="")
    metadaten_original: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    quelle_heruntergeladen: Mapped[bool] = mapped_column(Boolean, default=False)
    ausgewaehlt: Mapped[bool] = mapped_column(Boolean, default=False)
    auswahl_manuell: Mapped[bool] = mapped_column(Boolean, default=False)  # Nutzer hat entschieden
    stufe: Mapped[str] = mapped_column(String(16), default="entdeckt")
    fehler: Mapped[str] = mapped_column(Text, default="")
    prioritaet: Mapped[int] = mapped_column(Integer, default=0)
    notizen: Mapped[str] = mapped_column(Text, default="")
    erstellt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)
    aktualisiert: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt, onupdate=jetzt)

    quelle: Mapped[Quelle | None] = relationship(back_populates="videos")
    audio: Mapped[Audio | None] = relationship(back_populates="video", uselist=False, cascade="all, delete-orphan")
    transkripte: Mapped[list[Transkript]] = relationship(back_populates="video", cascade="all, delete-orphan")
    korrekturen: Mapped[list[Korrektur]] = relationship(back_populates="video", cascade="all, delete-orphan")
    chunks: Mapped[list[Chunk]] = relationship(back_populates="video", cascade="all, delete-orphan")
    auftraege: Mapped[list[Auftrag]] = relationship(back_populates="video", cascade="all, delete-orphan")


class Audio(Basis):
    __tablename__ = "audios"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=neue_id)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), unique=True)
    pfad: Mapped[str] = mapped_column(String(500))
    format: Mapped[str] = mapped_column(String(16), default="m4a")
    dauer_s: Mapped[float | None] = mapped_column(Float)
    groesse_bytes: Mapped[int | None] = mapped_column(Integer)
    abtastrate: Mapped[int | None] = mapped_column(Integer)
    kanaele: Mapped[int | None] = mapped_column(Integer)
    bezugsweg: Mapped[str] = mapped_column(String(32), default="")  # videostrom_ffmpeg, pi_extraktion
    erstellt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)

    video: Mapped[Video] = relationship(back_populates="audio")


class Transkript(Basis):
    __tablename__ = "transkripte"
    __table_args__ = (Index("ix_transkripte_video", "video_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=neue_id)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    engine: Mapped[str] = mapped_column(String(64), default="")
    modell: Mapped[str] = mapped_column(String(120), default="")
    sprache: Mapped[str] = mapped_column(String(16), default="de")
    volltext: Mapped[str] = mapped_column(Text, default="")
    # [{"start": 0.0, "end": 6.2, "text": "...", "words": [{"word","start","end"}]}]
    segmente: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    dauer_verarbeitung_s: Mapped[float | None] = mapped_column(Float)
    aktuell: Mapped[bool] = mapped_column(Boolean, default=True)
    erstellt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)

    video: Mapped[Video] = relationship(back_populates="transkripte")


class Korrektur(Basis):
    __tablename__ = "korrekturen"
    __table_args__ = (Index("ix_korrekturen_video", "video_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=neue_id)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    transkript_id: Mapped[str | None] = mapped_column(ForeignKey("transkripte.id", ondelete="SET NULL"))
    engine: Mapped[str] = mapped_column(String(64), default="")
    anbieter: Mapped[str] = mapped_column(String(120), default="")
    modell: Mapped[str] = mapped_column(String(120), default="")
    # [{"start": 0.0, "end": 41.3, "text": "...", "verworfen": false}]
    absaetze: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # [{"titel": "...", "start": 0.0, "end": 300.0, "kurz": "..."}]
    themen: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    zusammenfassung: Mapped[str] = mapped_column(Text, default="")
    aehnlichkeit: Mapped[float | None] = mapped_column(Float)
    bloecke_gesamt: Mapped[int] = mapped_column(Integer, default=0)
    bloecke_verworfen: Mapped[int] = mapped_column(Integer, default=0)
    dauer_verarbeitung_s: Mapped[float | None] = mapped_column(Float)
    manuell_bearbeitet: Mapped[bool] = mapped_column(Boolean, default=False)
    aktuell: Mapped[bool] = mapped_column(Boolean, default=True)
    erstellt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)

    video: Mapped[Video] = relationship(back_populates="korrekturen")


class Chunk(Basis):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("video_id", "reihenfolge", name="uq_chunk_video_reihenfolge"),
        Index("ix_chunks_video", "video_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=neue_id)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    korrektur_id: Mapped[str | None] = mapped_column(ForeignKey("korrekturen.id", ondelete="SET NULL"))
    reihenfolge: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    start_s: Mapped[float] = mapped_column(Float, default=0.0)
    end_s: Mapped[float] = mapped_column(Float, default=0.0)
    zeichen: Mapped[int] = mapped_column(Integer, default=0)
    thema: Mapped[str] = mapped_column(Text, default="")
    ueberlappung_vor: Mapped[int] = mapped_column(Integer, default=0)
    ueberlappung_nach: Mapped[int] = mapped_column(Integer, default=0)
    manuell_bearbeitet: Mapped[bool] = mapped_column(Boolean, default=False)
    erstellt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)
    aktualisiert: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt, onupdate=jetzt)

    video: Mapped[Video] = relationship(back_populates="chunks")
    einbettungen: Mapped[list[Einbettung]] = relationship(back_populates="chunk", cascade="all, delete-orphan")


class Einbettung(Basis):
    __tablename__ = "einbettungen"
    __table_args__ = (
        UniqueConstraint("chunk_id", "modell", name="uq_einbettung_chunk_modell"),
        Index("ix_einbettungen_modell", "modell"),
        Index(
            "ix_einbettungen_vektor_hnsw",
            "vektor",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 96},
            postgresql_ops={"vektor": "vector_cosine_ops"},
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=neue_id)
    chunk_id: Mapped[str] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"))
    anbieter: Mapped[str] = mapped_column(String(120), default="")
    modell: Mapped[str] = mapped_column(String(120))
    dimension: Mapped[int] = mapped_column(Integer)
    vektor: Mapped[list[float]] = mapped_column(Vector(einstellungen.einbettung_dimension))
    erstellt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)

    chunk: Mapped[Chunk] = relationship(back_populates="einbettungen")


class Auftrag(Basis):
    __tablename__ = "auftraege"
    __table_args__ = (
        Index("ix_auftraege_status_art", "status", "art"),
        Index("ix_auftraege_video", "video_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=neue_id)
    art: Mapped[str] = mapped_column(String(32))
    video_id: Mapped[str | None] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16), default="wartend")
    prioritaet: Mapped[int] = mapped_column(Integer, default=0)
    versuche: Mapped[int] = mapped_column(Integer, default=0)
    fortschritt: Mapped[float] = mapped_column(Float, default=0.0)
    meldung: Mapped[str] = mapped_column(Text, default="")
    fehler: Mapped[str] = mapped_column(Text, default="")
    parameter: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    ergebnis: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    gestartet: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    beendet: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    herzschlag: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    erstellt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)

    video: Mapped[Video | None] = relationship(back_populates="auftraege")
    protokoll: Mapped[list[AuftragProtokoll]] = relationship(
        back_populates="auftrag", cascade="all, delete-orphan", order_by="AuftragProtokoll.zeit"
    )


class AuftragProtokoll(Basis):
    __tablename__ = "auftrag_protokoll"
    __table_args__ = (Index("ix_auftrag_protokoll_auftrag_zeit", "auftrag_id", "zeit"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    auftrag_id: Mapped[str] = mapped_column(ForeignKey("auftraege.id", ondelete="CASCADE"))
    zeit: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)
    stufe: Mapped[str] = mapped_column(String(8), default="info")  # info, warn, fehler
    text: Mapped[str] = mapped_column(Text)

    auftrag: Mapped[Auftrag] = relationship(back_populates="protokoll")


class Einstellung(Basis):
    __tablename__ = "einstellungen"

    schluessel: Mapped[str] = mapped_column(String(120), primary_key=True)
    wert: Mapped[Any] = mapped_column(JSONB)
    aktualisiert: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt, onupdate=jetzt)


class Anbieter(Basis):
    __tablename__ = "anbieter"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=neue_id)
    name: Mapped[str] = mapped_column(String(120))
    typ: Mapped[str] = mapped_column(String(32))  # lmstudio, openai_kompatibel, fastembed
    art: Mapped[str] = mapped_column(String(16))  # sprachmodell, einbettung
    basis_url: Mapped[str] = mapped_column(String(500), default="")
    api_schluessel: Mapped[str] = mapped_column(String(500), default="")
    modell: Mapped[str] = mapped_column(String(200), default="")
    parameter: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
    erstellt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)
    aktualisiert: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt, onupdate=jetzt)


class Werkzeug(Basis):
    """Ein fremder Dienst oder ein Werkzeug, das der Chat neben der Bibliothek befragen kann."""

    __tablename__ = "werkzeuge"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=neue_id)
    name: Mapped[str] = mapped_column(String(120))
    typ: Mapped[str] = mapped_column(String(32))  # http_json, mcp
    beschreibung: Mapped[str] = mapped_column(Text, default="")  # für das Sprachmodell
    konfiguration: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Entdeckte Werkzeuge eines MCP-Servers: [{"name","beschreibung","parameter_schema","aktiv"}]
    entdeckt: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
    vorausgewaehlt: Mapped[bool] = mapped_column(Boolean, default=False)  # im Chat vorab an
    zuletzt_geprueft: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pruefung: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # {"ok": bool, "hinweis": str}
    erstellt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)
    aktualisiert: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt, onupdate=jetzt)


class Unterhaltung(Basis):
    __tablename__ = "unterhaltungen"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=neue_id)
    titel: Mapped[str] = mapped_column(String(300), default="Neue Unterhaltung")
    suchparameter: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    erstellt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)
    aktualisiert: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt, onupdate=jetzt)

    nachrichten: Mapped[list[Nachricht]] = relationship(
        back_populates="unterhaltung", cascade="all, delete-orphan", order_by="Nachricht.erstellt"
    )


class Nachricht(Basis):
    __tablename__ = "nachrichten"
    __table_args__ = (Index("ix_nachrichten_unterhaltung", "unterhaltung_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=neue_id)
    unterhaltung_id: Mapped[str] = mapped_column(ForeignKey("unterhaltungen.id", ondelete="CASCADE"))
    rolle: Mapped[str] = mapped_column(String(16))  # nutzer, assistent
    inhalt: Mapped[str] = mapped_column(Text, default="")
    # [{"chunk_id","video_id","titel","start_s","end_s","wert","benutzt":true}]
    stellen: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    parameter: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    modell: Mapped[str] = mapped_column(String(200), default="")
    dauer_ms: Mapped[int | None] = mapped_column(Integer)
    tokens_ein: Mapped[int | None] = mapped_column(Integer)
    tokens_aus: Mapped[int | None] = mapped_column(Integer)
    fehler: Mapped[str] = mapped_column(Text, default="")
    erstellt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=jetzt)

    unterhaltung: Mapped[Unterhaltung] = relationship(back_populates="nachrichten")
