"""Global hotkey listener using evdev (Linux input subsystem)."""

import getpass
import grp
import logging
import select
import threading
import time
from typing import Callable

import evdev
from evdev import ecodes

log = logging.getLogger(__name__)

# Push-to-talk key
_RIGHT_ALT = ecodes.KEY_RIGHTALT

# How long Right Alt must be held before recording starts (seconds).
# Shorter presses are forwarded as normal keystrokes so that shortcuts
# like Alt+Enter, Alt+Space, etc. still work.
_HOLD_THRESHOLD = 1.0

# Used for keyboard detection (any real keyboard has alphabetic keys)
_KEY_A = ecodes.KEY_A
_KEY_Z = ecodes.KEY_Z

# Right Alt states
_IDLE = "idle"              # not held
_PENDING = "pending"        # held, waiting for threshold
_RECORDING = "recording"    # held past threshold, audio being captured
_PASSTHROUGH = "passthrough" # held but used as modifier in a combo

# Reconnection backoff
_INITIAL_BACKOFF = 1.0      # seconds
_MAX_BACKOFF = 30.0         # seconds


def find_keyboard() -> evdev.InputDevice:
    """Auto-detect the primary keyboard device."""
    device_paths = evdev.list_devices()
    if not device_paths:
        try:
            input_members = grp.getgrnam("input").gr_mem
        except KeyError:
            input_members = []
        user = getpass.getuser()
        if user not in input_members:
            raise RuntimeError(
                f"Cannot access /dev/input — user '{user}' is not in the "
                f"'input' group.\n\n"
                f"  1. Run:  sudo usermod -aG input {user}\n"
                f"  2. Log out and log back in (required for group change)\n"
                f"  3. Re-run:  python -m whisper_typewriter\n\n"
                f"  Quick test without re-login:\n"
                f"    sudo .venv/bin/python -m whisper_typewriter"
            )
        raise RuntimeError(
            "No input devices found despite being in the 'input' group. "
            "Check that /dev/input/event* files exist."
        )

    devices = [evdev.InputDevice(path) for path in device_paths]

    chosen: evdev.InputDevice | None = None
    fallback: evdev.InputDevice | None = None

    for dev in devices:
        caps = dev.capabilities(verbose=False)
        ev_key = ecodes.EV_KEY
        if ev_key not in caps:
            continue
        keys = caps[ev_key]
        # Prefer devices with alphabetic keys and Right Alt (real keyboards)
        if chosen is None and _KEY_A in keys and _KEY_Z in keys and _RIGHT_ALT in keys:
            chosen = dev
        # Fallback: any device with Right Alt
        elif fallback is None and _RIGHT_ALT in keys:
            fallback = dev

    result = chosen or fallback

    # Close every device we opened except the one we're returning
    for dev in devices:
        if dev is not result:
            try:
                dev.close()
            except OSError:
                pass

    if result is None:
        raise RuntimeError(
            "No keyboard device found among %d input devices. "
            "Is a keyboard connected?" % len(devices)
        )

    kind = "keyboard" if result is chosen else "keyboard (fallback)"
    log.info("Using %s: %s (%s)", kind, result.name, result.path)
    return result


