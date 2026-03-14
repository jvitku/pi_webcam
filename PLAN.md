# Pi Webcam — Project Plan

## 1. Overview

A Raspberry Pi Zero 2 W + Camera Module 3 wildlife camera that:
- Connects to home WiFi automatically on boot
- Streams live high-quality video (WebRTC/RTSP/HLS)
- Captures 1 JPEG per second, stores on disk with metadata in SQLite
- Serves a web viewer with a time slider for browsing captured images
- Is extensible to AI (YOLO object detection, motion detection)

---

## 2. Hardware

| Component | Details |
|---|---|
| **Board** | Raspberry Pi Zero 2 W (quad-core Cortex-A53 @ 1 GHz, 512 MB RAM, WiFi 2.4 GHz) |
| **Camera** | Raspberry Pi Camera Module 3 (Sony IMX708, 12 MP, autofocus, HDR). Consider the **NoIR variant** for night/dusk wildlife observation — pair with an IR illuminator for night vision. |
| **Cable** | Pi Zero camera ribbon cable (15-pin to 22-pin adapter — the standard cable does NOT fit the Zero) |
| **Storage** | microSD card, **256 GB+ recommended**, A2 class for better random I/O |
| **Power** | 5V/2.5A micro-USB power supply |
| **Heatsink** | **Required.** Stick-on aluminum heatsink for the SoC — continuous encoding + capture will push temps near 80C throttle point without it, especially in an enclosure. |
| **Case** | Any Pi Zero case with camera slot (optional: weatherproof for outdoor use, ensure ventilation) |

### Storage Budget

At 1 frame/second, **~150 KB average JPEG** (720p, high quality, natural outdoor scenes):
- **Per day:** ~12.6 GB (86,400 frames)
- **128 GB card:** ~9 days retention
- **256 GB card:** ~19 days retention
- **512 GB card:** ~39 days retention

A retention policy (auto-delete older than N days) is essential. For longer retention:
- Mount NFS/SMB network storage (recommended if NAS available)
- Use date-based subdirectory structure to avoid single-directory file limits

### Night Vision (Optional)

The Camera Module 3 comes in a **NoIR variant** (no infrared filter). For a wildlife camera:
- NoIR + IR LED illuminator = invisible-to-animals night vision
- Standard variant works great for daytime only
- If using NoIR: daytime images will have a pink/purple tint (fixable with white balance tuning)
- The plan works with either variant — only the `rpiCameraAwbMode` config changes

---

## 3. Operating System

**Raspberry Pi OS Lite 64-bit (Bookworm)** — the only sensible choice because:
- Lightest official OS (~200 MB installed, no desktop)
- Best libcamera + Camera Module 3 support (IMX708 tuning files included)
- 64-bit uses the Cortex-A53 natively, better performance than 32-bit
- H.264 hardware encoder works out of the box
- Large community, well-documented

### OS Setup (via Raspberry Pi Imager)

1. Flash **Raspberry Pi OS Lite (64-bit, Bookworm)** to SD card using Raspberry Pi Imager
2. In Imager settings (gear icon), configure:
   - **Hostname:** `picam` (or your choice)
   - **Enable SSH** with **SSH key only** (disable password auth for security)
   - **WiFi SSID + password** for your home network
   - **Locale/timezone** (important: NTP-synced time for accurate frame timestamps)
3. Insert SD card, connect camera ribbon cable (contacts face the board on Zero), power on
4. SSH in: `ssh pi@picam.local`

### Post-Boot Setup

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Verify camera is detected
rpicam-hello --list-cameras
# Should show: imx708 [4608x2592 10-bit RGGB] (stills mode)
# Video modes: 2304x1296@30fps, 1536x864@30fps, 1280x720@30fps, etc.

# Test camera capture
rpicam-still -o test.jpg
rpicam-vid -t 5000 -o test.h264

# Install required system packages
sudo apt install -y \
    python3-pip python3-venv \
    ffmpeg \
    sqlite3

# Configure swap (256 MB — small enough to limit SD wear, big enough to prevent OOM)
sudo dphys-swapfile swapoff
sudo sed -i 's/CONF_SWAPSIZE=.*/CONF_SWAPSIZE=256/' /etc/dphys-swapfile
sudo dphys-swapfile setup
sudo dphys-swapfile swapon

