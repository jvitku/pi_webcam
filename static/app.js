/* Pi Webcam — Frontend */

const timeDisplay = document.getElementById("time-display");
const frameImage = document.getElementById("frame-image");
const frameInfo = document.getElementById("frame-info");
const noFrames = document.getElementById("no-frames");
const frameCount = document.getElementById("frame-count");
const datePicker = document.getElementById("date-picker");
const streamError = document.getElementById("stream-error");
const liveVideo = document.getElementById("live-video");
const btnPrev = document.getElementById("btn-prev");
const btnNext = document.getElementById("btn-next");
const btnPlay = document.getElementById("btn-play");
const fpsSelect = document.getElementById("fps-select");
const fpsStatus = document.getElementById("fps-status");

// Status pills
const statConnection = document.getElementById("stat-connection");
const statCpu = document.getElementById("stat-cpu");
const statTemp = document.getElementById("stat-temp");
const statRam = document.getElementById("stat-ram");
const statNet = document.getElementById("stat-net");
const statDisk = document.getElementById("stat-disk");
const statFrames = document.getElementById("stat-frames");

let currentFrames = [];
let currentIndex = -1;
let debounceTimer = null;

// --- Initialization ---

function localDateStr() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
}

function init() {
    const today = localDateStr();
    datePicker.value = today;

    datePicker.addEventListener("change", () => loadDay(datePicker.value));
    btnPrev.addEventListener("click", () => stepFrame(-1));
    btnNext.addEventListener("click", () => stepFrame(1));
    btnPlay.addEventListener("click", togglePlay);
    fpsSelect.addEventListener("change", onFpsChange);
    initScrub();

    document.addEventListener("keydown", (e) => {
        if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
        if (e.key === "ArrowLeft") stepFrame(-1);
        else if (e.key === "ArrowRight") stepFrame(1);
        else if (e.key === " ") { e.preventDefault(); togglePlay(); }
    });

    initTabs();
    initCameraControls();
    loadDay(today);
    loadStatus();
    initStream();
    setInterval(loadStatus, 10000);
    setInterval(pollNewFrames, 5000);
}

// --- Tabs ---

function initTabs() {
    document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
            document.querySelectorAll(".tab-content").forEach(t => t.classList.remove("active"));
            btn.classList.add("active");
            document.getElementById(btn.dataset.tab).classList.add("active");

            // Mirror live stream to settings video when switching to settings
            if (btn.dataset.tab === "tab-settings") {
                const settingsVideo = document.getElementById("settings-video");
                if (liveVideo.srcObject) {
                    settingsVideo.srcObject = liveVideo.srcObject;
                } else if (liveVideo.src) {
                    settingsVideo.src = liveVideo.src;
                }
                loadCameraSettings();
            }
        });
    });
}

// --- Live Stream ---

async function initStream() {
    streamError.classList.add("hidden");
    try {
        const res = await fetch(WEBRTC_URL + "/whep", { method: "POST",
            headers: { "Content-Type": "application/sdp" },
            body: await createOffer() });
        if (res.ok) {
            const answer = await res.text();
            await setAnswer(answer);
            return;
        }
    } catch (e) {
        console.warn("WebRTC failed, trying HLS:", e);
    }

    try {
        liveVideo.src = HLS_URL + "/index.m3u8";
        liveVideo.play().catch(() => {});
    } catch (e) {
        console.error("HLS failed:", e);
        streamError.classList.remove("hidden");
    }
}

let pc = null;

async function createOffer() {
    pc = new RTCPeerConnection({ iceServers: [] });
    pc.addTransceiver("video", { direction: "recvonly" });
    pc.addTransceiver("audio", { direction: "recvonly" });

    pc.ontrack = (e) => { liveVideo.srcObject = e.streams[0]; };

    pc.oniceconnectionstatechange = () => {
        if (pc.iceConnectionState === "failed" || pc.iceConnectionState === "disconnected") {
            streamError.classList.remove("hidden");
        }
    };

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    await new Promise((resolve) => {
        if (pc.iceGatheringState === "complete") resolve();
        else pc.onicegatheringstatechange = () => {
            if (pc.iceGatheringState === "complete") resolve();
        };
    });

    return pc.localDescription.sdp;
}

