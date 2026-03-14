#!/bin/bash
# Pi Webcam — Installation Script
# Run on Raspberry Pi Zero 2 W with Raspberry Pi OS Lite 64-bit (Bookworm)
# Usage: cd ~/pi_webcam && sudo bash deploy/install.sh
set -euo pipefail

# Resolve project root (parent of the directory containing this script)
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

MEDIAMTX_VERSION="1.16.3"
MEDIAMTX_URL="https://github.com/bluenviron/mediamtx/releases/download/v${MEDIAMTX_VERSION}/mediamtx_v${MEDIAMTX_VERSION}_linux_arm64v8.tar.gz"
INSTALL_DIR="/opt/pi_webcam"
DATA_DIR="/data/pi_webcam"
CONFIG_DIR="/etc/pi_webcam"
UV_BIN="/root/.local/bin/uv"

echo "=== Pi Webcam Installation ==="
echo "Project directory: $PROJECT_DIR"

# Check root
if [[ $EUID -ne 0 ]]; then
    echo "Error: Run as root (sudo bash deploy/install.sh)"
    exit 1
fi

# Verify project structure
if [[ ! -d "$PROJECT_DIR/src" || ! -d "$PROJECT_DIR/config" || ! -d "$PROJECT_DIR/deploy" ]]; then
    echo "Error: Cannot find project files in $PROJECT_DIR"
    echo "Make sure you run this from the project root: cd ~/pi_webcam && sudo bash deploy/install.sh"
    exit 1
fi

# System packages
if dpkg -s ffmpeg python3-venv sqlite3 &>/dev/null; then
    echo "--- System packages: already installed, skipping ---"
else
    echo "--- Installing system packages ---"
    apt-get update -qq
    apt-get install -y -qq python3-pip python3-venv ffmpeg sqlite3
fi

# SD card optimization
if grep -q "noatime" /etc/fstab; then
    echo "--- SD card mount options: already set, skipping ---"
else
    echo "--- Optimizing SD card mount options ---"
    sed -i 's/defaults/defaults,noatime,commit=60/' /etc/fstab
    echo "Mount options updated (reboot to apply)"
fi

# Swap configuration
if grep -q "CONF_SWAPSIZE=256" /etc/dphys-swapfile 2>/dev/null; then
    echo "--- Swap: already configured, skipping ---"
elif command -v dphys-swapfile &>/dev/null; then
    echo "--- Configuring swap (256 MB) ---"
    dphys-swapfile swapoff || true
    sed -i 's/CONF_SWAPSIZE=.*/CONF_SWAPSIZE=256/' /etc/dphys-swapfile
    dphys-swapfile setup
    dphys-swapfile swapon
fi

# Install uv
if [[ -f "$UV_BIN" ]]; then
    echo "--- uv: already installed, skipping ---"
else
    echo "--- Installing uv ---"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# Install MediaMTX
if [[ -f /usr/local/bin/mediamtx ]] && /usr/local/bin/mediamtx --version 2>&1 | grep -q "${MEDIAMTX_VERSION}"; then
    echo "--- MediaMTX v${MEDIAMTX_VERSION}: already installed, skipping ---"
else
    echo "--- Installing MediaMTX v${MEDIAMTX_VERSION} ---"
    TMP=$(mktemp -d)
    curl -L -o "$TMP/mediamtx.tar.gz" "$MEDIAMTX_URL"
    tar -xzf "$TMP/mediamtx.tar.gz" -C "$TMP"
    install -m 755 "$TMP/mediamtx" /usr/local/bin/mediamtx
    rm -rf "$TMP"
    echo "MediaMTX v${MEDIAMTX_VERSION} installed"
fi

# Create directories
mkdir -p "$DATA_DIR/frames" "$CONFIG_DIR" "$INSTALL_DIR"

# Deploy application
echo "--- Deploying application ---"
cp -r "$PROJECT_DIR/src" "$PROJECT_DIR/static" "$PROJECT_DIR/pyproject.toml" "$PROJECT_DIR/README.md" "$INSTALL_DIR/"

# Install Python dependencies (only if lockfile changed)
LOCK_SRC="$PROJECT_DIR/uv.lock"
LOCK_DST="$INSTALL_DIR/uv.lock"
if [[ -f "$LOCK_SRC" ]] && cmp -s "$LOCK_SRC" "$LOCK_DST" 2>/dev/null; then
    echo "--- Python dependencies: unchanged, skipping ---"
else
    echo "--- Installing Python dependencies ---"
    cp "$LOCK_SRC" "$LOCK_DST" 2>/dev/null || true
    cd "$INSTALL_DIR"
    "$UV_BIN" sync --no-dev --no-group dev 2>/dev/null || "$UV_BIN" pip install -e . 2>/dev/null || true
fi

# Copy configs
echo "--- Copying configuration ---"
mkdir -p /etc/mediamtx
cp "$PROJECT_DIR/config/mediamtx.yml" /etc/mediamtx/mediamtx.yml

if [[ ! -f "$CONFIG_DIR/pi-webcam.env" ]]; then
    cp "$PROJECT_DIR/config/pi-webcam.env.example" "$CONFIG_DIR/pi-webcam.env"
    echo "Created $CONFIG_DIR/pi-webcam.env from example (edit as needed)"
fi

# Install systemd services
echo "--- Installing systemd services ---"
cp "$PROJECT_DIR/deploy/mediamtx.service" /etc/systemd/system/
cp "$PROJECT_DIR/deploy/pi-webcam.service" /etc/systemd/system/

# Journal limits (only write if missing)
if [[ ! -f /etc/systemd/journald.conf.d/pi-webcam.conf ]]; then
    mkdir -p /etc/systemd/journald.conf.d
    cat > /etc/systemd/journald.conf.d/pi-webcam.conf << 'JOURNALEOF'
[Journal]
SystemMaxUse=50M
SystemKeepFree=100M
MaxRetentionSec=7day
JOURNALEOF
fi

systemctl daemon-reload
systemctl enable mediamtx pi-webcam 2>/dev/null

# Only restart services if they need it
if systemctl is-active --quiet mediamtx; then
    echo "--- MediaMTX: already running, reloading config ---"
    systemctl restart mediamtx
else
    echo "--- Starting MediaMTX ---"
    systemctl start mediamtx
fi

sleep 2

echo "--- Restarting pi-webcam ---"
systemctl restart pi-webcam

echo ""
echo "=== Installation Complete ==="
echo "Web UI:     http://$(hostname).local:8080"
echo "RTSP:       rtsp://$(hostname).local:8554/cam"
echo "WebRTC:     http://$(hostname).local:8889/cam"
echo "Config:     $CONFIG_DIR/pi-webcam.env"
echo "Data:       $DATA_DIR"
echo "Logs:       journalctl -u pi-webcam -f"