# Optimize SD card longevity: add noatime and commit=60
# In /etc/fstab, change the root partition line to include:
#   defaults,noatime,commit=60
sudo sed -i 's/defaults/defaults,noatime,commit=60/' /etc/fstab
```

---

## 4. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     Raspberry Pi Zero 2 W                    │
│                                                              │
│  ┌───────────┐   RTSP    ┌───────────────────────────────┐   │
│  │ MediaMTX  │◄─────────►│  Python App (FastAPI)         │   │
│  │           │  (local)  │                               │   │
│  │ rpicamera │           │  ┌──────────┐  ┌──────────┐   │   │
│  │ source    │           │  │ Capture  │  │ Web API  │   │   │
│  │           │           │  │ Worker   │  │ + Viewer │   │   │
│  │ Streams:  │           │  │ (1 fps)  │  │          │   │   │
│  │ - WebRTC  │           │  └────┬─────┘  └────┬─────┘   │   │
│  │ - RTSP    │           │       │             │         │   │
│  │ - HLS     │           │  ┌────▼─────────────▼──────┐  │   │
│  └───────────┘           │  │  SQLite  │  JPEG Dirs   │  │   │
│                          │  │          │  YYYY/MM/DD/  │  │   │
│                          │  └─────────────────────────┘  │   │
│                          └───────────────────────────────┘   │
│                                                              │
└──────────────────────────────────────────────────────────────┘
        │                              │
        ▼                              ▼
   Browser: live video            Browser: image viewer
   (WebRTC, ~250ms latency)       (time slider, REST API)
```

### Component Responsibilities

| Component | Role | Tech |
|---|---|---|
| **MediaMTX** | Camera access, H.264 HW encoding, multi-protocol streaming | Go binary, ~15 MB RAM |
| **Capture Worker** | Grabs 1 frame/sec from local RTSP via ffmpeg, saves JPEG + thumbnail to disk, records metadata in SQLite | Python, ffmpeg subprocess |
| **Web Server** | REST API for image browsing (with pagination), serves viewer UI, embeds live stream | Python, FastAPI, 1 Uvicorn worker |
| **Frontend** | Live video player (WebRTC, HLS fallback) + image timeline slider with thumbnail prefetching | Vanilla HTML/CSS/JS |
| **SQLite** | Frame metadata (timestamps, filenames, future AI results), WAL mode, auto-vacuum | WAL mode, ~0 MB overhead |

### Why This Architecture

- **MediaMTX handles the camera exclusively** — no access conflicts, proven reliability on Pi, battle-tested Go binary
- **ffmpeg grabs frames from local RTSP** — decoupled from camera, no camera sharing conflicts, no heavy OpenCV dependency
- **Thumbnails generated alongside full images** — enables fast timeline scrubbing without transferring full JPEGs
- **Date-based subdirectories** (`YYYY/MM/DD/`) — prevents ext4 performance degradation with many files
- **SQLite** — zero-config, no daemon, built-in to Python, perfect for metadata
- **FastAPI** — async, lightweight, auto-generated API docs, easy testing
- **Vanilla frontend** — no build step, no Node.js on Pi, minimal resources
- **Systemd services** — auto-start on boot, auto-restart on crash, proper logging

### Capture Approach: ffmpeg from RTSP

The capture worker runs ffmpeg to software-decode the local RTSP stream and extract 1 frame/sec as JPEG. Trade-offs acknowledged:

| Concern | Mitigation |
|---|---|
| **CPU cost of H.264 software decoding** | At 720p15, ffmpeg uses ~20-30% of one core (5-8% total on quad-core). Acceptable. Set `nice -n 10` for lower priority. |
| **Re-encoding artifacts** (H.264 → JPEG) | At `-q:v 3` and 2.5 Mbps bitrate, artifacts are minimal for wildlife observation. Not a photography system. |
| **14/15 decoded frames wasted** | Unavoidable with RTSP, but the CPU cost is manageable. Alternative (picamera2 dual-stream) adds complexity and Python camera management overhead. |

**Alternatives considered and rejected:**
- **picamera2 for everything**: More complex, Python owns the camera (fragile), higher RAM from picamera2 library
- **rpicam-still --timelapse**: Conflicts with MediaMTX camera access (only one libcamera client at a time)
- **MediaMTX snapshot API**: Not available for rpicamera source in current versions

### Startup Sequencing

