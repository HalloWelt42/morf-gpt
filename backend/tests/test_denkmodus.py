"""Denkmodus je Anbieter: Feld in der Anfrage, Denk-Token und Abschneiden in der Antwort."""

import httpx
import pytest

from app.dienste.anbieter.basis import AnbieterInfo, Antwortparameter, Nachricht
from app.dienste.anbieter.openai_kompatibel import OpenAiKompatibel, denk_tokens_aus

INFO = AnbieterInfo(kennung="a", name="Probe", typ="openai_kompatibel", modell="m", basis_url="http://dienst/v1")


def test_denkmodus_in_der_nutzlast():
    p = Antwortparameter()
    nachrichten = [Nachricht("user", "hallo")]
    assert "chat_template_kwargs" not in OpenAiKompatibel(INFO)._nutzlast(nachrichten, p, False)
    assert OpenAiKompatibel(INFO, denken="aus")._nutzlast(nachrichten, p, False)["chat_template_kwargs"] == {"enable_thinking": False}
    assert OpenAiKompatibel(INFO, denken="an")._nutzlast(nachrichten, p, False)["chat_template_kwargs"] == {"enable_thinking": True}


def test_denk_tokens_aus_nutzung():
    assert denk_tokens_aus({"completion_tokens_details": {"reasoning_tokens": 1000}}) == 1000
    assert denk_tokens_aus({"completion_tokens_details": {}}) == 0
    assert denk_tokens_aus({}) == 0


@pytest.mark.asyncio
async def test_leere_antwort_traegt_denk_tokens(monkeypatch):
    daten = {
        "choices": [{"message": {"role": "assistant", "content": "", "reasoning": "..."}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 93, "completion_tokens": 1000, "completion_tokens_details": {"reasoning_tokens": 1000}},
        "model": "m",
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=daten))
    echter = httpx.AsyncClient

    def client(*args, **kwargs):
        return echter(*args, transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    antwort = await OpenAiKompatibel(INFO, denken="").antworte([Nachricht("user", "x")], Antwortparameter(max_tokens=1000))
    assert antwort.text == "" and antwort.denk_tokens == 1000 and antwort.abgeschnitten
