# Pi Webcam

Wildlife camera for Raspberry Pi Zero 2 W + Camera Module 3. Live video streaming, automatic frame capture with timelapse viewer, and camera controls — all served from a single web UI.

## How It Works

### Architecture

```
┌─────────────────── Raspberry Pi Zero 2 W ───────────────────┐
│                                                              │
│  MediaMTX ──── H.264 HW encode ──── WebRTC / RTSP / HLS     │
│  (owns camera)        │                                      │
│                       │ local RTSP                           │
│                       ▼                                      │
│  Python App (FastAPI)                                        │
│  ├── ffmpeg ──── decode keyframes ──── latest.jpg            │
│  │                                        │                  │
│  ├── Capture worker ── copy + timestamp ── YYYY/MM/DD/*.jpg  │
│  │                                        + thumbnails       │
│  ├── Retention worker ── age + disk watermark cleanup        │
│  ├── Web API ── /api/frames, /api/status, /api/camera        │
│  └── Web UI ── noUiSlider + filmstrip + WebRTC player        │
│                                                              │
│  SQLite DB ── frame metadata (timestamps, paths, sizes)      │
└──────────────────────────────────────────────────────────────┘
```

### Streaming

**MediaMTX** exclusively owns the camera and handles all video streaming. It uses the Pi's hardware H.264 encoder (VideoCore IV) to encode 720p at 15fps with minimal CPU cost. Clients can connect via:

- **WebRTC** (port 8889) — lowest latency (~250ms), used by the web UI
- **RTSP** (port 8554) — for VLC or other media players
- **HLS** (port 8888) — fallback for browsers without WebRTC support

The web UI auto-detects the hostname from the browser's address bar, so streaming works over both local WiFi (`picam.local`) and VPN (`10.0.0.X`) without configuration changes.

### Frame Capture

**ffmpeg** connects to the local RTSP stream and extracts frames using `-update 1`, which continuously overwrites a single `latest.jpg` file. The Python capture worker polls this file every 0.5s for modification time changes, then copies it to a timestamped file (`YYYYMMDD_HHMMSS.jpg`) in a date-based directory structure (`YYYY/MM/DD/`).

Each captured frame also gets a 320x180 thumbnail generated via Pillow, stored in a `thumb/` subdirectory alongside the full frame. Frame metadata (timestamp, file size, paths) is recorded in SQLite.

The default capture rate is 0.5 FPS (one frame every 2 seconds), configurable from the web UI.

### Timeline Viewer

The viewer uses a two-tier data loading strategy for responsiveness:

1. **Sampled overview** — on page load, fetches ~1000 evenly-sampled frames covering the entire day. This powers the main slider (noUiSlider) for fast coarse navigation. Thumbnails are shown while dragging.

2. **Detail window** — when you press play or use arrow keys, 200 full-density frames are fetched around the current position. Arrows step through these frame-by-frame (2s intervals). Playback skips frames based on the speed dropdown selection.

Prefetching starts at 50% through the detail window, loading the next chunk forward in the background (append mode). This keeps playback smooth without stalling.

A filmstrip of ~12 thumbnail previews shows the surrounding context, with a blue cursor line tracking the current position. The filmstrip auto-rebuilds as you navigate.

### Camera Controls

Camera settings (exposure, metering, brightness, contrast, saturation) are adjusted in real-time via MediaMTX's HTTP API (`PATCH /v3/config/paths/patch/cam`). These are "hot-reloadable" parameters — they take effect immediately without restarting the camera pipeline.

Focus controls (AF mode, lens position) are not exposed in the UI because they require a full pipeline restart, which temporarily crashes the stream.

### Retention

A background worker runs every 15 minutes and enforces two cleanup rules:

1. **Age limit** — frames older than `RETENTION_DAYS` (default 14) are deleted
2. **Disk watermark** — if free space drops below `DISK_WATERMARK_MB` (default 5 GB), the oldest frames are deleted in batches until the threshold is met

Both frame files, thumbnails, and database entries are cleaned up. Empty date directories are removed.

### System Monitoring

The status bar shows live system stats updated every 10 seconds:

- CPU usage, temperature, RAM usage, network throughput
- Disk free space, total frame count, capture rate
- Throttling indicators (under-voltage, thermal throttling, frequency capping) — read from `vcgencmd get_throttled`