```
1. mediamtx.service starts → opens camera, begins streaming
2. pi-webcam.service starts (After=mediamtx.service)
   └─ ExecStartPre: wait for RTSP endpoint (retry ffprobe for up to 30s)
   └─ ExecStart: Python app starts
      ├─ Initialize SQLite (create tables if needed)
      ├─ Reconcile: scan image dir for orphan files not in DB, register them
      ├─ Start capture worker (spawns ffmpeg)
      ├─ Start retention worker (hourly cleanup)
      └─ Start Uvicorn web server
```

### Graceful Shutdown

- FastAPI lifespan event sends SIGTERM to ffmpeg subprocess, awaits exit
- Pending SQLite writes complete (WAL mode ensures consistency even on hard kill)
- Systemd `TimeoutStopSec=10` gives time for graceful shutdown before SIGKILL

---

## 5. Software Stack

### On the Pi

| Tool | Version | Purpose |
|---|---|---|
| **MediaMTX** | v1.12.0 (pinned) | Video streaming server with built-in rpicamera support |
| **Python** | 3.11+ (ships with Bookworm) | Application runtime |
| **uv** | Latest | Python package manager (fast, modern, replaces pip+venv) |
| **FastAPI** | Latest | Async web framework |
| **Uvicorn** | Latest | ASGI server for FastAPI (**1 worker**, explicit) |
| **ffmpeg** | System package | Frame extraction from RTSP stream |
| **SQLite** | System (via Python stdlib `sqlite3`) | Metadata database — use `run_in_executor` for non-blocking access (avoids `aiosqlite` dependency) |
| **Pydantic** | v2 | Data validation, settings management, models |
| **Jinja2** | Latest | HTML template rendering (minimal) |
| **Pillow** | Latest | Thumbnail generation (lightweight, only for resize) |

### Development (on your Mac)

| Tool | Purpose |
|---|---|
| **uv** | Package management + virtual env |
| **ruff** | Linting + formatting (replaces black, isort, flake8) |
| **pytest** | Testing framework |
| **pytest-asyncio** | Async test support |
| **httpx** | Async HTTP client for API testing (FastAPI TestClient) |
| **mypy** | Static type checking |

---

## 6. Project Structure

```
pi_webcam/
├── pyproject.toml              # Project config, dependencies, tool settings
├── .gitignore                  # Includes config/*.env, *.db, data/
├── PLAN.md                     # This file
│
├── src/
│   └── pi_webcam/
│       ├── __init__.py
│       ├── config.py           # Pydantic Settings (paths, DB, retention, stream URL, etc.)
│       ├── database.py         # SQLite schema, CRUD, run_in_executor wrapper
│       ├── models.py           # Pydantic models (Frame, FrameList, TimeRange, CaptureStatus)
│       ├── capture.py          # Frame capture worker (ffmpeg → JPEG + thumbnail → SQLite)
│       ├── retention.py        # Cleanup old frames (age-based + disk-space watermark)
│       ├── thumbnails.py       # Thumbnail generation (Pillow resize)
│       ├── server.py           # FastAPI app (API routes + static files + auth)
│       └── main.py             # Entry point: lifespan, startup reconciliation, workers
│
├── static/
│   ├── index.html              # Main page: live stream + image viewer
│   ├── style.css               # Minimal responsive styling
│   └── app.js                  # Video player + time slider + debounced fetching
│
├── tests/
│   ├── conftest.py             # Shared fixtures (temp DB file, temp image dir, sample JPEGs)
│   ├── test_config.py          # Env var parsing, defaults, validation
│   ├── test_database.py        # CRUD, time range queries, pagination, schema init
│   ├── test_capture.py         # Mocked ffmpeg subprocess, file detection, error recovery
│   ├── test_retention.py       # Age-based + watermark cleanup, orphan handling
│   ├── test_thumbnails.py      # Resize logic, edge cases
│   ├── test_server.py          # All API endpoints (TestClient), auth, error responses
│   ├── test_models.py          # Serialization, validation
│   └── test_integration.py    # End-to-end: capture → DB → API → serve (no camera needed)
│
├── config/
│   ├── mediamtx.yml            # MediaMTX configuration (checked in)
│   └── pi-webcam.env.example   # Example env vars (checked in; actual .env is gitignored)
│
├── deploy/
│   ├── install.sh              # Idempotent setup script for Pi
│   ├── mediamtx.service        # Systemd unit for MediaMTX
│   ├── pi-webcam.service       # Systemd unit for the Python app (with readiness check)
│   └── logrotate.conf          # Log rotation configuration
│
└── .github/
    └── workflows/
        └── ci.yml              # Lint + type check + test on push (x86_64; no HW tests)
```

