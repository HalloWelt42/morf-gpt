"""Werkzeuge: Pfadsprache, Platzhalter, Argumentableitung, Stellen aus Ergebnissen, Werkzeugschleife."""

from __future__ import annotations

from typing import Any

import pytest

from app.dienste.anbieter.basis import Antwort, Antwortparameter, Nachricht, Werkzeugaufruf
from app.dienste.werkzeuge import argumente, http_json
from app.dienste.werkzeuge.ausfuehrung import stellen_aus_ergebnis
from app.dienste.werkzeuge.basis import Quellenangabe, Werkzeugbeschreibung, funktionsname


def test_pfad_werte_sammelt_ueber_listen() -> None:
    daten = {"ergebnisse": [{"text": "a", "url": "u1"}, {"text": "b"}], "antwort": {"kern": "x"}}
    assert http_json.pfad_werte(daten, "ergebnisse[].text") == ["a", "b"]
    assert http_json.pfad_werte(daten, "ergebnisse[].url") == ["u1"]
    assert http_json.pfad_werte(daten, "antwort.kern") == ["x"]
    assert http_json.pfad_werte(daten, "ergebnisse[1].text") == ["b"]
    assert http_json.pfad_werte(daten, "fehlt.auch") == []
    assert http_json.pfad_werte(daten, "") == [daten]


def test_platzhalter_url_kodiert_und_rumpf_json_sicher() -> None:
    a = {"frage": 'Was ist "Kasualisierung" & Co?'}
    assert (
        http_json.platzhalter_fuellen("https://x/?q={frage}", a, url=True) == "https://x/?q=Was%20ist%20%22Kasualisierung%22%20%26%20Co%3F"
    )
    rumpf = http_json.platzhalter_fuellen('{"query": "{frage}"}', a, url=False)
    import json

    assert json.loads(rumpf) == {"query": 'Was ist "Kasualisierung" & Co?'}


def test_ergebnis_aus_antwort_liefert_stellen_mit_quellen() -> None:
    k = {"antwort_text": "treffer[].text", "antwort_url": "treffer[].url", "antwort_titel": "treffer[].titel"}
    daten = {"treffer": [{"text": "eins", "url": "http://a", "titel": "A"}, {"text": "zwei", "url": "http://b", "titel": "B"}]}
    e = http_json.ergebnis_aus_antwort(k, daten, "")
    assert [t for t, _ in e.stellen] == ["eins", "zwei"]
    assert e.stellen[1][1] == Quellenangabe(titel="B", url="http://b")


def test_ergebnis_ohne_pfad_nimmt_ganze_antwort() -> None:
    e = http_json.ergebnis_aus_antwort({}, None, "  Nur Text  ")
    assert e.text == "Nur Text"


def _b(props: dict[str, Any], pflicht: list[str]) -> Werkzeugbeschreibung:
    return Werkzeugbeschreibung(
        kennung="k", name="n", titel="T", beschreibung="", parameter_schema={"type": "object", "properties": props, "required": pflicht}
    )


def test_direkt_nur_bei_freitextparameter() -> None:
    assert argumente.direkt(_b({}, []), "Frage") == {}
    assert argumente.direkt(_b({"query": {"type": "string"}, "top_k": {"type": "integer"}}, ["query"]), "Frage") == {"query": "Frage"}
    assert argumente.direkt(_b({"ort": {"type": "string"}}, []), "Wetter in Leipzig?") is None
    assert argumente.direkt(_b({"query": {"type": "string"}, "titel": {"type": "string"}}, ["query", "titel"]), "x") is None


def test_notloesung_nimmt_ersten_textparameter() -> None:
    assert argumente.notloesung(_b({"ort": {"type": "string"}}, []), "Leipzig") == {"ort": "Leipzig"}
    assert argumente.notloesung(_b({"tage": {"type": "integer"}}, []), "x") == {}


class _FakeAnbieter:
    info = None

    def __init__(self, text: str) -> None:
        self._text = text
        self.aufrufe: list[list[Nachricht]] = []

    async def antworte(self, nachrichten: list[Nachricht], parameter: Antwortparameter) -> Antwort:
        self.aufrufe.append(nachrichten)
        return Antwort(text=self._text, modell="fake")


@pytest.mark.asyncio
async def test_ableiten_per_modell_und_pflichtfeld_ergaenzt() -> None:
    b = _b({"ort": {"type": "string"}, "tage": {"type": "integer"}}, [])
    a = _FakeAnbieter('{"ort": "Leipzig"}')
    args, herkunft = await argumente.ableiten(b, "Wetter in Leipzig morgen?", a, per_modell=True, zeitgrenze_s=5)
    assert args == {"ort": "Leipzig"} and herkunft == "modell"
    b2 = _b({"query": {"type": "string"}, "ort": {"type": "string"}}, ["query", "ort"])
    a2 = _FakeAnbieter('{"ort": "Leipzig"}')
    args2, _ = await argumente.ableiten(b2, "Frage", a2, per_modell=True, zeitgrenze_s=5)
    assert args2 == {"ort": "Leipzig", "query": "Frage"}


@pytest.mark.asyncio
async def test_ableiten_ohne_modell_faellt_auf_notloesung() -> None:
    b = _b({"ort": {"type": "string"}}, [])
    args, herkunft = await argumente.ableiten(b, "Leipzig", None, per_modell=False, zeitgrenze_s=5)
    assert args == {"ort": "Leipzig"} and herkunft == "notloesung"


def test_stellen_aus_ergebnis_bereinigt_und_kuerzt() -> None:
    b = _b({}, [])
    stellen = stellen_aus_ergebnis(b, [("Wetter – 20 °C 认为", Quellenangabe(titel="Q", url="http://q"))], ergebnis_zeichen=100)
    assert stellen[0].art == "werkzeug" and stellen[0].werkzeug == "T" and stellen[0].quelle_url == "http://q"
    assert "–" not in stellen[0].text and "认为" not in stellen[0].text


def test_funktionsname_ascii() -> None:
    assert funktionsname("Fundus: Wetter (Ort)") == "fundus_wetter_ort"
    assert funktionsname("Größe") == "groesse"


def test_werkzeugaufruf_in_openai_nachricht() -> None:
    n = Nachricht("assistant", "", werkzeugaufrufe=[Werkzeugaufruf(id="1", name="f", argumente={"a": 1})])
    d = n.als_openai()
    assert d["content"] is None and d["tool_calls"][0]["function"]["name"] == "f"
    t = Nachricht("tool", "Ergebnis", werkzeugaufruf_id="1").als_openai()
    assert t == {"role": "tool", "content": "Ergebnis", "tool_call_id": "1"}
