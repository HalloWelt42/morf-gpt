"""Rundreise des Bibliothekspakets ohne Datenbank: Fake-Quelle schreibt, Fake-Ziel liest.

Alle Dateien entstehen unter backend/.test-tmp/export/<Kennung> und werden nach jedem
Test entfernt.
"""

from __future__ import annotations

import shutil
import tarfile
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

import pytest

from app.dienste.export import paket
from app.dienste.export.paket import (
    AbschnittZeile,
    ChunkZeile,
    DokumentChunkZeile,
    Dokumentexport,
    DokumentZeile,
    EinbettungZeile,
    KorrekturZeile,
    Manifest,
    PaketFehler,
    TranskriptZeile,
    Videoexport,
    Videostand,
    VideoZeile,
    VorhandenesVideo,
    VorhandeneVideos,
    Zaehler,
)
from app.domaene.fliessband import Dokumentstufe, Stufe

TEST_WURZEL = Path(__file__).resolve().parents[1] / ".test-tmp" / "export"
DIMENSION = 4
ZEIT = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


@pytest.fixture
def ordner() -> Iterator[Path]:
    pfad = TEST_WURZEL / uuid.uuid4().hex
    pfad.mkdir(parents=True)
    try:
        yield pfad
    finally:
        shutil.rmtree(pfad, ignore_errors=True)


# --------------------------------------------------------------------------- Beispieldaten
def _video(nr: int, extern_id: str) -> VideoZeile:
    return VideoZeile(
        id=f"video{nr:02d}" + "0" * 25,
        extern_id=extern_id,
        original_url=f"https://youtu.be/{extern_id}",
        titel=f"mmM#{nr} Größenordnungen und Übergänge",
        beschreibung="Ein Erklärvideo über Straßen, Flüsse und Brücken.",
        veroeffentlicht=ZEIT,
        dauer_s=1200 + nr,
        typ="video",
        aufrufe=1000,
        schlagworte=["mathe", "größe"],
        kanal_name="morf",
        serie="mmM",
        folge_nr=nr,
        ausgewaehlt=True,
        auswahl_manuell=False,
        notizen="",
        stufe="eingebettet",
    )


def _transkript(video_id: str) -> TranskriptZeile:
    return TranskriptZeile(
        id="t" + video_id[1:],
        video_id=video_id,
        engine="whisper",
        modell="large-v3",
        sprache="de",
        volltext="rohtext äöü",
        segmente=[{"start": 0.0, "end": 3.0, "text": "rohtext äöü"}],
        erstellt=ZEIT,
    )


def _korrektur(video_id: str, transkript_id: str | None) -> KorrekturZeile:
    return KorrekturZeile(
        id="k" + video_id[1:],
        video_id=video_id,
        transkript_id=transkript_id,
        engine="sprachmodell",
        anbieter="lokal",
        modell="qwen",
        absaetze=[{"start": 0.0, "end": 3.0, "text": "Rohtext äöü."}],
        themen=[{"titel": "Einstieg", "start": 0.0, "end": 3.0, "kurz": "Übersicht"}],
        zusammenfassung="Kurz und bündig.",
        aehnlichkeit=0.97,
        bloecke_gesamt=1,
        erstellt=ZEIT,
    )


def _chunk(video_id: str, korrektur_id: str | None, nr: int) -> ChunkZeile:
    return ChunkZeile(
        id=f"c{nr}" + video_id[2:],
        video_id=video_id,
        korrektur_id=korrektur_id,
        reihenfolge=nr,
        text=f"Stück {nr} über Straßen.",
        start_s=nr * 10.0,
        end_s=nr * 10.0 + 9.5,
        zeichen=24,
        thema="Einstieg",
        erstellt=ZEIT,
    )


def _einbettung(chunk_id: str, modell: str = "bge-m3") -> EinbettungZeile:
    return EinbettungZeile(chunk_id=chunk_id, modell=modell, anbieter="lmstudio", dimension=DIMENSION, vektor=[0.1, 0.2, 0.3, 0.4])


DOKUMENT_ID = "dok" + "1" * 29


