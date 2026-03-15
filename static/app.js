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
let playInterval = null;
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
    // Filmstrip drag is initialized when frames load

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

async function loadDay(dateStr) {
    const dayStart = new Date(dateStr + "T00:00:00").getTime() / 1000;
    const dayEnd = dayStart + 86399;

    try {
        const res = await fetch(`/api/frames?start=${dayStart}&end=${dayEnd}&limit=1000`);
        const data = await res.json();
        currentFrames = data.frames;
        frameCount.textContent = `${data.total}`;

        if (currentFrames.length === 0) {
            noFrames.classList.remove("hidden");
            frameImage.classList.remove("visible");
            frameInfo.textContent = "";
            // no frames
            document.getElementById("time-start").textContent = "--:--";
            document.getElementById("time-end").textContent = "--:--";
            document.getElementById("scrub-filmstrip").innerHTML = '<div id="scrub-cursor" class="scrub-cursor"></div>';
            return;
        }

        if (data.has_more) {
            await loadAllFrames(dayStart, dayEnd, data.total);
        }

        noFrames.classList.add("hidden");

        // Time range labels
        const tStart = new Date(currentFrames[0].captured_at * 1000);
        const tEnd = new Date(currentFrames[currentFrames.length - 1].captured_at * 1000);
        document.getElementById("time-start").textContent = fmtTime(tStart);
        document.getElementById("time-end").textContent = fmtTime(tEnd);

        buildFilmstrip();
        showFrame(currentFrames.length - 1);
    } catch (e) {
        console.error("Failed to load frames:", e);
    }
}

function fmtTime(d) {
    return `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`;
}

async function loadAllFrames(start, end, total) {
    let offset = currentFrames.length;
    while (offset < total) {
        const res = await fetch(`/api/frames?start=${start}&end=${end}&limit=1000&offset=${offset}`);
        const data = await res.json();
        currentFrames = currentFrames.concat(data.frames);
        offset += data.frames.length;
        if (!data.has_more) break;
    }
    frameCount.textContent = `${currentFrames.length}`;
}

// --- Scrub system ---

let scrubInited = false;

function buildFilmstrip() {
    const strip = document.getElementById("scrub-filmstrip");
    const cursor = document.getElementById("scrub-cursor");
    strip.innerHTML = "";
    strip.appendChild(cursor);

    if (currentFrames.length === 0) return;

    // Fill the strip width with evenly-spaced thumbnails
    const maxThumbs = 60;
    const step = Math.max(1, Math.floor(currentFrames.length / maxThumbs));

    for (let i = 0; i < currentFrames.length; i += step) {
        const frame = currentFrames[i];
        const div = document.createElement("div");
        div.className = "film-frame";

        const img = document.createElement("img");
        img.src = frame.thumb_path
            ? `/thumbs/${frame.thumb_path}`
            : `/images/${frame.file_path}`;
        img.loading = "lazy";
        img.draggable = false;
        div.appendChild(img);
        strip.appendChild(div);
    }

    updateScrubPosition(currentIndex);
    if (!scrubInited) {
        initScrubDrag();
        scrubInited = true;
    }
}

function updateScrubPosition(idx) {
    if (currentFrames.length <= 1) return;
    const pct = (idx / (currentFrames.length - 1)) * 100;
    document.getElementById("scrub-fill").style.width = pct + "%";
    document.getElementById("scrub-handle").style.left = pct + "%";
    document.getElementById("scrub-cursor").style.left = pct + "%";
}

function initScrubDrag() {
    const track = document.getElementById("scrub-track");
    const strip = document.getElementById("scrub-filmstrip");
    let dragging = false;

    function scrubToX(clientX) {
        if (currentFrames.length === 0) return;
        // Use the track rect for position calculation
        const rect = track.getBoundingClientRect();
        const pct = Math.max(0, Math.min(1,
            (clientX - rect.left) / rect.width
        ));
        const idx = Math.round(pct * (currentFrames.length - 1));
        if (idx !== currentIndex) showFrame(idx);
    }

    // Track + filmstrip both respond to drag
    function onDown(x) {
        dragging = true;
        scrubToX(x);
    }

    [track, strip].forEach(el => {
        el.addEventListener("mousedown", (e) => {
            e.preventDefault();
            onDown(e.clientX);
        });
        el.addEventListener("touchstart", (e) => {
            onDown(e.touches[0].clientX);
        }, { passive: true });
    });

    document.addEventListener("mousemove", (e) => {
        if (dragging) scrubToX(e.clientX);
    });
    document.addEventListener("touchmove", (e) => {
        if (dragging) {
            e.preventDefault();
            scrubToX(e.touches[0].clientX);
        }
    }, { passive: false });

    document.addEventListener("mouseup", () => { dragging = false; });
    document.addEventListener("touchend", () => { dragging = false; });
}

function showFrame(idx) {
    if (idx < 0 || idx >= currentFrames.length) return;
    currentIndex = idx;
    const frame = currentFrames[idx];
    updateTimeDisplay(idx);
    updateScrubPosition(idx);

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

function togglePlay() {
    if (playInterval) {
        clearInterval(playInterval);
        playInterval = null;
        btnPlay.textContent = "\u25B6";
    } else {
        btnPlay.textContent = "\u23F8";
        playInterval = setInterval(() => {
            if (currentIndex >= currentFrames.length - 1) { togglePlay(); return; }
            stepFrame(1);
        }, 200);
    }
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

    const dayStart = new Date(today + "T00:00:00").getTime() / 1000;
    const dayEnd = dayStart + 86399;

    try {
        const res = await fetch(`/api/frames?start=${dayStart}&end=${dayEnd}&limit=1000`);
        const data = await res.json();
        if (data.total === currentFrames.length) return;

        const wasAtEnd = currentIndex >= currentFrames.length - 1;
        currentFrames = data.frames;

        if (data.has_more) await loadAllFrames(dayStart, dayEnd, data.total);

        frameCount.textContent = `${currentFrames.length}`;

        if (wasAtEnd) showFrame(currentFrames.length - 1);
    } catch (e) { /* ignore */ }
}

// --- Start ---
document.addEventListener("DOMContentLoaded", init);
