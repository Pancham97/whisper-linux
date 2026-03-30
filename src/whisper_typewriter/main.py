"""Whisper Typewriter - main entry point."""

import logging
import signal
import threading

from whisper_typewriter.audio import AudioRecorder
from whisper_typewriter.config import Config, Mode
from whisper_typewriter.hotkey import HotkeyListener
from whisper_typewriter.refiner import Refiner
from whisper_typewriter.transcriber import Transcriber
from whisper_typewriter.tray import TrayIcon, preflight as tray_preflight
from whisper_typewriter.typer import type_text

log = logging.getLogger(__name__)


class App:
    """Orchestrates all components."""

    def __init__(self):
        self._config = Config.from_env()
        self._recorder = AudioRecorder(self._config)
        self._transcriber = Transcriber(self._config)
        self._refiner = Refiner(self._config)
        self._tray: TrayIcon | None = None
        self._hotkey: HotkeyListener | None = None
        self._shutdown = threading.Event()

    def run(self) -> None:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        log.info("Starting Whisper Typewriter...")

        # Check tray deps early — warn before slow model loading
        try:
            tray_preflight()
            self._tray_available = True
        except Exception as e:
            log.warning("Tray icon will be unavailable: %s", e)
            self._tray_available = False

        # Load models (heavy - downloads on first run)
        self._transcriber.load()
        self._refiner.load()
        log.info("All models loaded. Ready.")

        # Start hotkey listener
        self._hotkey = HotkeyListener(
            on_record_start=self._on_record_start,
            on_record_stop=self._on_record_stop,
        )
        self._hotkey.start()

        # Handle Ctrl+C gracefully
        signal.signal(signal.SIGINT, lambda *_: self._quit())
        signal.signal(signal.SIGTERM, lambda *_: self._quit())

        log.info("Hold Right Alt to record. Use tray menu to switch modes.")
        log.info("Running in %s mode. Ctrl+C to quit.", self._config.mode.value)

        # Run tray icon on the main thread (GTK/AppIndicator requires it).
        # Falls back to blocking on shutdown event if tray is unavailable.
        if self._tray_available:
            try:
                self._tray = TrayIcon(
                    initial_mode=self._config.mode,
                    on_mode_verbatim=lambda: self._set_mode(Mode.VERBATIM),
                    on_mode_refine=lambda: self._set_mode(Mode.REFINE),
                    on_quit=self._quit,
                    initial_language=self._config.language,
                    on_language=self._set_language,
                )
                self._tray.start()  # blocks until tray exits
            except Exception as e:
                log.warning("Tray icon failed: %s", e)
                self._tray = None
                self._shutdown.wait()
        else:
            self._shutdown.wait()

        self._cleanup()

    # -- callbacks --

    def _on_record_start(self) -> None:
        log.info("Recording...")
        self._recorder.start()
        if self._tray:
            self._tray.set_recording(True)

    def _on_record_stop(self) -> None:
        audio = self._recorder.stop()
        if self._tray:
            self._tray.set_recording(False)

        if len(audio) == 0:
            log.info("No audio captured.")
            return

        # Process in a thread to keep hotkey listener responsive
        threading.Thread(
            target=self._process_audio,
            args=(audio,),
            daemon=True,
        ).start()

    def _process_audio(self, audio) -> None:
        try:
            log.info("Transcribing...")
            text = self._transcriber.transcribe(audio)
            if not text:
                log.info("No speech detected.")
                return

            log.info("Raw: %s", text[:100])

            if self._config.mode == Mode.REFINE:
                log.info("Refining...")
                text = self._refiner.refine(text)
                log.info("Refined: %s", text[:100])

            type_text(text)
            log.info("Typed %d chars.", len(text))
        except Exception:
            log.exception("Error processing audio")

    def _set_mode(self, mode: Mode) -> None:
        self._config.mode = mode
        if self._tray:
            self._tray.set_mode(mode)
        log.info("Mode: %s", mode.value)

    def _set_language(self, language: str | None) -> None:
        self._config.language = language
        log.info("Language: %s", language or "auto-detect")

    def _quit(self) -> None:
        """Request shutdown — safe to call from any thread or signal handler."""
        self._shutdown.set()
        if self._tray:
            self._tray.stop()

    def _cleanup(self) -> None:
        """Tear down resources (call from main thread after tray exits)."""
        log.info("Shutting down...")
        if self._hotkey:
            self._hotkey.stop()


def main():
    App().run()


if __name__ == "__main__":
    main()
