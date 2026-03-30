"""Type text at the cursor position (Wayland).

Tries wtype first (wlroots compositors), then falls back to
clipboard-paste via wl-copy + evdev uinput Ctrl+Shift+V (GNOME/Mutter).
"""

import atexit
import logging
import shutil
import subprocess
import time

log = logging.getLogger(__name__)

# Persistent uinput device for Ctrl+V simulation (lazy-init)
_uinput = None
_backend: str | None = None


def _detect_backend() -> str:
    """Detect which typing backend to use.  Result is cached."""
    global _backend
    if _backend is not None:
        return _backend

    if shutil.which("wtype"):
        # Probe whether the compositor supports the virtual-keyboard protocol
        result = subprocess.run(
            ["wtype", "--", ""],
            capture_output=True, text=True, timeout=5,
        )
        if "not support" not in (result.stderr or ""):
            _backend = "wtype"
            log.info("Typing backend: wtype")
            return _backend

    if shutil.which("wl-copy"):
        _backend = "clipboard"
        log.info("Typing backend: wl-copy + uinput Ctrl+Shift+V")
        return _backend

    raise RuntimeError(
        "No typing backend found. Install one of:\n"
        "  sudo apt install wtype        # for wlroots compositors (Sway)\n"
        "  sudo apt install wl-clipboard  # for GNOME/Mutter"
    )


def _get_uinput():
    """Get or create a persistent uinput device for Ctrl+Shift+V simulation."""
    global _uinput
    if _uinput is not None:
        return _uinput

    import evdev
    from evdev import ecodes

    capabilities = {ecodes.EV_KEY: [ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTSHIFT, ecodes.KEY_V]}
    _uinput = evdev.UInput(capabilities, name="whisper-typewriter-paste")
    # Give the compositor time to discover the new input device
    time.sleep(0.5)
    atexit.register(_cleanup_uinput)
    log.debug("Created persistent uinput device for paste simulation.")
    return _uinput


def _cleanup_uinput():
    global _uinput
    if _uinput is not None:
        try:
            _uinput.close()
        except OSError:
            pass
        _uinput = None


def _type_via_wtype(text: str) -> None:
    subprocess.run(
        ["wtype", "--", text],
        check=True,
        timeout=30,
    )


def _type_via_clipboard(text: str) -> None:
    """Copy text to clipboard then simulate Ctrl+V."""
    from evdev import ecodes

    # Set clipboard
    subprocess.run(
        ["wl-copy", "--", text],
        check=True,
        timeout=5,
    )
    # Let the clipboard manager register the content
    time.sleep(0.1)

    # Simulate Ctrl+Shift+V through the persistent uinput device
    # (Ctrl+Shift+V works in terminals and most GUI apps)
    ui = _get_uinput()
    ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 1)
    ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 1)
    ui.write(ecodes.EV_KEY, ecodes.KEY_V, 1)
    ui.syn()
    time.sleep(0.02)
    ui.write(ecodes.EV_KEY, ecodes.KEY_V, 0)
    ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 0)
    ui.write(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 0)
    ui.syn()

    # Wait for the target application to read from clipboard
    time.sleep(0.15)


def type_text(text: str) -> None:
    """Type the given text at the current cursor position.

    Prefers wtype (wlroots/Sway).  On GNOME/Mutter (which lacks the
    virtual-keyboard protocol), falls back to wl-copy + uinput Ctrl+Shift+V.
    """
    if not text:
        return

    backend = _detect_backend()

    if backend == "wtype":
        _type_via_wtype(text)
    else:
        _type_via_clipboard(text)

    log.debug("Typed %d chars via %s.", len(text), backend)