---

## 7. Database Schema

```sql
CREATE TABLE frames (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    filename    TEXT    NOT NULL UNIQUE,      -- e.g. "20260314_153022.jpg"
    captured_at INTEGER NOT NULL,            -- Unix epoch (INTEGER for fast range queries)
    file_size   INTEGER,                     -- bytes
    file_path   TEXT    NOT NULL,            -- relative: "2026/03/14/153022.jpg"
    thumb_path  TEXT,                        -- relative: "2026/03/14/thumb/153022.jpg"
    metadata    TEXT,                        -- JSON: extensible (AI results, etc.)
    created_at  INTEGER DEFAULT (unixepoch())
);

CREATE INDEX idx_frames_captured_at ON frames(captured_at);

-- Enable auto-vacuum to reclaim space from deleted rows
PRAGMA auto_vacuum = INCREMENTAL;
```

Using `INTEGER` (Unix epoch) for timestamps instead of TEXT — faster for range queries and comparisons.

The `metadata` JSON column enables future extension without schema changes:
```json
{
    "detections": [{"class": "bird", "confidence": 0.92, "bbox": [100, 200, 300, 400]}],
    "motion_score": 0.73,
    "brightness": 128
}
```

### Image Directory Structure

```
/data/pi_webcam/
├── frames/
│   └── 2026/
│       └── 03/
│           ├── 14/
│           │   ├── 153022.jpg          # Full frame (720p, ~150 KB)
│           │   ├── 153023.jpg
│           │   └── thumb/
│           │       ├── 153022.jpg      # Thumbnail (320x180, ~10 KB)
│           │       └── 153023.jpg
│           └── 15/
│               └── ...
└── pi_webcam.db                        # SQLite database
```

Date-based subdirectories prevent any single directory from holding more than ~86,400 files (one day). Thumbnails in a `thumb/` subdirectory alongside full frames.

---

## 8. Implementation Steps

### Phase 1: Project Skeleton
1. Initialize Python project with `uv init`, configure `pyproject.toml`
2. Set up `ruff` (linting/formatting), `mypy` (type checking), `pytest`
3. Create project structure (directories, `__init__.py` files)
4. Create `.gitignore` (include `*.env`, `*.db`, `data/`, `__pycache__/`)
5. Add CI workflow (GitHub Actions: `ruff check`, `mypy`, `pytest` on push)
6. Note: CI runs on x86_64 runners — tests are hardware-independent by design

### Phase 2: Configuration & Database
1. Implement `config.py` — Pydantic Settings with env var support
   - Image directory path, DB path, capture interval (default 1s), retention days
   - MediaMTX RTSP URL (default `rtsp://localhost:8554/cam`)
   - Web server host/port, thumbnail size
   - Disk space low-watermark (e.g., 1 GB — triggers immediate cleanup)
   - Optional basic auth credentials (username/password hash)
2. Implement `database.py` — SQLite operations with `run_in_executor`
   - Schema creation with `IF NOT EXISTS`
   - `insert_frame()`, `get_frames(start, end, limit, offset)` (paginated)
   - `get_frame_by_id()`, `get_latest_frame()`, `get_frame_count()`
   - `delete_frames_before(timestamp)` — returns deleted file paths
   - `get_orphan_files(known_paths)` — for startup reconciliation
   - WAL mode enabled on connection
3. Implement `models.py` — Pydantic models
   - `Frame`, `FrameList` (with `next_offset` for pagination), `TimeRange`
   - `CaptureStatus`, `SystemStatus` (disk usage, frame count, uptime, temperature)
4. Write tests for all of the above

