"""Das Fließband: Stufen eines Videos und die zugehörigen Auftragsarten.

Einzige Wahrheit über die Reihenfolge der Stufen. Wer wissen will, welche Stufe
auf welche folgt oder welcher Auftrag eine Stufe herstellt, fragt hier.
"""

from __future__ import annotations

from enum import StrEnum


class Stufe(StrEnum):
    """Höchste fertige Stufe eines Videos."""

    ENTDECKT = "entdeckt"
    AUDIO = "audio"
    TRANSKRIBIERT = "transkribiert"
    KORRIGIERT = "korrigiert"
    GESTUECKELT = "gestueckelt"
    EINGEBETTET = "eingebettet"


class Auftragsart(StrEnum):
    """Arten von Aufträgen auf dem Fließband."""

    QUELLE_ABGLEICH = "quelle_abgleich"
    AUDIO = "audio"
    TRANSKRIPTION = "transkription"
    KORREKTUR = "korrektur"
    STUECKELUNG = "stueckelung"
    EINBETTUNG = "einbettung"


class Auftragsstatus(StrEnum):
    WARTEND = "wartend"
    LAEUFT = "laeuft"
    FERTIG = "fertig"
    FEHLER = "fehler"
    PAUSIERT = "pausiert"
    ABGEBROCHEN = "abgebrochen"


STUFEN_REIHENFOLGE: tuple[Stufe, ...] = (
    Stufe.ENTDECKT,
    Stufe.AUDIO,
    Stufe.TRANSKRIBIERT,
    Stufe.KORRIGIERT,
    Stufe.GESTUECKELT,
    Stufe.EINGEBETTET,
)

# Welche Auftragsart stellt welche Stufe her (und braucht welche Vorstufe).
AUFTRAG_JE_STUFE: dict[Stufe, Auftragsart] = {
    Stufe.AUDIO: Auftragsart.AUDIO,
    Stufe.TRANSKRIBIERT: Auftragsart.TRANSKRIPTION,
    Stufe.KORRIGIERT: Auftragsart.KORREKTUR,
    Stufe.GESTUECKELT: Auftragsart.STUECKELUNG,
    Stufe.EINGEBETTET: Auftragsart.EINBETTUNG,
}

STUFE_JE_AUFTRAG: dict[Auftragsart, Stufe] = {v: k for k, v in AUFTRAG_JE_STUFE.items()}

VIDEO_AUFTRAGSARTEN: tuple[Auftragsart, ...] = (
    Auftragsart.AUDIO,
    Auftragsart.TRANSKRIPTION,
    Auftragsart.KORREKTUR,
    Auftragsart.STUECKELUNG,
    Auftragsart.EINBETTUNG,
)


def stufen_index(stufe: Stufe) -> int:
    return STUFEN_REIHENFOLGE.index(stufe)


def naechste_stufe(stufe: Stufe) -> Stufe | None:
    """Die Stufe nach der gegebenen, oder None am Ende des Bands."""
    i = stufen_index(stufe)
    if i + 1 >= len(STUFEN_REIHENFOLGE):
        return None
    return STUFEN_REIHENFOLGE[i + 1]


def vorstufe(art: Auftragsart) -> Stufe:
    """Welche Stufe ein Video mindestens haben muss, damit dieser Auftrag laufen kann."""
    ziel = STUFE_JE_AUFTRAG[art]
    return STUFEN_REIHENFOLGE[stufen_index(ziel) - 1]


def naechste_auftragsart(stufe: Stufe) -> Auftragsart | None:
    """Der Auftrag, der ein Video mit dieser Stufe eine Stufe weiterbringt."""
    folge = naechste_stufe(stufe)
    if folge is None:
        return None
    return AUFTRAG_JE_STUFE[folge]


STUFEN_TITEL: dict[Stufe, str] = {
    Stufe.ENTDECKT: "Entdeckt",
    Stufe.AUDIO: "Audio bereit",
    Stufe.TRANSKRIBIERT: "Transkribiert",
    Stufe.KORRIGIERT: "Korrigiert",
    Stufe.GESTUECKELT: "Gestückelt",
    Stufe.EINGEBETTET: "Eingebettet",
}

AUFTRAGSART_TITEL: dict[Auftragsart, str] = {
    Auftragsart.QUELLE_ABGLEICH: "Quelle abgleichen",
    Auftragsart.AUDIO: "Audio beschaffen",
    Auftragsart.TRANSKRIPTION: "Transkribieren",
    Auftragsart.KORREKTUR: "Korrigieren",
    Auftragsart.STUECKELUNG: "Stückeln",
    Auftragsart.EINBETTUNG: "Einbetten",
}
