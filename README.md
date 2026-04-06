# Whisper Typewriter

Local speech-to-text that types wherever your cursor is. Hold **Right Alt** for
one second to start dictating, release to type. Runs entirely on your machine —
no cloud, no API keys, no data leaves your computer.

Uses [Whisper Large v3 Turbo](https://huggingface.co/openai/whisper-large-v3-turbo)
for transcription and [Phi-3.5-mini](https://huggingface.co/microsoft/Phi-3.5-mini-instruct)
for optional text refinement.

## How it works

```
Hold Right Alt  -->  Record audio  -->  Whisper transcription
                                              |
                            [Verbatim mode]   -->  type at cursor
                            [Refine mode]     -->  LLM cleanup  -->  type at cursor
```

- **Right Alt (hold)** — push-to-talk; hold for ~1 second to start recording,
  release to transcribe. Short taps and key combos (e.g. Alt+Enter) are
  forwarded normally.
- **Tray icon menu** — switch between Verbatim/Refine mode, select language, quit
- **Tray icon color** — blue = Verbatim, purple = Refine, red = recording,
  gray = keyboard disconnected

## Modes

| Mode | Behavior |
|------|----------|
| **Verbatim** | Types exactly what you said |
| **Refine** | Cleans up grammar, filler words, and tone using a local LLM |

Switch modes from the tray icon's right-click menu.

## Requirements

- Linux with Wayland (GNOME, Sway, Hyprland, etc.)
- Debian/Ubuntu (install commands below use `apt`; adapt for other distros)
- Python 3.11+
- ~4 GB disk for models (downloaded automatically on first run)
- Microphone
- User must be in the `input` group (for keyboard access)

## Quick start

```bash
git clone https://github.com/Pancham97/whisper-linux.git
cd whisper-linux
./setup.sh
```

The setup script handles everything: system packages, GNOME extension, input
group, Python venv, and optionally installs a background service.

Then run:

```bash
source .venv/bin/activate
whisper-typewriter
```

Or equivalently: `python -m whisper_typewriter`

First run downloads ~4 GB of models. Subsequent starts are fast.

## Manual installation

If you prefer to set things up yourself:

### 1. System packages

```bash
# Clipboard-based typing (GNOME/Mutter)
sudo apt install -y wl-clipboard

# System tray support
sudo apt install -y gir1.2-appindicator3-0.1 libgirepository-2.0-dev libcairo2-dev

# Optional: direct typing for Sway/wlroots compositors
sudo apt install -y wtype
```

### 2. GNOME Shell extension

The tray icon requires the **AppIndicator** GNOME Shell extension. It's
pre-installed on Ubuntu but may be disabled:

```bash
gnome-extensions enable ubuntu-appindicators@ubuntu.com
```

If not installed: open the **Extensions** app or run:

```bash
sudo apt install gnome-shell-extension-appindicator
```

### 3. Input group

The push-to-talk key uses evdev, which requires membership in the `input` group:

```bash
sudo usermod -aG input $USER
# Log out and back in for this to take effect
```

### 4. Python environment

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e .
```

The `--system-site-packages` flag is important — it gives the venv access to the
system-installed `gi` (PyGObject) module needed for the tray icon.

## Run as a background service

Install as a systemd user service so it starts automatically on login:

```bash
# Copy the service file
mkdir -p ~/.config/systemd/user
cp whisper-typewriter.service ~/.config/systemd/user/

# Edit ExecStart path if your repo isn't at ~/projects/whisper-typewriter
# nano ~/.config/systemd/user/whisper-typewriter.service

# Enable and start
systemctl --user daemon-reload
systemctl --user enable --now whisper-typewriter
```

Useful commands:

```bash
# View logs
journalctl --user -u whisper-typewriter -f

# Restart after code changes
systemctl --user restart whisper-typewriter

# Stop
systemctl --user stop whisper-typewriter

# Disable autostart
systemctl --user disable whisper-typewriter
```

Or just run `./setup.sh` and answer **y** when it asks about the background service.

## Configuration

Environment variables (set in your shell or in the systemd service file):

| Variable | Default | Description |
|----------|---------|-------------|
| `WT_WHISPER_MODEL` | `large-v3-turbo` | Whisper model name ([options](https://huggingface.co/Systran)) |
| `WT_WHISPER_DEVICE` | `cpu` | Device for Whisper inference (`cpu` or `cuda`) |
| `WT_WHISPER_COMPUTE` | `int8` | Compute type (`int8`, `float16`, `float32`) |
| `WT_LLM_THREADS` | `4` | CPU threads for LLM inference |
| `WT_MODE` | `verbatim` | Starting mode (`verbatim` or `refine`) |

Language can be set from the tray menu at runtime (Auto-detect, English,
Spanish, French, German, and more). Pinning a language improves accuracy for
short recordings.

## Troubleshooting

### Tray icon not visible

1. **Enable the GNOME Shell extension:**

   ```bash
   gnome-extensions enable ubuntu-appindicators@ubuntu.com
   ```

   This is the most common cause. The extension is pre-installed on Ubuntu but
   often disabled.

2. **Check AppIndicator3 is installed:**

   ```bash
   sudo apt install gir1.2-appindicator3-0.1
   ```

3. **"No module named 'gi'"** — your venv doesn't have access to system packages.
   Recreate it with `--system-site-packages`:

   ```bash
   python3 -m venv --system-site-packages .venv
   source .venv/bin/activate
   pip install -e .
   ```

### "No keyboard device found"

Add yourself to the `input` group and **log out/in**:

```bash
sudo usermod -aG input $USER
```

### "No typing backend found"

```bash
# GNOME/Mutter
sudo apt install wl-clipboard

# Sway/wlroots
sudo apt install wtype
```

### Text doesn't appear in some apps (clipboard backend only)

When using the clipboard backend (GNOME/Mutter), text is pasted via
**Ctrl+Shift+V**. This works in terminals and most GUI apps. In some
applications (e.g., LibreOffice), this may open a "Paste Special" dialog — the
text is still on your clipboard, just press Ctrl+V manually. This does not
apply when using the wtype backend (Sway/wlroots), which types directly.

### Right Alt stuck / keyboard not working after crash

If the app crashes without releasing the keyboard grab, replug your keyboard or:

```bash
# Install evemu-tools if not already present
sudo apt install -y evemu-tools

# Find your keyboard device
cat /proc/bus/input/devices | grep -A4 keyboard

# Force-release Right Alt (replace eventX with your device)
sudo evemu-event /dev/input/eventX --type EV_KEY --code 100 --value 0
```

### Slow transcription

Try a smaller model:

```bash
WT_WHISPER_MODEL=medium python -m whisper_typewriter
```

## Architecture

| Component | File | Role |
|-----------|------|------|
| Orchestrator | `src/whisper_typewriter/main.py` | Wires everything together, runs main loop |
| Audio | `src/whisper_typewriter/audio.py` | Records from microphone via sounddevice |
| Transcriber | `src/whisper_typewriter/transcriber.py` | Whisper speech-to-text (faster-whisper) |
| Refiner | `src/whisper_typewriter/refiner.py` | LLM transcript cleanup (llama-cpp-python) |
| Typer | `src/whisper_typewriter/typer.py` | Types text at cursor (wtype or clipboard paste) |
| Hotkey | `src/whisper_typewriter/hotkey.py` | Push-to-talk via evdev keyboard grab |
| Tray | `src/whisper_typewriter/tray.py` | System tray icon via AppIndicator3 + GTK |
| Config | `src/whisper_typewriter/config.py` | Settings and environment variable overrides |

## License

MIT