def _dokument() -> DokumentZeile:
    return DokumentZeile(
        id=DOKUMENT_ID,
        titel="Das gesellschaftliche Problem",
        autor="M. Q. Flink",
        art="epub",
        sprache="de",
        dateiname="buch.epub",
        groesse_bytes=12,
        zeichen=40,
        felder_manuell=["titel"],
        stufe="eingebettet",
    )


def _abschnitt(nr: int) -> AbschnittZeile:
    return AbschnittZeile(
        id=f"abs{nr}" + "0" * 28,
        dokument_id=DOKUMENT_ID,
        reihenfolge=nr,
        ebene=1,
        titel=f"Kapitel {nr}",
        text="Text äöü",
        zeichen=8,
        erstellt=ZEIT,
    )


def _dokument_chunk(nr: int, abschnitt_id: str | None) -> DokumentChunkZeile:
    return DokumentChunkZeile(
        id=f"dc{nr}" + "0" * 29,
        dokument_id=DOKUMENT_ID,
        abschnitt_id=abschnitt_id,
        reihenfolge=nr,
        text=f"Dokumentstück {nr}",
        zeichen=15,
        thema=f"Kapitel {nr}",
        position_von=nr * 10,
        position_bis=nr * 10 + 9,
        erstellt=ZEIT,
    )


class FakeQuelle:
    """Zwei Videos: das erste voll verarbeitet mit Vorschaubild, das zweite nur gestückelt. Dazu ein
    Dokument mit zwei Abschnitten, zwei Stücken (eines eingebettet) und Originaldatei."""

    def __init__(self, miniatur: Path | None, dokument_datei: Path | None = None) -> None:
        self.v1 = _video(1, "abcDEF12345")
        self.v2 = _video(2, "xyzXYZ67890")
        self.miniatur = miniatur
        self.t1 = _transkript(self.v1.id)
        self.k1 = _korrektur(self.v1.id, self.t1.id)
        self.k2 = _korrektur(self.v2.id, None)
        self.c = [_chunk(self.v1.id, self.k1.id, 0), _chunk(self.v1.id, self.k1.id, 1), _chunk(self.v2.id, self.k2.id, 0)]
        self.d = _dokument()
        self.dokument_datei = dokument_datei
        self.a = [_abschnitt(1), _abschnitt(2)]
        self.dc = [_dokument_chunk(1, self.a[0].id), _dokument_chunk(2, "unbekannt")]
        self.e = [_einbettung(self.c[0].id), _einbettung(self.c[1].id), _einbettung(self.c[1].id, "andere"), _einbettung(self.dc[0].id)]

    async def zaehler(self) -> Zaehler:
        return Zaehler(
            videos=2, transkripte=1, korrekturen=2, chunks=3, einbettungen=4, dokumente=1, dokument_abschnitte=2, dokument_chunks=2
        )

    async def dokumente(self) -> AsyncIterator[Dokumentexport]:
        yield Dokumentexport(zeile=self.d, datei=self.dokument_datei)

    async def dokument_abschnitte(self) -> AsyncIterator[AbschnittZeile]:
        for a in self.a:
            yield a

    async def dokument_chunks(self) -> AsyncIterator[DokumentChunkZeile]:
        for c in self.dc:
            yield c

    async def videos(self) -> AsyncIterator[Videoexport]:
        yield Videoexport(zeile=self.v1, miniatur_datei=self.miniatur)
        yield Videoexport(zeile=self.v2, miniatur_datei=None)

    async def transkripte(self) -> AsyncIterator[TranskriptZeile]:
        yield self.t1

    async def korrekturen(self) -> AsyncIterator[KorrekturZeile]:
        yield self.k1
        yield self.k2

    async def chunks(self) -> AsyncIterator[ChunkZeile]:
        for c in self.c:
            yield c

    async def einbettungen(self) -> AsyncIterator[EinbettungZeile]:
        for e in self.e:
            yield e


