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
import sys
from pathlib import Path
from typing import Any

from .basis import Fortschritt, Rohtranskript, Segment, woerter_aus

# Mel-Rahmen je Sekunde Audio (10 ms je Rahmen), so zählt die Bibliothek ihren Fortschritt
RAHMEN_JE_SEKUNDE = 100


class _Balken:
    """Ersatz für den Fortschrittsbalken der Bibliothek: reicht verarbeitete Rahmen als Sekunden weiter."""

    def __init__(self, fortschritt: Fortschritt | None, total: int | None = None, **_: Any) -> None:
        self._fortschritt = fortschritt
        self.total = int(total or 0)
        self.n = 0

    def __enter__(self) -> _Balken:
        return self

    def __exit__(self, *ausnahme: Any) -> bool:
        return False

    def update(self, n: int = 1) -> None:
        self.n += int(n)
        if self._fortschritt and self.total:
            self._fortschritt(self.n / RAHMEN_JE_SEKUNDE, self.total / RAHMEN_JE_SEKUNDE)

    def close(self) -> None:
        return None


class _Balkenfabrik:
    """Steht im Modul der Bibliothek an der Stelle von `tqdm`; `tqdm.tqdm(...)` liefert unseren Balken."""

    def __init__(self, fortschritt: Fortschritt | None) -> None:
        self._fortschritt = fortschritt

    def tqdm(self, *args: Any, **kwargs: Any) -> _Balken:
        return _Balken(self._fortschritt, *args, **kwargs)


def _echtes_tqdm() -> Any:
    import tqdm

    return tqdm


_ECHTES_TQDM = _echtes_tqdm()


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

    def transkribiere(
        self, pfad: Path, sprache_code: str | None, wortzeiten: bool, fortschritt: Fortschritt | None = None
    ) -> Rohtranskript:
        import mlx.core as mx
        import mlx_whisper

        # Die Bibliothek meldet ihren Stand nur über einen Fortschrittsbalken; der wird hier abgefangen.
        # Das Paket überdeckt sein Untermodul mit der gleichnamigen Funktion, darum der Weg über sys.modules.
        transcribe_modul = sys.modules["mlx_whisper.transcribe"]
        transcribe_modul.tqdm = _Balkenfabrik(fortschritt)
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
            transcribe_modul.tqdm = _ECHTES_TQDM
            mx.clear_cache()
        segmente = [
            Segment(float(s.get("start", 0.0)), float(s.get("end", 0.0)), str(s.get("text", "")), woerter_aus(s.get("words")))
            for s in roh.get("segments", [])
            if isinstance(s, dict)
        ]
        return Rohtranskript(
            text=str(roh.get("text", "")), segmente=segmente, sprache=str(roh.get("language") or sprache_code or ""), modell=self.modell
        )
