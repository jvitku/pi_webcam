# CLAUDE.md — Project Context for AI Development

## What This Is

Pi Webcam: a wildlife camera running on Raspberry Pi Zero 2 W + Camera Module 3. Web UI for live streaming (WebRTC) and timelapse browsing. Python/FastAPI backend, vanilla JS frontend.

## Key Constraints

- **Pi Zero 2 W**: 512 MB RAM, quad-core 1 GHz ARM, 2.4 GHz WiFi only
- **MediaMTX v1.12.0**: newer versions (v1.16.3) have H.264 encoder bugs on this hardware (`ioctl(VIDIOC_QBUF) failed`)
- **No `-strftime` with RTSP**: ffmpeg's `-strftime` flag doesn't work with RTSP input on the Pi's ffmpeg. We use `-update 1` (overwrite `latest.jpg`) and Python-side timestamping instead
- **No hot-reload for focus**: AfMode, LensPosition, AfWindow changes restart the MediaMTX pipeline and crash the stream. Only EV, brightness, contrast, saturation, metering are hot-reloadable
- **MediaMTX API**: v1.12.0 has no PATCH endpoint. We use read-modify-POST via `/v3/config/paths/replace/cam`. The PATCH endpoint exists in v1.13+ but we can't upgrade due to the encoder bug

## Architecture

```
MediaMTX (rpicamera source) → RTSP stream → ffmpeg (-update 1) → latest.jpg
Python capture worker polls latest.jpg → copies to YYYY/MM/DD/HHMMSS.jpg + thumbnail
FastAPI serves: web UI, REST API, proxies MediaMTX camera API
Frontend: noUiSlider + filmstrip + WebRTC player, two tabs (Live + Settings)
SQLite DB: frame metadata (captured_at as Unix epoch in local time)
```

## Project Structure

```
src/pi_webcam/
  config.py      — Pydantic Settings, env vars with PI_WEBCAM_ prefix
  database.py    — SQLite wrapper, CRUD, sampling via ROW_NUMBER
  capture.py     — ffmpeg subprocess, latest.jpg polling, timestamped copy
  retention.py   — age-based + disk watermark cleanup
  thumbnails.py  — Pillow resize to 320x180
  server.py      — FastAPI app, camera API proxy, system stats
  main.py        — lifespan, background workers, entry point
  models.py      — Pydantic models

static/
  index.html     — two tabs (Live + Settings), noUiSlider CDN
  app.js          — all frontend logic
  style.css       — dark theme, iOS-style design

deploy/
  install.sh      — idempotent Pi setup script
  mediamtx.service, pi-webcam.service — systemd units

config/
  mediamtx.yml    — camera config (720p15, H.264, continuous AF)
```

## Frontend Data Flow

1. **Page load**: fetches sampled overview (~1000 frames) via `/api/frames?sample=N`
2. **Slider drag**: shows thumbnails from sampled frames (fast)
3. **Slider release**: shows full image, clears detail window
4. **Play/arrows**: loads "detail window" of 200 frames at chosen sample rate
5. **Prefetch**: at 50% through detail window, appends next chunk (non-blocking)
6. **Speed dropdown**: changing it restarts playback (togglePlay × 2)
7. **`detailGeneration` counter**: prevents stale in-flight fetches from corrupting state

## Important Implementation Details

- `captured_at` is Unix epoch in **local time** (not UTC) — matches ffmpeg's system clock
- `filename_to_epoch` uses `time.mktime` (local) not `datetime(tzinfo=UTC)`
- Frontend date handling: `new Date(dateStr + "T00:00:00")` without `Z` suffix = local time
- `scrubSlider.set(value, false)` — second arg prevents animation (avoids handle disappearing)
- `scrubUpdating` flag prevents slider event feedback loops during programmatic updates
- `showFrameFromSampled` must increment `detailGeneration` to cancel stale prefetches
- Play uses `Image()` preload — only advances on `onload`, skips on `onerror`
- System stats (`/proc/stat`, `/proc/meminfo`, `/proc/net/dev`) need two samples for rates

## Testing

```bash
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest -v
```

- 101 tests, all hardware-independent
- File-backed SQLite (not in-memory) to test WAL mode
- Mock ffmpeg subprocess for capture tests
- FastAPI TestClient for API tests
- `tmp_path` fixtures for all file operations

## Deployment

On the Pi:
```bash
cd ~/pi_webcam && git pull -r && sudo bash deploy/install.sh  # full
cd ~/pi_webcam && git pull -r && sudo cp -r src static /opt/pi_webcam/ && sudo systemctl restart pi-webcam  # quick
```

Services: `mediamtx.service` → `pi-webcam.service` (depends on mediamtx, waits for RTSP via curl healthcheck)

## Known Issues (see TODO.md)

- Timeline arrows step by sampled intervals (~30s) not raw frames (2s) — detail window needed
- MediaMTX v1.12.0 API only supports replace, not patch
- Focus controls disabled (pipeline restart)
- ffmpeg `-strftime` broken with RTSP on Pi
