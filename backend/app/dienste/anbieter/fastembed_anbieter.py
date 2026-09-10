"""Lokale Einbettung über fastembed (ONNX, CPU). Braucht keinen laufenden Dienst.

Damit kann die Bibliothek an einem Ort ohne LM Studio laufen. Das Modell wird beim
ersten Aufruf in das Modellverzeichnis des Projekts geladen (nicht ins Home).
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from ...config import einstellungen
from .basis import AnbieterFehler, AnbieterInfo

_modelle: dict[str, Any] = {}
_sperre = threading.Lock()

BEKANNTE_MODELLE: dict[str, int] = {
    "BAAI/bge-m3": 1024,
    "intfloat/multilingual-e5-large": 1024,
    "BAAI/bge-small-en-v1.5": 384,
}


def _lade(name: str) -> Any:
    with _sperre:
        if name not in _modelle:
            try:
                from fastembed import TextEmbedding
            except ImportError as e:  # pragma: no cover - Abhängigkeit fehlt
                raise AnbieterFehler("fastembed ist nicht installiert") from e
            einstellungen.modelle_verzeichnis.mkdir(parents=True, exist_ok=True)
            _modelle[name] = TextEmbedding(model_name=name, cache_dir=str(einstellungen.modelle_verzeichnis))
        return _modelle[name]


class FastembedEinbettung:
    def __init__(self, info: AnbieterInfo) -> None:
        self.info = info

    async def einbetten(self, texte: list[str], zeitgrenze_s: float = 600.0) -> list[list[float]]:
        if not texte:
            return []

        def _rechne() -> list[list[float]]:
            modell = _lade(self.info.modell)
            return [list(map(float, v)) for v in modell.embed(texte, batch_size=16)]

        try:
            return await asyncio.wait_for(asyncio.to_thread(_rechne), timeout=zeitgrenze_s)
        except TimeoutError as e:
            raise AnbieterFehler(f"{self.info.name}: Zeitgrenze überschritten") from e
        except Exception as e:  # Modell-Ladefehler, ONNX
            raise AnbieterFehler(f"{self.info.name}: {e}") from e

    async def erreichbar(self) -> tuple[bool, str]:
        try:
            from fastembed import TextEmbedding  # noqa: F401
        except ImportError:
            return False, "fastembed nicht installiert"
        if self.info.modell in _modelle:
            return True, "Modell geladen"
        return True, "bereit (Modell wird beim ersten Aufruf geladen)"

    async def modelle(self) -> list[dict[str, Any]]:
        return [{"id": name, "geladen": name in _modelle, "dimension": dim} for name, dim in BEKANNTE_MODELLE.items()]
