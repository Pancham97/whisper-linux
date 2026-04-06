"""System tray icon for Whisper Typewriter using AppIndicator3 directly."""

import logging
import os
import tempfile
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

from whisper_typewriter.config import Mode

log = logging.getLogger(__name__)

# Languages shown in the tray menu. Key = Whisper language code, value = label.
_LANGUAGES: dict[str | None, str] = {
    None: "Auto-detect",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "ru": "Russian",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "ar": "Arabic",
    "hi": "Hindi",
    "tr": "Turkish",
    "pl": "Polish",
    "uk": "Ukrainian",
}

# Icon size
_SIZE = 64

# Colors
_COLORS = {
    Mode.VERBATIM: "#3B82F6",   # blue
    Mode.REFINE: "#8B5CF6",     # purple
}
_RECORDING_COLOR = "#EF4444"    # red
_DISCONNECTED_COLOR = "#6B7280" # gray


def _init_gi():
    """Import and configure gi bindings. Returns (AppIndicator3, Gtk, GLib)."""
    import gi as _gi
    _gi.require_version("AppIndicator3", "0.1")
    _gi.require_version("Gtk", "3.0")
    from gi.repository import AppIndicator3, GLib, Gtk
    return AppIndicator3, Gtk, GLib


def preflight() -> None:
    """Verify that AppIndicator3 GLib introspection bindings are available.

    Call early so errors surface before any heavy model loading.
    """
    try:
        import gi as _gi
    except ImportError:
        raise RuntimeError(
            "PyGObject ('gi' module) not found. The system tray requires it.\n\n"
            "  Option A — use the project venv (has system site-packages):\n"
            "    source .venv/bin/activate && python -m whisper_typewriter\n\n"
            "  Option B — install PyGObject for your current Python:\n"
            "    sudo apt install libgirepository-2.0-dev libcairo2-dev\n"
            "    pip install PyGObject\n"
        )
    try:
        _gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3 as _ai  # noqa: F401
    except (ImportError, ValueError):
        raise RuntimeError(
            "AppIndicator3 typelib not found. Install with:\n"
            "  sudo apt install gir1.2-appindicator3-0.1\n\n"
            "You may also need the GNOME Shell extension:\n"
            "  'AppIndicator and KStatusNotifierItem Support'\n"
            "  (pre-installed on Ubuntu, check Extensions app)"
        )


