"""Textregeln, die überall gelten: gerade Zeichen statt typografischer Sonderzeichen.

Sprachmodelle setzen gern Gedankenstriche und geschwungene Anführungszeichen. Alles,
was aus einem Modell in die Bibliothek oder in eine Antwort fließt, läuft hier durch.
"""

from __future__ import annotations

import re

_ERSATZ: dict[str, str] = {
    "—": "-",  # Geviertstrich
    "–": "-",  # Halbgeviertstrich
    "‒": "-",  # Ziffernstrich
    "‑": "-",  # geschützter Bindestrich
    "‐": "-",  # Trennstrich
    "“": '"',
    "”": '"',
    "„": '"',
    "‟": '"',
    "«": '"',
    "»": '"',
    "‹": "'",
    "›": "'",
    "‘": "'",
    "’": "'",
    "‚": "'",
    "…": "...",
    " ": " ",  # geschütztes Leerzeichen
}


def gerade(text: str) -> str:
    """Typografische Sonderzeichen auf gerade Zeichen zurückführen; Umlaute bleiben unberührt."""
    for alt, neu in _ERSATZ.items():
        if alt in text:
            text = text.replace(alt, neu)
    return text


# Schriftblöcke, die in deutschen (oder englischen) Antworten nichts verloren haben.
# Sprachmodelle in niedriger Quantisierung streuen gelegentlich einzelne Zeichen daraus
# ein ("weil er认为 in ..."). Griechisch und Mathematik bleiben erlaubt.
_FREMDE_SCHRIFT = re.compile(
    "["
    "\u0400-\u052f"  # Kyrillisch
    "\u0590-\u06ff"  # Hebräisch, Arabisch
    "\u0900-\u0dff"  # indische Schriften
    "\u0e00-\u0e7f"  # Thai
    "\u1100-\u11ff"  # Hangul-Jamo
    "\u2e80-\u2fdf"  # CJK-Radikale
    "\u3000-\u30ff"  # CJK-Zeichensetzung, Hiragana, Katakana
    "\u3100-\u31ff"  # Bopomofo, Hangul-Kompatibilität
    "\u3400-\u4dbf"  # CJK-Erweiterung A
    "\u4e00-\u9fff"  # CJK-Ideogramme
    "\ua960-\ua97f"  # Hangul-Jamo Erweiterung
    "\uac00-\ud7ff"  # Hangul-Silben
    "\uf900-\ufaff"  # CJK-Kompatibilität
    "\uff00-\uffef"  # Vollbreite Formen
    "\U00020000-\U0003134f"  # CJK-Erweiterungen B bis G
    "]+"
)
_DOPPELTE_LEERZEICHEN = re.compile(r"[ \t]{2,}")


def nur_lateinisch(text: str) -> str:
    """Entfernt Zeichen fremder Schriften (chinesisch, kyrillisch, arabisch ...)."""
    if not _FREMDE_SCHRIFT.search(text):
        return text
    return _DOPPELTE_LEERZEICHEN.sub(" ", _FREMDE_SCHRIFT.sub("", text))


def bereinige(text: str) -> str:
    """Alles, was aus einem Sprachmodell kommt: gerade Zeichen und nur lateinische Schrift."""
    return nur_lateinisch(gerade(text))
