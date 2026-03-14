/* Pi Webcam — Frontend */

const slider = document.getElementById("time-slider");
const timeDisplay = document.getElementById("time-display");
const frameImage = document.getElementById("frame-image");
const frameInfo = document.getElementById("frame-info");
const noFrames = document.getElementById("no-frames");
const frameCount = document.getElementById("frame-count");
const datePicker = document.getElementById("date-picker");
const statusEl = document.getElementById("status");
const streamError = document.getElementById("stream-error");
const liveVideo = document.getElementById("live-video");
const btnPrev = document.getElementById("btn-prev");
const btnNext = document.getElementById("btn-next");
const btnPlay = document.getElementById("btn-play");

let currentFrames = [];
let currentIndex = -1;
let playInterval = null;
let debounceTimer = null;

// --- Initialization ---

function init() {
    const today = new Date().toISOString().split("T")[0];
    datePicker.value = today;

    datePicker.addEventListener("change", () => loadDay(datePicker.value));
    slider.addEventListener("input", onSliderInput);
    slider.addEventListener("change", onSliderChange);
    btnPrev.addEventListener("click", () => stepFrame(-1));
    btnNext.addEventListener("click", () => stepFrame(1));
    btnPlay.addEventListener("click", togglePlay);

    document.addEventListener("keydown", (e) => {
        if (e.key === "ArrowLeft") stepFrame(-1);
        else if (e.key === "ArrowRight") stepFrame(1);
        else if (e.key === " ") { e.preventDefault(); togglePlay(); }
    });

    loadDay(today);
    loadStatus();
    initStream();
    setInterval(loadStatus, 10000);
    setInterval(pollNewFrames, 5000);
}

// --- Live Stream ---

