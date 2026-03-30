"""LLM-based transcript refinement using llama-cpp-python."""

import logging
from pathlib import Path

from huggingface_hub import hf_hub_download
from llama_cpp import Llama

from whisper_typewriter.config import Config

log = logging.getLogger(__name__)


class Refiner:
    """Cleans up transcripts using a local LLM."""

    def __init__(self, config: Config):
        self._config = config
        self._llm: Llama | None = None

    def load(self) -> None:
        """Download (if needed) and load the LLM. Call once at startup."""
        model_path = self._download_model()
        log.info("Loading LLM from %s ...", model_path)
        self._llm = Llama(
            model_path=str(model_path),
            n_ctx=self._config.llm_n_ctx,
            n_threads=self._config.llm_n_threads,
            verbose=False,
        )
        log.info("LLM loaded.")

    def refine(self, text: str) -> str:
        """Refine a raw transcript into formal, clean text."""
        if self._llm is None:
            raise RuntimeError("LLM not loaded. Call load() first.")

        if not text.strip():
            return ""

        response = self._llm.create_chat_completion(
            messages=[
                {"role": "system", "content": self._config.refine_prompt},
                {"role": "user", "content": text},
            ],
            max_tokens=len(text.split()) * 3,
            temperature=0.0,
        )

        choice = response["choices"][0]["message"]["content"]  # type: ignore[index]
        return choice.strip() if choice else text

    def _download_model(self) -> Path:
        """Download the GGUF model if not cached."""
        log.info("Ensuring LLM model is available (repo=%s, file=%s) ...",
                 self._config.llm_repo, self._config.llm_filename)
        path = hf_hub_download(
            repo_id=self._config.llm_repo,
            filename=self._config.llm_filename,
        )
        return Path(path)