### Phase 3: Frame Capture & Thumbnails
1. Implement `capture.py` — background worker
   - Spawns ffmpeg subprocess with robust flags:
     ```
     ffmpeg -rtsp_transport tcp -fflags nobuffer -flags low_delay
       -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 30
       -i rtsp://localhost:8554/cam
       -vf fps=1 -q:v 3 -f image2 -strftime 1
       <output_dir>/%Y/%m/%d/%H%M%S.jpg
     ```
   - Monitors output directory for new files (polling every 0.5s)
   - On new file: generate thumbnail, read file size, insert metadata into SQLite
   - **Timestamp source**: filename (from ffmpeg `-strftime`) is authoritative; `captured_at` derived from it
   - Handle ffmpeg crashes: auto-restart with exponential backoff (1s, 2s, 4s, max 30s)
   - Handle ffmpeg stderr: log warnings, detect fatal errors
2. Implement `thumbnails.py`
   - Resize to 320x180 using Pillow (LANCZOS filter)
   - Save to `thumb/` subdirectory alongside full frame
   - Lightweight: Pillow only loads/saves, no heavy processing
3. Implement `retention.py` — periodic cleanup
   - **Age-based**: delete frames older than configured retention period
   - **Watermark-based**: if free disk < watermark, delete oldest frames until free > watermark
   - Remove from both disk and database (delete files, then delete DB rows)
   - Clean empty date directories after deletion
   - Runs every 15 minutes as background task (not hourly — faster response to disk pressure)
4. Implement startup reconciliation in `main.py`:
   - Scan image directory for JPEG files not in database → insert them
   - Scan database for entries whose files don't exist on disk → delete them
5. Write tests:
   - Mock ffmpeg subprocess (simulate stdout/stderr, exit codes, crashes)
   - Test file detection with real tmp_path files
   - Test thumbnail generation with a real small JPEG
   - Test retention with age-based and watermark-based scenarios
   - Test reconciliation with orphan files and stale DB entries

### Phase 4: Web Server & API
1. Implement `server.py` — FastAPI application
   - **Optional basic auth** (configurable, disabled by default for local network simplicity):
     - If credentials configured, all endpoints require HTTP Basic Auth
     - `/api/stream-url` returns authenticated MediaMTX URL if auth is enabled
   - `GET /` — serve main HTML page
   - `GET /api/frames?start=<epoch>&end=<epoch>&limit=100&offset=0` — paginated frame list
   - `GET /api/frames/latest` — most recent frame metadata
   - `GET /api/frames/{id}` — single frame metadata
   - `GET /api/days` — list of days that have frames (for date picker)
   - `GET /api/status` — system status (uptime, frame count, disk free, capture status, CPU temp)
   - `GET /images/{path:path}` — serve JPEG files via StaticFiles mount
     - **Path validation**: reject `..`, absolute paths, non-JPEG extensions
   - `GET /thumbs/{path:path}` — serve thumbnail files
   - `GET /api/stream-url` — returns MediaMTX WebRTC/HLS endpoint URLs
   - `GET /api/export?start=<epoch>&end=<epoch>` — stream a tar archive of frames in range (future nice-to-have)
2. Implement `main.py` — entry point with FastAPI lifespan
   - Lifespan `startup`: init DB, reconcile, start capture + retention workers
   - Lifespan `shutdown`: stop ffmpeg (SIGTERM), cancel background tasks, close DB
   - Run with: `uvicorn pi_webcam.main:app --host 0.0.0.0 --port 8080 --workers 1`
3. Write tests:
   - FastAPI TestClient for all endpoints
   - Test pagination (offset/limit)
   - Test path traversal rejection on image endpoints
   - Test auth enabled/disabled modes
   - Test error responses (404 for missing frame, 400 for invalid params)

### Phase 5: Frontend Viewer
1. `index.html` — two-panel layout:
   - **Top panel:** Live video stream (WebRTC via MediaMTX, automatic HLS fallback)
   - **Bottom panel:** Image viewer with time slider
   - **Error/loading states:** "Camera offline", "No images yet", "Loading..."
2. `app.js`:
   - **Live stream:**
     - Connect to MediaMTX WebRTC endpoint using `RTCPeerConnection`
     - Monitor ICE connection state; on failure, fall back to HLS `<video>` source
     - LAN-only assumption: no STUN/TURN needed (documented as limitation)
   - **Time slider:**
     - Date picker for day selection (populated from `/api/days`)
     - `<input type="range">` mapped to selected day's time range (0–86399 seconds)
     - **Debounced fetching**: on slider `input` event, debounce 150ms, then fetch nearest thumbnail from `/thumbs/...`
     - On slider `change` event (release), fetch full-resolution image
     - **Prefetching**: on idle, preload thumbnails for ±30 seconds around current position
     - Arrow keys / buttons for stepping ±1 frame
     - Timestamp overlay on displayed image
   - **Cache headers**: server sets `Cache-Control: public, max-age=31536000, immutable` on images (frames are write-once)