async function setAnswer(sdp) {
    await pc.setRemoteDescription({ type: "answer", sdp });
}

// --- Fullscreen ---

function toggleFullscreen() {
    const video = document.getElementById("live-video");
    const container = document.getElementById("video-container");

    if (video.webkitEnterFullscreen) {
        video.webkitEnterFullscreen();
    } else if (document.fullscreenElement) {
        document.exitFullscreen();
    } else if (container.requestFullscreen) {
        container.requestFullscreen();
    } else if (container.webkitRequestFullscreen) {
        container.webkitRequestFullscreen();
    }
}

function toggleSettingsFullscreen() {
    const video = document.getElementById("settings-video");
    const container = document.getElementById("settings-video-container");

    if (video.webkitEnterFullscreen) {
        video.webkitEnterFullscreen();
    } else if (document.fullscreenElement) {
        document.exitFullscreen();
    } else if (container.requestFullscreen) {
        container.requestFullscreen();
    }
}

// --- Timeline ---

let currentDayStart = 0;
let currentDayEnd = 0;
let totalFrameCount = 0;

async function loadDay(dateStr) {
    currentDayStart = new Date(dateStr + "T00:00:00").getTime() / 1000;
    currentDayEnd = currentDayStart + 86399;

    noFrames.textContent = "Loading...";
    noFrames.classList.remove("hidden");
    frameImage.classList.remove("visible");

    try {
        // First get total count, then sample to fit in ~1000 frames
        const countRes = await fetch(
            `/api/frames?start=${currentDayStart}&end=${currentDayEnd}&limit=1`
        );
        const countData = await countRes.json();
        const sampleRate = Math.max(1, Math.ceil(countData.total / 1000));
        const res = await fetch(
            `/api/frames?start=${currentDayStart}&end=${currentDayEnd}&limit=2000&sample=${sampleRate}`
        );
        const data = await res.json();
        currentFrames = data.frames;
        totalFrameCount = data.total;
        frameCount.textContent = `${totalFrameCount}`;

        if (currentFrames.length === 0) {
            noFrames.textContent = "No frames for this day";
            frameInfo.textContent = "";
            document.getElementById("time-start").textContent = "--:--";
            document.getElementById("time-end").textContent = "--:--";
            document.getElementById("filmstrip").innerHTML = "";
            return;
        }

        noFrames.classList.add("hidden");

        const tStart = new Date(currentFrames[0].captured_at * 1000);
        const tEnd = new Date(currentFrames[currentFrames.length - 1].captured_at * 1000);
        document.getElementById("time-start").textContent = fmtTime(tStart);
        document.getElementById("time-end").textContent = fmtTime(tEnd);

        // Update slider range and build filmstrip
        if (scrubSlider) {
            scrubSlider.updateOptions({
                range: { min: 0, max: Math.max(1, currentFrames.length - 1) },
            });
        }
        rebuildFilmstrip(currentFrames.length - 1);
        showFrame(currentFrames.length - 1);
    } catch (e) {
        console.error("Failed to load frames:", e);
        noFrames.textContent = "Error loading frames";
    }
}

function fmtTime(d) {
    return `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`;
}

// --- Scrub system (noUiSlider + filmstrip) ---

let scrubSlider = null;
let scrubUpdating = false;

// Filmstrip state: which index range is currently displayed
let filmIdxStart = 0;
let filmIdxEnd = 0;

