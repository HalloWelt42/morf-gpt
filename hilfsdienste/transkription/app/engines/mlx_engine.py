"""Engine mlx: Whisper über MLX auf Apple Silicon (Grafikeinheit).

Die Modellablage liegt im Projekt (HF_HOME zeigt darauf, bevor irgendetwas davon importiert
wird). Das Modell bleibt je Prozess geladen; die Größe wird nach dem Laden gemessen.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .basis import Rohtranskript, Segment, woerter_aus


class MlxEngine:
    kennung = "mlx"

    def __init__(self, modell: str, cache: str) -> None:
        self.modell = modell
        self._cache = Path(cache)
        self._groesse_gb = 0.0

    def laden(self) -> None:
        os.environ["HF_HOME"] = str(self._cache)
        import mlx.core as mx
        from mlx_whisper.transcribe import ModelHolder

        ModelHolder.get_model(self.modell, mx.float16)
        messen = getattr(mx, "get_active_memory", None) or getattr(getattr(mx, "metal", None), "get_active_memory", None)
        self._groesse_gb = float(messen()) / 1024**3 if messen else 0.0

    def groesse_gb(self) -> float:
        return self._groesse_gb

    def transkribiere(self, pfad: Path, sprache_code: str | None, wortzeiten: bool) -> Rohtranskript:
        import mlx_whisper

        roh: dict[str, Any] = mlx_whisper.transcribe(
            str(pfad),
            path_or_hf_repo=self.modell,
            language=sprache_code,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            compression_ratio_threshold=2.4,
            word_timestamps=wortzeiten,
            verbose=False,
        )
        segmente = [
            Segment(float(s.get("start", 0.0)), float(s.get("end", 0.0)), str(s.get("text", "")), woerter_aus(s.get("words")))
            for s in roh.get("segments", [])
            if isinstance(s, dict)
        ]
        return Rohtranskript(
            text=str(roh.get("text", "")), segmente=segmente, sprache=str(roh.get("language") or sprache_code or ""), modell=self.modell
        )
