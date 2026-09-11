"""Abweichungswächter: das Sprachmodell darf die Form verbessern, nie den Inhalt.

Verglichen wird auf normalisiertem Text (Kleinschreibung, ohne Satzzeichen und ohne
Leerraum), damit genau die erlaubten Änderungen (Zeichensetzung, Groß- und
Kleinschreibung, Absätze) den Wert nicht drücken. Liegt die Ähnlichkeit unter der
Schwelle, weicht die Länge zu stark ab, ist die Antwort leer oder besteht sie aus einer
Einleitung statt aus dem Text, bleibt der Rohtext des Blocks stehen und der Block gilt
als verworfen (docs/ARCHITEKTUR.md, Abschnitt 5).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

# Modul-Vorgabe: um höchstens diesen Anteil darf die Länge der Antwort vom Rohtext
# abweichen. Gehört ins Einstellungsregister (Vorschlag: korrektur.max_laengenabweichung).
MAX_LAENGENABWEICHUNG: float = 0.35

# So lang darf eine Zeile höchstens sein, um noch als Einleitung des Modells zu gelten.
# Längere Zeilen sind Text, auch wenn sie mit einer der Wendungen beginnen.
META_ZEILE_MAX_ZEICHEN: int = 160

# So viele Einleitungszeilen werden am Anfang und am Ende höchstens abgeschnitten.
META_MAX_ZEILEN: int = 3

# Wendungen, mit denen Sprachmodelle ihre Antwort gern kommentieren.
META_ANFAENGE: tuple[str, ...] = (
    "hier ist",
    "hier der",
    "hier die",
    "hier das",
    "hier kommt",
    "hier nun",
    "gerne",
    "gern!",
    "gern,",
    "gern.",
    "natürlich",
    "selbstverständlich",
    "klar",
    "okay",
    "ok,",
    "ok.",
    "ok!",
    "korrigierter text",
    "korrigierte fassung",
    "korrigierte version",
    "korrektur:",
    "der korrigierte",
    "die korrigierte",
    "das korrigierte",
    "ich habe",
    "ich hab",
    "anmerkung",
    "hinweis",
)

# Stichworte, die eine kurze Zeile als Kommentar über den Text ausweisen.
META_STICHWORTE: tuple[str, ...] = (
    "korrigiert",
    "korrektur",
    "text",
    "fassung",
    "version",
    "absatz",
    "absätze",
    "zeichensetzung",
    "rechtschreibung",
    "transkript",
)

_DENKBLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_ZAUN_ANFANG = re.compile(r"\A```[a-zA-Z]*[ \t]*\n")
_ZAUN_ENDE = re.compile(r"\n```[ \t]*\Z")
_LEERRAUM_IN_ZEILE = re.compile(r"[ \t]+")
_MEHRFACHE_LEERZEILEN = re.compile(r"\n{3,}")


@dataclass(slots=True)
class Pruefung:
    """Ergebnis des Wächters: der Text, der stehen bleibt, und warum."""

    text: str
    aehnlichkeit: float
    verworfen: bool
    grund: str = ""


def normalisiere(text: str) -> str:
    """Kleinschreibung, nur Buchstaben und Ziffern (Satzzeichen und Leerraum entfernt)."""
    return "".join(zeichen for zeichen in text.lower() if zeichen.isalnum())


def aehnlichkeit(roh: str, korrigiert: str) -> float:
    """Ähnlichkeit 0 bis 1 auf normalisiertem Text (Zeichen-Diff, ohne Junk-Heuristik)."""
    a = normalisiere(roh)
    b = normalisiere(korrigiert)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def laengenabweichung(roh: str, korrigiert: str) -> float:
    """Anteil, um den die Länge der Antwort von der des Rohtexts abweicht."""
    basis = len(roh.strip())
    if basis == 0:
        return 0.0 if not korrigiert.strip() else 1.0
    return abs(len(korrigiert.strip()) - basis) / basis


def ist_meta_zeile(zeile: str) -> bool:
    """Ob eine Zeile ein Kommentar des Modells ist statt Teil des Textes."""
    z = zeile.strip().lower()
    if not z or len(z) > META_ZEILE_MAX_ZEICHEN:
        return False
    if not z.startswith(META_ANFAENGE):
        return False
    if z.endswith(":"):
        return True
    if len(z.split()) <= 3:
        return True
    return any(wort in z for wort in META_STICHWORTE)


def _ohne_denkbloecke_und_zaeune(text: str) -> str:
    bereinigt = _DENKBLOCK.sub("", text).replace("\r\n", "\n").strip()
    bereinigt = _ZAUN_ANFANG.sub("", bereinigt)
    bereinigt = _ZAUN_ENDE.sub("", bereinigt)
    return bereinigt.strip()


def _glaette_leerraum(text: str) -> str:
    zeilen = [_LEERRAUM_IN_ZEILE.sub(" ", zeile).strip() for zeile in text.split("\n")]
    return _MEHRFACHE_LEERZEILEN.sub("\n\n", "\n".join(zeilen)).strip()


def _ohne_meta_zeilen(text: str) -> str:
    zeilen = text.split("\n")
    abgeschnitten = 0
    while zeilen and abgeschnitten < META_MAX_ZEILEN and ist_meta_zeile(zeilen[0]):
        zeilen.pop(0)
        abgeschnitten += 1
    abgeschnitten = 0
    while zeilen and abgeschnitten < META_MAX_ZEILEN and ist_meta_zeile(zeilen[-1]):
        zeilen.pop()
        abgeschnitten += 1
    return "\n".join(zeilen).strip()


def bereinige_antwort(antwort: str) -> str:
    """Entfernt Denkblöcke, Code-Zäune, überflüssigen Leerraum und Einleitungszeilen."""
    return _ohne_meta_zeilen(_glaette_leerraum(_ohne_denkbloecke_und_zaeune(antwort)))


def _verworfen(roh: str, wert: float, grund: str) -> Pruefung:
    return Pruefung(text=roh.strip(), aehnlichkeit=wert, verworfen=True, grund=grund)


def pruefe_block(roh: str, antwort: str, mindest_aehnlichkeit: float) -> Pruefung:
    """Entscheidet je Block, ob die Antwort des Modells stehen bleibt oder der Rohtext.

    Reihenfolge der Sperren: leere Antwort, verbleibende Einleitung, Längenabweichung,
    Ähnlichkeit unter der Schwelle. Die Ähnlichkeit wird auch bei Verwerfen berichtet.
    """
    text = bereinige_antwort(antwort)
    if not text:
        return _verworfen(roh, 0.0, "Antwort leer")
    wert = aehnlichkeit(roh, text)
    if ist_meta_zeile(text.split("\n", 1)[0]):
        return _verworfen(roh, wert, "Antwort besteht aus einer Einleitung statt aus dem Text")
    abweichung = laengenabweichung(roh, text)
    if abweichung > MAX_LAENGENABWEICHUNG:
        return _verworfen(roh, wert, f"Länge weicht um {round(abweichung * 100)} Prozent vom Rohtext ab")
    if wert < mindest_aehnlichkeit:
        return _verworfen(roh, wert, f"Ähnlichkeit {wert:.2f} liegt unter der Schwelle {mindest_aehnlichkeit:.2f}")
    return Pruefung(text=text, aehnlichkeit=wert, verworfen=False)
