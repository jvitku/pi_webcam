#!/bin/bash
# Pi Webcam — Quick Update Script
# Pulls latest code and restarts the service.
# Usage: cd ~/pi_webcam && bash deploy/update.sh
#
# For full redeploy (dependencies/services changed):
#   cd ~/pi_webcam && sudo bash deploy/install.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_DIR="/opt/pi_webcam"

echo "=== Pi Webcam Update ==="

# Git runs as the current user (needs SSH keys / agent forwarding)
cd "$PROJECT_DIR"
git reset --hard
git pull --rebase

# Privileged operations
sudo cp -r src static "$INSTALL_DIR/"
sudo cp deploy/pi-webcam.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart pi-webcam

echo "=== Done — checking status ==="
sleep 2
sudo systemctl status pi-webcam --no-pager -l | head -15
