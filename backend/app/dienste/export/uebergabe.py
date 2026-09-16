"""Übergabe: alles Entstandene als Ordner für einen Empfänger, der die Bibliothek ohne die
Werkstatt weiterbetreiben soll.

Ein Ordner je Übergabe, benannt nach einer zufälligen Kennung (UUID). Wer den Ordner unter
einer Webadresse ablegt, gibt mit der Adresse den Zugang weiter: nur wer die Kennung kennt,
findet die Dateien. Inhalt:

    uebergabe.json                    Manifest: Kennung, Teile mit Größe und Prüfsumme, Zähler
    PRUEFSUMMEN.sha256                dieselben Prüfsummen im Format von sha256sum
    ANLEITUNG.md                      Was der Empfänger tun muss
    morf-gpt-bibliothek-<datum>.tar.gz   das Bibliothekspaket (paket.py), mit Transkripten und Dokumenten
    audio-01.tar, audio-02.tar, ...   die Audiodateien, unkomprimiert, höchstens TEIL_BYTES je Teil
    modelle.tar                       die lokalen Modelle (Whisper, Einbettung), soweit vorhanden

Audio ist schon komprimiert (AAC), darum unkomprimierte Teile: Packen und Prüfen bleiben
schnell, und ein Abbruch beim Herunterladen kostet höchstens einen Teil. Geheimnisse
(Schlüssel, Anbieter, Einstellungen, Aufträge, Unterhaltungen) sind nie Teil einer Übergabe.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
import tarfile
import uuid
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy import select

from ...db.engine import sitzung
from ...db.modelle import Audio, Video
from ..audio import bezug
from . import paket

log = logging.getLogger(__name__)

FORMAT_KENNUNG = "morf-gpt-uebergabe"
FORMAT_VERSION = 1
MANIFEST = "uebergabe.json"
PRUEFSUMMEN = "PRUEFSUMMEN.sha256"
ANLEITUNG = "ANLEITUNG.md"
AUDIO_PRAEFIX = "audio-"
MODELLE_DATEI = "modelle.tar"
AUDIO_ORDNER = "audio"
# Höchstgröße eines Audioteils; groß genug für wenige Teile, klein genug für einen Neuversuch.
TEIL_BYTES = 2 * 1024**3
LESE_BLOCK = 4 * 1024 * 1024
# Modellablagen mit Symbolverknüpfungen (Hugging-Face-Zwischenspeicher): Verknüpfungen werden aufgelöst,
# die Blob-Ordner und Sperrdateien bleiben draußen, sonst reist jedes Gewicht doppelt.
MODELL_AUSLASSEN = ("blobs", ".locks", ".DS_Store", "CACHEDIR.TAG")

Fortschrittsmelder = Callable[[float, str], Awaitable[None]]


class UebergabeFehler(RuntimeError):
    """Eine Übergabe konnte nicht erstellt oder geholt werden (sprechende Meldung)."""


class Teil(BaseModel):
    name: str
    art: str  # bibliothek | audio | modelle
    bytes: int
    sha256: str
    eintraege: int = 0


class Uebergabemanifest(BaseModel):
    format: str = FORMAT_KENNUNG
    format_version: int = FORMAT_VERSION
    kennung: str
    erstellt: datetime
    version: str
    bibliothek: str
    teile: list[Teil] = Field(default_factory=list)
    audio_dateien: int = 0
    audio_bytes: int = 0
    modelle: list[str] = Field(default_factory=list)
    zaehler: paket.Zaehler = Field(default_factory=paket.Zaehler)

    @property
    def gesamt_bytes(self) -> int:
        return sum(t.bytes for t in self.teile)


@dataclass(slots=True)
class Uebergabeergebnis:
    ordner: Path
    manifest: Uebergabemanifest


@dataclass(slots=True)
class Audiodatei:
    video_id: str
    pfad: Path
    bytes: int


# --------------------------------------------------------------------------- Hilfen
def sha256_datei(pfad: Path) -> str:
    h = hashlib.sha256()
    with pfad.open("rb") as f:
        while block := f.read(LESE_BLOCK):
            h.update(block)
    return h.hexdigest()


def pruefe_kennung(kennung: str) -> str:
    try:
        return str(uuid.UUID(kennung))
    except ValueError as e:
        raise UebergabeFehler(f"Ungültige Übergabekennung '{kennung}'") from e


def _groesse(byte: int) -> str:
    if byte >= 1024**3:
        return f"{byte / 1024**3:.2f} GB".replace(".", ",")
    return f"{byte / 1024**2:.1f} MB".replace(".", ",")


async def _melde(melde: Fortschrittsmelder | None, anteil: float, meldung: str) -> None:
    if melde is not None:
        await melde(anteil, meldung)


def audio_in_teile(dateien: list[Audiodatei], teil_bytes: int = TEIL_BYTES) -> list[list[Audiodatei]]:
    """Verteilt die Dateien der Reihe nach auf Teile, die teil_bytes nicht überschreiten
    (eine einzelne größere Datei bildet einen eigenen Teil)."""
    teile: list[list[Audiodatei]] = []
    aktuell: list[Audiodatei] = []
    summe = 0
    for d in dateien:
        if aktuell and summe + d.bytes > teil_bytes:
            teile.append(aktuell)
            aktuell, summe = [], 0
        aktuell.append(d)
        summe += d.bytes
    if aktuell:
        teile.append(aktuell)
    return teile


def _audio_teil_schreiben(ziel: Path, dateien: list[Audiodatei]) -> None:
    with tarfile.open(ziel, "w") as tar:
        for d in dateien:
            tar.add(d.pfad, arcname=f"{AUDIO_ORDNER}/{d.video_id}{d.pfad.suffix.lower()}")


def _aktueller_schnappschuss(modellordner: Path) -> str | None:
    """Die Revision, auf die refs/main eines Hugging-Face-Modellordners zeigt; sonst der neueste Schnappschuss."""
    ref = modellordner / "refs" / "main"
    if ref.is_file():
        return ref.read_text(encoding="utf-8").strip() or None
    schnappschuesse = modellordner / "snapshots"
    if schnappschuesse.is_dir():
        kandidaten = sorted((p for p in schnappschuesse.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
        if kandidaten:
            return kandidaten[-1].name
    return None


def _hf_teil(rel: Path) -> tuple[Path, list[str]] | None:
    """(Modellordner relativ, Teile darunter) für Pfade in einem Hugging-Face-Modellordner models--org--name."""
    for i, teil in enumerate(rel.parts):
        if teil.startswith("models--"):
            return Path(*rel.parts[: i + 1]), list(rel.parts[i + 1 :])
    return None


def modell_dateien(modelle_verzeichnis: Path) -> Iterator[Path]:
    """Alle Dateien der Modellablage, die ein Empfänger braucht: bei Hugging-Face-Ordnern nur der aktuelle
    Schnappschuss und die Verweise, keine Blob-Ordner (Verknüpfungen werden beim Packen aufgelöst) und
    keine Sperrdateien; alles andere vollständig."""
    if not modelle_verzeichnis.is_dir():
        return
    aktuell: dict[Path, str | None] = {}
    for p in sorted(modelle_verzeichnis.rglob("*")):
        rel = p.relative_to(modelle_verzeichnis)
        if any(teil in MODELL_AUSLASSEN for teil in rel.parts):
            continue
        if not (p.is_file() or (p.is_symlink() and p.resolve().is_file())):
            continue
        hf = _hf_teil(rel)
        if hf is not None:
            ordner, unter = hf
            if ordner not in aktuell:
                aktuell[ordner] = _aktueller_schnappschuss(modelle_verzeichnis / ordner)
            if len(unter) >= 2 and unter[0] == "snapshots" and unter[1] != aktuell[ordner]:
                continue
        yield p


def modell_namen(modelle_verzeichnis: Path) -> list[str]:
    """Sprechende Namen der abgelegten Modelle: Hugging-Face-Ordner models--org--name als org/name, sonst
    der oberste Ordnername (ohne den Zwischenspeicherordner hf selbst)."""
    namen: set[str] = set()
    for p in modell_dateien(modelle_verzeichnis):
        rel = p.relative_to(modelle_verzeichnis)
        hf = _hf_teil(rel)
        if hf is not None:
            namen.add(hf[0].name.removeprefix("models--").replace("--", "/"))
        elif rel.parts[0] != "hf":
            namen.add(rel.parts[0])
    return sorted(namen)


def _modelle_schreiben(ziel: Path, modelle_verzeichnis: Path) -> int:
    anzahl = 0
    with tarfile.open(ziel, "w", dereference=True) as tar:
        for p in modell_dateien(modelle_verzeichnis):
            tar.add(p, arcname=str(p.relative_to(modelle_verzeichnis)))
            anzahl += 1
    return anzahl


async def audiodateien() -> list[Audiodatei]:
    """Audio aller Videos im Umfang, sortiert nach Video-Kennung; fehlende Dateien werden übersprungen."""
    async with sitzung() as s:
        stmt = (
            select(Audio.video_id, Audio.pfad)
            .join(Video, Video.id == Audio.video_id)
            .where(Video.ausgewaehlt.is_(True))
            .order_by(Audio.video_id)
        )
        rows = (await s.execute(stmt)).all()
    aus: list[Audiodatei] = []
    for video_id, pfad in rows:
        p = bezug.pfad_aufloesen(pfad)
        if p.is_file():
            aus.append(Audiodatei(video_id=video_id, pfad=p, bytes=p.stat().st_size))
    return aus


def anleitung(manifest: Uebergabemanifest) -> str:
    audio = [t for t in manifest.teile if t.art == "audio"]
    zeilen = [
        "# morf-gpt: Übergabe der Bibliothek",
        "",
        f"Erstellt am {manifest.erstellt.astimezone().strftime('%d.%m.%Y %H:%M')} mit morf-gpt {manifest.version}.",
        f"Kennung: {manifest.kennung}",
        "",
        "## Was hier liegt",
        "",
        f"- {manifest.bibliothek}: die Bibliothek ({manifest.zaehler.videos} Videos, {manifest.zaehler.chunks} Stücke, "
        f"{manifest.zaehler.einbettungen} Einbettungen, {manifest.zaehler.dokumente} Dokumente, Rohtranskripte, Korrekturen, "
        "Vorschaubilder). Damit funktionieren Chat, Suche und Belege sofort; nichts muss neu gerechnet werden.",
    ]
    if audio:
        zeilen.append(
            f"- {audio[0].name} bis {audio[-1].name}: die Audiodateien ({manifest.audio_dateien} Dateien, "
            f"{_groesse(manifest.audio_bytes)}), nur für den eingebauten Abspieler und zum erneuten Transkribieren."
        )
    if manifest.modelle:
        zeilen.append(
            f"- {MODELLE_DATEI}: die lokalen Modelle ({', '.join(manifest.modelle)}), damit nichts aus dem Netz geladen werden muss."
        )
    zeilen += [
        f"- {PRUEFSUMMEN}: Prüfsummen aller Teile (sha256sum -c {PRUEFSUMMEN}).",
        "",
        "Nicht enthalten, weil es dir gehört: Zugangsschlüssel zu Sprachmodell-Diensten, Anbieter, Einstellungen.",
        "",
        "## So geht es weiter",
        "",
        "1. morf-gpt einrichten: das Projekt klonen (https://github.com/HalloWelt42/morf-gpt) und `./start.sh start`",
        "   ausführen; Voraussetzungen stehen in der README (Docker, Python 3.12 mit uv, Node 22, ffmpeg).",
        '2. In der Oberfläche unter Einstellungen, Umzug im Feld "Übergabe holen" die Adresse dieses Ordners',
        "   eintragen (die Webadresse mit der Kennung oder, wenn die Dateien schon auf deinem Rechner liegen, den",
        "   Ordnerpfad). morf-gpt lädt die Teile, prüft die Prüfsummen und übernimmt Bibliothek, Audio und Modelle.",
        '3. Unter Einstellungen, Anbieter die Rolle Einbettung auf "Lokal - bge-m3 (fastembed)" stellen: das',
        "   mitgelieferte Modell rechnet auf dem Prozessor und liefert dieselben Vektoren wie der Index. Dann ein",
        "   Sprachmodell für Chat und Korrektur eintragen: ein Dienst mit OpenAI-kompatibler Schnittstelle mit",
        "   deinem eigenen Schlüssel (Denkmodus aus) oder ein lokales Modell. Der Chat antwortet danach aus der",
        "   Bibliothek; Audio spielt der eingebaute Abspieler ab.",
        "4. Nur wenn du selbst neue Videos verarbeiten willst: der mitgelieferte Transkriptionsdienst startet mit",
        "   der Anwendung. Das Whisper-Modell in dieser Übergabe ist die MLX-Fassung für Apple Silicon; auf anderen",
        "   Rechnern lädt der Dienst beim ersten Auftrag selbst eine passende Fassung.",
        "",
        "Die Adresse mit der Kennung ist der Zugang: gib sie nur weiter, wer die Bibliothek bekommen soll.",
        "",
    ]
    return "\n".join(zeilen)


async def _teil(pfad: Path, art: str, eintraege: int) -> Teil:
    return Teil(name=pfad.name, art=art, bytes=pfad.stat().st_size, sha256=await asyncio.to_thread(sha256_datei, pfad), eintraege=eintraege)


# --------------------------------------------------------------------------- Erstellen
async def erstelle(
    quelle: paket.Datenquelle,
    wurzel: Path,
    *,
    version: str,
    dimension: int,
    mit_audio: bool,
    mit_modellen: bool,
    modelle_verzeichnis: Path,
    melde: Fortschrittsmelder | None = None,
    teil_bytes: int = TEIL_BYTES,
) -> Uebergabeergebnis:
    """Schreibt einen Übergabeordner unter wurzel/<kennung> und gibt Ordner und Manifest zurück."""
    kennung = str(uuid.uuid4())
    ordner = wurzel / kennung
    ordner.mkdir(parents=True, exist_ok=False)
    teile: list[Teil] = []
    try:
        await _melde(melde, 0.0, "Bibliothekspaket wird geschrieben")

        async def melde_paket(anteil: float, meldung: str) -> None:
            await _melde(melde, anteil * 0.3, f"Bibliothek: {meldung}")

        export = await paket.exportiere(quelle, ordner, version=version, dimension=dimension, mit_transkripten=True, melde=melde_paket)
        teile.append(await _teil(export.datei, "bibliothek", export.manifest.zaehler.videos))

        audio_dateien = 0
        audio_bytes = 0
        if mit_audio:
            dateien = await audiodateien()
            gruppen = audio_in_teile(dateien, teil_bytes)
            audio_dateien = len(dateien)
            audio_bytes = sum(d.bytes for d in dateien)
            for nr, gruppe in enumerate(gruppen, start=1):
                name = f"{AUDIO_PRAEFIX}{nr:02d}.tar"
                anteil = 0.3 + 0.55 * (nr - 1) / max(1, len(gruppen))
                await _melde(melde, anteil, f"Audio: Teil {nr} von {len(gruppen)} ({len(gruppe)} Dateien)")
                ziel = ordner / name
                await asyncio.to_thread(_audio_teil_schreiben, ziel, gruppe)
                teile.append(await _teil(ziel, "audio", len(gruppe)))

        modelle: list[str] = []
        if mit_modellen:
            modelle = modell_namen(modelle_verzeichnis)
            if modelle:
                await _melde(melde, 0.87, f"Modelle werden gepackt: {', '.join(modelle)}")
                ziel = ordner / MODELLE_DATEI
                anzahl = await asyncio.to_thread(_modelle_schreiben, ziel, modelle_verzeichnis)
                teile.append(await _teil(ziel, "modelle", anzahl))

        manifest = Uebergabemanifest(
            kennung=kennung,
            erstellt=datetime.now(UTC),
            version=version,
            bibliothek=export.datei.name,
            teile=teile,
            audio_dateien=audio_dateien,
            audio_bytes=audio_bytes,
            modelle=modelle,
            zaehler=export.manifest.zaehler,
        )
        await _melde(melde, 0.97, "Manifest, Prüfsummen und Anleitung werden geschrieben")
        (ordner / MANIFEST).write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        (ordner / PRUEFSUMMEN).write_text("".join(f"{t.sha256}  {t.name}\n" for t in teile), encoding="utf-8")
        (ordner / ANLEITUNG).write_text(anleitung(manifest), encoding="utf-8")
    except BaseException:
        shutil.rmtree(ordner, ignore_errors=True)
        raise
    await _melde(melde, 1.0, f"Fertig: Übergabe {kennung} ({_groesse(manifest.gesamt_bytes)} in {len(teile)} Teilen)")
    return Uebergabeergebnis(ordner=ordner, manifest=manifest)


def manifest_lesen(pfad: Path) -> Uebergabemanifest:
    try:
        return Uebergabemanifest.model_validate_json(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise UebergabeFehler(f"Das Übergabe-Manifest '{pfad}' ist unlesbar: {e}") from e


def vorhandene(wurzel: Path) -> list[Uebergabemanifest]:
    """Alle fertigen Übergaben unter wurzel (Ordner mit Manifest), neueste zuerst."""
    aus: list[Uebergabemanifest] = []
    if not wurzel.is_dir():
        return aus
    for ordner in wurzel.iterdir():
        datei = ordner / MANIFEST
        if ordner.is_dir() and datei.is_file():
            try:
                aus.append(manifest_lesen(datei))
            except UebergabeFehler as e:
                log.warning("Übergabe %s übersprungen: %s", ordner.name, e)
    aus.sort(key=lambda m: m.erstellt, reverse=True)
    return aus
