"""Nachbearbeitung der Rohsegmente: offensichtliche Halluzinationen entfernen und kurze
Segmente zu Blöcken zusammenführen, die als Absätze taugen.

Whisper erfindet bei Stille oder Musik gern Untertitel-Floskeln und wiederholt sich in
Schleifen. Erkannt wird: leerer Text, direkte Wiederholung des vorigen Segments, sehr
geringe Wortvielfalt, bekannte Floskeln in kurzen Segmenten. Danach werden Segmente zu
Blöcken zwischen min und max Sekunden zusammengeführt, getrennt nur an Pausen; die
Wortzeiten bleiben dabei erhalten.
"""

from __future__ import annotations

from dataclasses import dataclass

from .engines.basis import Segment

FLOSKELN: tuple[str, ...] = (
    "Untertitel von",
    "Untertitelung",
    "Vielen Dank fürs Zuschauen",
    "Vielen Dank für's Zuschauen",
    "Danke fürs Zuschauen",
    "Copyright",
    "www.",
    "http",
    "Abonniere",
    "♪",
)
FLOSKEL_HOECHSTLAENGE = 50
VIELFALT_MINDESTANTEIL = 0.3


@dataclass(slots=True, frozen=True)
class Blockregeln:
    min_s: float = 6.0
    max_s: float = 15.0
    pause_s: float = 0.3


def ist_halluzination(text: str, voriger: str) -> bool:
    t = text.strip()
    if not t or t == voriger:
        return True
    woerter = t.split()
    if len(woerter) > 3 and len({w.lower() for w in woerter}) / len(woerter) < VIELFALT_MINDESTANTEIL:
        return True
    return len(t) < FLOSKEL_HOECHSTLAENGE and any(f in t for f in FLOSKELN)


def bereinigen(segmente: list[Segment]) -> list[Segment]:
    aus: list[Segment] = []
    voriger = ""
    for s in segmente:
        if ist_halluzination(s.text, voriger):
            continue
        voriger = s.text.strip()
        aus.append(Segment(s.start, s.end, voriger, list(s.woerter)))
    return aus


def zusammenfuehren(segmente: list[Segment], regeln: Blockregeln) -> list[Segment]:
    if not segmente:
        return []
    bloecke: list[Segment] = []
    aktuell = Segment(segmente[0].start, segmente[0].end, segmente[0].text, list(segmente[0].woerter))
    for s in segmente[1:]:
        dauer = aktuell.end - aktuell.start
        pause = s.start - aktuell.end
        if dauer >= regeln.max_s or (dauer >= regeln.min_s and pause >= regeln.pause_s):
            bloecke.append(aktuell)
            aktuell = Segment(s.start, s.end, s.text, list(s.woerter))
            continue
        aktuell.end = s.end
        aktuell.text = f"{aktuell.text} {s.text}".strip()
        aktuell.woerter.extend(s.woerter)
    bloecke.append(aktuell)
    return bloecke


def nachbearbeiten(segmente: list[Segment], regeln: Blockregeln) -> list[Segment]:
    return zusammenfuehren(bereinigen(segmente), regeln)


def volltext(segmente: list[Segment]) -> str:
    return " ".join(s.text.strip() for s in segmente if s.text.strip())