class FakeZiel:
    """Merkt sich alles, was der Import tut, in einfachen Wörterbüchern."""

    def __init__(self, ordner: Path, vorhandene: dict[str, VorhandenesVideo] | None = None) -> None:
        self.ordner = ordner
        self.vorhandene = vorhandene or {}  # extern_id -> Video im Ziel
        self.angelegt: dict[str, VideoZeile] = {}
        self.aktualisiert: dict[str, tuple[VideoZeile, bool]] = {}
        self.geloescht: list[tuple[str, str]] = []
        self.transkripte: list[TranskriptZeile] = []
        self.korrekturen: list[KorrekturZeile] = []
        self.chunks: list[ChunkZeile] = []
        self.einbettungen: list[EinbettungZeile] = []
        self.miniaturen: dict[str, bytes] = {}
        self.stufen: dict[str, tuple[Stufe, str | None]] = {}
        self.abgeschlossen = False
        self.vorhandene_dok: dict[str, str] = {}
        self.dokumente_angelegt: dict[str, DokumentZeile] = {}
        self.dokumente_aktualisiert: dict[str, DokumentZeile] = {}
        self.abschnitte: list[AbschnittZeile] = []
        self.dokument_chunks: list[DokumentChunkZeile] = []
        self.dokument_dateien: dict[str, bytes] = {}
        self.dokument_stufen: dict[str, tuple[Dokumentstufe, str | None]] = {}

    async def vorhandene_dokumente(self) -> dict[str, str]:
        return dict(self.vorhandene_dok)

    async def dokument_anlegen(self, zeile: DokumentZeile) -> None:
        self.dokumente_angelegt[zeile.id] = zeile

    async def dokument_aktualisieren(self, zeile: DokumentZeile) -> None:
        self.dokumente_aktualisiert[zeile.id] = zeile

    async def dokument_abschnitte_loeschen(self, dokument_id: str) -> None:
        self.geloescht.append(("abschnitte", dokument_id))

    async def dokument_chunks_loeschen(self, dokument_id: str) -> None:
        self.geloescht.append(("dokument_chunks", dokument_id))

    async def dokument_abschnitte_einfuegen(self, zeilen: list[AbschnittZeile]) -> None:
        self.abschnitte.extend(zeilen)

    async def dokument_chunks_einfuegen(self, zeilen: list[DokumentChunkZeile]) -> None:
        self.dokument_chunks.extend(zeilen)

    async def dokument_datei_ablegen(self, dokument_id: str, endung: str, daten: IO[bytes]) -> str:
        self.dokument_dateien[dokument_id] = daten.read()
        return f"/ablage/dokumente/{dokument_id}{endung}"

    async def dokument_abschliessen(self, dokument_id: str, stufe: Dokumentstufe, datei_pfad: str | None) -> None:
        self.dokument_stufen[dokument_id] = (stufe, datei_pfad)

    async def vorhandene_videos(self) -> VorhandeneVideos:
        return VorhandeneVideos(je_extern_id=dict(self.vorhandene), ids={v.id for v in self.vorhandene.values()})

    async def video_anlegen(self, video_id: str, zeile: VideoZeile) -> None:
        self.angelegt[video_id] = zeile

    async def video_aktualisieren(self, video_id: str, zeile: VideoZeile, ausgewaehlt_uebernehmen: bool) -> None:
        self.aktualisiert[video_id] = (zeile, ausgewaehlt_uebernehmen)

    async def transkripte_loeschen(self, video_id: str) -> None:
        self.geloescht.append(("transkripte", video_id))

    async def korrekturen_loeschen(self, video_id: str) -> None:
        self.geloescht.append(("korrekturen", video_id))

    async def chunks_loeschen(self, video_id: str) -> None:
        self.geloescht.append(("chunks", video_id))

    async def transkripte_einfuegen(self, zeilen: list[TranskriptZeile]) -> None:
        self.transkripte.extend(zeilen)

    async def korrekturen_einfuegen(self, zeilen: list[KorrekturZeile]) -> None:
        self.korrekturen.extend(zeilen)

    async def chunks_einfuegen(self, zeilen: list[ChunkZeile]) -> None:
        self.chunks.extend(zeilen)

    async def einbettungen_einfuegen(self, zeilen: list[EinbettungZeile]) -> None:
        self.einbettungen.extend(zeilen)

    async def miniatur_ablegen(self, video_id: str, daten: IO[bytes]) -> str:
        self.miniaturen[video_id] = daten.read()
        return f"miniaturen/{video_id}.jpg"

    async def video_abschliessen(self, video_id: str, stufe: Stufe, miniatur_pfad: str | None) -> None:
        self.stufen[video_id] = (stufe, miniatur_pfad)

    async def abschliessen(self) -> None:
        self.abgeschlossen = True


