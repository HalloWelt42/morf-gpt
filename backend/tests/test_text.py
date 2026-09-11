"""Textregeln: gerade Zeichen, nur lateinische Schrift."""

from app.dienste.text import bereinige, gerade, nur_lateinisch


def test_gerade_ersetzt_typografische_zeichen() -> None:
    assert gerade("Cashflow – staatlich „so“ … ‚ja‘") == 'Cashflow - staatlich "so" ... \'ja\''


def test_umlaute_bleiben() -> None:
    assert nur_lateinisch("Größe, Übermut, Ärger, ß") == "Größe, Übermut, Ärger, ß"


def test_chinesische_zeichen_werden_entfernt() -> None:
    assert nur_lateinisch("weil er认为 in einer Demokratie") == "weil er in einer Demokratie"


def test_kyrillisch_und_vollbreite_entfernt() -> None:
    assert nur_lateinisch("Politik ist Привет Strategie") == "Politik ist Strategie"
    assert nur_lateinisch("Marketing）ist") == "Marketingist"


def test_bereinige_kombiniert() -> None:
    assert bereinige("Strategie – 认为 wichtig") == "Strategie - wichtig"


def test_griechisch_bleibt() -> None:
    assert nur_lateinisch("Entropie α und β") == "Entropie α und β"