class HotkeyListener:
    """Listens for Right Alt (push-to-talk) with a hold threshold.

    Right Alt must be held for at least _HOLD_THRESHOLD seconds before
    recording starts. If released sooner or combined with another key,
    the keystrokes are forwarded normally.

    The listener automatically reconnects to the keyboard device if it
    becomes unavailable (e.g. sleep/wake, USB replug, device
    re-enumeration).  An optional *on_status* callback is invoked with
    ``True`` when connected and ``False`` when disconnected.
    """

    def __init__(
        self,
        on_record_start: Callable[[], None],
        on_record_stop: Callable[[], None],
        on_status: Callable[[bool], None] | None = None,
    ):
        self._on_record_start = on_record_start
        self._on_record_stop = on_record_stop
        self._on_status = on_status
        self._device: evdev.InputDevice | None = None
        self._uinput: evdev.UInput | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._stop_event = threading.Event()
        self._lock = threading.Lock()  # guards _uinput access during shutdown

        # Right Alt hold state
        self._ralt_state = _IDLE
        self._ralt_press_time = 0.0

    # ── lifecycle ────────────────────────────────────────────────────

    def start(self) -> None:
        """Start listening in a background thread.

        Connection and reconnection are handled inside the thread, so
        this method returns immediately.
        """
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop listening and release the device."""
        self._running = False
        self._stop_event.set()          # unblock backoff sleeps
        self._disconnect()              # unblock select()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    # ── connection management ────────────────────────────────────────

    def _connect(self) -> bool:
        """Find the keyboard, grab it, and create the passthrough UInput.

        Returns ``True`` on success, ``False`` on failure (caller should
        retry after a delay).
        """
        try:
            device = find_keyboard()
            device.grab()
            uinput = evdev.UInput.from_device(
                device, name="whisper-typewriter-passthrough",
            )
        except Exception as e:
            log.warning("Could not connect to keyboard: %s", e)
            # Clean up anything that was partially created
            try:
                device.ungrab()  # type: ignore[possibly-undefined]
            except Exception:
                pass
            try:
                device.close()  # type: ignore[possibly-undefined]
            except Exception:
                pass
            return False

        self._device = device
        with self._lock:
            self._uinput = uinput
        return True

    def _disconnect(self) -> None:
        """Release current device resources.  Idempotent."""
        with self._lock:
            if self._uinput is not None:
                try:
                    self._uinput.close()
                except OSError:
                    pass
                self._uinput = None
        if self._device is not None:
            try:
                self._device.ungrab()
            except OSError:
                pass
            try:
                self._device.close()
            except OSError:
                pass
            self._device = None

    # ── helpers ──────────────────────────────────────────────────────

    def _notify_status(self, connected: bool) -> None:
        if self._on_status is not None:
            try:
                self._on_status(connected)
            except Exception:
                pass

    def _safe_record_start(self) -> None:
        """Call the record-start callback, catching errors so the event
        loop is not killed by e.g. audio-device failures."""
        try:
            self._on_record_start()
        except Exception:
            log.exception("Error in record-start callback")

    def _safe_record_stop(self) -> None:
        """Call the record-stop callback safely."""
        try:
            self._on_record_stop()
        except Exception:
            log.exception("Error in record-stop callback")

    # ── main thread entry ────────────────────────────────────────────

    def _run(self) -> None:
        """Outer loop: connect, run event loop, reconnect on failure.

        Uses exponential backoff between reconnection attempts.  Resets
        the backoff on every successful connection.
        """
        backoff = _INITIAL_BACKOFF

        while self._running:
            if not self._connect():
                self._notify_status(False)
                if self._stop_event.wait(timeout=min(backoff, _MAX_BACKOFF)):
                    break  # stop() was called
                backoff = min(backoff * 2, _MAX_BACKOFF)
                continue

            # Connected successfully
            self._notify_status(True)
            backoff = _INITIAL_BACKOFF     # reset backoff
            self._ralt_state = _IDLE       # reset state machine
            self._ralt_press_time = 0.0

            self._loop()                   # blocks until error or stop

            self._disconnect()

            if self._running:
                self._notify_status(False)
                log.info(
                    "Will attempt to reconnect in %.0f seconds...",
                    min(backoff, _MAX_BACKOFF),
                )
                if self._stop_event.wait(timeout=min(backoff, _MAX_BACKOFF)):
                    break  # stop() was called
                backoff = min(backoff * 2, _MAX_BACKOFF)

    # ── event loop ───────────────────────────────────────────────────

    def _loop(self) -> None:
        """Event loop with select-based timeout for the hold threshold.

        Returns on device error (caller will reconnect) or when
        ``stop()`` is called.
        """
        assert self._device is not None
        try:
            while self._running:
                # When Right Alt is pending, use a timeout so we know
                # when the threshold is reached even if no keys are pressed.
                timeout = None
                if self._ralt_state == _PENDING:
                    elapsed = time.monotonic() - self._ralt_press_time
                    timeout = max(0, _HOLD_THRESHOLD - elapsed)

                ready, _, _ = select.select([self._device], [], [], timeout)

                if not self._running:
                    break

                if not ready:
                    # Timeout fired — Right Alt held past threshold
                    self._ralt_state = _RECORDING
                    self._safe_record_start()
                    continue

                for event in self._device.read():
                    if not self._running:
                        return
                    if event.type == ecodes.EV_KEY:
                        self._handle_key(event)
                    else:
                        self._forward_event(event)
        except Exception as e:
            if self._running:
                log.error("Keyboard error (%s): %s", type(e).__name__, e)

    def _handle_key(self, event: evdev.InputEvent) -> None:
        key = event.code

        # ── Right Alt events ────────────────────────────────────────
        if key == _RIGHT_ALT:
            if event.value == 1:  # press
                self._ralt_state = _PENDING
                self._ralt_press_time = time.monotonic()
                return  # buffer — don't forward yet

            elif event.value == 0:  # release
                if self._ralt_state == _RECORDING:
                    self._safe_record_stop()
                elif self._ralt_state == _PENDING:
                    # Quick tap — forward as a normal Right Alt press+release
                    self._inject_key(_RIGHT_ALT, 1)
                    self._inject_key(_RIGHT_ALT, 0)
                elif self._ralt_state == _PASSTHROUGH:
                    # Was used as modifier — forward the release
                    self._inject_key(_RIGHT_ALT, 0)
                self._ralt_state = _IDLE
                return

            elif event.value == 2:  # repeat
                if self._ralt_state == _PASSTHROUGH:
                    self._inject_key(_RIGHT_ALT, 2)
                # Consume repeats during pending/recording
                return

        # ── Other keys while Right Alt is pending ───────────────────
        if self._ralt_state == _PENDING:
            # Another key was pressed — this is a combo (e.g. Alt+Enter).
            # Forward the buffered Right Alt press, then this key.
            self._ralt_state = _PASSTHROUGH
            self._inject_key(_RIGHT_ALT, 1)
            self._forward_event(event)
            return

        # ── All other cases: forward normally ───────────────────────
        self._forward_event(event)

    def _inject_key(self, code: int, value: int) -> None:
        """Inject a synthetic key event through uinput."""
        with self._lock:
            if self._uinput is None:
                return
            try:
                self._uinput.write(ecodes.EV_KEY, code, value)
                self._uinput.syn()
            except OSError:
                pass

    def _forward_event(self, event: evdev.InputEvent) -> None:
        """Re-inject an event so non-hotkey input still works normally."""
        with self._lock:
            if self._uinput is None:
                return
            try:
                self._uinput.write_event(event)
            except OSError:
                pass
