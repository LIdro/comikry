/**
 * Comikry — main viewer module.
 *
 * Responsibilities:
 *  - Upload screen: file selection → POST /comics
 *  - Progress screen: poll GET /comics/{id}/status until done
 *  - Player screen: render panels, sync bubble highlights, play audio
 *  - Shareable URL: load from /play/{token} on page load
 */

const API = "";          // empty = same origin
const POLL_MS = 1500;    // status poll interval

// ── Safe fetch helpers ────────────────────────────────────────────────────────
// Every API call goes through apiGet / apiPost so that:
//   • Non-2xx responses throw with a readable message instead of crashing in .json()
//   • Tunnel auth-pages (HTML instead of JSON) are caught and reported clearly
//   • Network failures show a useful message

async function apiGet(path) {
  let res;
  try {
    res = await fetch(`${API}${path}`, {
      headers: { "Accept": "application/json" },
    });
  } catch (err) {
    throw new Error(`Network error on GET ${path}: ${err.message}`);
  }
  return _parseJsonResponse(res, "GET", path);
}

async function apiPost(url, body, extraHeaders = {}) {
  let res;
  try {
    res = await fetch(url, {
      method: "POST",
      body,
      headers: { "Accept": "application/json", ...extraHeaders },
    });
  } catch (err) {
    throw new Error(`Network error on POST ${url}: ${err.message}`);
  }
  return _parseJsonResponse(res, "POST", url);
}

async function _parseJsonResponse(res, method, url) {
  const contentType = res.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    // Tunnel returned an HTML page (auth wall, rate limit, etc.)
    const preview = (await res.text().catch(() => "")).slice(0, 200);
    throw new Error(
      `Server returned non-JSON (${res.status}) for ${method} ${url}.\n` +
      `Content-Type: ${contentType}\n` +
      `Body preview: ${preview || "(empty)"}\n\n` +
      `If you are using a Colab tunnel, open the tunnel URL directly in a new tab first ` +
      `to dismiss any auth warning, then return here and refresh.`
    );
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(
      `HTTP ${res.status} on ${method} ${url}: ${body.detail ?? res.statusText}`
    );
  }
  return res.json();
}

// ── DOM refs ─────────────────────────────────────────────────────────────────
const uploadScreen   = document.getElementById("upload-screen");
const rangeScreen    = document.getElementById("range-screen");
const progressScreen = document.getElementById("progress-screen");
const playerScreen   = document.getElementById("player-screen");

const pdfInput       = document.getElementById("pdf-input");
const uploadLabel    = document.querySelector(".upload-label");
const normaliseToggle= document.getElementById("normalise-toggle");
const uploadBtn      = document.getElementById("upload-btn");

const rangeTotal     = document.getElementById("range-total");
const rangeStart     = document.getElementById("range-start");
const rangeEnd       = document.getElementById("range-end");
const rangeAll       = document.getElementById("range-all");
const rangeBtn       = document.getElementById("range-btn");

const stageLabel     = document.getElementById("stage-label");
const progressFill   = document.getElementById("progress-fill");
const progressPct    = document.getElementById("progress-pct");

const panelImg       = document.getElementById("panel-img");
const bubbleOverlay  = document.getElementById("bubble-overlay");
const overlayCtx     = bubbleOverlay.getContext("2d");

const btnPrev        = document.getElementById("btn-prev");
const btnPlay        = document.getElementById("btn-play");
const btnNext        = document.getElementById("btn-next");
const voiceVol       = document.getElementById("voice-vol");
const sfxVol         = document.getElementById("sfx-vol");
const speedSelect    = document.getElementById("speed-select");
const langSelect     = document.getElementById("lang-select");
const btnShare       = document.getElementById("btn-share");

// ── Shared state ──────────────────────────────────────────────────────────────
let _pendingFile  = null;   // File held between upload and range screens
let _totalPages   = 1;

// ── Playback state ────────────────────────────────────────────────────────────
let manifest = null;          // full Comic JSON from /manifest
let pageIdx  = 0;
let panelIdx = 0;
let bubbleIdx= 0;
let playing  = false;
let voiceAudio = null;
let sfxAudio   = null;

const STAGE_LABELS = {
  queued:               "Preparing…",
  pdf_to_images:        "Rendering pages…",
  panel_detection:      "Detecting panels…",
  bubble_ocr:           "Extracting text…",
  speaker_attribution:  "Identifying speakers…",
  voice_assignment:     "Assigning voices…",
  tts_generation:       "Generating voices…",
  sfx_generation:       "Generating sound effects…",
  normalization:        "Normalising images…",
  done:                 "Ready!",
  failed:               "Processing failed.",
};

