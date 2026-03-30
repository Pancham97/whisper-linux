"""Whisper transcription using faster-whisper."""

import logging
import numpy as np
from faster_whisper import WhisperModel

from whisper_typewriter.config import Config

log = logging.getLogger(__name__)

# Minimum audio duration (seconds) to attempt transcription
_MIN_DURATION_S = 0.3


class Transcriber:
    """Loads Whisper model and transcribes audio buffers."""

    def __init__(self, config: Config):
        self._config = config
        self._model: WhisperModel | None = None

    def load(self) -> None:
        """Load the Whisper model. Call once at startup."""
        log.info("Loading Whisper model '%s' on %s ...",
                 self._config.whisper_model, self._config.whisper_device)
        self._model = WhisperModel(
            self._config.whisper_model,
            device=self._config.whisper_device,
            compute_type=self._config.whisper_compute_type,
        )
        log.info("Whisper model loaded.")

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe a float32 16kHz audio array to text."""
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        duration = len(audio) / self._config.audio_sample_rate
        if duration < _MIN_DURATION_S:
            log.debug("Audio too short (%.2fs), skipping.", duration)
            return ""

        segments, info = self._model.transcribe(
            audio,
            beam_size=5,
            language=self._config.language,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        text = " ".join(seg.text.strip() for seg in segments)
        log.debug("Transcribed (%.1fs, lang=%s): %s",
                  duration, info.language, text[:80])
        return text.strip()