## Hardware Required

- Raspberry Pi Zero 2 W
- Raspberry Pi Camera Module 3 (standard or NoIR for night vision)
- Pi Zero camera ribbon cable (15→22 pin adapter — the standard cable does not fit)
- microSD card, 128 GB+ (A2 class recommended)
- 5V/2.5A micro-USB power supply
- Stick-on aluminum heatsink (required — continuous encoding throttles without it)

## Setup Guide

Everything below is done over SSH from another machine.

### Step 1: Flash the SD Card

1. Install [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Select **Raspberry Pi Zero 2 W**, **Raspberry Pi OS Lite (64-bit, Bookworm)**
3. In OS Customisation (gear icon):
   - **Hostname:** `picam`
   - **SSH:** public-key only (paste your `~/.ssh/id_ed25519.pub`)
   - **WiFi:** your home network SSID + password, **country code must match your location** (controls which radio channels are used)
   - **Locale:** set your timezone
4. Flash and insert into Pi

### Step 2: Assemble and Boot

1. Attach heatsink to SoC
2. Connect Camera Module 3 (gold contacts face the board on the Zero)
3. Insert SD card, power on
4. Wait ~90 seconds, then: `ssh pi@picam.local`

### Step 3: Verify Camera

```bash
rpicam-hello --list-cameras
# Should show: imx708
rpicam-still -o test.jpg
```

### Step 4: Deploy

```bash
# Clone the project
git clone https://github.com/jvitku/pi_webcam.git ~/pi_webcam

# Run the installer
cd ~/pi_webcam
sudo bash deploy/install.sh
```

The installer is idempotent (safe to re-run). It installs system packages, MediaMTX, Python deps, systemd services, and configures swap/SD card optimizations.

### Step 5: Open in Browser

| What | URL |
|---|---|
| **Web UI** | `http://picam.local:8080` |
| **RTSP stream** | `rtsp://picam.local:8554/cam` |
| **API docs** | `http://picam.local:8080/docs` |

## Configuration

```bash
sudo nano /etc/pi_webcam/pi-webcam.env
```

```env
PI_WEBCAM_CAPTURE_FPS=0.5          # frames per second (0.5 = every 2s)
PI_WEBCAM_DISK_WATERMARK_MB=5120   # keep 5 GB free
PI_WEBCAM_RETENTION_DAYS=14        # delete frames older than 14 days
PI_WEBCAM_JPEG_QUALITY=3           # 1=best, 31=worst
PI_WEBCAM_AUTH_USERNAME=admin      # optional basic auth
PI_WEBCAM_AUTH_PASSWORD=changeme
```

Camera settings via MediaMTX:

```bash
sudo nano /etc/mediamtx/mediamtx.yml
```

```yaml
rpiCameraWidth: 1280
rpiCameraHeight: 720
rpiCameraFPS: 15
rpiCameraBitrate: 2500000
# Silent fixed-focus for wildlife:
rpiCameraAfMode: manual
rpiCameraLensPosition: 0.0
```

After changes: `sudo systemctl restart mediamtx && sudo systemctl restart pi-webcam`

## Storage

At 0.5 FPS, ~50 KB per JPEG:

| SD Card | Approx. Retention |
|---|---|
| 128 GB | ~30 days |
| 256 GB | ~60 days |

The disk watermark (default 5 GB free) auto-deletes the oldest frames before the card fills up.

## Development

Quick deploy after code changes:

```bash
cd ~/pi_webcam && git pull -r && sudo cp -r src static /opt/pi_webcam/ && sudo systemctl restart pi-webcam
```

Full redeploy (dependencies/services changed):

```bash
cd ~/pi_webcam && git pull -r && sudo bash deploy/install.sh
```

## Troubleshooting

```bash
# Check service status
sudo systemctl status mediamtx pi-webcam

# Watch logs
journalctl -u pi-webcam -f

# Check temperature
vcgencmd measure_temp

# Check throttling
vcgencmd get_throttled
# 0x0 = OK, 0x50005 = under-voltage + throttled

# Check disk
df -h /data
```

## Remote Access

The web UI works over VPN (e.g. WireGuard, Tailscale) — stream URLs are automatically derived from the browser's hostname, so no configuration change is needed when accessing via VPN IP instead of `picam.local`.
