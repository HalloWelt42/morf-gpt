"""Markdown und reinen Text lesen: Überschriften eröffnen Abschnitte, Auszeichnung wird zu Text.

Der Text der Abschnitte ist reiner Text (für Stückelung und Einbettung); die Leseansicht zeigt
ihn als Absätze. Ein Kopf (Frontmatter mit titel, autor, sprache, beschreibung, datum) wird
übernommen, wenn vorhanden.
"""

from __future__ import annotations

import re

from ..quellen.tubevault import datum_parsen
from .basis import Abschnitt, Dokumentinhalt, absaetze_verbinden, abschnitte_bereinigen, titel_aus_text

_KOPF = re.compile(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?")
_UEBERSCHRIFT = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_ZAUN = re.compile(r"^(```|~~~)")
_BILD = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_CODE = re.compile(r"`([^`]*)`")
_BETONUNG = re.compile(r"(\*\*|__)(.+?)\1")
_KURSIV = re.compile(r"(?<![\w*])([*_])(?!\s)(.+?)(?<!\s)\1(?![\w*])")
_ZITAT = re.compile(r"^\s{0,3}>\s?", re.M)
_LISTE = re.compile(r"^\s*([-*+]|\d+[.)])\s+", re.M)
_TABELLENRAND = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$", re.M)


def kopf_lesen(quelle: str) -> tuple[dict[str, str], str]:
    treffer = _KOPF.match(quelle)
    if not treffer:
        return {}, quelle
    meta: dict[str, str] = {}
    for zeile in treffer.group(1).splitlines():
        i = zeile.find(":")
        if i > 0:
            meta[zeile[:i].strip().lower()] = zeile[i + 1 :].strip().strip("\"'")
    return meta, quelle[treffer.end() :]


def auszeichnung_entfernen(text: str) -> str:
    """Inline-Auszeichnung zu reinem Text: Links zu ihrem Text, Bilder zu ihrer Beschreibung."""
    text = _BILD.sub(lambda m: m.group(1), text)
    text = _LINK.sub(lambda m: m.group(1), text)
    text = _CODE.sub(lambda m: m.group(1), text)
    text = _BETONUNG.sub(lambda m: m.group(2), text)
    text = _KURSIV.sub(lambda m: m.group(2), text)
    text = _ZITAT.sub("", text)
    text = _TABELLENRAND.sub("", text)
    text = _LISTE.sub("- ", text)
    return text.replace("|", " ")


def lese_markdown(quelle: str, titel_vorgabe: str = "Dokument") -> Dokumentinhalt:
    meta, rumpf = kopf_lesen(quelle.replace("\r\n", "\n"))
    abschnitte: list[Abschnitt] = []
    aktuell: Abschnitt | None = None
    absaetze: list[str] = []
    puffer: list[str] = []
    im_zaun = False
    titel_aus_h1 = ""

    def absatz_abschliessen() -> None:
        nonlocal puffer
        if puffer:
            absaetze.append(auszeichnung_entfernen(" ".join(z.strip() for z in puffer)))
            puffer = []

    def abschnitt_abschliessen() -> None:
        nonlocal aktuell, absaetze
        absatz_abschliessen()
        if aktuell is not None:
            aktuell.text = absaetze_verbinden(absaetze)
            abschnitte.append(aktuell)
        aktuell = None
        absaetze = []

    for zeile in rumpf.split("\n"):
        if _ZAUN.match(zeile):
            im_zaun = not im_zaun
            continue
        if im_zaun:
            puffer.append(zeile)
            continue
        ue = _UEBERSCHRIFT.match(zeile)
        if ue and len(ue.group(1)) <= 3:
            titel = auszeichnung_entfernen(ue.group(2)).strip()
            if len(ue.group(1)) == 1 and not titel_aus_h1:
                titel_aus_h1 = titel
            abschnitt_abschliessen()
            aktuell = Abschnitt(titel=titel, ebene=len(ue.group(1)))
            continue
        if ue:
            absatz_abschliessen()
            puffer.append(auszeichnung_entfernen(ue.group(2)))
            absatz_abschliessen()
            continue
        if not zeile.strip():
            absatz_abschliessen()
            continue
        if aktuell is None:
            aktuell = Abschnitt(titel=meta.get("titel") or meta.get("title") or titel_aus_text(zeile, titel_vorgabe), ebene=1)
        puffer.append(zeile)
    abschnitt_abschliessen()
    abschnitte = abschnitte_bereinigen(abschnitte)
    datum = meta.get("datum") or meta.get("date") or ""
    return Dokumentinhalt(
        titel=meta.get("titel") or meta.get("title") or titel_aus_h1 or titel_vorgabe,
        autor=meta.get("autor") or meta.get("author") or "",
        sprache=(meta.get("sprache") or meta.get("language") or "de")[:16],
        beschreibung=meta.get("beschreibung") or meta.get("description") or "",
        veroeffentlicht=datum_parsen(datum) if datum else None,
        abschnitte=abschnitte,
        metadaten={"kopf": meta, "abschnitte": len(abschnitte)},
    )


def lese_text(quelle: str, titel_vorgabe: str = "Text") -> Dokumentinhalt:
    """Reiner Text: Absätze an Leerzeilen, ein Abschnitt mit dem Titel aus der ersten Zeile."""
    text = quelle.replace("\r\n", "\n").strip()
    absaetze = [a for a in re.split(r"\n\s*\n", text) if a.strip()]
    titel = titel_aus_text(text, titel_vorgabe)
    abschnitte = abschnitte_bereinigen([Abschnitt(titel=titel, ebene=1, text=absaetze_verbinden([" ".join(a.split()) for a in absaetze]))])
    return Dokumentinhalt(titel=titel, abschnitte=abschnitte, metadaten={"absaetze": len(absaetze)})
