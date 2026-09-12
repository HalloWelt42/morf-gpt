"""Engine mlx: Whisper über MLX auf Apple Silicon (Grafikeinheit).

Die Modellablage liegt im Projekt (HF_HOME zeigt darauf, bevor irgendetwas davon importiert
wird). Das Modell bleibt je Prozess geladen; die Größe wird nach dem Laden gemessen.

Speicher: MLX hält freigegebene Grafikpuffer in einem Zwischenspeicher für die Wiederverwendung.
Ohne Grenze wächst er über lange Videos auf zig Gigabyte (gemessen: 91 GB nach drei Videos
von 40 Minuten), die macOS dann komprimiert. Darum bekommt der Zwischenspeicher eine Grenze
und wird nach jeder Datei geleert; das Modell selbst bleibt geladen.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .basis import Rohtranskript, Segment, woerter_aus


class MlxEngine:
    kennung = "mlx"

    def __init__(self, modell: str, cache: str, cache_limit_gb: float = 2.0) -> None:
        self.modell = modell
        self._cache = Path(cache)
        self._cache_limit_gb = cache_limit_gb
        self._groesse_gb = 0.0

    def laden(self) -> None:
        os.environ["HF_HOME"] = str(self._cache)
        import mlx.core as mx
        from mlx_whisper.transcribe import ModelHolder

        mx.set_cache_limit(int(self._cache_limit_gb * 1024**3))
        ModelHolder.get_model(self.modell, mx.float16)
        self._groesse_gb = self.speicher_gb()

    def groesse_gb(self) -> float:
        return self._groesse_gb

    def speicher_gb(self) -> float:
        """Belegte Grafikpuffer dieses Prozesses (Modell plus gerade genutzte Zwischenergebnisse)."""
        import mlx.core as mx

        return float(mx.get_active_memory() + mx.get_cache_memory()) / 1024**3

    def transkribiere(self, pfad: Path, sprache_code: str | None, wortzeiten: bool) -> Rohtranskript:
        import mlx.core as mx
        import mlx_whisper

        try:
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
        finally:
            mx.clear_cache()
        segmente = [
            Segment(float(s.get("start", 0.0)), float(s.get("end", 0.0)), str(s.get("text", "")), woerter_aus(s.get("words")))
            for s in roh.get("segments", [])
            if isinstance(s, dict)
        ]
        return Rohtranskript(
            text=str(roh.get("text", "")), segmente=segmente, sprache=str(roh.get("language") or sprache_code or ""), modell=self.modell
        )