async def _exportiere(ordner: Path, mit_transkripten: bool, miniatur: bool = True) -> tuple[paket.ExportErgebnis, FakeQuelle]:
    bild: Path | None = None
    if miniatur:
        bild = ordner / "bild.jpg"
        bild.write_bytes(b"\xff\xd8\xff\xe0JPEGPROBE")
    buch = ordner / "buch.epub"
    buch.write_bytes(b"PK\x03\x04EPUBPROBE")
    quelle = FakeQuelle(bild, buch)
    meldungen: list[tuple[float, str]] = []

    async def melde(anteil: float, meldung: str) -> None:
        meldungen.append((anteil, meldung))

    ergebnis = await paket.exportiere(
        quelle,
        ordner / "export",
        version="0.1.0",
        dimension=DIMENSION,
        mit_transkripten=mit_transkripten,
        melde=melde,
    )
    assert meldungen and meldungen[-1][0] == 1.0
    return ergebnis, quelle


# --------------------------------------------------------------------------- JSONL
def test_jsonl_rundreise_mit_umlauten(ordner: Path) -> None:
    pfad = ordner / "probe.jsonl"
    zeilen = [_chunk("video01" + "0" * 25, None, 0), _chunk("video01" + "0" * 25, None, 1)]
    with paket.JsonlSchreiber(pfad) as js:
        for z in zeilen:
            js.schreibe(z)
        assert js.anzahl == 2
    roh = pfad.read_text(encoding="utf-8")
    assert "Straßen" in roh and roh.count("\n") == 2
    with pfad.open("rb") as f:
        gelesen = list(paket.lese_jsonl(f, ChunkZeile, "probe.jsonl"))
    assert gelesen == zeilen


def test_jsonl_fehler_nennt_zeile(ordner: Path) -> None:
    pfad = ordner / "kaputt.jsonl"
    pfad.write_bytes(b'{"id":"a","video_id":"b","reihenfolge":0,"text":"x","erstellt":"2026-01-01T00:00:00Z"}\n{"id":1\n')
    with pfad.open("rb") as f, pytest.raises(PaketFehler, match="Zeile 2"):
        list(paket.lese_jsonl(f, ChunkZeile, "kaputt.jsonl"))


def test_jsonl_fehlendes_feld_wird_genannt(ordner: Path) -> None:
    pfad = ordner / "feld.jsonl"
    pfad.write_bytes(b'{"id":"a","video_id":"b","text":"x","erstellt":"2026-01-01T00:00:00Z"}\n')
    with pfad.open("rb") as f, pytest.raises(PaketFehler, match="reihenfolge"):
        list(paket.lese_jsonl(f, ChunkZeile, "feld.jsonl"))


# --------------------------------------------------------------------------- Export
async def test_export_schreibt_paket_in_richtiger_reihenfolge(ordner: Path) -> None:
    ergebnis, _ = await _exportiere(ordner, mit_transkripten=True)
    assert ergebnis.datei.name.startswith(paket.PAKET_PRAEFIX) and ergebnis.datei.name.endswith(".tar.gz")
    assert ergebnis.groesse_bytes > 0
    assert not list((ordner / "export").glob(".arbeit-*")), "Arbeitsverzeichnis muss weg sein"
    with tarfile.open(ergebnis.datei, "r:gz") as tar:
        namen = tar.getnames()
    assert namen == [
        "manifest.json",
        "videos.jsonl",
        "transkripte.jsonl",
        "korrekturen.jsonl",
        "chunks.jsonl",
        "dokumente.jsonl",
        "dokument_abschnitte.jsonl",
        "dokument_chunks.jsonl",
        "einbettungen.jsonl",
        "miniaturen/abcDEF12345.jpg",
        f"dokumente/{DOKUMENT_ID}.epub",
    ]
    m = ergebnis.manifest
    assert m.format == paket.FORMAT_KENNUNG and m.version == "0.1.0" and m.dimension == DIMENSION
    assert m.einbettung_modelle == ["andere", "bge-m3"]
    assert m.zaehler == Zaehler(
        videos=2,
        transkripte=1,
        korrekturen=2,
        chunks=3,
        einbettungen=4,
        miniaturen=1,
        dokumente=1,
        dokument_abschnitte=2,
        dokument_chunks=2,
        dokument_dateien=1,
    )