// ── Error display ─────────────────────────────────────────────────────────────
function showError(err) {
  console.error(err);
  stageLabel.textContent = "Error — see details below";
  progressFill.style.width = "0%";
  progressPct.textContent = "";

  // Reuse the progress card to show the error message
  let detail = document.getElementById("error-detail");
  if (!detail) {
    detail = document.createElement("pre");
    detail.id = "error-detail";
    detail.style.cssText =
      "margin:12px 0 0;padding:10px;background:#1a0a0a;color:#f87171;" +
      "border-radius:6px;font-size:12px;white-space:pre-wrap;word-break:break-word;" +
      "max-height:200px;overflow-y:auto;text-align:left";
    document.querySelector(".progress-card").appendChild(detail);
  }
  detail.textContent = err.message ?? String(err);
  showScreen(progressScreen);
}

// ── Screen helpers ────────────────────────────────────────────────────────────
function showScreen(screen) {
  [uploadScreen, rangeScreen, progressScreen, playerScreen].forEach(s =>
    s.classList.toggle("active", s === screen)
  );
}

// ── Upload flow ───────────────────────────────────────────────────────────────
pdfInput.addEventListener("change", () => {
  if (pdfInput.files.length) {
    uploadLabel.classList.add("has-file");
    uploadLabel.querySelector("span").textContent = pdfInput.files[0].name;
    uploadBtn.disabled = false;
  }
});

uploadLabel.addEventListener("dragover", e => { e.preventDefault(); uploadLabel.style.borderColor = "#5b9cf6"; });
uploadLabel.addEventListener("dragleave", () => { uploadLabel.style.borderColor = ""; });
uploadLabel.addEventListener("drop", e => {
  e.preventDefault();
  uploadLabel.style.borderColor = "";
  const file = e.dataTransfer.files[0];
  if (file?.type === "application/pdf") {
    const dt = new DataTransfer();
    dt.items.add(file);
    pdfInput.files = dt.files;
    pdfInput.dispatchEvent(new Event("change"));
  }
});

// Step 1: "Open Comic" → call /pdf/info to get page count → show range screen
uploadBtn.addEventListener("click", async () => {
  const file = pdfInput.files[0];
  if (!file) return;

  uploadBtn.disabled = true;
  uploadBtn.textContent = "Reading PDF…";

  try {
    const formData = new FormData();
    formData.append("file", file);
    const info = await apiPost(`${API}/pdf/info`, formData);

    _pendingFile  = file;
    _totalPages   = info.page_count ?? 1;

    // Populate range inputs
    rangeTotal.textContent = `${_totalPages} page${_totalPages !== 1 ? "s" : ""} detected in ${info.filename ?? file.name}`;
    rangeStart.min = 1;
    rangeStart.max = _totalPages;
    rangeStart.value = 1;
    rangeEnd.min   = 1;
    rangeEnd.max   = _totalPages;
    rangeEnd.value = _totalPages;
    rangeAll.checked = true;
    rangeStart.disabled = true;
    rangeEnd.disabled   = true;

    showScreen(rangeScreen);
  } catch (err) {
    uploadBtn.disabled = false;
    uploadBtn.textContent = "Open Comic";
    showError(err);
  }
});

// ── Range screen ──────────────────────────────────────────────────────────────
rangeAll.addEventListener("change", () => {
  rangeStart.disabled = rangeAll.checked;
  rangeEnd.disabled   = rangeAll.checked;
  if (rangeAll.checked) {
    rangeStart.value = 1;
    rangeEnd.value   = _totalPages;
  }
});

// Clamp values when user types
rangeStart.addEventListener("change", () => {
  let v = Math.max(1, Math.min(parseInt(rangeStart.value) || 1, _totalPages));
  if (v > parseInt(rangeEnd.value)) v = parseInt(rangeEnd.value);
  rangeStart.value = v;
});
rangeEnd.addEventListener("change", () => {
  let v = Math.max(1, Math.min(parseInt(rangeEnd.value) || _totalPages, _totalPages));
  if (v < parseInt(rangeStart.value)) v = parseInt(rangeStart.value);
  rangeEnd.value = v;
});

