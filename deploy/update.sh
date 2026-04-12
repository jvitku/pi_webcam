#!/bin/bash
# Pi Webcam — Quick Update Script
# Pulls latest code and restarts the service.
# Usage: cd ~/pi_webcam && sudo bash deploy/update.sh
#
# For full redeploy (dependencies/services changed):
#   cd ~/pi_webcam && sudo bash deploy/install.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_DIR="/opt/pi_webcam"

echo "=== Pi Webcam Update ==="

# Pull latest (as the real user, not root — root lacks SSH keys)
cd "$PROJECT_DIR"
REAL_USER="${SUDO_USER:-$(whoami)}"
sudo -u "$REAL_USER" git reset --hard
sudo -u "$REAL_USER" git pull --rebase

# Copy source + static + service files
cp -r src static "$INSTALL_DIR/"
cp deploy/pi-webcam.service /etc/systemd/system/

# Reload and restart
systemctl daemon-reload
systemctl restart pi-webcam

echo "=== Done — checking status ==="
sleep 2
systemctl status pi-webcam --no-pager -l | head -15
