"""Textregeln, die überall gelten: gerade Zeichen statt typografischer Sonderzeichen.

Sprachmodelle setzen gern Gedankenstriche und geschwungene Anführungszeichen. Alles,
was aus einem Modell in die Bibliothek oder in eine Antwort fließt, läuft hier durch.
"""

from __future__ import annotations

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