function initScrub() {
    const el = document.getElementById("scrub-slider");
    noUiSlider.create(el, {
        start: 0,
        step: 1,
        range: { min: 0, max: 1 },
    });
    scrubSlider = el.noUiSlider;

    let userDragging = false;

    // "start" fires when user grabs the handle
    scrubSlider.on("start", () => {
        userDragging = true;
        if (playing) togglePlay();
    });

    // "slide" fires continuously during drag — show thumbnail (fast)
    scrubSlider.on("slide", (values) => {
        if (!userDragging) return;
        const idx = Math.round(parseFloat(values[0]));
        if (idx >= 0 && idx < currentFrames.length) {
            showFrameThumb(idx);
        }
    });

    // "end" fires when user releases — load full image + rebuild
    scrubSlider.on("end", (values) => {
        if (!userDragging) return;
        userDragging = false;
        const idx = Math.round(parseFloat(values[0]));
        if (idx >= 0 && idx < currentFrames.length) {
            showFrame(idx);
            rebuildFilmstrip(idx);
        }
    });
}

function rebuildFilmstrip(centerIdx) {
    const strip = document.getElementById("filmstrip");
    strip.innerHTML = "";
    if (currentFrames.length === 0) return;

    // Show ~12 thumbnails centered on centerIdx
    const half = 6;
    const maxIdx = currentFrames.length - 1;

    // Calculate frame index range for filmstrip
    // Use index-based windowing (simpler, always correct)
    const windowSize = Math.min(currentFrames.length, Math.max(12, Math.floor(currentFrames.length / 5)));
    let iStart = Math.max(0, centerIdx - Math.floor(windowSize / 2));
    let iEnd = Math.min(maxIdx, iStart + windowSize - 1);
    iStart = Math.max(0, iEnd - windowSize + 1); // re-adjust if clamped at end

    filmIdxStart = iStart;
    filmIdxEnd = iEnd;

    const count = iEnd - iStart + 1;
    const step = Math.max(1, Math.floor(count / 12));

    for (let i = iStart; i <= iEnd; i += step) {
        const frame = currentFrames[i];
        const div = document.createElement("div");
        div.className = "film-frame";
        const img = document.createElement("img");
        img.src = frame.thumb_path ? `/thumbs/${frame.thumb_path}` : `/images/${frame.file_path}`;
        img.draggable = false;
        div.appendChild(img);
        strip.appendChild(div);
    }

    updateFilmCursor(centerIdx);
}

function updateFilmCursor(idx) {
    if (currentFrames.length === 0 || filmIdxEnd <= filmIdxStart) return;
    const pct = ((idx - filmIdxStart) / (filmIdxEnd - filmIdxStart)) * 100;
    document.getElementById("film-cursor").style.left =
        Math.max(0, Math.min(100, pct)) + "%";

    // Rebuild filmstrip if cursor goes outside the visible window
    if (idx < filmIdxStart || idx > filmIdxEnd) {
        rebuildFilmstrip(idx);
    }
}

function syncSlider(idx) {
    if (scrubSlider) {
        scrubUpdating = true;
        scrubSlider.set(idx);
        scrubUpdating = false;
    }
}

function showFrameThumb(idx) {
    if (idx < 0 || idx >= currentFrames.length) return;
    currentIndex = idx;
    const frame = currentFrames[idx];
    updateTimeDisplay(idx);
    updateFilmCursor(idx);

    const src = frame.thumb_path ? `/thumbs/${frame.thumb_path}` : `/images/${frame.file_path}`;
    frameImage.src = src;
    frameImage.classList.add("visible");
    noFrames.classList.add("hidden");

    const dt = new Date(frame.captured_at * 1000);
    const sizeKb = frame.file_size ? `${Math.round(frame.file_size / 1024)}KB` : "";
    frameInfo.textContent = `${dt.toLocaleTimeString()} | ${sizeKb} | ${idx + 1}/${currentFrames.length}`;
}

