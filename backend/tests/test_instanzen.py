"""Tests für die Instanzenverwaltung der Einbettung: Kennungen, Speicherregel, Verteilung (ohne LM Studio)."""

from __future__ import annotations

from app.dienste.einbettung import instanzen
from app.dienste.einbettung.dienst import instanzen_verteilung


def test_kennungen() -> None:
    assert instanzen.kennungen("bge", 1) == ["bge"]
    assert instanzen.kennungen("bge", 3) == ["bge", "bge-instanz-2", "bge-instanz-3"]


def test_speicherregel() -> None:
    assert instanzen.passt_in_speicher(20.0, 0.63, 8) is True
    assert instanzen.passt_in_speicher(8.5, 0.63, 8) is False
    assert instanzen.passt_in_speicher(0.0, 0.63, 0) is False


def test_verteilung_rund_um() -> None:
    stapel = [["a"], ["b"], ["c"], ["d"], ["e"]]
    ziele = instanzen_verteilung(stapel, ["bge", "bge-instanz-2"])  # type: ignore[arg-type]
    assert [k for _, k in ziele] == ["bge", "bge-instanz-2", "bge", "bge-instanz-2", "bge"]
    assert [k for _, k in instanzen_verteilung(stapel[:2], [None])] == [None, None]  # type: ignore[arg-type]


def test_aktive_kennungen_nur_geladene() -> None:
    s = instanzen.Instanzstand(
        modell="bge",
        gewuenscht=3,
        geladen=[instanzen.Instanz("bge", 0.6), instanzen.Instanz("bge-instanz-3", 0.6)],
        speicher=instanzen.Speicherstand(128, 20, 20),
    )
    assert instanzen.aktive_kennungen(s) == ["bge", "bge-instanz-3"]
    assert instanzen.aktive_kennungen(instanzen.Instanzstand("bge", 2, [], instanzen.Speicherstand(1, 1, 1))) == ["bge"]