async def test_export_ohne_transkripte(ordner: Path) -> None:
    ergebnis, _ = await _exportiere(ordner, mit_transkripten=False, miniatur=False)
    with tarfile.open(ergebnis.datei, "r:gz") as tar:
        namen = tar.getnames()
    assert "transkripte.jsonl" not in namen and not any(n.startswith("miniaturen/") for n in namen)
    assert ergebnis.manifest.mit_transkripten is False
    assert ergebnis.manifest.zaehler.transkripte == 0 and ergebnis.manifest.zaehler.miniaturen == 0


async def test_export_bricht_bei_falscher_dimension_ab(ordner: Path) -> None:
    quelle = FakeQuelle(None)
    with pytest.raises(PaketFehler, match="Dimensionen"):
        await paket.exportiere(quelle, ordner / "export", version="0.1.0", dimension=3, mit_transkripten=False)
    assert not list((ordner / "export").iterdir()), "Nach einem Fehler bleibt nichts liegen"


# --------------------------------------------------------------------------- Import
async def test_import_in_leeres_ziel(ordner: Path) -> None:
    ergebnis, quelle = await _exportiere(ordner, mit_transkripten=True)
    ziel = FakeZiel(ordner)
    meldungen: list[str] = []

    async def melde(anteil: float, meldung: str) -> None:
        meldungen.append(meldung)

    zaehler = await paket.importiere(ergebnis.datei, ziel, erwartete_dimension=DIMENSION, melde=melde)

    assert ziel.abgeschlossen
    assert zaehler.videos_neu == 2 and zaehler.videos_aktualisiert == 0
    assert (zaehler.transkripte, zaehler.korrekturen, zaehler.chunks, zaehler.einbettungen, zaehler.miniaturen) == (1, 2, 3, 4, 1)
    assert zaehler.einbettung_modelle == ["andere", "bge-m3"] and zaehler.paket_version == "0.1.0"
    # Kennungen bleiben erhalten, Verweise zeigen auf die importierten Zeilen
    assert set(ziel.angelegt) == {quelle.v1.id, quelle.v2.id}
    assert ziel.angelegt[quelle.v1.id].miniatur is True and ziel.angelegt[quelle.v2.id].miniatur is False
    assert [k.transkript_id for k in ziel.korrekturen] == [quelle.t1.id, None]
    assert [c.korrektur_id for c in ziel.chunks] == [quelle.k1.id, quelle.k1.id, quelle.k2.id]
    assert ziel.einbettungen[0].vektor == [0.1, 0.2, 0.3, 0.4]
    # Vor dem Einfügen wird je Video genau einmal gelöscht
    assert ziel.geloescht.count(("chunks", quelle.v1.id)) == 1
    assert ("transkripte", quelle.v2.id) not in ziel.geloescht
    # Stufen: Video 1 voll eingebettet, Video 2 nur gestückelt (Chunk ohne Einbettung)
    assert ziel.stufen[quelle.v1.id] == (Stufe.EINGEBETTET, f"miniaturen/{quelle.v1.id}.jpg")
    assert ziel.stufen[quelle.v2.id] == (Stufe.GESTUECKELT, None)
    assert ziel.miniaturen[quelle.v1.id].startswith(b"\xff\xd8")
    assert meldungen[-1].startswith("Fertig")