async function initStream() {
    streamError.classList.add("hidden");
    try {
        // Try WebRTC first
        const res = await fetch(WEBRTC_URL + "/whep", { method: "POST", headers: { "Content-Type": "application/sdp" },
            body: await createOffer() });
        if (res.ok) {
            const answer = await res.text();
            await setAnswer(answer);
            return;
        }
    } catch (e) {
        console.warn("WebRTC failed, trying HLS:", e);
    }

    // Fallback to HLS
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

    pc.ontrack = (e) => {
        liveVideo.srcObject = e.streams[0];
    };

    pc.oniceconnectionstatechange = () => {
        if (pc.iceConnectionState === "failed" || pc.iceConnectionState === "disconnected") {
            streamError.classList.remove("hidden");
        }
    };

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    // Wait for ICE gathering
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

// --- Timeline ---

async function loadDay(dateStr) {
    const dayStart = new Date(dateStr + "T00:00:00Z").getTime() / 1000;
    const dayEnd = dayStart + 86399;

    try {
        const res = await fetch(`/api/frames?start=${dayStart}&end=${dayEnd}&limit=1000`);
        const data = await res.json();
        currentFrames = data.frames;
        frameCount.textContent = `${data.total} frames`;

        if (currentFrames.length === 0) {
            noFrames.classList.remove("hidden");
            frameImage.classList.remove("visible");
            frameInfo.textContent = "";
            slider.disabled = true;
            return;
        }

        noFrames.classList.add("hidden");
        slider.disabled = false;
        slider.max = currentFrames.length - 1;
        slider.value = currentFrames.length - 1;
        showFrame(currentFrames.length - 1);

        // Load more if needed
        if (data.has_more) {
            await loadAllFrames(dayStart, dayEnd, data.total);
        }
    } catch (e) {
        console.error("Failed to load frames:", e);
    }
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
    slider.max = currentFrames.length - 1;
    frameCount.textContent = `${currentFrames.length} frames`;
}

function onSliderInput() {
    clearTimeout(debounceTimer);
    const idx = parseInt(slider.value);
    updateTimeDisplay(idx);

    debounceTimer = setTimeout(() => {
        showThumbnail(idx);
    }, 100);
}

function onSliderChange() {
    clearTimeout(debounceTimer);
    const idx = parseInt(slider.value);
    showFrame(idx);
}

function showFrame(idx) {
    if (idx < 0 || idx >= currentFrames.length) return;
    currentIndex = idx;
    slider.value = idx;
    const frame = currentFrames[idx];
    updateTimeDisplay(idx);

    frameImage.src = `/images/${frame.file_path}`;
    frameImage.classList.add("visible");
    frameImage.onerror = () => {
        // Try thumbnail as fallback
        if (frame.thumb_path) {
            frameImage.src = `/thumbs/${frame.thumb_path}`;
        }
    };

    const dt = new Date(frame.captured_at * 1000);
    const sizeKb = frame.file_size ? `${Math.round(frame.file_size / 1024)} KB` : "";
    frameInfo.textContent = `${dt.toLocaleString()} | ${sizeKb} | Frame ${idx + 1}/${currentFrames.length}`;
}

function showThumbnail(idx) {
    if (idx < 0 || idx >= currentFrames.length) return;
    currentIndex = idx;
    const frame = currentFrames[idx];

    const src = frame.thumb_path ? `/thumbs/${frame.thumb_path}` : `/images/${frame.file_path}`;
    frameImage.src = src;
    frameImage.classList.add("visible");
    noFrames.classList.add("hidden");
}

function updateTimeDisplay(idx) {
    if (idx < 0 || idx >= currentFrames.length) return;
    const frame = currentFrames[idx];
    const dt = new Date(frame.captured_at * 1000);
    timeDisplay.textContent = dt.toTimeString().split(" ")[0];
}

function stepFrame(delta) {
    const newIdx = currentIndex + delta;
    if (newIdx >= 0 && newIdx < currentFrames.length) {
        showFrame(newIdx);
    }
}

function togglePlay() {
    if (playInterval) {
        clearInterval(playInterval);
        playInterval = null;
        btnPlay.textContent = "Play";
    } else {
        btnPlay.textContent = "Pause";
        playInterval = setInterval(() => {
            if (currentIndex >= currentFrames.length - 1) {
                togglePlay();
                return;
            }
            stepFrame(1);
        }, 200);
    }
}

// --- Status ---

async function loadStatus() {
    try {
        const res = await fetch("/api/status");
        const data = await res.json();

        if (data.capture.running) {
            const fpsLabel = data.capture_fps >= 1
                ? `${data.capture_fps} fps`
                : `1 frame/${Math.round(1 / data.capture_fps)}s`;
            const diskGb = (data.disk_free_mb / 1024).toFixed(1);
            statusEl.textContent = `Online | ${fpsLabel} | ${data.total_frames} frames | ${diskGb} GB free`;
            statusEl.className = "status online";
        } else {
            statusEl.textContent = "Capture stopped";
            statusEl.className = "status error";
        }
    } catch (e) {
        statusEl.textContent = "Disconnected";
        statusEl.className = "status error";
    }
}

// --- Auto-refresh ---

async function pollNewFrames() {
    // Only poll if viewing today
    const today = new Date().toISOString().split("T")[0];
    if (datePicker.value !== today) return;

    const dayStart = new Date(today + "T00:00:00Z").getTime() / 1000;
    const dayEnd = dayStart + 86399;

    try {
        const res = await fetch(`/api/frames?start=${dayStart}&end=${dayEnd}&limit=1000`);
        const data = await res.json();

        if (data.total === currentFrames.length) return;

        // New frames arrived
        const wasAtEnd = currentIndex >= currentFrames.length - 1;
        currentFrames = data.frames;

        // Load remaining pages if needed
        if (data.has_more) {
            await loadAllFrames(dayStart, dayEnd, data.total);
        }

        frameCount.textContent = `${currentFrames.length} frames`;
        slider.max = currentFrames.length - 1;

        // If user was at the latest frame, follow the new ones
        if (wasAtEnd) {
            showFrame(currentFrames.length - 1);
        }
    } catch (e) {
        // Silently ignore poll errors
    }
}

// --- Days ---

async function loadDays() {
    try {
        const res = await fetch("/api/days");
        const days = await res.json();
        if (days.length > 0 && !datePicker.value) {
            datePicker.value = days[0];
            loadDay(days[0]);
        }
    } catch (e) {
        console.error("Failed to load days:", e);
    }
}

// --- Start ---
document.addEventListener("DOMContentLoaded", init);
