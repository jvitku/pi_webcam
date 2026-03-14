# Pi Webcam

Wildlife camera for Raspberry Pi Zero 2 W + Camera Module 3. Live video streaming (WebRTC/RTSP/HLS), automatic frame capture to disk with SQLite metadata, and a web-based timeline viewer.

## Hardware Required

- Raspberry Pi Zero 2 W
- Raspberry Pi Camera Module 3 (standard or NoIR for night vision)
- Pi Zero camera ribbon cable (15→22 pin adapter — the standard cable does not fit)
- microSD card, 128 GB+ (A2 class recommended)
- 5V/2.5A micro-USB power supply
- Stick-on aluminum heatsink for the SoC (required — continuous encoding throttles without it)

## Setup Guide

Everything below is done over SSH from another machine. You need: a Mac/Linux/Windows machine with an SD card reader and SSH client.

### Step 1: Flash the SD Card

On your computer (not the Pi):

1. Install [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Open it and select:
   - **Device:** Raspberry Pi Zero 2 W
   - **OS:** Raspberry Pi OS Lite (64-bit, Bookworm)
   - **Storage:** your SD card
3. Click the **gear icon** (OS Customisation) and set:
   - **Hostname:** `picam`
   - **Enable SSH:** check it, select **Allow public-key authentication only**
   - Paste your public key (run `cat ~/.ssh/id_ed25519.pub` on your machine to get it; if it doesn't exist, run `ssh-keygen -t ed25519` first)
   - **WiFi:** enter your home network SSID and password
   - **Locale:** set your timezone (important for accurate frame timestamps)
4. Click **Write** and wait for it to finish

### Step 2: Assemble and Boot

1. Attach the heatsink to the Pi's SoC chip
2. Connect the Camera Module 3 via the ribbon cable (gold contacts face the board on the Zero)
3. Insert the SD card
4. Plug in power — the green LED will blink during boot

Wait ~90 seconds for first boot (it resizes the filesystem and generates SSH keys).

### Step 3: Connect via SSH

```bash
ssh pi@picam.local
```

If `picam.local` doesn't resolve, find the Pi's IP from your router admin page and use `ssh pi@<IP>`.

### Step 4: Verify Camera

```bash
rpicam-hello --list-cameras
```

Expected output includes `imx708` with available modes. If you see "no cameras available", check the ribbon cable connection and orientation.

Quick test:
```bash
rpicam-still -o test.jpg
ls -lh test.jpg
```

### Step 5: Get the Project on the Pi

**Option A: Git clone (recommended)** — on the Pi via SSH:

```bash
# If your repo is public:
git clone https://github.com/jvitku/pi_webcam.git ~/pi_webcam

# If private, use SSH agent forwarding from your Mac:
#   ssh -A pi@picam.local
# then:
#   git clone git@github.com:jvitku/pi_webcam.git ~/pi_webcam
```

**Option B: rsync from your Mac** (if you prefer not to use git on the Pi):

```bash
# Run this on your Mac, not the Pi:
cd /path/to/pi_webcam
rsync -avz --exclude '.venv' --exclude '__pycache__' --exclude '.git' \
  --exclude '.mypy_cache' --exclude '.pytest_cache' --exclude '.ruff_cache' \
  . pi@picam.local:~/pi_webcam/
```

### Step 6: Run the Installer

**On the Pi** (SSH) — must be run from the project directory:

```bash
cd ~/pi_webcam
sudo bash deploy/install.sh
```

This is idempotent (safe to re-run) and does:
- Installs system packages (ffmpeg, sqlite3, python3)
- Configures 256 MB swap
- Optimizes SD card mount options (`noatime`, `commit=60`)
- Downloads and installs MediaMTX v1.12.0 (ARM64)
- Copies the app to `/opt/pi_webcam`, installs Python deps
- Creates data directory at `/data/pi_webcam/frames/`
- Installs and enables systemd services
- Configures journal log rotation (50 MB max)

The installer prints the URLs when done.

### Step 7: Verify Everything is Running

```bash
# Both services should show "active (running)"
sudo systemctl status mediamtx
sudo systemctl status pi-webcam

# Watch live logs
journalctl -u pi-webcam -f

# Check RTSP stream is up
ffprobe -v quiet -i rtsp://localhost:8554/cam -t 1 && echo "RTSP OK"

# Check temperature (should be under 70C with heatsink)
vcgencmd measure_temp

# Check disk space
df -h /data
```

### Step 8: Open in Browser

From any device on your home network:

| What | URL |
|---|---|
| **Web UI** (live stream + timeline viewer) | `http://picam.local:8080` |
| **RTSP stream** (for VLC, etc.) | `rtsp://picam.local:8554/cam` |
| **API docs** (auto-generated) | `http://picam.local:8080/docs` |

The web UI shows the live WebRTC stream at the top and a timeline slider at the bottom. Frames start appearing after a few seconds.

## Configuration

Edit on the Pi:

```bash
sudo nano /etc/pi_webcam/pi-webcam.env
```

Key settings:

```env
# Capture rate (default: 0.5 = one frame every 2 seconds)
PI_WEBCAM_CAPTURE_FPS=0.5

# Keep at least 5 GB free on SD card (oldest frames auto-deleted)
PI_WEBCAM_DISK_WATERMARK_MB=5120

# Auto-delete frames older than 14 days
PI_WEBCAM_RETENTION_DAYS=14

# JPEG quality: 1=best/largest, 31=worst/smallest
PI_WEBCAM_JPEG_QUALITY=3

# Optional basic auth
PI_WEBCAM_AUTH_USERNAME=admin
PI_WEBCAM_AUTH_PASSWORD=changeme
```

After editing:

```bash
sudo systemctl restart pi-webcam
```

### Camera Settings

Edit MediaMTX config:

```bash
sudo nano /etc/mediamtx/mediamtx.yml
```

Common changes:

```yaml
# Resolution (default 720p — increase for better quality, more CPU)
rpiCameraWidth: 1280
rpiCameraHeight: 720

# Framerate for live stream
rpiCameraFPS: 15

# Bitrate (higher = better quality, more bandwidth)
rpiCameraBitrate: 2500000

# Silent fixed-focus (no AF motor clicks — better for wildlife)
rpiCameraAfMode: manual
rpiCameraLensPosition: 0.0   # infinity focus
```

After editing:

```bash
sudo systemctl restart mediamtx
# Wait a few seconds, then restart the app too
sudo systemctl restart pi-webcam
```

## Storage

At the default 0.5 FPS with ~150 KB per JPEG:

| SD Card | Retention (approx) |
|---|---|
| 128 GB | ~18 days |
| 256 GB | ~38 days |
| 512 GB | ~78 days |

The retention system runs every 15 minutes and enforces two rules:
1. **Age limit:** frames older than `RETENTION_DAYS` are deleted
2. **Disk watermark:** if free space drops below `DISK_WATERMARK_MB` (default 5 GB), the oldest frames are deleted until there's enough space

Both frame files and thumbnails are removed, and empty date directories are cleaned up.

## Troubleshooting

### Service won't start

```bash
# Check logs for errors
journalctl -u pi-webcam -n 50 --no-pager
journalctl -u mediamtx -n 50 --no-pager
```

### Camera not detected

```bash
# Check if the camera device exists
ls /dev/video*
rpicam-hello --list-cameras

# If nothing shows up:
# 1. Power off, reseat the ribbon cable (gold contacts face the board)
# 2. Make sure you're using the Pi Zero adapter cable (15→22 pin)
```

### High CPU temperature

```bash
vcgencmd measure_temp
# Should be under 70C. If higher:
# - Attach a heatsink
# - Reduce resolution in mediamtx.yml (try 640x480)
# - Reduce FPS (try rpiCameraFPS: 10)
```

### Out of disk space

```bash
df -h /data

# Manual cleanup: delete frames older than 3 days
sqlite3 /data/pi_webcam/pi_webcam.db "SELECT COUNT(*) FROM frames;"

# Or reduce DISK_WATERMARK_MB and restart
```

### Reboot survival

Both services are enabled via systemd and start automatically on boot. To verify:

```bash
sudo reboot
# Wait ~2 minutes, then reconnect:
ssh pi@picam.local
sudo systemctl status mediamtx pi-webcam
```

## Updating

**If using git** (on the Pi):

```bash
cd ~/pi_webcam
git pull -r
sudo bash deploy/install.sh
```

**If using rsync** (from your Mac):

```bash
cd /path/to/pi_webcam
rsync -avz --exclude '.venv' --exclude '__pycache__' --exclude '.git' \
  --exclude '.mypy_cache' --exclude '.pytest_cache' --exclude '.ruff_cache' \
  . pi@picam.local:~/pi_webcam/

# Then on the Pi:
cd ~/pi_webcam
sudo bash deploy/install.sh
```

## Development

Quick deploy after code changes (on the Pi):

```bash
cd ~/pi_webcam && git pull -r && sudo cp -r static /opt/pi_webcam/ && sudo systemctl restart pi-webcam
```

For full redeploy (dependencies changed, service files updated, etc.):

```bash
cd ~/pi_webcam && git pull -r && sudo bash deploy/install.sh
```

## Architecture

```
MediaMTX (camera + streaming) ──RTSP──> Python App (FastAPI)
                                         ├── Capture worker (ffmpeg → JPEG + thumbnail)
                                         ├── Retention worker (age + disk watermark cleanup)
                                         ├── Web API (frames, status, days)
                                         └── Web UI (live stream + timeline slider)
                                              │
                                         SQLite DB + JPEG files on disk
                                         (date-based dirs: YYYY/MM/DD/)
```
