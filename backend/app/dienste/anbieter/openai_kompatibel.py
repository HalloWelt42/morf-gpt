"""OpenAI-kompatibler Anbieter (Chat und Einbettung) über httpx.

Deckt LM Studio (`/v1`) und Cloud-Dienste wie die Hetzner-Inferenz ab. Sendet das
Modell IMMER mit (LM Studio lädt es sonst nicht per JIT und antwortet mit 400) und
liest Fehlerkörper aus, statt nackte HTTP-Codes zu melden.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .basis import (
    AnbieterFehler,
    AnbieterInfo,
    Antwort,
    Antwortparameter,
    Delta,
    Nachricht,
    Werkzeugaufruf,
)


def _fehlertext(resp: httpx.Response) -> str:
    try:
        daten = resp.json()
        if isinstance(daten, dict):
            err = daten.get("error")
            if isinstance(err, dict) and err.get("message"):
                return str(err["message"])
            if isinstance(err, str):
                return err
            if daten.get("detail"):
                return str(daten["detail"])
    except ValueError:
        pass
    return resp.text[:400] or f"HTTP {resp.status_code}"


def denk_tokens_aus(nutzung: dict[str, Any]) -> int:
    """Token für unsichtbares Denken aus dem Nutzungsblock (OpenAI-Form completion_tokens_details.reasoning_tokens)."""
    details = nutzung.get("completion_tokens_details")
    if isinstance(details, dict):
        try:
            return int(details.get("reasoning_tokens") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def _werkzeugaufrufe_lesen(roh: Any) -> list[Werkzeugaufruf]:
    """tool_calls der OpenAI-Antwort in Werkzeugaufrufe wandeln; kaputte Argumente werden leer."""
    aus: list[Werkzeugaufruf] = []
    for i, tc in enumerate(roh or []):
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        argumente_roh = fn.get("arguments")
        argumente: dict[str, Any] = {}
        if isinstance(argumente_roh, dict):
            argumente = argumente_roh
        elif isinstance(argumente_roh, str) and argumente_roh.strip():
            try:
                geparst = json.loads(argumente_roh)
                if isinstance(geparst, dict):
                    argumente = geparst
            except ValueError:
                argumente = {}
        aus.append(Werkzeugaufruf(id=str(tc.get("id") or f"aufruf_{i}"), name=name, argumente=argumente))
    return aus


class OpenAiKompatibel:
    """Sprachmodell über /v1/chat/completions."""

    def __init__(self, info: AnbieterInfo, api_schluessel: str = "", zusatz: dict[str, Any] | None = None, denken: str = "") -> None:
        self.info = info
        self._basis = info.basis_url.rstrip("/")
        self._schluessel = api_schluessel
        self._zusatz = zusatz or {}
        # Denkmodus: "aus" oder "an" wird als chat_template_kwargs.enable_thinking gesendet (vLLM-artige
        # Dienste wie Hetzner); "" lässt den Dienst entscheiden.
        self._denken = denken

    def _kopf(self) -> dict[str, str]:
        kopf = {"Content-Type": "application/json"}
        if self._schluessel:
            kopf["Authorization"] = f"Bearer {self._schluessel}"
        return kopf

    def _nutzlast(self, nachrichten: list[Nachricht], p: Antwortparameter, stream: bool) -> dict[str, Any]:
        nutzlast: dict[str, Any] = {
            "model": self.info.modell,
            "messages": [n.als_openai() for n in nachrichten],
            "temperature": p.temperatur,
            "max_tokens": p.max_tokens,
            "stream": stream,
        }
        if stream:
            nutzlast["stream_options"] = {"include_usage": True}
        if p.json_schema is not None:
            # LM Studio kennt nur json_schema/text, OpenAI-kompatible Dienste meist beides.
            nutzlast["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "antwort", "strict": True, "schema": p.json_schema},
            }
        elif p.json_modus:
            nutzlast["response_format"] = {"type": "json_object"}
        if p.stopp:
            nutzlast["stop"] = p.stopp
        if p.werkzeuge:
            nutzlast["tools"] = p.werkzeuge
            nutzlast["tool_choice"] = "auto"
        if self._denken in ("aus", "an"):
            nutzlast["chat_template_kwargs"] = {"enable_thinking": self._denken == "an"}
        nutzlast.update(self._zusatz)
        return nutzlast

    async def antworte(self, nachrichten: list[Nachricht], parameter: Antwortparameter) -> Antwort:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(parameter.zeitgrenze_s, connect=20)) as client:
                resp = await client.post(
                    f"{self._basis}/chat/completions",
                    headers=self._kopf(),
                    json=self._nutzlast(nachrichten, parameter, stream=False),
                )
        except httpx.HTTPError as e:
            raise AnbieterFehler(f"{self.info.name}: nicht erreichbar ({e.__class__.__name__})") from e
        if resp.status_code != 200:
            raise AnbieterFehler(f"{self.info.name}: {_fehlertext(resp)}")
        daten = resp.json()
        try:
            nachricht = daten["choices"][0]["message"]
            text = nachricht.get("content") or ""
        except (KeyError, IndexError, TypeError) as e:
            raise AnbieterFehler(f"{self.info.name}: unerwartete Antwort") from e
        nutzung = daten.get("usage") or {}
        return Antwort(
            text=text,
            modell=str(daten.get("model") or self.info.modell),
            tokens_ein=nutzung.get("prompt_tokens"),
            tokens_aus=nutzung.get("completion_tokens"),
            roh=daten,
            werkzeugaufrufe=_werkzeugaufrufe_lesen(nachricht.get("tool_calls")),
            denk_tokens=denk_tokens_aus(nutzung),
            abgeschnitten=str(daten["choices"][0].get("finish_reason") or "") == "length",
        )

    async def streame(self, nachrichten: list[Nachricht], parameter: Antwortparameter) -> AsyncIterator[Delta]:
        modell = self.info.modell
        tokens_ein: int | None = None
        tokens_aus: int | None = None
        geliefert = False
        fehlerkoerper = ""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(parameter.zeitgrenze_s, connect=20)) as client:
                async with client.stream(
                    "POST",
                    f"{self._basis}/chat/completions",
                    headers=self._kopf(),
                    json=self._nutzlast(nachrichten, parameter, stream=True),
                ) as resp:
                    if resp.status_code != 200:
                        await resp.aread()
                        raise AnbieterFehler(f"{self.info.name}: {_fehlertext(resp)}")
                    async for zeile in resp.aiter_lines():
                        if not zeile:
                            continue
                        if not zeile.startswith("data:"):
                            fehlerkoerper += zeile[:300]
                            continue
                        nutz = zeile[5:].strip()
                        if nutz == "[DONE]":
                            break
                        try:
                            obj = json.loads(nutz)
                        except ValueError:
                            continue
                        if isinstance(obj, dict) and obj.get("error"):
                            err = obj["error"]
                            raise AnbieterFehler(f"{self.info.name}: {err.get('message') if isinstance(err, dict) else err}")
                        modell = str(obj.get("model") or modell)
                        nutzung = obj.get("usage")
                        if nutzung:
                            tokens_ein = nutzung.get("prompt_tokens", tokens_ein)
                            tokens_aus = nutzung.get("completion_tokens", tokens_aus)
                        for wahl in obj.get("choices") or []:
                            delta = (wahl.get("delta") or {}).get("content")
                            if delta:
                                geliefert = True
                                yield Delta(text=delta)
        except httpx.HTTPError as e:
            raise AnbieterFehler(f"{self.info.name}: Verbindung abgebrochen ({e.__class__.__name__})") from e
        if not geliefert:
            hinweis = fehlerkoerper.strip()[:200]
            raise AnbieterFehler(
                f"{self.info.name} lieferte keine Antwort. Ist das Modell '{self.info.modell}' geladen?"
                + (f" ({hinweis})" if hinweis else "")
            )
        yield Delta(fertig=True, modell=modell, tokens_ein=tokens_ein, tokens_aus=tokens_aus)

    async def erreichbar(self) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5)) as client:
                resp = await client.get(f"{self._basis}/models", headers=self._kopf())
        except httpx.HTTPError as e:
            return False, f"nicht erreichbar ({e.__class__.__name__})"
        if resp.status_code != 200:
            return False, _fehlertext(resp)
        return True, "erreichbar"

    async def modelle(self) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5)) as client:
                resp = await client.get(f"{self._basis}/models", headers=self._kopf())
        except httpx.HTTPError:
            return []
        if resp.status_code != 200:
            return []
        daten = resp.json()
        return [{"id": m.get("id", ""), "geladen": None} for m in daten.get("data", []) if isinstance(m, dict)]


class OpenAiKompatibelEinbettung:
    """Einbettung über /v1/embeddings."""

    def __init__(self, info: AnbieterInfo, api_schluessel: str = "") -> None:
        self.info = info
        self._basis = info.basis_url.rstrip("/")
        self._schluessel = api_schluessel

    def _kopf(self) -> dict[str, str]:
        kopf = {"Content-Type": "application/json"}
        if self._schluessel:
            kopf["Authorization"] = f"Bearer {self._schluessel}"
        return kopf

    async def einbetten(self, texte: list[str], zeitgrenze_s: float = 600.0, instanz: str | None = None) -> list[list[float]]:
        if not texte:
            return []
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(zeitgrenze_s, connect=20)) as client:
                resp = await client.post(
                    f"{self._basis}/embeddings",
                    headers=self._kopf(),
                    json={"model": instanz or self.info.modell, "input": texte},
                )
        except httpx.HTTPError as e:
            raise AnbieterFehler(f"{self.info.name}: nicht erreichbar ({e.__class__.__name__})") from e
        if resp.status_code != 200:
            raise AnbieterFehler(f"{self.info.name}: {_fehlertext(resp)}")
        daten = resp.json().get("data") or []
        daten = sorted(daten, key=lambda d: d.get("index", 0))
        vektoren = [list(map(float, d["embedding"])) for d in daten]
        if len(vektoren) != len(texte):
            raise AnbieterFehler(f"{self.info.name}: {len(vektoren)} Vektoren für {len(texte)} Texte")
        return vektoren

    async def erreichbar(self) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5)) as client:
                resp = await client.get(f"{self._basis}/models", headers=self._kopf())
        except httpx.HTTPError as e:
            return False, f"nicht erreichbar ({e.__class__.__name__})"
        if resp.status_code != 200:
            return False, _fehlertext(resp)
        return True, "erreichbar"

    async def modelle(self) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5)) as client:
                resp = await client.get(f"{self._basis}/models", headers=self._kopf())
        except httpx.HTTPError:
            return []
        if resp.status_code != 200:
            return []
        return [{"id": m.get("id", ""), "geladen": None} for m in resp.json().get("data", []) if isinstance(m, dict)]
