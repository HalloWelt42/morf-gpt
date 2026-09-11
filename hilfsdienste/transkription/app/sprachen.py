"""Sprachangaben: Whisper-Namen und Zweibuchstabencodes auf den Code abbilden."""

from __future__ import annotations

NAMEN_ZU_CODE: dict[str, str] = {
    "german": "de",
    "deutsch": "de",
    "english": "en",
    "englisch": "en",
    "french": "fr",
    "spanish": "es",
    "italian": "it",
    "dutch": "nl",
    "portuguese": "pt",
    "polish": "pl",
    "russian": "ru",
    "turkish": "tr",
    "chinese": "zh",
    "japanese": "ja",
    "korean": "ko",
    "arabic": "ar",
    "czech": "cs",
    "danish": "da",
    "swedish": "sv",
    "norwegian": "no",
    "finnish": "fi",
    "hungarian": "hu",
    "greek": "el",
    "ukrainian": "uk",
    "romanian": "ro",
}


def code_fuer(sprache: str) -> str | None:
    """Sprachcode zu einem Namen oder Code; None heißt: die Engine erkennt die Sprache selbst."""
    s = sprache.strip().lower()
    if not s or s == "auto":
        return None
    if s in NAMEN_ZU_CODE:
        return NAMEN_ZU_CODE[s]
    if len(s) == 2 and s.isalpha():
        return s
    raise ValueError(f"Unbekannte Sprache: {sprache}")
