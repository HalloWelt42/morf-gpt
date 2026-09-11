"""Blockbildung: Rohsegmente an Segmentgrenzen zu Zeitblöcken bündeln.

Ein Block umfasst ganze Segmente und etwa `ziel_zeichen` Zeichen. Ein Segment wird nie
zerschnitten; ist ein einzelnes Segment länger als das Ziel, bildet es allein einen
Block. Jeder Block kennt sein Zeitfenster, damit die Absätze der Korrektur zum Audio
springbar bleiben (docs/ARCHITEKTUR.md, Abschnitt 5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Zeitliche Toleranz beim Zuordnen von Segmenten zu einem Blockfenster (Rundung der
# gespeicherten Absatzzeiten auf zwei Nachkommastellen).
FENSTER_TOLERANZ_S: float = 0.05


@dataclass(slots=True)
class Segment:
    """Ein Rohsegment des Transkripts mit Zeitfenster und Text."""

    start_s: float
    end_s: float
    text: str


@dataclass(slots=True)
class Block:
    """Ein Zeitblock aus ganzen Segmenten.

    `segment_von` und `segment_bis` zeigen (beide einschließlich) in die Segmentliste,
    aus der der Block gebildet wurde.
    """

    index: int
    start_s: float
    end_s: float
    text: str
    segment_von: int
    segment_bis: int

    @property
    def zeichen(self) -> int:
        return len(self.text)

    @property
    def dauer_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)


def _zahl(wert: Any, vorgabe: float = 0.0) -> float:
    try:
        return float(wert)
    except (TypeError, ValueError):
        return vorgabe


def segmente_lesen(rohsegmente: list[dict[str, Any]]) -> list[Segment]:
    """Liest die JSON-Segmente eines Transkripts.

    Akzeptiert die Schlüssel `start`/`end` (Ablage im Transkript) und `start_s`/`end_s`.
    Segmente ohne Text werden übersprungen; Texte werden an den Rändern bereinigt.
    """
    aus: list[Segment] = []
    for roh in rohsegmente:
        if not isinstance(roh, dict):
            continue
        text = str(roh.get("text") or "").strip()
        if not text:
            continue
        start = _zahl(roh.get("start", roh.get("start_s")))
        end = _zahl(roh.get("end", roh.get("end_s")), start)
        aus.append(Segment(start_s=start, end_s=max(start, end), text=text))
    return aus


def _schliesse_block(index: int, teile: list[Segment], von: int, bis: int) -> Block:
    return Block(
        index=index,
        start_s=teile[0].start_s,
        end_s=teile[-1].end_s,
        text=" ".join(t.text for t in teile),
        segment_von=von,
        segment_bis=bis,
    )


def bilde_bloecke(segmente: list[Segment], ziel_zeichen: int) -> list[Block]:
    """Bündelt Segmente der Reihe nach zu Blöcken von etwa `ziel_zeichen` Zeichen.

    Ein Block wird geschlossen, sobald das nächste Segment ihn über das Ziel heben würde.
    Ein Block ist nie leer, darum darf ein einzelnes Segment das Ziel überschreiten.
    """
    if ziel_zeichen <= 0:
        raise ValueError("Die Blockgröße muss größer als 0 Zeichen sein")
    bloecke: list[Block] = []
    offen: list[Segment] = []
    offen_von = 0
    laenge = 0
    for i, seg in enumerate(segmente):
        zusatz = len(seg.text) + (1 if offen else 0)
        if offen and laenge + zusatz > ziel_zeichen:
            bloecke.append(_schliesse_block(len(bloecke), offen, offen_von, i - 1))
            offen, offen_von, laenge = [], i, 0
            zusatz = len(seg.text)
        offen.append(seg)
        laenge += zusatz
    if offen:
        bloecke.append(_schliesse_block(len(bloecke), offen, offen_von, len(segmente) - 1))
    return bloecke


def segmente_im_fenster(segmente: list[Segment], start_s: float, end_s: float) -> list[Segment]:
    """Alle Segmente, deren zeitliche Mitte im Fenster liegt.

    Dient der Rückgewinnung des Rohtexts eines Blocks aus dem Zeitfenster seiner Absätze.
    """
    aus: list[Segment] = []
    for seg in segmente:
        mitte = (seg.start_s + seg.end_s) / 2
        if start_s - FENSTER_TOLERANZ_S <= mitte <= end_s + FENSTER_TOLERANZ_S:
            aus.append(seg)
    return aus


def rohtext_im_fenster(segmente: list[Segment], start_s: float, end_s: float) -> str:
    """Der Rohtext aller Segmente im Fenster, mit Leerzeichen verbunden."""
    return " ".join(seg.text for seg in segmente_im_fenster(segmente, start_s, end_s))
