"""Modellfamilien der Einbettung: derselbe Vektorraum unter verschiedenen Namen.

Dasselbe Einbettungsmodell heißt je Anbieter anders: in LM Studio "text-embedding-bge-m3", bei
fastembed "BAAI/bge-m3", bei einem Netzdienst vielleicht "bge-m3". Die Vektoren sind trotzdem
austauschbar (gemessen: Cosinus 0,9995 zwischen LM Studio und fastembed). Der Index speichert
den Namen des erzeugenden Anbieters; verglichen wird über die Familie, damit ein Empfänger mit
einem anderen Anbieter dieselben Vektoren nutzen kann, ohne neu zu rechnen.
"""

from __future__ import annotations

import re

_FAMILIEN: dict[str, tuple[str, ...]] = {
    "bge-m3": ("bge-m3",),
    "multilingual-e5-large": ("multilingual-e5-large",),
    "bge-small-en-v1.5": ("bge-small-en-v1.5",),
}
_ANBIETER_VORSILBEN = ("text-embedding-",)


def familie(modell: str) -> str:
    """Familienschlüssel eines Modellnamens: Anbietervorsilben, Organisation und Dateiendungen fallen weg."""
    name = modell.strip().lower()
    if "/" in name:
        name = name.rsplit("/", 1)[-1]
    for vorsilbe in _ANBIETER_VORSILBEN:
        name = name.removeprefix(vorsilbe)
    name = re.sub(r"(\.gguf|-gguf|-q\d.*|@.*)$", "", name)
    for schluessel, kennzeichen in _FAMILIEN.items():
        if any(k in name for k in kennzeichen):
            return schluessel
    return name


def gleiche_familie(a: str, b: str) -> bool:
    return familie(a) == familie(b)
