"""Configuration for Whisper Typewriter."""

from dataclasses import dataclass, field
from enum import Enum
import os


class Mode(Enum):
    VERBATIM = "verbatim"
    REFINE = "refine"


@dataclass
class Config:
    whisper_model: str = "large-v3-turbo"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    llm_repo: str = "bartowski/Phi-3.5-mini-instruct-GGUF"
    llm_filename: str = "Phi-3.5-mini-instruct-Q4_K_M.gguf"
    llm_n_ctx: int = 2048
    llm_n_threads: int = 4

    audio_sample_rate: int = 16000
    audio_channels: int = 1

    mode: Mode = Mode.VERBATIM
    language: str | None = None  # None = auto-detect

    refine_prompt: str = (
        "Rewrite the following spoken transcript to be clear, formal, and "
        "professional. Preserve all meaning. Fix grammar and filler words. "
        "Output ONLY the rewritten text, nothing else."
    )

    @classmethod
    def from_env(cls) -> "Config":
        """Create config with environment variable overrides."""
        cfg = cls()
        if v := os.environ.get("WT_WHISPER_MODEL"):
            cfg.whisper_model = v
        if v := os.environ.get("WT_LLM_THREADS"):
            cfg.llm_n_threads = int(v)
        if v := os.environ.get("WT_MODE"):
            cfg.mode = Mode(v.lower())
        return cfg