async def test_import_gleicht_vorhandene_videos_ueber_extern_id_ab(ordner: Path) -> None:
    ergebnis, quelle = await _exportiere(ordner, mit_transkripten=False)
    bestehend = VorhandenesVideo(id="bestehend" + "0" * 23, stufe="eingebettet", auswahl_manuell=True)
    ziel = FakeZiel(ordner, vorhandene={quelle.v1.extern_id: bestehend})

    zaehler = await paket.importiere(ergebnis.datei, ziel, erwartete_dimension=DIMENSION)

    assert zaehler.videos_neu == 1 and zaehler.videos_aktualisiert == 1
    zeile, uebernehmen = ziel.aktualisiert[bestehend.id]
    assert zeile.extern_id == quelle.v1.extern_id and uebernehmen is False, "Handauswahl im Ziel bleibt"
    # Kinder tragen die Kennung des Ziels, nicht die der Quelle
    assert {c.video_id for c in ziel.chunks if c.reihenfolge in (0, 1) and c.id.endswith(quelle.v1.id[2:])} == {bestehend.id}
    assert ziel.stufen[bestehend.id][0] == Stufe.EINGEBETTET
    assert ziel.miniaturen and bestehend.id in ziel.miniaturen
    assert ("chunks", bestehend.id) in ziel.geloescht and ("korrekturen", bestehend.id) in ziel.geloescht
    assert ("transkripte", bestehend.id) not in ziel.geloescht, "Ohne Transkripte im Paket bleiben die alten"


async def test_import_lehnt_falsche_dimension_ab(ordner: Path) -> None:
    ergebnis, _ = await _exportiere(ordner, mit_transkripten=False)
    ziel = FakeZiel(ordner)
    with pytest.raises(PaketFehler, match="erwartet 1024"):
        await paket.importiere(ergebnis.datei, ziel, erwartete_dimension=1024)
    assert not ziel.angelegt and not ziel.abgeschlossen


def _paket_aus(ordner: Path, eintraege: list[tuple[str, bytes]]) -> Path:
    pfad = ordner / "hand.tar.gz"
    with tarfile.open(pfad, "w:gz") as tar:
        for name, inhalt in eintraege:
            datei = ordner / name.replace("/", "_")
            datei.write_bytes(inhalt)
            tar.add(datei, arcname=name)
    return pfad


def _manifest_bytes(**aenderungen: object) -> bytes:
    m = Manifest(version="0.1.0", erstellt=ZEIT, dimension=DIMENSION, zaehler=Zaehler(videos=1, chunks=1, einbettungen=1))
    return m.model_copy(update=aenderungen).model_dump_json().encode("utf-8")


async def test_import_ohne_manifest_am_anfang(ordner: Path) -> None:
    pfad = _paket_aus(ordner, [("videos.jsonl", _video(1, "abc").model_dump_json().encode("utf-8") + b"\n")])
    with pytest.raises(PaketFehler, match="Manifest"):
        await paket.importiere(pfad, FakeZiel(ordner), erwartete_dimension=DIMENSION)


async def test_import_fremdes_format_und_neuere_version(ordner: Path) -> None:
    pfad = _paket_aus(ordner, [("manifest.json", _manifest_bytes(format="anderes"))])
    with pytest.raises(PaketFehler, match="stammt nicht"):
        await paket.importiere(pfad, FakeZiel(ordner), erwartete_dimension=DIMENSION)
    pfad = _paket_aus(ordner, [("manifest.json", _manifest_bytes(format_version=paket.FORMAT_VERSION + 1))])
    with pytest.raises(PaketFehler, match="neuer"):
        await paket.importiere(pfad, FakeZiel(ordner), erwartete_dimension=DIMENSION)


async def test_import_einbettung_ohne_chunk_und_falscher_vektor(ordner: Path) -> None:
    video = _video(1, "abc")
    chunk = _chunk(video.id, None, 0)
    grund = [
        ("manifest.json", _manifest_bytes()),
        ("videos.jsonl", video.model_dump_json().encode("utf-8") + b"\n"),
        ("chunks.jsonl", chunk.model_dump_json().encode("utf-8") + b"\n"),
    ]
    fremd = _einbettung("unbekannt").model_dump_json().encode("utf-8") + b"\n"
    with pytest.raises(PaketFehler, match="fehlt im Paket"):
        await paket.importiere(_paket_aus(ordner, [*grund, ("einbettungen.jsonl", fremd)]), FakeZiel(ordner), erwartete_dimension=DIMENSION)
    kurz = _einbettung(chunk.id).model_copy(update={"vektor": [0.1, 0.2]}).model_dump_json().encode("utf-8") + b"\n"
    with pytest.raises(PaketFehler, match="statt 4 Dimensionen"):
        await paket.importiere(_paket_aus(ordner, [*grund, ("einbettungen.jsonl", kurz)]), FakeZiel(ordner), erwartete_dimension=DIMENSION)