def _render_icon(
    mode: Mode, recording: bool = False, connected: bool = True,
) -> Image.Image:
    """Generate a tray icon as a PIL image."""
    if not connected:
        bg = _DISCONNECTED_COLOR
    elif recording:
        bg = _RECORDING_COLOR
    else:
        bg = _COLORS[mode]
    img = Image.new("RGBA", (_SIZE, _SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle(
        [(2, 2), (_SIZE - 2, _SIZE - 2)],
        radius=12,
        fill=bg,
    )

    label = "R" if mode == Mode.REFINE else "V"
    if recording:
        label = "\u25cf"

    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32
        )
    except (OSError, IOError):
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (_SIZE - tw) // 2
    y = (_SIZE - th) // 2 - 2
    draw.text((x, y), label, fill="white", font=font)

    return img


class TrayIcon:
    """System tray icon using AppIndicator3 + Gtk directly."""

    def __init__(
        self,
        initial_mode: Mode,
        on_mode_verbatim: Callable[[], None],
        on_mode_refine: Callable[[], None],
        on_quit: Callable[[], None],
        initial_language: str | None = None,
        on_language: Callable[[str | None], None] | None = None,
    ):
        self._mode = initial_mode
        self._language = initial_language
        self._recording = False
        self._connected = True
        self._on_mode_verbatim = on_mode_verbatim
        self._on_mode_refine = on_mode_refine
        self._on_quit = on_quit
        self._on_language = on_language

        # Lazy-import gi bindings
        self._AppIndicator3, self._Gtk, self._GLib = _init_gi()

        # Temp directory for icon PNGs (AppIndicator needs file paths)
        self._icon_dir = tempfile.mkdtemp(prefix="whisper-tray-")

        # Pre-render the initial icon before creating the indicator —
        # AppIndicator needs a valid icon at construction time.
        initial_icon_name = f"wt-{self._mode.value}"
        _render_icon(self._mode).save(
            os.path.join(self._icon_dir, f"{initial_icon_name}.png")
        )

        # Create the AppIndicator with icon + theme path set together
        self._indicator = self._AppIndicator3.Indicator.new_with_path(
            "whisper-typewriter",
            initial_icon_name,
            self._AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
            self._icon_dir,
        )
        self._indicator.set_status(self._AppIndicator3.IndicatorStatus.ACTIVE)

        # Build menu
        self._menu = self._Gtk.Menu()
        self._build_menu()
        self._indicator.set_menu(self._menu)

    def _build_menu(self) -> None:
        """Populate the Gtk.Menu."""
        Gtk = self._Gtk

        # Mode radio group
        self._verbatim_item = Gtk.RadioMenuItem.new_with_label(
            [], "Verbatim mode"
        )
        self._refine_item = Gtk.RadioMenuItem.new_with_label_from_widget(
            self._verbatim_item, "Refine mode"
        )
        if self._mode == Mode.REFINE:
            self._refine_item.set_active(True)
        else:
            self._verbatim_item.set_active(True)

        self._verbatim_item.connect("toggled", self._on_mode_toggled, Mode.VERBATIM)
        self._refine_item.connect("toggled", self._on_mode_toggled, Mode.REFINE)

        self._menu.append(self._verbatim_item)
        self._menu.append(self._refine_item)
        self._menu.append(Gtk.SeparatorMenuItem())

        # Language submenu
        lang_menu_item = Gtk.MenuItem.new_with_label("Language")
        lang_submenu = Gtk.Menu()
        group_widget = None
        for code, label in _LANGUAGES.items():
            if group_widget is None:
                item = Gtk.RadioMenuItem.new_with_label([], label)
                group_widget = item
            else:
                item = Gtk.RadioMenuItem.new_with_label_from_widget(
                    group_widget, label
                )
            if code == self._language:
                item.set_active(True)
            item.connect("toggled", self._on_lang_toggled, code)
            lang_submenu.append(item)

        lang_menu_item.set_submenu(lang_submenu)
        self._menu.append(lang_menu_item)

        self._menu.append(Gtk.SeparatorMenuItem())

        # Quit
        quit_item = Gtk.MenuItem.new_with_label("Quit")
        quit_item.connect("activate", lambda _: self._on_quit())
        self._menu.append(quit_item)

        self._menu.show_all()

    def _on_mode_toggled(self, item, mode: Mode) -> None:
        if not item.get_active():
            return
        self._mode = mode
        self._save_and_set_icon()
        if mode == Mode.VERBATIM:
            self._on_mode_verbatim()
        else:
            self._on_mode_refine()

    def _on_lang_toggled(self, item, code: str | None) -> None:
        if not item.get_active():
            return
        self._language = code
        if self._on_language:
            self._on_language(code)
        log.info("Language: %s", _LANGUAGES.get(code, code))

    def _save_and_set_icon(self) -> None:
        """Render the current icon to a PNG and tell AppIndicator to use it."""
        # AppIndicator loads icons by name from the theme path.
        # Use a unique name per state so it detects changes.
        if not self._connected:
            suffix = f"disconnected-{self._mode.value}"
        elif self._recording:
            suffix = "rec"
        else:
            suffix = self._mode.value
        icon_name = f"wt-{suffix}"
        path = os.path.join(self._icon_dir, f"{icon_name}.png")
        if not os.path.exists(path):
            img = _render_icon(
                self._mode, self._recording, self._connected,
            )
            img.save(path)
        self._indicator.set_icon(icon_name)

    def start(self) -> None:
        """Run the GTK main loop (blocks — call on the main thread)."""
        self._Gtk.main()

    def stop(self) -> None:
        """Quit the GTK main loop (safe to call from any thread)."""
        self._GLib.idle_add(self._Gtk.main_quit)

    def set_mode(self, mode: Mode) -> None:
        """Update displayed mode (thread-safe)."""
        self._mode = mode
        self._GLib.idle_add(self._save_and_set_icon)

    def set_recording(self, recording: bool) -> None:
        """Update recording indicator (thread-safe)."""
        self._recording = recording
        self._GLib.idle_add(self._save_and_set_icon)

    def set_connected(self, connected: bool) -> None:
        """Update keyboard connection indicator (thread-safe)."""
        self._connected = connected
        self._GLib.idle_add(self._save_and_set_icon)

    def preflight(self) -> None:
        """No-op — kept for API compatibility. Call module-level preflight()."""
        pass