// Step 2: "Start Processing" → POST /comics with page_start / page_end
rangeBtn.addEventListener("click", async () => {
  if (!_pendingFile) return;

  const pageStart = parseInt(rangeStart.value);
  const pageEnd   = parseInt(rangeEnd.value);
  const processAll = rangeAll.checked;

  const formData = new FormData();
  formData.append("file", _pendingFile);

  const url = new URL(`${API}/comics`, location.href);
  if (normaliseToggle.checked) url.searchParams.set("normalization", "true");
  if (!processAll) {
    url.searchParams.set("page_start", pageStart);
    url.searchParams.set("page_end",   pageEnd);
  }

  rangeBtn.disabled = true;
  uploadBtn.disabled = false;
  uploadBtn.textContent = "Open Comic";
  showScreen(progressScreen);

  try {
    const data = await apiPost(url.toString(), formData);
    if (data.cached && data.stage === "done") {
      await loadAndPlay(data.comic_id);
    } else {
      pollStatus(data.comic_id);
    }
  } catch (err) {
    rangeBtn.disabled = false;
    showError(err);
  }
});

// ── Status polling ────────────────────────────────────────────────────────────
function pollStatus(comicId) {
  const interval = setInterval(async () => {
    let data;
    try {
      data = await apiGet(`/comics/${comicId}/status`);
    } catch (err) {
      clearInterval(interval);
      showError(err);
      return;
    }

    stageLabel.textContent = STAGE_LABELS[data.stage] ?? data.stage;
    progressFill.style.width = `${data.progress_pct}%`;
    progressPct.textContent  = `${data.progress_pct} %`;

    if (data.stage === "done") {
      clearInterval(interval);
      try {
        await loadAndPlay(comicId);
      } catch (err) {
        showError(err);
      }
    } else if (data.stage === "failed") {
      clearInterval(interval);
      showError(new Error(`Pipeline failed: ${data.error ?? "unknown error"}`));
    }
  }, POLL_MS);
}

// ── Load manifest and start playback ─────────────────────────────────────────
async function loadAndPlay(comicId) {
  const manifest_data = await apiGet(`/comics/${comicId}/manifest`);
  manifest = manifest_data;

  // Populate language selector
  langSelect.innerHTML = "";
  for (const lang of manifest.available_languages ?? ["en"]) {
    const opt = document.createElement("option");
    opt.value = lang;
    opt.textContent = lang.toUpperCase();
    langSelect.appendChild(opt);
  }

  pageIdx = panelIdx = bubbleIdx = 0;
  showScreen(playerScreen);
  renderPanel();
}

// ── Panel rendering ───────────────────────────────────────────────────────────
function currentPanel() {
  return manifest?.pages?.[pageIdx]?.panels?.[panelIdx] ?? null;
}

function renderPanel() {
  const panel = currentPanel();
  if (!panel) return;

  const imgSrc = panel.normalized_image_path || panel.image_path;
  panelImg.src = `${API}/storage/${encodeURIPath(imgSrc)}`;
  panelImg.onload = () => {
    resizeOverlay();
    clearHighlight();
    loadPanelAudio(panel);
    if (playing) playBubble();
  };
}

function encodeURIPath(p) {
  return p.split("/").map(encodeURIComponent).join("/");
}

function resizeOverlay() {
  bubbleOverlay.width  = panelImg.naturalWidth;
  bubbleOverlay.height = panelImg.naturalHeight;
  bubbleOverlay.style.width  = panelImg.offsetWidth  + "px";
  bubbleOverlay.style.height = panelImg.offsetHeight + "px";
}

// ── Bubble highlight ──────────────────────────────────────────────────────────
function clearHighlight() {
  overlayCtx.clearRect(0, 0, bubbleOverlay.width, bubbleOverlay.height);
}

function drawHighlight(bubble) {
  clearHighlight();
  if (!bubble?.bbox) return;
  const { x, y, w, h } = bubble.bbox;
  const scaleX = panelImg.offsetWidth  / panelImg.naturalWidth;
  const scaleY = panelImg.offsetHeight / panelImg.naturalHeight;

  overlayCtx.save();
  overlayCtx.scale(scaleX, scaleY);
  overlayCtx.strokeStyle = "#5b9cf6";
  overlayCtx.lineWidth   = 3 / scaleX;
  overlayCtx.shadowColor = "#5b9cf6";
  overlayCtx.shadowBlur  = 8;
  overlayCtx.strokeRect(x, y, w, h);
  overlayCtx.restore();
}

// ── Audio ─────────────────────────────────────────────────────────────────────
function loadPanelAudio(panel) {
  if (sfxAudio) { sfxAudio.pause(); sfxAudio = null; }
  if (panel.sfx_audio_path) {
    sfxAudio = new Audio(`${API}/storage/${encodeURIPath(panel.sfx_audio_path)}`);
    sfxAudio.loop   = true;
    sfxAudio.volume = parseFloat(sfxVol.value);
  }
}