function showFrame(idx) {
    if (idx < 0 || idx >= currentFrames.length) return;
    currentIndex = idx;
    const frame = currentFrames[idx];
    updateTimeDisplay(idx);
    syncSlider(idx);
    updateFilmCursor(idx);

    frameImage.src = `/images/${frame.file_path}`;
    frameImage.classList.add("visible");
    frameImage.onerror = () => {
        if (frame.thumb_path) frameImage.src = `/thumbs/${frame.thumb_path}`;
    };

    const dt = new Date(frame.captured_at * 1000);
    const sizeKb = frame.file_size ? `${Math.round(frame.file_size / 1024)}KB` : "";
    frameInfo.textContent = `${sizeKb}  ${idx + 1}/${currentFrames.length}`;
}

function updateTimeDisplay(idx) {
    if (idx < 0 || idx >= currentFrames.length) return;
    const dt = new Date(currentFrames[idx].captured_at * 1000);
    timeDisplay.textContent = dt.toTimeString().split(" ")[0];
}

function stepFrame(delta) {
    const newIdx = currentIndex + delta;
    if (newIdx >= 0 && newIdx < currentFrames.length) showFrame(newIdx);
}

let playing = false;

function togglePlay() {
    if (playing) {
        playing = false;
        btnPlay.textContent = "\u25B6";
    } else {
        playing = true;
        btnPlay.textContent = "\u23F8";
        playNext();
    }
}

function playNext() {
    if (!playing) return;
    if (currentIndex >= currentFrames.length - 1) { togglePlay(); return; }

    const nextIdx = currentIndex + 1;
    const frame = currentFrames[nextIdx];
    // Use full-res image for playback
    const src = `/images/${frame.file_path}`;

    // Preload the image, then show it and advance
    const img = new Image();
    img.onload = () => {
        if (!playing) return;
        currentIndex = nextIdx;
        frameImage.src = src;
        frameImage.classList.add("visible");
        noFrames.classList.add("hidden");
        updateTimeDisplay(nextIdx);
        syncSlider(nextIdx);
        updateFilmCursor(nextIdx);
        const dt = new Date(frame.captured_at * 1000);
        const sizeKb = frame.file_size ? `${Math.round(frame.file_size / 1024)}KB` : "";
        frameInfo.textContent = `${dt.toLocaleTimeString()} | ${sizeKb} | ${nextIdx + 1}/${currentFrames.length}`;

        setTimeout(playNext, 50);
    };
    img.onerror = () => {
        if (!playing) return;
        // Skip broken frame
        currentIndex = nextIdx;
        setTimeout(playNext, 50);
    };
    img.src = src;
}

// --- Status ---

function setPill(el, text, level) {
    el.textContent = text;
    el.className = "pill" + (level ? " " + level : "");
}

function fmtRate(kbps) {
    return kbps > 1024 ? `${(kbps / 1024).toFixed(1)} Mb` : `${Math.round(kbps)} kb`;
}

