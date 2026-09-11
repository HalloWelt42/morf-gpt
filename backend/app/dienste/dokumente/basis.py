"""Dokumente als Werkart: gemeinsame Datenträger und die Erkennung der Art.

Ein Leser (`epub.py`, `markdown.py`) übersetzt eine Datei in einen `Dokumentinhalt`: Titel,
Autor, Sprache und die Abschnitte in Lesereihenfolge (Kapitel mit Ebene, Titel, bereinigtem
Text). Der Import speichert das, die Stückelung arbeitet nur noch auf Abschnitten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ART_EPUB = "epub"
ART_MARKDOWN = "markdown"
ART_TEXT = "text"
ART_PDF = "pdf"

ARTEN_TITEL: dict[str, str] = {
    ART_EPUB: "E-Book (EPUB)",
    ART_MARKDOWN: "Markdown",
    ART_TEXT: "Text",
    ART_PDF: "PDF",
}

# Dateiendung -> Art. PDF folgt in einem späteren Schritt.
ENDUNGEN: dict[str, str] = {
    ".epub": ART_EPUB,
    ".md": ART_MARKDOWN,
    ".markdown": ART_MARKDOWN,
    ".txt": ART_TEXT,
    ".text": ART_TEXT,
}

# Abschnitte mit weniger Zeichen sind Reste (leere Überschriften, Trennseiten).
MINDEST_ZEICHEN_ABSCHNITT = 20


class DokumentFehler(RuntimeError):
    """Eine Datei konnte nicht als Dokument gelesen werden (sprechende Meldung)."""


@dataclass(slots=True)
class Abschnitt:
    """Ein Kapitel oder Unterkapitel: Ebene 1 ist ein Kapitel, 2 und 3 sind Unterkapitel."""

    titel: str
    ebene: int
    text: str = ""
    anker: str = ""
    seite_von: int | None = None
    seite_bis: int | None = None

    @property
    def zeichen(self) -> int:
        return len(self.text)


@dataclass(slots=True)
class Dokumentinhalt:
    """Was ein Leser aus einer Datei macht."""

    titel: str
    autor: str = ""
    sprache: str = "de"
    beschreibung: str = ""
    veroeffentlicht: datetime | None = None
    abschnitte: list[Abschnitt] = field(default_factory=list)
    metadaten: dict[str, Any] = field(default_factory=dict)

    @property
    def zeichen(self) -> int:
        return sum(a.zeichen for a in self.abschnitte)


def art_aus_dateiname(dateiname: str) -> str:
    endung = Path(dateiname or "").suffix.lower()
    art = ENDUNGEN.get(endung)
    if art is None:
        bekannt = ", ".join(sorted(ENDUNGEN))
        raise DokumentFehler(f"Die Endung '{endung or '(keine)'}' wird nicht unterstützt (bekannt: {bekannt})")
    return art


_MEHRFACH_LEER = re.compile(r"[ \t ]+")
_MEHRFACH_ABSATZ = re.compile(r"\n{3,}")


def text_bereinigen(text: str) -> str:
    """Leerraum glätten: Zeilen ohne Randleerzeichen, höchstens eine Leerzeile zwischen Absätzen."""
    zeilen = [_MEHRFACH_LEER.sub(" ", z).strip() for z in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return _MEHRFACH_ABSATZ.sub("\n\n", "\n".join(zeilen)).strip()


def absaetze_verbinden(absaetze: list[str]) -> str:
    """Absätze mit einer Leerzeile dazwischen; leere Absätze fallen weg."""
    return "\n\n".join(a.strip() for a in absaetze if a and a.strip())


def abschnitte_bereinigen(abschnitte: list[Abschnitt]) -> list[Abschnitt]:
    """Text glätten, Reste entfernen. Ein Titel ohne Text bleibt nur, wenn Unterabschnitte folgen."""
    aus: list[Abschnitt] = []
    for i, a in enumerate(abschnitte):
        a.text = text_bereinigen(a.text)
        a.titel = " ".join(a.titel.split())
        if a.zeichen >= MINDEST_ZEICHEN_ABSCHNITT:
            aus.append(a)
            continue
        folgt_tieferer = i + 1 < len(abschnitte) and abschnitte[i + 1].ebene > a.ebene
        if a.titel and folgt_tieferer:
            aus.append(a)
    return aus


def titel_aus_text(text: str, vorgabe: str, hoechstens: int = 80) -> str:
    """Erste nicht leere Zeile als Titel, gekürzt; sonst die Vorgabe."""
    for zeile in text.splitlines():
        z = zeile.strip()
        if z:
            return z[:hoechstens]
    return vorgabe
