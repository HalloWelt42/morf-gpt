"""Tests für Dokumente: EPUB- und Markdown-Leser, Stückelung je Kapitel, Suche und Belege (ohne Datenbank)."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

from app.dienste.chat import prompts
from app.dienste.dokumente import basis, epub, markdown
from app.dienste.stueckelung import stueckler
from app.dienste.stufen import stueckelung as stufe_stueckelung
from app.dienste.suche.retrieval import Suchparameter, Treffer, begrenze_je_video, fuege_nachbarn_zusammen, nachbar_nummern

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

OPF = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Der Systembegriff</dc:title>
    <dc:creator>morf</dc:creator>
    <dc:language>de</dc:language>
    <dc:date>2024-05-01</dc:date>
    <dc:description>Ein Buch zur Probe.</dc:description>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="k1" href="kapitel1.xhtml" media-type="application/xhtml+xml"/>
    <item id="k2" href="text/kapitel2.xhtml" media-type="application/xhtml+xml"/>
    <item id="css" href="stil.css" media-type="text/css"/>
  </manifest>
  <spine><itemref idref="nav"/><itemref idref="k1"/><itemref idref="k2"/></spine>
</package>"""

NAV = """<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body>
<nav epub:type="toc"><ol>
<li><a href="kapitel1.xhtml">Erstes Kapitel</a></li>
<li><a href="text/kapitel2.xhtml">Zweites Kapitel</a><ol><li><a href="text/kapitel2.xhtml#u1">Unterpunkt</a></li></ol></li>
</ol></nav></body></html>"""

K1 = """<html xmlns="http://www.w3.org/1999/xhtml"><head><title>egal</title><style>p{}</style></head><body>
<h1>Erstes Kapitel</h1>
<p>Ein System ist eine Menge von Elementen, die miteinander in Beziehung stehen. Das ist der erste Satz.</p>
<p>Der zweite Absatz erklärt, warum Grenzen eine Entscheidung des Beobachters sind und keine Eigenschaft der Welt.</p>
</body></html>"""

K2 = """<html xmlns="http://www.w3.org/1999/xhtml"><body>
<p>Text vor der ersten Überschrift, der zum Kapitel aus dem Inhaltsverzeichnis gehört und lang genug ist.</p>
<h2 id="u1">Unterpunkt</h2>
<p>Hier steht ein Unterabschnitt mit genug Zeichen, damit er nicht als Rest verworfen wird.</p>
<script>alert("nicht sichtbar")</script>
</body></html>"""


def _epub() -> bytes:
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/content.opf", OPF)
        z.writestr("OEBPS/nav.xhtml", NAV)
        z.writestr("OEBPS/kapitel1.xhtml", K1)
        z.writestr("OEBPS/text/kapitel2.xhtml", K2)
        z.writestr("OEBPS/stil.css", "p{}")
    return puffer.getvalue()


def test_epub_metadaten_und_abschnitte() -> None:
    inhalt = epub.lese_epub(_epub(), "probe.epub")
    assert inhalt.titel == "Der Systembegriff" and inhalt.autor == "morf" and inhalt.sprache == "de"
    assert inhalt.veroeffentlicht is not None and inhalt.veroeffentlicht.year == 2024
    titel = [(a.titel, a.ebene) for a in inhalt.abschnitte]
    assert titel == [("Erstes Kapitel", 1), ("Zweites Kapitel", 1), ("Unterpunkt", 2)]
    assert "Beobachters" in inhalt.abschnitte[0].text and "\n\n" in inhalt.abschnitte[0].text
    assert "nicht sichtbar" not in inhalt.abschnitte[2].text
    assert inhalt.abschnitte[2].anker == "text/kapitel2.xhtml#u1"
    assert inhalt.zeichen > 200


def test_epub_kaputt() -> None:
    try:
        epub.lese_epub(b"kein zip", "x.epub")
    except basis.DokumentFehler as e:
        assert "Zip" in str(e)
    else:
        raise AssertionError("kaputtes EPUB muss einen DokumentFehler geben")


def test_markdown_abschnitte_und_kopf() -> None:
    quelle = """---
titel: Notizen zu morf
autor: Ich
---
# Einleitung

Ein **fetter** Satz mit [Link](https://x.example) und `Code`, lang genug für einen Abschnitt.

## Details

- erster Punkt mit genug Text, damit der Abschnitt bleibt
- zweiter Punkt

```
code bleibt als Text
```
"""
    inhalt = markdown.lese_markdown(quelle, "vorgabe")
    assert inhalt.titel == "Notizen zu morf" and inhalt.autor == "Ich"
    assert [a.titel for a in inhalt.abschnitte] == ["Einleitung", "Details"]
    assert "**" not in inhalt.abschnitte[0].text and "Link" in inhalt.abschnitte[0].text and "https" not in inhalt.abschnitte[0].text
    assert "- erster Punkt" in inhalt.abschnitte[1].text and "code bleibt" in inhalt.abschnitte[1].text


