"""Audio capture using sounddevice."""

import threading

import numpy as np
import sounddevice as sd

from whisper_typewriter.config import Config


class AudioRecorder:
    """Records audio from the microphone into a buffer."""

    def __init__(self, config: Config):
        self._rate = config.audio_sample_rate
        self._channels = config.audio_channels
        self._lock = threading.Lock()
        self._chunks: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None

    def start(self) -> None:
        """Begin recording."""
        # Close any existing stream (e.g. rapid re-trigger)
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()

        with self._lock:
            self._chunks.clear()

        self._stream = sd.InputStream(
            samplerate=self._rate,
            channels=self._channels,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        """Stop recording and return audio as float32 numpy array."""
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        with self._lock:
            if not self._chunks:
                return np.array([], dtype=np.float32)
            audio = np.concatenate(self._chunks, axis=0)
            self._chunks.clear()

        return audio.flatten()

    def _callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        with self._lock:
            self._chunks.append(indata.copy())