async def test_import_kind_vor_videoliste(ordner: Path) -> None:
    chunk = _chunk("video01" + "0" * 25, None, 0)
    pfad = _paket_aus(ordner, [("manifest.json", _manifest_bytes()), ("chunks.jsonl", chunk.model_dump_json().encode("utf-8") + b"\n")])
    with pytest.raises(PaketFehler, match="vor der Videoliste"):
        await paket.importiere(pfad, FakeZiel(ordner), erwartete_dimension=DIMENSION)


async def test_import_keine_tar_datei(ordner: Path) -> None:
    pfad = ordner / "kein.tar.gz"
    pfad.write_bytes(b"das ist kein Archiv")
    with pytest.raises(PaketFehler, match="kein lesbares Paket|beschädigt"):
        await paket.importiere(pfad, FakeZiel(ordner), erwartete_dimension=DIMENSION)


# --------------------------------------------------------------------------- Stufenregel
@pytest.mark.parametrize(
    ("bestehend", "transkripte", "korrekturen", "chunks", "eingebettet", "erwartet"),
    [
        (None, 0, 0, 0, 0, Stufe.ENTDECKT),
        (None, 1, 0, 0, 0, Stufe.TRANSKRIBIERT),
        (None, 0, 1, 0, 0, Stufe.KORRIGIERT),
        (None, 0, 1, 2, 1, Stufe.GESTUECKELT),
        (None, 0, 1, 2, 2, Stufe.EINGEBETTET),
        (Stufe.EINGEBETTET, 0, 0, 0, 0, Stufe.EINGEBETTET),
        (Stufe.EINGEBETTET, 0, 1, 0, 0, Stufe.EINGEBETTET),
        (Stufe.EINGEBETTET, 0, 1, 3, 1, Stufe.GESTUECKELT),
        (Stufe.AUDIO, 0, 1, 0, 0, Stufe.KORRIGIERT),
        (Stufe.AUDIO, 0, 0, 2, 2, Stufe.EINGEBETTET),
    ],
)
def test_stufe_nach_import(
    bestehend: Stufe | None, transkripte: int, korrekturen: int, chunks: int, eingebettet: int, erwartet: Stufe
) -> None:
    stand = Videostand(
        ziel_id="x",
        neu=bestehend is None,
        bestehende_stufe=bestehend,
        transkripte=transkripte,
        korrekturen=korrekturen,
        chunks=chunks,
        chunks_eingebettet=eingebettet,
    )
    assert paket.stufe_nach_import(stand) == erwartet


# --------------------------------------------------------------------------- Namen
@pytest.mark.parametrize("name", ["morf-gpt-bibliothek-20260910-120000.tar.gz", "a.tar.gz", "x_y-1.2.tar.gz"])
def test_gueltige_paketnamen(name: str) -> None:
    assert paket.pruefe_paketname(name) == name


@pytest.mark.parametrize("name", ["../x.tar.gz", "ordner/x.tar.gz", ".versteckt.tar.gz", "x.zip", "x.tar.gz/", ""])
def test_ungueltige_paketnamen(name: str) -> None:
    with pytest.raises(PaketFehler):
        paket.pruefe_paketname(name)


def test_sicherer_dateiname() -> None:
    assert paket.sicherer_dateiname("../../böse datei.tar.gz") == "b_se_datei.tar.gz"
    assert paket.sicherer_dateiname(None) == "paket.tar.gz"
    assert paket.sicherer_dateiname("...") == "paket.tar.gz"


def test_vektor_kompakt_rundet() -> None:
    assert paket.vektor_kompakt([0.123456789123, 1.0]) == [0.12345679, 1.0]