def test_text_ein_abschnitt() -> None:
    inhalt = markdown.lese_text("Erste Zeile als Titel\n\nAbsatz eins mit Text.\n\nAbsatz zwei mit noch mehr Text.", "vorgabe")
    assert inhalt.titel == "Erste Zeile als Titel"
    assert len(inhalt.abschnitte) == 1 and inhalt.abschnitte[0].text.count("\n\n") == 2


def test_art_aus_dateiname() -> None:
    assert basis.art_aus_dateiname("Buch.EPUB") == basis.ART_EPUB
    assert basis.art_aus_dateiname("x.md") == basis.ART_MARKDOWN
    try:
        basis.art_aus_dateiname("x.docx")
    except basis.DokumentFehler:
        pass
    else:
        raise AssertionError("unbekannte Endung muss scheitern")


@dataclass
class _Abschnitt:
    id: str
    ebene: int
    titel: str
    text: str
    position_von: int


def test_stueckelung_je_kapitel_mit_thema_und_abschnitt() -> None:
    a1 = _Abschnitt("a1", 1, "Kapitel eins", "Satz eins ist hier. " * 40, 0)
    a2 = _Abschnitt("a2", 2, "Unterpunkt", "Satz zwei folgt nun. " * 40, 900)
    a3 = _Abschnitt("a3", 1, "Kapitel zwei", "Satz drei zum Schluss. " * 40, 1800)
    gruppen = stufe_stueckelung.kapitel_gruppen([a1, a2, a3])  # type: ignore[list-item]
    assert [[a.id for a in g] for g in gruppen] == [["a1", "a2"], ["a3"]]
    absaetze, themen, bereiche = stufe_stueckelung.absaetze_und_themen(gruppen[0])  # type: ignore[arg-type]
    assert absaetze[0].text == "Kapitel eins" and [t.titel for t in themen] == ["Kapitel eins", "Unterpunkt"]
    stuecke = stueckler.stueckeln(absaetze, themen, 400, 60)
    assert len(stuecke) >= 3
    assert stuecke[0].thema == "Kapitel eins" and stuecke[-1].thema == "Unterpunkt"
    assert stufe_stueckelung._abschnitt_fuer(bereiche, (stuecke[-1].start_s + stuecke[-1].end_s) / 2) == "a2"


def _t(chunk_id: str, werk: str, art: str, reihenfolge: int, wert: float = 0.5) -> Treffer:
    if art == "dokument":
        return Treffer(
            chunk_id,
            "",
            "Buch",
            "",
            None,
            0,
            0,
            f"t{reihenfolge}",
            wert,
            reihenfolge,
            "Kap",
            "",
            "",
            art="dokument",
            dokument_id=werk,
            abschnitt="Kap",
            position_von=reihenfolge * 10,
        )
    return Treffer(chunk_id, werk, "Video", "mmM", 1, 0, 10, f"t{reihenfolge}", wert, reihenfolge, "", "", "")


def test_vielfalt_und_nachbarn_je_werk() -> None:
    kandidaten = [
        _t("c1", "d1", "dokument", 1, 0.9),
        _t("c2", "d1", "dokument", 2, 0.8),
        _t("c3", "v1", "video", 1, 0.7),
        _t("c4", "v1", "video", 5, 0.6),
    ]
    assert [k.chunk_id for k in begrenze_je_video(kandidaten, 1)] == ["c1", "c3"]
    nummern = nachbar_nummern([kandidaten[0], kandidaten[2]], 1)
    assert nummern == {"d1": {0, 2}, "v1": {0, 2}}
    zusammen = fuege_nachbarn_zusammen([kandidaten[0]], [_t("c2", "d1", "dokument", 2, 0.0)])
    assert len(zusammen) == 1 and zusammen[0].art == "dokument" and zusammen[0].werk_id == "d1" and "t2" in zusammen[0].text
    assert zusammen[0].als_dict()["werk_id"] == "d1"


def test_suchparameter_werkart() -> None:
    p = Suchparameter.aus_dict({"werkart": "dokument", "dokument_ids": ["d1"], "treffer": 3})
    assert p.werkart == "dokument" and p.dokument_ids == ["d1"] and p.treffer == 3
    assert Suchparameter.aus_dict({}).werkart == ""


def test_stellenkopf_dokument() -> None:
    t = _t("c1", "d1", "dokument", 1)
    assert prompts.stellenkopf(3, t) == "[3] Dokument Buch (Kapitel Kap)"
    t.seite_von = 12
    assert "Seite 12" in prompts.stellenkopf(1, t)


def test_bereinigen_titelseite_mit_kurzer_unterzeile_faellt_weg() -> None:
    roh = [
        basis.Abschnitt("Das Buch", 1, ""),
        basis.Abschnitt("Untertitel kurz", 2, "zu kurz"),
        basis.Abschnitt("Kapitel eins", 1, "Genug Text für einen richtigen Abschnitt im Buch."),
        basis.Abschnitt("Teil", 1, ""),
        basis.Abschnitt("Unterkapitel", 2, "Auch hier steht genug Text, damit der Abschnitt bleibt."),
    ]
    titel = [a.titel for a in basis.abschnitte_bereinigen(roh)]
    assert titel == ["Kapitel eins", "Teil", "Unterkapitel"]