async function loadStatus() {
    try {
        const res = await fetch("/api/status");
        const data = await res.json();

        if (data.capture.running) {
            const fpsLabel = data.capture_fps >= 1
                ? `${data.capture_fps} fps`
                : `1/${Math.round(1 / data.capture_fps)}s`;
            statConnection.innerHTML = `<span class="dot"></span> ${fpsLabel}`;
            statConnection.className = "pill ok";
            syncFpsDropdown(data.capture_fps);
        } else {
            statConnection.innerHTML = '<span class="dot"></span> Offline';
            statConnection.className = "pill offline";
        }

        if (data.cpu_percent != null) {
            const lv = data.cpu_percent > 90 ? "crit" : data.cpu_percent > 70 ? "warn" : "";
            setPill(statCpu, `CPU ${data.cpu_percent}%`, lv);
        }
        if (data.cpu_temp != null) {
            const lv = data.cpu_temp > 75 ? "crit" : data.cpu_temp > 65 ? "warn" : "";
            setPill(statTemp, `${data.cpu_temp.toFixed(0)}\u00b0C`, lv);
        }
        if (data.mem_used_mb != null && data.mem_total_mb != null) {
            const pct = Math.round(data.mem_used_mb / data.mem_total_mb * 100);
            const lv = pct > 90 ? "crit" : pct > 75 ? "warn" : "";
            setPill(statRam, `RAM ${pct}%`, lv);
        }
        if (data.net_tx_kbps != null) {
            setPill(statNet, `\u2191${fmtRate(data.net_tx_kbps)} \u2193${fmtRate(data.net_rx_kbps)}`, "");
        }

        // Throttle
        const tEl = document.getElementById("stat-throttle");
        if (data.throttled != null && data.throttled !== 0) {
            const t = data.throttled;
            const parts = [];
            if (t & 0x1) parts.push("\u26a1Under-voltage");
            if (t & 0x4) parts.push("Throttled now");
            if (t & 0x2) parts.push("Capped now");
            if ((t & 0x10000) && !(t & 0x1)) parts.push("\u26a1prev");
            if ((t & 0x40000) && !(t & 0x4)) parts.push("Throttled prev");
            if ((t & 0x20000) && !(t & 0x2)) parts.push("Capped prev");
            const hasNow = t & 0x7;
            tEl.textContent = parts.join(" | ");
            tEl.className = `pill ${hasNow ? "crit" : "warn"}`;
        } else {
            tEl.className = "pill hidden";
        }

        const diskGb = (data.disk_free_mb / 1024).toFixed(1);
        const diskLv = data.disk_free_mb < 2048 ? "crit" : data.disk_free_mb < 5120 ? "warn" : "";
        setPill(statDisk, `${diskGb} GB`, diskLv);
        setPill(statFrames, `${data.total_frames}`, "");

    } catch (e) {
        statConnection.innerHTML = '<span class="dot"></span> Disconnected';
        statConnection.className = "pill offline";
    }
}

// --- FPS Control ---

async function onFpsChange() {
    const fps = parseFloat(fpsSelect.value);
    fpsStatus.textContent = "Applying...";
    try {
        const res = await fetch(`/api/capture-fps?fps=${fps}`, { method: "POST" });
        if (res.ok) {
            fpsStatus.textContent = "OK";
            setTimeout(() => { fpsStatus.textContent = ""; }, 2000);
        } else {
            fpsStatus.textContent = "Error";
        }
    } catch (e) {
        fpsStatus.textContent = "Failed";
    }
}

function syncFpsDropdown(fps) {
    const options = Array.from(fpsSelect.options);
    let best = options[0];
    let bestDiff = Infinity;
    for (const opt of options) {
        const diff = Math.abs(parseFloat(opt.value) - fps);
        if (diff < bestDiff) { bestDiff = diff; best = opt; }
    }
    fpsSelect.value = best.value;
}

// --- Camera Controls ---

let cameraDebounce = null;

function initCameraControls() {
    // Segmented controls
    document.querySelectorAll(".seg-control").forEach(ctrl => {
        ctrl.querySelectorAll("button").forEach(btn => {
            btn.addEventListener("click", () => {
                ctrl.querySelectorAll("button").forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                onSegChange(ctrl.id, btn.dataset.val);
            });
        });
    });

    // EV slider
    const evSlider = document.getElementById("ev-slider");
    const evValue = document.getElementById("ev-value");
    evSlider.addEventListener("input", () => {
        const v = parseFloat(evSlider.value);
        evValue.textContent = v > 0 ? `+${v}` : `${v}`;
        debouncedCamera({ ev: v });
    });

    // Brightness
    const brSlider = document.getElementById("brightness-slider");
    const brValue = document.getElementById("brightness-value");
    brSlider.addEventListener("input", () => {
        brValue.textContent = parseFloat(brSlider.value).toFixed(2);
        debouncedCamera({ brightness: parseFloat(brSlider.value) });
    });

    // Contrast
    const ctSlider = document.getElementById("contrast-slider");
    const ctValue = document.getElementById("contrast-value");
    ctSlider.addEventListener("input", () => {
        ctValue.textContent = parseFloat(ctSlider.value).toFixed(1);
        debouncedCamera({ contrast: parseFloat(ctSlider.value) });
    });

    // Saturation
    const satSlider = document.getElementById("saturation-slider");
    const satValue = document.getElementById("saturation-value");
    satSlider.addEventListener("input", () => {
        satValue.textContent = parseFloat(satSlider.value).toFixed(1);
        debouncedCamera({ saturation: parseFloat(satSlider.value) });
    });

}