3. `style.css` — minimal responsive styling, works on mobile
   - Flexbox layout, max-width for readability
   - Slider styled for easy thumb (handle) dragging

### Phase 6: Deployment & Autostart
1. Write `deploy/install.sh` (idempotent — safe to re-run):
   ```bash
   #!/bin/bash
   set -euo pipefail
   # Check if already installed, skip completed steps
   # Install system deps (apt)
   # Download MediaMTX v1.12.0 ARM64 binary (pinned version, checksum verified)
   # Create /data/pi_webcam/ directory structure
   # Install Python app with uv
   # Copy systemd units (overwrite if exist)
   # Copy logrotate config
   # Reload systemd daemon
   # Enable and start services
   ```
2. Write `deploy/mediamtx.service`:
   ```ini
   [Unit]
   Description=MediaMTX RTSP/WebRTC Server
   After=network-online.target
   Wants=network-online.target

   [Service]
   ExecStart=/usr/local/bin/mediamtx /etc/mediamtx/mediamtx.yml
   Restart=always
   RestartSec=5
   Nice=-5

   [Install]
   WantedBy=multi-user.target
   ```
3. Write `deploy/pi-webcam.service`:
   ```ini
   [Unit]
   Description=Pi Webcam Application
   After=mediamtx.service
   Requires=mediamtx.service

   [Service]
   # Wait for RTSP stream to be available before starting
   ExecStartPre=/bin/bash -c 'for i in $(seq 1 30); do ffprobe -v quiet rtsp://localhost:8554/cam && exit 0; sleep 1; done; exit 1'
   ExecStart=/usr/local/bin/uv run uvicorn pi_webcam.main:app --host 0.0.0.0 --port 8080 --workers 1
   WorkingDirectory=/opt/pi_webcam
   Restart=always
   RestartSec=5
   Nice=10
   TimeoutStopSec=10
   Environment=PI_WEBCAM_ENV=/etc/pi_webcam/pi-webcam.env

   [Install]
   WantedBy=multi-user.target
   ```
4. Write `deploy/logrotate.conf` for systemd journal limits
5. Write `config/mediamtx.yml` (see section 9)

### Phase 7: Testing & Polish
1. Ensure all tests pass locally and in CI (`ruff check`, `mypy --strict`, `pytest -v`)
2. Deploy to Pi, run end-to-end smoke test (manual):
   - Verify live stream works in browser (WebRTC + HLS fallback)
   - Verify frames appear in `/data/pi_webcam/frames/`
   - Verify viewer loads and slider works
   - Verify retention deletes old frames
3. Monitor resource usage for 24h:
   - `htop` for CPU/RAM
   - `vcgencmd measure_temp` for temperature
   - `df -h` for disk usage
4. Tune parameters based on monitoring:
   - Resolution (720p vs 480p), framerate (15 vs 10), JPEG quality, bitrate
5. Document final tuned settings in README

---

## 9. MediaMTX Configuration

```yaml
# config/mediamtx.yml
# Logging
logLevel: warn

# WebRTC (browser live view)
webrtcAddress: :8889

# RTSP (local capture + external clients)
rtspAddress: :8554

# HLS (fallback for browsers without WebRTC)
hlsAddress: :8888

paths:
  cam:
    source: rpiCamera
    rpiCameraWidth: 1280
    rpiCameraHeight: 720
    rpiCameraFPS: 15
    rpiCameraIDRPeriod: 30
    rpiCameraCodec: h264
    rpiCameraBitrate: 2500000
    rpiCameraAfMode: continuous
    # For fixed-focus (quieter, no AF motor clicks — better for wildlife):
    # rpiCameraAfMode: manual
    # rpiCameraLensPosition: 0.0   # 0.0 = infinity focus
    rpiCameraTextOverlayEnable: true
    rpiCameraTextOverlay: "%Y-%m-%d %H:%M:%S"
    # HDR: disabled by default (increases CPU load, can reduce framerate)
    # rpiCameraHDR: false
```