# --------------------------------------------------------------------------- Dokumente
async def test_export_und_import_mit_dokumenten(ordner: Path) -> None:
    ergebnis, quelle = await _exportiere(ordner, mit_transkripten=True)
    with tarfile.open(ergebnis.datei, "r:gz") as tar:
        namen = tar.getnames()
    assert namen.index(paket.CHUNKS) < namen.index(paket.DOKUMENTE) < namen.index(paket.DOKUMENT_ABSCHNITTE)
    assert namen.index(paket.DOKUMENT_ABSCHNITTE) < namen.index(paket.DOKUMENT_CHUNKS) < namen.index(paket.EINBETTUNGEN)
    assert f"{paket.DOKUMENTE_ORDNER}/{DOKUMENT_ID}.epub" in namen and namen[-1].startswith(paket.DOKUMENTE_ORDNER + "/")
    z = ergebnis.manifest.zaehler
    assert (z.dokumente, z.dokument_abschnitte, z.dokument_chunks, z.dokument_dateien, z.einbettungen) == (1, 2, 2, 1, 4)
    assert ergebnis.manifest.format_version == 2

    ziel = FakeZiel(ordner)
    imp = await paket.importiere(ergebnis.datei, ziel, erwartete_dimension=DIMENSION)
    assert imp.dokumente_neu == 1 and imp.dokument_abschnitte == 2 and imp.dokument_chunks == 2 and imp.dokument_dateien == 1
    assert imp.einbettungen == 4
    assert ziel.dokumente_angelegt[DOKUMENT_ID].datei and ziel.dokumente_angelegt[DOKUMENT_ID].felder_manuell == ["titel"]
    assert ziel.dokument_dateien[DOKUMENT_ID] == b"PK\x03\x04EPUBPROBE"
    assert [c.abschnitt_id for c in ziel.dokument_chunks] == [quelle.a[0].id, None], "unbekannter Abschnitt wird gelöst"
    assert ("abschnitte", DOKUMENT_ID) in ziel.geloescht and ("dokument_chunks", DOKUMENT_ID) in ziel.geloescht
    # ein Stück von zweien eingebettet: gestückelt, nicht eingebettet
    assert ziel.dokument_stufen[DOKUMENT_ID] == (Dokumentstufe.GESTUECKELT, f"/ablage/dokumente/{DOKUMENT_ID}.epub")
    assert ziel.stufen[quelle.v1.id][0] == Stufe.EINGEBETTET


async def test_import_vorhandenes_dokument_wird_ersetzt(ordner: Path) -> None:
    ergebnis, _ = await _exportiere(ordner, mit_transkripten=False)
    ziel = FakeZiel(ordner)
    ziel.vorhandene_dok = {DOKUMENT_ID: "eingebettet"}
    imp = await paket.importiere(ergebnis.datei, ziel, erwartete_dimension=DIMENSION)
    assert imp.dokumente_neu == 0 and imp.dokumente_aktualisiert == 1
    assert DOKUMENT_ID in ziel.dokumente_aktualisiert and DOKUMENT_ID not in ziel.dokumente_angelegt


async def test_import_paket_ohne_dokumenttabellen_bleibt_lesbar(ordner: Path) -> None:
    """Ein Paket der Formatversion 1 kennt keine Dokumente; der Leser darf sie nicht vermissen."""
    ergebnis, _ = await _exportiere(ordner, mit_transkripten=False)
    alt = ordner / "alt.tar.gz"
    with tarfile.open(ergebnis.datei, "r:gz") as quelle, tarfile.open(alt, "w:gz") as ziel_tar:
        for mitglied in quelle:
            if mitglied.name.startswith("dokument") or mitglied.name == paket.EINBETTUNGEN:
                continue
            daten = quelle.extractfile(mitglied)
            ziel_tar.addfile(mitglied, daten)
    ziel = FakeZiel(ordner)
    imp = await paket.importiere(alt, ziel, erwartete_dimension=DIMENSION)
    assert imp.videos_neu == 2 and imp.dokumente_neu == 0 and not ziel.dokument_stufen


def test_dokumentstufe_nach_import() -> None:
    from app.dienste.export.paket import Dokumentstand, dokumentstufe_nach_import

    assert dokumentstufe_nach_import(Dokumentstand("d", True, None)) == Dokumentstufe.IMPORTIERT
    assert dokumentstufe_nach_import(Dokumentstand("d", True, None, chunks=3, chunks_eingebettet=2)) == Dokumentstufe.GESTUECKELT
    assert dokumentstufe_nach_import(Dokumentstand("d", True, None, chunks=3, chunks_eingebettet=3)) == Dokumentstufe.EINGEBETTET
