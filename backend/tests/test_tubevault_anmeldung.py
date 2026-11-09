"""HELF-169: TubeVault steht im Heimnetz hinter dem Vorbau des Pi; morf-gpt meldet sich dort mit seinem App-Schlüssel
der Kellerwolke an. Ohne Schlüssel geht kein Kopf mit."""

from __future__ import annotations

import httpx
import pytest

from app.dienste.quellen.tubevault import TubeVault


@pytest.mark.asyncio
async def test_app_schluessel_geht_mit_jeder_anfrage() -> None:
    koepfe: list[str | None] = []

    def antwort(r: httpx.Request) -> httpx.Response:
        koepfe.append(r.headers.get("authorization"))
        return httpx.Response(200, json={"channel_id": "k1", "channel_name": "Kanal"})

    mit = TubeVault("https://tube.test", "k1", transport=httpx.MockTransport(antwort), schluessel="kw_app_morf")
    ohne = TubeVault("https://tube.test", "k1", transport=httpx.MockTransport(antwort))
    try:
        assert (await mit.kanal()).name == "Kanal"
        await ohne.kanal()
    finally:
        await mit.schliessen()
        await ohne.schliessen()
    assert koepfe == ["Bearer kw_app_morf", None]
