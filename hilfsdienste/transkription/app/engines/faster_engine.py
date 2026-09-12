"""Engine faster: Whisper über CTranslate2 (Prozessor oder CUDA), für Rechner ohne Apple Silicon.

Modellnamen wie large-v3-turbo oder ein Ablageverzeichnis; die Gewichte landen unter der
Modellablage des Projekts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .basis import Rohtranskript, Segment, Wort


class FasterEngine:
    kennung = "faster"

    def __init__(self, modell: str, cache: str, rechner: str = "auto") -> None:
        self.modell = modell
        self._cache = Path(cache) / "faster"
        self._rechner = rechner
        self._modell: Any = None
        self._groesse_gb = 0.0

    def laden(self) -> None:
        from faster_whisper import WhisperModel
        from faster_whisper.utils import download_model

        self._cache.mkdir(parents=True, exist_ok=True)
        pfad = Path(self.modell) if Path(self.modell).is_dir() else Path(download_model(self.modell, cache_dir=str(self._cache)))
        self._groesse_gb = sum(p.stat().st_size for p in pfad.rglob("*") if p.is_file()) / 1024**3
        self._modell = WhisperModel(str(pfad), device=self._rechner, compute_type="auto")

    def groesse_gb(self) -> float:
        return self._groesse_gb

    def speicher_gb(self) -> float:
        return self._groesse_gb

    def transkribiere(self, pfad: Path, sprache_code: str | None, wortzeiten: bool) -> Rohtranskript:
        if self._modell is None:
            self.laden()
        segmente_roh, info = self._modell.transcribe(
            str(pfad),
            language=sprache_code,
            word_timestamps=wortzeiten,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            compression_ratio_threshold=2.4,
            beam_size=5,
        )
        segmente: list[Segment] = []
        for s in segmente_roh:
            woerter = [Wort(w.word, float(w.start), float(w.end)) for w in (s.words or []) if w.word.strip()] if wortzeiten else []
            segmente.append(Segment(float(s.start), float(s.end), s.text, woerter))
        text = " ".join(s.text.strip() for s in segmente if s.text.strip())
        sprache = str(getattr(info, "language", "") or sprache_code or "")
        return Rohtranskript(text=text, segmente=segmente, sprache=sprache, modell=self.modell)
