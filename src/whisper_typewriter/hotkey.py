"""Global hotkey listener using evdev (Linux input subsystem)."""

import getpass
import grp
import logging
import threading
from typing import Callable

import evdev
from evdev import ecodes

log = logging.getLogger(__name__)

# Push-to-talk key
_RIGHT_ALT = ecodes.KEY_RIGHTALT

# Used for keyboard detection (any real keyboard has alphabetic keys)
_KEY_A = ecodes.KEY_A
_KEY_Z = ecodes.KEY_Z


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

    # Prefer devices with alphabetic keys and Right Alt (real keyboards)
    for dev in devices:
        caps = dev.capabilities(verbose=False)
        ev_key = ecodes.EV_KEY
        if ev_key not in caps:
            continue
        keys = caps[ev_key]
        if _KEY_A in keys and _KEY_Z in keys and _RIGHT_ALT in keys:
            log.info("Using keyboard: %s (%s)", dev.name, dev.path)
            return dev

    # Fallback: any device with Right Alt
    for dev in devices:
        caps = dev.capabilities(verbose=False)
        if ecodes.EV_KEY in caps and _RIGHT_ALT in caps[ecodes.EV_KEY]:
            log.info("Using keyboard (fallback): %s (%s)", dev.name, dev.path)
            return dev

    raise RuntimeError(
        "No keyboard device found among %d input devices. "
        "Is a keyboard connected?" % len(devices)
    )


class HotkeyListener:
    """Listens for Right Alt (push-to-talk)."""

    def __init__(
        self,
        on_record_start: Callable[[], None],
        on_record_stop: Callable[[], None],
    ):
        self._on_record_start = on_record_start
        self._on_record_stop = on_record_stop
        self._device: evdev.InputDevice | None = None
        self._uinput: evdev.UInput | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()  # guards _uinput access during shutdown

    def start(self) -> None:
        """Start listening in a background thread."""
        self._device = find_keyboard()
        self._device.grab()  # exclusive access — prevents Right Alt reaching apps
        self._uinput = evdev.UInput.from_device(
            self._device, name="whisper-typewriter-passthrough"
        )
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop listening and release the device."""
        self._running = False
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
            self._device.close()
            self._device = None

    def _loop(self) -> None:
        """Event loop reading from the evdev device."""
        assert self._device is not None
        try:
            for event in self._device.read_loop():
                if not self._running:
                    break
                if event.type == ecodes.EV_KEY:
                    self._handle_key(event)
                else:
                    # Forward all non-key events (EV_MSC, EV_SYN, EV_LED, etc.)
                    self._forward_event(event)
        except OSError:
            if self._running:
                log.error("Keyboard device disconnected.")

    def _handle_key(self, event: evdev.InputEvent) -> None:
        key = event.code

        # Right Alt push-to-talk (consumed entirely — never forwarded)
        if key == _RIGHT_ALT:
            if event.value == 1:  # press
                self._on_record_start()
            elif event.value == 0:  # release
                self._on_record_stop()
            # value == 2 (hold/repeat) is intentionally ignored
            return

        # Forward all other key events
        self._forward_event(event)

    def _forward_event(self, event: evdev.InputEvent) -> None:
        """Re-inject an event so non-hotkey input still works normally."""
        with self._lock:
            if self._uinput is None:
                return
            try:
                self._uinput.write_event(event)
            except OSError:
                pass
