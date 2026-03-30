#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Whisper Typewriter Setup ==="
echo ""

# ── 1. System packages ──────────────────────────────────────────────

echo "-- System packages --"

if command -v wl-copy &>/dev/null; then
    echo "[ok] wl-clipboard"
else
    echo "[install] wl-clipboard..."
    sudo apt install -y wl-clipboard
fi

if command -v wtype &>/dev/null; then
    echo "[ok] wtype"
else
    echo "[skip] wtype (optional, only for Sway/wlroots)"
fi

if python3 -c "import gi; gi.require_version('AppIndicator3', '0.1')" 2>/dev/null; then
    echo "[ok] AppIndicator3 bindings"
else
    echo "[install] AppIndicator3 bindings..."
    sudo apt install -y gir1.2-appindicator3-0.1 libgirepository-2.0-dev libcairo2-dev
fi

# ── 2. GNOME Shell extension ────────────────────────────────────────

echo ""
echo "-- GNOME Shell AppIndicator extension --"

if command -v gnome-extensions &>/dev/null; then
    if gnome-extensions list --enabled 2>/dev/null | grep -q appindicator; then
        echo "[ok] AppIndicator extension enabled"
    elif gnome-extensions list 2>/dev/null | grep -q appindicator; then
        echo "[enable] AppIndicator extension..."
        gnome-extensions enable ubuntu-appindicators@ubuntu.com 2>/dev/null \
            || gnome-extensions enable appindicatorsupport@rgcjonas.gmail.com 2>/dev/null \
            || echo "[warn] Could not auto-enable. Open GNOME Extensions app and enable 'AppIndicator'."
    else
        echo "[warn] AppIndicator extension not installed."
        echo "       Install from: https://extensions.gnome.org/extension/615/appindicator-support/"
        echo "       Or: sudo apt install gnome-shell-extension-appindicator"
    fi
else
    echo "[skip] Not running GNOME Shell"
fi

# ── 3. Input group ──────────────────────────────────────────────────

echo ""
echo "-- Input group (for keyboard access) --"

if groups "$USER" | grep -qw input; then
    echo "[ok] User '$USER' is in 'input' group"
else
    echo "[fix] Adding '$USER' to 'input' group..."
    sudo usermod -aG input "$USER"
    echo ""
    echo "  *** You MUST log out and back in for this to take effect. ***"
    echo ""
fi

# ── 4. Python venv ──────────────────────────────────────────────────

echo ""
echo "-- Python virtual environment --"

VENV="$REPO_DIR/.venv"
if [ -d "$VENV" ] && "$VENV/bin/python" -c "import whisper_typewriter" 2>/dev/null; then
    echo "[ok] .venv exists and package is installed"
else
    echo "[setup] Creating .venv with system site-packages..."
    python3 -m venv --system-site-packages "$VENV"
    "$VENV/bin/pip" install --upgrade pip
    "$VENV/bin/pip" install -e "$REPO_DIR"
    echo "[ok] Installed"
fi

# ── 5. Systemd user service (optional) ──────────────────────────────

echo ""
echo "-- Background service (systemd) --"

SERVICE_SRC="$REPO_DIR/whisper-typewriter.service"
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_DST="$SERVICE_DIR/whisper-typewriter.service"

read -rp "Install as a background service that starts on login? [y/N] " answer
if [[ "${answer,,}" == "y" ]]; then
    mkdir -p "$SERVICE_DIR"

    # Rewrite ExecStart to use this repo's venv
    sed "s|ExecStart=.*|ExecStart=$VENV/bin/python -m whisper_typewriter|" \
        "$SERVICE_SRC" > "$SERVICE_DST"

    systemctl --user daemon-reload
    systemctl --user enable whisper-typewriter.service
    echo "[ok] Service installed and enabled."
    echo "     Start now:  systemctl --user start whisper-typewriter"
    echo "     View logs:  journalctl --user -u whisper-typewriter -f"
else
    echo "[skip] You can install it later with:"
    echo "       ./setup.sh   (re-run and answer 'y')"
    echo "   Or manually:"
    echo "       cp whisper-typewriter.service ~/.config/systemd/user/"
    echo "       systemctl --user daemon-reload"
    echo "       systemctl --user enable --now whisper-typewriter"
fi

# ── Done ────────────────────────────────────────────────────────────

echo ""
echo "=== Setup complete ==="
echo ""
echo "Quick start:"
echo "  source .venv/bin/activate"
echo "  python -m whisper_typewriter"
echo ""
echo "First run downloads ~4 GB of models. Subsequent starts are fast."
