"""EPUB lesen ohne Fremdpaket: Zip mit OPF-Manifest, Spine (Lesereihenfolge) und XHTML-Kapiteln.

Ablauf: META-INF/container.xml nennt die OPF-Datei; die OPF liefert Metadaten (Dublin Core),
das Manifest (Kennung -> Datei) und den Spine (Reihenfolge). Das Inhaltsverzeichnis (nav.xhtml
nach EPUB 3, sonst toc.ncx) liefert Kapiteltitel je Datei. Jede Spine-Datei wird in Absätze
zerlegt; Überschriften h1 bis h3 eröffnen Abschnitte. Hat eine Datei keine Überschrift, gilt
der Titel aus dem Inhaltsverzeichnis, sonst die erste Zeile.
"""

from __future__ import annotations

import io
import posixpath
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from xml.etree import ElementTree as ET

from ..quellen.tubevault import datum_parsen
from .basis import Abschnitt, DokumentFehler, Dokumentinhalt, absaetze_verbinden, abschnitte_bereinigen, titel_aus_text

NS_CONTAINER = "{urn:oasis:names:tc:opendocument:xmlns:container}"
NS_OPF = "{http://www.idpf.org/2007/opf}"
NS_DC = "{http://purl.org/dc/elements/1.1/}"
NS_NCX = "{http://www.daisy.org/z3986/2005/ncx/}"
NS_XHTML = "{http://www.w3.org/1999/xhtml}"
NS_EPUB = "{http://www.idpf.org/2007/ops}"

XHTML_TYPEN = ("application/xhtml+xml", "text/html")
UEBERSCHRIFTEN = {"h1": 1, "h2": 2, "h3": 3}
BLOCK_ELEMENTE = {
    "p",
    "div",
    "li",
    "blockquote",
    "pre",
    "section",
    "article",
    "aside",
    "header",
    "footer",
    "figure",
    "figcaption",
    "td",
    "th",
    "tr",
    "dd",
    "dt",
    "br",
    "hr",
    "ul",
    "ol",
    "table",
}
UNSICHTBAR = {"script", "style", "head", "title", "svg", "math", "nav"}
UEBERSCHRIFT_HOECHSTENS = 200


@dataclass(slots=True)
class Manifesteintrag:
    kennung: str
    href: str
    medientyp: str
    eigenschaften: str = ""


@dataclass(slots=True)
class Tocpunkt:
    href: str  # Pfad ohne Fragment, relativ zur OPF
    fragment: str
    titel: str
    ebene: int


@dataclass(slots=True)
class Block:
    """Ein Textblock einer XHTML-Datei: Absatz oder Überschrift (mit Ebene)."""

    text: str
    ebene: int = 0  # 0 = Absatz, 1 bis 3 = Überschrift
    kennung: str = ""  # id-Attribut, falls vorhanden (für Anker)


