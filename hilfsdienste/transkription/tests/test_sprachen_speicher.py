import pytest

from app.speicher import Speicherstand, darf_laden, speicherstand
from app.sprachen import code_fuer


def test_sprachcodes():
    assert code_fuer("german") == "de"
    assert code_fuer("Deutsch") == "de"
    assert code_fuer("en") == "en"
    assert code_fuer("auto") is None
    assert code_fuer("") is None
    with pytest.raises(ValueError):
        code_fuer("klingonisch")


def test_speicherregel():
    erlaubt, hinweis = darf_laden(Speicherstand(128, 40, True), 3.5, 8)
    assert erlaubt and hinweis == ""
    erlaubt, hinweis = darf_laden(Speicherstand(128, 10, True), 3.5, 8)
    assert not erlaubt and "Nicht genug" in hinweis
    erlaubt, hinweis = darf_laden(Speicherstand(0, 0, False), 3.5, 8)
    assert erlaubt and "unbekannt" in hinweis


def test_speicherstand_dieses_rechners():
    stand = speicherstand()
    if stand.bekannt:
        assert stand.gesamt_gb > 0 and 0 <= stand.verfuegbar_gb <= stand.gesamt_gb