function playBubble() {
  const panel = currentPanel();
  if (!panel) return;

  const bubble = panel.bubbles?.[bubbleIdx];
  if (!bubble) {
    advancePanel();
    return;
  }

  drawHighlight(bubble);

  if (!bubble.tts_audio_path) {
    // No audio for this bubble — advance immediately
    bubbleIdx++;
    playBubble();
    return;
  }

  if (voiceAudio) { voiceAudio.pause(); voiceAudio = null; }

  voiceAudio = new Audio(`${API}/storage/${encodeURIPath(bubble.tts_audio_path)}`);
  voiceAudio.playbackRate = parseFloat(speedSelect.value);
  voiceAudio.volume       = parseFloat(voiceVol.value);

  voiceAudio.addEventListener("ended", () => {
    bubbleIdx++;
    if (bubbleIdx < (panel.bubbles?.length ?? 0)) {
      playBubble();
    } else {
      advancePanel();
    }
  });

  if (sfxAudio && sfxAudio.paused) sfxAudio.play();
  voiceAudio.play();
}

function advancePanel() {
  clearHighlight();
  if (sfxAudio) { sfxAudio.pause(); sfxAudio = null; }
  bubbleIdx = 0;

  const page = manifest.pages[pageIdx];
  if (panelIdx + 1 < page.panels.length) {
    panelIdx++;
  } else if (pageIdx + 1 < manifest.pages.length) {
    pageIdx++;
    panelIdx = 0;
  } else {
    // End of comic
    playing = false;
    btnPlay.innerHTML = "&#9654;";
    return;
  }
  renderPanel();
  if (playing) playBubble();
}

// ── Controls ──────────────────────────────────────────────────────────────────
btnPlay.addEventListener("click", togglePlay);

function togglePlay() {
  playing = !playing;
  btnPlay.innerHTML = playing ? "&#9646;&#9646;" : "&#9654;";
  if (playing) {
    playBubble();
  } else {
    voiceAudio?.pause();
    sfxAudio?.pause();
  }
}

btnPrev.addEventListener("click", () => {
  voiceAudio?.pause();
  bubbleIdx = 0;
  if (panelIdx > 0) {
    panelIdx--;
  } else if (pageIdx > 0) {
    pageIdx--;
    panelIdx = manifest.pages[pageIdx].panels.length - 1;
  }
  renderPanel();
});

btnNext.addEventListener("click", () => {
  voiceAudio?.pause();
  advancePanel();
});

voiceVol.addEventListener("input", () => { if (voiceAudio) voiceAudio.volume = parseFloat(voiceVol.value); });
sfxVol.addEventListener("input",   () => { if (sfxAudio)   sfxAudio.volume   = parseFloat(sfxVol.value); });
speedSelect.addEventListener("change", () => { if (voiceAudio) voiceAudio.playbackRate = parseFloat(speedSelect.value); });

// ── Keyboard shortcuts ────────────────────────────────────────────────────────
document.addEventListener("keydown", e => {
  if (!manifest) return;
  if (e.code === "Space")       { e.preventDefault(); togglePlay(); }
  if (e.code === "ArrowLeft")   btnPrev.click();
  if (e.code === "ArrowRight")  btnNext.click();
  if (e.key  === "[")           speedSelect.value = Math.max(0.75, parseFloat(speedSelect.value) - 0.25);
  if (e.key  === "]")           speedSelect.value = Math.min(1.5,  parseFloat(speedSelect.value) + 0.25);
});

// ── Share button ──────────────────────────────────────────────────────────────
btnShare.addEventListener("click", () => {
  navigator.clipboard.writeText(location.href).then(() => {
    btnShare.textContent = "✓ Copied!";
    setTimeout(() => { btnShare.innerHTML = "🔗 Share"; }, 2000);
  });
});

// ── Load from /play/{token} on page open ──────────────────────────────────────
(async () => {
  const match = location.pathname.match(/^\/play\/(.+)$/);
  if (match) {
    showScreen(progressScreen);
    stageLabel.textContent = "Loading…";
    try {
      // The backend redirects /play/{token} → /comics/{id}/manifest
      const res = await fetch(`/play/${match[1]}`, {
        redirect: "follow",
        headers: { "Accept": "application/json" },
      });
      const contentType = res.headers.get("content-type") ?? "";
      if (!res.ok || !contentType.includes("application/json")) {
        throw new Error(`Could not load comic (status ${res.status}). The link may be invalid or expired.`);
      }
      manifest = await res.json();
      pageIdx = panelIdx = bubbleIdx = 0;
      showScreen(playerScreen);
      renderPanel();
    } catch (err) {
      showError(err);
    }
  }
})();