class _Blocksammler(HTMLParser):
    """Zerlegt XHTML in Blöcke; unsichtbare Elemente werden übersprungen."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.bloecke: list[Block] = []
        self._puffer: list[str] = []
        self._ebene = 0
        self._kennung = ""
        self._unsichtbar = 0

    def _abschliessen(self) -> None:
        text = " ".join("".join(self._puffer).split())
        if text:
            self.bloecke.append(Block(text=text, ebene=self._ebene, kennung=self._kennung))
        self._puffer = []
        self._ebene = 0
        self._kennung = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in UNSICHTBAR:
            self._unsichtbar += 1
            return
        if self._unsichtbar:
            return
        kennung = next((w for k, w in attrs if k == "id" and w), "")
        if tag in UEBERSCHRIFTEN:
            self._abschliessen()
            self._ebene = UEBERSCHRIFTEN[tag]
            self._kennung = kennung
        elif tag in BLOCK_ELEMENTE:
            self._abschliessen()
            if kennung and not self._kennung:
                self._kennung = kennung
        elif kennung and not self._kennung and not self._puffer:
            self._kennung = kennung

    def handle_endtag(self, tag: str) -> None:
        if tag in UNSICHTBAR:
            self._unsichtbar = max(0, self._unsichtbar - 1)
            return
        if self._unsichtbar:
            return
        if tag in UEBERSCHRIFTEN or tag in BLOCK_ELEMENTE:
            self._abschliessen()

    def handle_data(self, data: str) -> None:
        if not self._unsichtbar and data:
            self._puffer.append(data)

    def ergebnis(self) -> list[Block]:
        self._abschliessen()
        return self.bloecke


def bloecke_aus_xhtml(quelle: str) -> list[Block]:
    sammler = _Blocksammler()
    sammler.feed(quelle)
    return sammler.ergebnis()


# ---------------------------------------------------------------- OPF und Inhaltsverzeichnis
def _xml(daten: bytes, name: str) -> ET.Element:
    try:
        return ET.fromstring(daten)
    except ET.ParseError as e:
        raise DokumentFehler(f"'{name}' ist kein gültiges XML: {e}") from e


def _opf_pfad(zip_datei: zipfile.ZipFile) -> str:
    try:
        wurzel = _xml(zip_datei.read("META-INF/container.xml"), "container.xml")
    except KeyError as e:
        raise DokumentFehler("Kein EPUB: META-INF/container.xml fehlt") from e
    for rootfile in wurzel.iter(f"{NS_CONTAINER}rootfile"):
        pfad = rootfile.get("full-path")
        if pfad:
            return pfad
    raise DokumentFehler("Kein EPUB: container.xml nennt keine OPF-Datei")


def _text(element: ET.Element | None) -> str:
    return " ".join((element.text or "").split()) if element is not None else ""


def _dc(metadaten: ET.Element | None, name: str) -> list[str]:
    if metadaten is None:
        return []
    return [t for t in (_text(e) for e in metadaten.findall(f"{NS_DC}{name}")) if t]


@dataclass(slots=True)
class Opf:
    titel: str
    autoren: list[str]
    sprache: str
    beschreibung: str
    datum: str
    manifest: dict[str, Manifesteintrag]
    spine: list[str]
    ncx_kennung: str
    verzeichnis: str  # Verzeichnis der OPF im Zip
    roh: dict[str, Any] = field(default_factory=dict)


def opf_lesen(daten: bytes, pfad: str) -> Opf:
    wurzel = _xml(daten, pfad)
    metadaten = wurzel.find(f"{NS_OPF}metadata")
    manifest: dict[str, Manifesteintrag] = {}
    for item in wurzel.iter(f"{NS_OPF}item"):
        kennung, href, typ = item.get("id", ""), item.get("href", ""), item.get("media-type", "")
        if kennung and href:
            manifest[kennung] = Manifesteintrag(kennung, href, typ, item.get("properties", "") or "")
    spine_el = wurzel.find(f"{NS_OPF}spine")
    spine = [r.get("idref", "") for r in (spine_el.findall(f"{NS_OPF}itemref") if spine_el is not None else []) if r.get("idref")]
    titel = _dc(metadaten, "title")
    return Opf(
        titel=titel[0] if titel else "",
        autoren=_dc(metadaten, "creator"),
        sprache=(_dc(metadaten, "language") or ["de"])[0],
        beschreibung=" ".join(_dc(metadaten, "description")),
        datum=(_dc(metadaten, "date") or [""])[0],
        manifest=manifest,
        spine=spine,
        ncx_kennung=(spine_el.get("toc", "") if spine_el is not None else "") or "",
        verzeichnis=posixpath.dirname(pfad),
        roh={
            "titel": titel,
            "autoren": _dc(metadaten, "creator"),
            "sprache": _dc(metadaten, "language"),
            "datum": _dc(metadaten, "date"),
            "herausgeber": _dc(metadaten, "publisher"),
            "kennungen": _dc(metadaten, "identifier"),
            "rechte": _dc(metadaten, "rights"),
            "dateien_im_spine": len(spine),
        },
    )


def _pfad_im_zip(verzeichnis: str, href: str) -> str:
    return posixpath.normpath(posixpath.join(verzeichnis, href)) if verzeichnis else posixpath.normpath(href)


def _href_teilen(href: str) -> tuple[str, str]:
    pfad, _, fragment = href.partition("#")
    return pfad, fragment


def toc_aus_nav(daten: bytes, name: str) -> list[Tocpunkt]:
    """EPUB 3: <nav epub:type="toc"> mit verschachtelten Listen."""
    wurzel = _xml(daten, name)
    nav = next((n for n in wurzel.iter(f"{NS_XHTML}nav") if (n.get(f"{NS_EPUB}type") or "") == "toc"), None)
    if nav is None:
        nav = next(iter(wurzel.iter(f"{NS_XHTML}nav")), None)
    if nav is None:
        return []
    punkte: list[Tocpunkt] = []

    def liste(ol: ET.Element, ebene: int) -> None:
        for li in ol.findall(f"{NS_XHTML}li"):
            a = li.find(f"{NS_XHTML}a")
            if a is not None and a.get("href"):
                pfad, fragment = _href_teilen(a.get("href", ""))
                punkte.append(Tocpunkt(pfad, fragment, " ".join("".join(a.itertext()).split()), min(ebene, 3)))
            for unter in li.findall(f"{NS_XHTML}ol"):
                liste(unter, ebene + 1)

    for ol in nav.findall(f"{NS_XHTML}ol"):
        liste(ol, 1)
    return punkte


def toc_aus_ncx(daten: bytes, name: str) -> list[Tocpunkt]:
    """EPUB 2: navMap mit verschachtelten navPoints."""
    wurzel = _xml(daten, name)
    punkte: list[Tocpunkt] = []

    def punkt(np: ET.Element, ebene: int) -> None:
        label = np.find(f"{NS_NCX}navLabel/{NS_NCX}text")
        inhalt = np.find(f"{NS_NCX}content")
        if inhalt is not None and inhalt.get("src"):
            pfad, fragment = _href_teilen(inhalt.get("src", ""))
            punkte.append(Tocpunkt(pfad, fragment, _text(label), min(ebene, 3)))
        for unter in np.findall(f"{NS_NCX}navPoint"):
            punkt(unter, ebene + 1)

    nav_map = wurzel.find(f"{NS_NCX}navMap")
    for np in nav_map.findall(f"{NS_NCX}navPoint") if nav_map is not None else []:
        punkt(np, 1)
    return punkte


def inhaltsverzeichnis(zip_datei: zipfile.ZipFile, opf: Opf) -> list[Tocpunkt]:
    nav = next((m for m in opf.manifest.values() if "nav" in m.eigenschaften.split()), None)
    if nav is not None:
        try:
            return toc_aus_nav(zip_datei.read(_pfad_im_zip(opf.verzeichnis, nav.href)), nav.href)
        except (KeyError, DokumentFehler):
            pass
    ncx = opf.manifest.get(opf.ncx_kennung) or next((m for m in opf.manifest.values() if m.medientyp == "application/x-dtbncx+xml"), None)
    if ncx is not None:
        try:
            return toc_aus_ncx(zip_datei.read(_pfad_im_zip(opf.verzeichnis, ncx.href)), ncx.href)
        except (KeyError, DokumentFehler):
            pass
    return []


# ---------------------------------------------------------------- Abschnitte bilden
def abschnitte_aus_bloecken(bloecke: list[Block], href: str, toc: dict[str, list[Tocpunkt]], vorgabe_titel: str) -> list[Abschnitt]:
    """Überschriften eröffnen Abschnitte; Text davor bekommt den Titel aus dem Inhaltsverzeichnis.

    Kennungen der Überschriften (id) werden zum Anker `datei#kennung`, damit die Leseansicht
    und der Beleg im Chat auf die Stelle zeigen können.
    """
    punkte = toc.get(href, [])
    je_fragment = {p.fragment: p for p in punkte if p.fragment}
    datei_titel = next((p.titel for p in punkte if not p.fragment), "") or (punkte[0].titel if punkte else "")
    datei_ebene = next((p.ebene for p in punkte if not p.fragment), punkte[0].ebene if punkte else 1)

    abschnitte: list[Abschnitt] = []
    aktuell: Abschnitt | None = None
    absaetze: list[str] = []

    def abschliessen() -> None:
        nonlocal aktuell, absaetze
        if aktuell is not None:
            aktuell.text = absaetze_verbinden(absaetze)
            abschnitte.append(aktuell)
        aktuell = None
        absaetze = []

    for b in bloecke:
        if b.ebene:
            abschliessen()
            titel = b.text[:UEBERSCHRIFT_HOECHSTENS]
            ebene = b.ebene
            if b.kennung in je_fragment:
                ebene = je_fragment[b.kennung].ebene
            aktuell = Abschnitt(titel=titel, ebene=ebene, anker=f"{href}#{b.kennung}" if b.kennung else href)
            continue
        if aktuell is None:
            # Text vor der ersten Überschrift: Titel aus dem Inhaltsverzeichnis, sonst erste Zeile
            titel = datei_titel or titel_aus_text(b.text, vorgabe_titel)
            aktuell = Abschnitt(titel=titel, ebene=datei_ebene, anker=href)
        absaetze.append(b.text)
    abschliessen()
    return abschnitte


def lese_epub(roh: bytes, dateiname: str = "") -> Dokumentinhalt:
    """Übersetzt eine EPUB-Datei in Titel, Autor und Abschnitte in Lesereihenfolge."""
    try:
        zip_datei = zipfile.ZipFile(io.BytesIO(roh))
    except zipfile.BadZipFile as e:
        raise DokumentFehler("Die Datei ist kein EPUB (kein gültiges Zip)") from e
    with zip_datei:
        opf_pfad = _opf_pfad(zip_datei)
        try:
            opf = opf_lesen(zip_datei.read(opf_pfad), opf_pfad)
        except KeyError as e:
            raise DokumentFehler(f"Die OPF-Datei '{opf_pfad}' fehlt im EPUB") from e
        toc: dict[str, list[Tocpunkt]] = {}
        for p in inhaltsverzeichnis(zip_datei, opf):
            toc.setdefault(p.href, []).append(p)
        abschnitte: list[Abschnitt] = []
        titel_vorgabe = opf.titel or dateiname or "Dokument"
        for nr, kennung in enumerate(opf.spine, start=1):
            eintrag = opf.manifest.get(kennung)
            if eintrag is None or eintrag.medientyp not in XHTML_TYPEN or "nav" in eintrag.eigenschaften.split():
                continue
            try:
                quelle = zip_datei.read(_pfad_im_zip(opf.verzeichnis, eintrag.href)).decode("utf-8", errors="replace")
            except KeyError:
                continue
            bloecke = bloecke_aus_xhtml(quelle)
            if not bloecke:
                continue
            abschnitte.extend(abschnitte_aus_bloecken(bloecke, eintrag.href, toc, f"Abschnitt {nr}"))
    abschnitte = abschnitte_bereinigen(abschnitte)
    if not abschnitte:
        raise DokumentFehler("Das EPUB enthält keinen lesbaren Text")
    return Dokumentinhalt(
        titel=opf.titel or titel_vorgabe,
        autor=", ".join(opf.autoren),
        sprache=opf.sprache[:16] or "de",
        beschreibung=opf.beschreibung,
        veroeffentlicht=datum_parsen(opf.datum[:10]) if opf.datum else None,
        abschnitte=abschnitte,
        metadaten=opf.roh,
    )