Notes:
- Start with 720p15 at 2.5 Mbps — the Zero 2 W handles this comfortably
- `rpiCameraAfMode: continuous` causes audible lens motor clicks — for wildlife, consider `manual` with `rpiCameraLensPosition: 0.0` (infinity focus) to avoid scaring animals
- Text overlay bakes timestamp into the video stream (useful for RTSP recordings)
- Increase bitrate to 4 Mbps for higher quality if network bandwidth allows

---

## 10. Testing Strategy

| Layer | What | How |
|---|---|---|
| **Config** | Env var parsing, defaults, validation, edge cases | Pytest, mock env vars |
| **Database** | CRUD, time range queries, pagination, schema init, vacuum | Pytest, **file-backed** SQLite in tmp_path (not in-memory, to test WAL mode) |
| **Capture** | ffmpeg invocation, file monitoring, crash recovery, backoff | Pytest, mock subprocess, temp dirs |
| **Thumbnails** | Resize logic, missing source handling, corrupt image handling | Pytest, real small test JPEG in fixtures |
| **Retention** | Age-based + watermark deletion, orphan cleanup, empty dir removal | Pytest, temp dirs + file-backed DB |
| **API** | All endpoints, pagination, auth, path validation, error responses | FastAPI TestClient + httpx |
| **Models** | Serialization, validation, epoch conversion | Pytest, Pydantic model tests |
| **Integration** | Capture → DB → API → serve image (full pipeline, no camera) | Pytest, mock ffmpeg, real DB + files |

### Testing Principles

- Every module has corresponding unit tests
- One integration test file verifies the full pipeline (mocked ffmpeg → real files → real DB → real API)
- Use `tmp_path` fixture for all file system operations
- Use **file-backed SQLite** (not `:memory:`) to test WAL mode and real locking behavior
- Mock external dependencies: ffmpeg subprocess, file system watches where needed
- CI runs `ruff check`, `mypy --strict`, and `pytest -v` on every push
- No tests require actual camera hardware or Pi — all hardware interactions are behind mockable boundaries
- CI architecture note: tests run on x86_64 GitHub Actions runners; Pi-specific integration is tested manually during deployment (Phase 7)

---

## 11. Security

Conscious decisions for a home LAN wildlife camera:

| Aspect | Decision |
|---|---|
| **Web API auth** | Optional HTTP Basic Auth (disabled by default). Enable if camera is on a shared/untrusted network. |
| **MediaMTX auth** | Not configured by default. MediaMTX supports auth hooks if needed. |
| **SSH** | Key-only authentication (password auth disabled in OS setup). |
| **HTTPS** | Not configured (local HTTP). For remote access, use a reverse proxy (nginx + Let's Encrypt) or a tunnel. |
| **Path traversal** | API validates image paths: reject `..`, absolute paths, non-image extensions. |
| **Firewall** | Not configured by default. Exposed ports: 8080 (web), 8554 (RTSP), 8888 (HLS), 8889 (WebRTC), 22 (SSH). |
| **Env file** | `config/pi-webcam.env` is gitignored; only `.env.example` is committed. |
| **Remote access** | For access outside LAN, recommend Tailscale or WireGuard (simple, encrypted tunnel). Not built-in. |

---

## 12. Future Extensions (AI)

The architecture supports AI extensions cleanly — AI workers are separate processes that read JPEGs and write results to SQLite:

### Motion Detection (Runs on Pi)
- Compare consecutive frames: pixel diff or structural similarity (SSIM)
- Store `motion_score` in frame metadata JSON
- Filter viewer to show only "interesting" moments
- Implementation: Pillow or OpenCV `absdiff` on thumbnails (320x180), very lightweight
- **Adaptive capture**: reduce capture rate to 1/10s when no motion, increase to 1/s when motion detected (saves ~90% storage on idle scenes)

### Object Detection (YOLO)

**On-device (batch, not real-time):**
- YOLOv8n with NCNN runtime: ~2 sec/frame on Zero 2 W
- Process every 5th–10th frame as a background worker
- Store detections in frame metadata JSON
- Add detection filter to the viewer (e.g., "show only frames with birds")

**Offloaded (recommended for real-time):**
- Zero 2 W uploads frames to a more powerful machine (Pi 5, NAS, server) via HTTP POST
- Detection runs there, results posted back via API
- Best of both worlds: lightweight capture device + powerful inference

### Notification System
- Telegram/push notification when specific animals detected
- Configurable alert rules (e.g., "notify when bird detected with confidence > 0.8")

### Timelapse Video Generation
- Combine day's frames into an MP4 timelapse (ffmpeg, 30x speed = 48 min of footage per day)
- Generate nightly as a cron job or on-demand via API
- Trivial with the date-based directory structure

### Extension Architecture
```
New AI workers follow this pattern:
1. Query SQLite for unprocessed frames (metadata IS NULL or specific field missing)
2. Read JPEG from disk (thumbnail for fast screening, full frame for detailed analysis)
3. Process (motion detection, YOLO, classification, etc.)
4. Write results back to SQLite metadata JSON column
5. Viewer filters/displays based on metadata fields
```

No changes to capture pipeline or streaming needed.

---

## 13. Resource Budget (Pi Zero 2 W — 512 MB RAM)

| Component | RAM (est.) | CPU (est., of total quad-core) |
|---|---|---|
| OS + system services | ~80 MB | ~5% |
| MediaMTX + rpicamera + H.264 HW encode | ~15 MB | ~25-30% |
| Python app (FastAPI + workers) | ~60-80 MB | ~5-10% |
| ffmpeg (H.264 SW decode, 720p15, extract 1fps) | ~20 MB | ~5-10% (one core at ~25%) |
| Pillow (thumbnail generation, per-frame) | ~5 MB transient | ~1% |
| SQLite | ~2 MB | negligible |
| **Total** | **~180-200 MB** | **~40-55%** |
| **Headroom** | **~250-300 MB** | **~45-60%** |
| **Swap configured** | **256 MB** | — |

Notes:
- ffmpeg CPU estimate accounts for software H.264 decoding of the full 15fps stream (only 1 frame/sec is saved, but all must be decoded)
- Python RAM estimate includes FastAPI, Pydantic v2, Jinja2, and Pillow loaded
- Headroom is sufficient for occasional AI processing or multiple browser clients
- Swap prevents OOM kills during transient spikes but should not be relied on continuously (SD card wear)

---

## 14. Risk Mitigation

| Risk | Mitigation |
|---|---|
| **SD card wear** | `noatime,commit=60` mount options; date-based dirs reduce metadata updates; thumbnails reduce read I/O; moderate swap (256 MB) |
| **SD card fills up** | Retention worker runs every 15 min; watermark trigger for immediate cleanup (< 1 GB free); disk usage in status API |
| **Camera freeze / MediaMTX crash** | Systemd `Restart=always`; capture worker detects ffmpeg exit and reconnects with backoff |
| **ffmpeg crash** | Auto-restart with exponential backoff (1s→30s); `-reconnect` flags handle transient RTSP drops without process restart |
| **WiFi drops** | NetworkManager/systemd auto-reconnects; capture continues locally (frames saved to SD); web UI unavailable until reconnect |
| **Power loss** | SQLite WAL mode ensures DB consistency; partial JPEG files detected and skipped on startup reconciliation |
| **Overheating** | Heatsink required (hardware section); temperature in status API; consider dynamic resolution/fps reduction at >75C |
| **Orphan files** | Startup reconciliation: scan dir for files not in DB, scan DB for entries without files |
| **Timestamp drift** | NTP synced system clock (default on Pi OS); ffmpeg `-strftime` uses system time; `captured_at` derived from filename |
| **SQLite bloat** | `auto_vacuum = INCREMENTAL`; run `PRAGMA incremental_vacuum` periodically |
| **SD card failure** | Recommend periodic backup of SQLite DB to NAS/cloud (small file, easy to rsync); images are expendable |

---

## 15. Step-by-Step Execution Order

```
1. [ ] Phase 1 — Project skeleton (pyproject.toml, ruff, mypy, pytest, CI, .gitignore)
2. [ ] Phase 2 — Config, database, models + tests
3. [ ] Phase 3 — Capture worker + thumbnails + retention + tests
4. [ ] Phase 4 — Web server API + tests
5. [ ] Phase 5 — Frontend viewer (HTML/JS/CSS)
6. [ ] Phase 6 — MediaMTX config, systemd services, install script, logrotate
7. [ ] Phase 7 — Deploy to Pi, smoke test, 24h monitoring, tune, document
```

Each phase is self-contained and testable before moving to the next. Phases 2-4 include comprehensive tests that run without any Pi hardware.