function onSegChange(controlId, value) {
    if (controlId === "metering-mode") {
        sendCamera({ metering: value });
    }
}

function debouncedCamera(settings) {
    clearTimeout(cameraDebounce);
    cameraDebounce = setTimeout(() => sendCamera(settings), 300);
}

async function sendCamera(settings) {
    try {
        await fetch("/api/camera", {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(settings),
        });
    } catch (e) {
        console.error("Camera setting failed:", e);
    }
}

async function loadCameraSettings() {
    try {
        const res = await fetch("/api/camera");
        const data = await res.json();
        if (data.error) return;

        // AF mode
        // Metering
        const metBtns = document.querySelectorAll("#metering-mode button");
        metBtns.forEach(b => b.classList.toggle("active", b.dataset.val === data.metering));

        // EV
        if (data.ev != null) {
            document.getElementById("ev-slider").value = data.ev;
            document.getElementById("ev-value").textContent = data.ev > 0 ? `+${data.ev}` : `${data.ev}`;
        }

        // Image adjustments
        if (data.brightness != null) {
            document.getElementById("brightness-slider").value = data.brightness;
            document.getElementById("brightness-value").textContent = data.brightness.toFixed(2);
        }
        if (data.contrast != null) {
            document.getElementById("contrast-slider").value = data.contrast;
            document.getElementById("contrast-value").textContent = data.contrast.toFixed(1);
        }
        if (data.saturation != null) {
            document.getElementById("saturation-slider").value = data.saturation;
            document.getElementById("saturation-value").textContent = data.saturation.toFixed(1);
        }
    } catch (e) {
        console.error("Failed to load camera settings:", e);
    }
}

// --- Reset ---

async function resetCameraDefaults() {
    await sendCamera({
        ev: 0,
        metering: "centre",
        brightness: 0,
        contrast: 1,
        saturation: 1,
    });
    await loadCameraSettings();
}

// --- Auto-refresh ---

async function pollNewFrames() {
    const today = localDateStr();
    if (datePicker.value !== today) return;
    if (playing) return; // don't interrupt playback

    try {
        const sampleRate = Math.max(1, Math.ceil(totalFrameCount / 1000));
        const res = await fetch(
            `/api/frames?start=${currentDayStart}&end=${currentDayEnd}&limit=2000&sample=${sampleRate}`
        );
        const data = await res.json();
        if (data.total === totalFrameCount) return;

        const wasAtEnd = currentIndex >= currentFrames.length - 2; // within last 2
        const oldLen = currentFrames.length;
        currentFrames = data.frames;
        totalFrameCount = data.total;
        frameCount.textContent = `${totalFrameCount}`;

        // Update slider range
        const newMax = Math.max(1, currentFrames.length - 1);
        if (scrubSlider) {
            scrubUpdating = true;
            scrubSlider.updateOptions({ range: { min: 0, max: newMax } });
            scrubUpdating = false;
        }

        // Update time labels
        if (currentFrames.length > 0) {
            document.getElementById("time-start").textContent =
                fmtTime(new Date(currentFrames[0].captured_at * 1000));
            document.getElementById("time-end").textContent =
                fmtTime(new Date(currentFrames[currentFrames.length - 1].captured_at * 1000));
        }

        // If user was at the latest frame, follow new frames
        if (wasAtEnd || oldLen === 0) {
            showFrame(currentFrames.length - 1);
            rebuildFilmstrip(currentIndex);
        }
    } catch (e) { /* ignore */ }
}

// --- Start ---
document.addEventListener("DOMContentLoaded", init);
