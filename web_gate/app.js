const state = {
  sessionName: "",
  sampleRate: null,
  tracks: [],
  selectedTrackNames: new Set(),
  params: {},
  lastPlan: null,
  extracted: null,
};

const PARAM_FIELDS = [
  { key: "activityThreshold", label: "Threshold", min: 0.1, max: 0.95, step: 0.05, decimals: 2, unit: "" },
  { key: "dominanceMargin", label: "Winner Margin", min: 0, max: 0.5, step: 0.01, decimals: 2, unit: "" },
  { key: "fallbackMinScore", label: "Fallback Min Score", min: 0, max: 0.95, step: 0.05, decimals: 2, unit: "" },
  { key: "rmsGateDbfs", label: "Original RMS Min", min: -80, max: -25, step: 1, decimals: 0, unit: " dBFS" },
  { key: "offGapFillSeconds", label: "Off Gap Fill", min: 0, max: 5, step: 0.1, decimals: 1, unit: "s" },
  { key: "minOnSeconds", label: "Min On Duration", min: 0, max: 2, step: 0.1, decimals: 1, unit: "s" },
  { key: "preRollSeconds", label: "Pre-roll", min: 0, max: 1, step: 0.05, decimals: 2, unit: "s" },
  { key: "releaseSeconds", label: "Release", min: 0, max: 1, step: 0.05, decimals: 2, unit: "s" },
  { key: "chunkMinutes", label: "Chunk Size (0 = 전체)", min: 0, max: 60, step: 1, decimals: 0, unit: "min" },
];

const ADVANCED_PARAM_FIELDS = [
  { key: "noisePercentile", label: "Noise Percentile", min: 0, max: 50, step: 1, decimals: 0, unit: "" },
  { key: "activePercentile", label: "Active Percentile", min: 50, max: 100, step: 1, decimals: 0, unit: "" },
  { key: "minDynamicRangeDb", label: "Min Dynamic Range", min: 0, max: 40, step: 1, decimals: 0, unit: " dB" },
];

const EXTRACT_LOADING_MESSAGES = [
  "오디오 트랙 디코딩 중...",
  "RMS 활동도 프로파일 계산 중...",
  "청크 단위 정규화 적용 중...",
  "화자 우세 구간 판정 중...",
  "스무딩 및 세이프티넷 적용 중...",
  "게이트 구간 정리하는 중...",
];

const BUILD_PLAN_LOADING_MESSAGES = [
  "청크 단위 정규화 적용 중...",
  "화자 우세 구간 판정 중...",
  "게이트 구간 정리하는 중...",
];

const $ = (selector) => document.querySelector(selector);

const recognizeBtn = $("#recognizeBtn");
const extractBtn = $("#extractBtn");
const buildPlanBtn = $("#buildPlanBtn");
const buildPlanTestBtn = $("#buildPlanTestBtn");
const applyBtn = $("#applyBtn");
const sessionInfoEl = $("#sessionInfo");
const statusLineEl = $("#statusLine");
const mainContentEl = $("#mainContent");
const trackListEl = $("#trackList");
const paramGridEl = $("#paramGrid");
const advancedParamGridEl = $("#advancedParamGrid");
const resultsPanelEl = $("#resultsPanel");
const resultsListEl = $("#resultsList");
const analyzeLoadingPanelEl = $("#analyzeLoadingPanel");
const loadingMessageEl = $("#loadingMessage");
const loadingSubEl = $("#loadingSub");
const confirmModalEl = $("#confirmModal");
const confirmBodyEl = $("#confirmBody");
const confirmCancelEl = $("#confirmCancel");
const confirmOkEl = $("#confirmOk");

function setStatus(message, isError = false) {
  statusLineEl.textContent = message;
  statusLineEl.style.color = isError ? "var(--danger)" : "var(--accent)";
}

function formatSeconds(seconds) {
  const total = Math.round(seconds);
  const h = String(Math.floor(total / 3600)).padStart(2, "0");
  const m = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
  const s = String(total % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

let loadingTimer = null;

function setLoadingMessage(text) {
  loadingMessageEl.style.opacity = "0";
  setTimeout(() => {
    loadingMessageEl.textContent = text;
    loadingMessageEl.style.opacity = "1";
  }, 220);
}

function startLoading(trackCount, messages) {
  clearInterval(loadingTimer);
  const startedAt = Date.now();
  let tick = 0;
  analyzeLoadingPanelEl.hidden = false;
  resultsPanelEl.hidden = true;
  loadingMessageEl.style.opacity = "1";
  loadingMessageEl.textContent = messages[0];
  loadingSubEl.textContent = `트랙 ${trackCount}개 · 00:00 경과`;
  loadingTimer = setInterval(() => {
    tick += 1;
    const elapsed = Math.floor((Date.now() - startedAt) / 1000);
    loadingSubEl.textContent = `트랙 ${trackCount}개 · ${formatSeconds(elapsed)} 경과`;
    if (tick % 3 === 0) {
      setLoadingMessage(messages[(tick / 3) % messages.length]);
    }
  }, 1000);
}

function stopLoading() {
  clearInterval(loadingTimer);
  loadingTimer = null;
  analyzeLoadingPanelEl.hidden = true;
}

function buildParamField(field, container) {
  const wrap = document.createElement("div");
  wrap.className = "param-field";
  const label = document.createElement("label");
  label.textContent = field.label;
  const row = document.createElement("div");
  row.className = "param-row";
  const input = document.createElement("input");
  input.type = "range";
  input.min = String(field.min);
  input.max = String(field.max);
  input.step = String(field.step);
  input.id = `param-${field.key}`;
  const output = document.createElement("output");
  const sync = () => {
    output.textContent = `${Number(input.value).toFixed(field.decimals)}${field.unit}`;
    state.params[field.key] = Number(input.value);
  };
  input.addEventListener("input", sync);
  row.append(input, output);
  wrap.append(label, row);
  container.appendChild(wrap);
  return { input, sync };
}

function renderParamFields(defaultParams) {
  paramGridEl.innerHTML = "";
  advancedParamGridEl.innerHTML = "";
  state.params = { ...defaultParams };
  for (const field of PARAM_FIELDS) {
    const { input, sync } = buildParamField(field, paramGridEl);
    input.value = String(defaultParams[field.key]);
    sync();
  }
  for (const field of ADVANCED_PARAM_FIELDS) {
    const { input, sync } = buildParamField(field, advancedParamGridEl);
    input.value = String(defaultParams[field.key]);
    sync();
  }
}

function statusBadgeLabel(status) {
  return { ok: "OK", flagged: "여러 클립", empty: "클립 없음", offline: "오프라인", unsupported: "미지원" }[status] || status;
}

function renderTrackList(tracks) {
  trackListEl.innerHTML = "";
  let defaultSelected = false;
  for (const track of tracks) {
    const row = document.createElement("label");
    row.className = `track-row${track.selectable ? "" : " unsupported"}`;

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.disabled = !track.selectable;
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.selectedTrackNames.add(track.name);
      else state.selectedTrackNames.delete(track.name);
    });
    if (track.selectable && !defaultSelected) {
      checkbox.checked = true;
      state.selectedTrackNames.add(track.name);
      defaultSelected = true;
    }

    const name = document.createElement("span");
    name.className = "track-name";
    name.textContent = track.name;

    const meta = document.createElement("span");
    meta.className = "track-meta";
    meta.textContent = track.source.filePath
      ? `${track.source.filePath}${track.source.reason ? ` — ${track.source.reason}` : ""}`
      : track.source.reason || "";

    const badge = document.createElement("span");
    badge.className = `track-badge ${track.source.status}`;
    badge.textContent = statusBadgeLabel(track.source.status);

    row.append(checkbox, name, meta, badge);
    trackListEl.appendChild(row);
  }
}

async function recognizeTracks() {
  recognizeBtn.disabled = true;
  setStatus("Pro Tools 세션을 확인하는 중입니다...");
  try {
    const response = await fetch("./api/tracks");
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `요청 실패 (${response.status})`);

    state.sessionName = payload.sessionName;
    state.sampleRate = payload.sampleRate;
    state.tracks = payload.tracks;
    state.selectedTrackNames = new Set();
    state.extracted = null;
    buildPlanBtn.disabled = true;
    buildPlanTestBtn.disabled = true;

    sessionInfoEl.textContent = `세션: ${payload.sessionName} · ${payload.sampleRate} Hz · 트랙 ${payload.tracks.length}개`;
    renderTrackList(payload.tracks);
    renderParamFields(payload.defaultParams);
    mainContentEl.hidden = false;
    resultsPanelEl.hidden = true;
    setStatus("트랙을 선택하고 파라미터를 확인한 뒤 분석을 눌러주세요.");
  } catch (error) {
    setStatus(`Pro Tools 연결 실패: ${error.message}. Pro Tools가 실행 중이고 세션이 열려 있는지 확인해주세요.`, true);
  } finally {
    recognizeBtn.disabled = false;
  }
}

function drawMinimap(canvas, track, duration) {
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);

  const toX = (seconds) => (seconds / duration) * width;

  ctx.fillStyle = "rgba(227, 107, 93, 0.35)";
  for (const interval of track.mutedIntervals) {
    const x = toX(interval.start);
    const w = Math.max(1, toX(interval.end) - x);
    ctx.fillRect(x, 0, w, height);
  }
  ctx.fillStyle = "rgba(87, 193, 167, 0.35)";
  for (const interval of track.enabledIntervals) {
    const x = toX(interval.start);
    const w = Math.max(1, toX(interval.end) - x);
    ctx.fillRect(x, 0, w, height);
  }

  const { mins, maxs } = track.waveform;
  const mid = height / 2;
  ctx.strokeStyle = "#f2f0e8";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 0; i < mins.length; i += 1) {
    const x = (i / mins.length) * width;
    const yMin = mid - mins[i] * mid * 0.9;
    const yMax = mid - maxs[i] * mid * 0.9;
    ctx.moveTo(x, yMin);
    ctx.lineTo(x, yMax);
  }
  ctx.stroke();
}

function renderResults(plan) {
  resultsListEl.innerHTML = "";
  for (const name of Object.keys(plan.tracks)) {
    const track = plan.tracks[name];
    const row = document.createElement("div");
    row.className = "result-row";

    const header = document.createElement("div");
    header.className = "result-header";
    const nameEl = document.createElement("span");
    nameEl.className = "result-name";
    nameEl.textContent = name;
    const statsEl = document.createElement("span");
    statsEl.className = "result-stats";
    statsEl.textContent = `활성 ${formatSeconds(track.stats.enabledSeconds)} · 음소거 ${formatSeconds(track.stats.mutedSeconds)} · ${track.stats.mutedIntervalCount}개 구간`;
    header.append(nameEl, statsEl);

    const canvas = document.createElement("canvas");
    canvas.className = "minimap";
    canvas.width = 1200;
    canvas.height = 80;

    row.append(header, canvas);
    resultsListEl.appendChild(row);
    drawMinimap(canvas, track, plan.duration);
  }
  if (plan.skipped && plan.skipped.length) {
    const note = document.createElement("p");
    note.className = "result-stats";
    note.textContent = `건너뜀: ${plan.skipped.map((item) => `${item.name} (${item.reason})`).join(", ")}`;
    resultsListEl.appendChild(note);
  }
}

async function extractTracks() {
  const trackNames = Array.from(state.selectedTrackNames);
  if (trackNames.length === 0) {
    setStatus("추출할 트랙을 최소 하나 선택해주세요.", true);
    return;
  }
  extractBtn.disabled = true;
  buildPlanBtn.disabled = true;
  buildPlanTestBtn.disabled = true;
  resultsPanelEl.hidden = true;
  setStatus("");
  startLoading(trackNames.length, EXTRACT_LOADING_MESSAGES);
  try {
    const response = await fetch("./api/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ trackNames }),
    });
    const extracted = await response.json();
    if (!response.ok) throw new Error(extracted.error || `RMS 추출 실패 (${response.status})`);

    state.extracted = extracted;
    buildPlanBtn.disabled = false;
    buildPlanTestBtn.disabled = false;
    const skippedNote = extracted.skipped && extracted.skipped.length
      ? ` (건너뜀: ${extracted.skipped.map((item) => item.name).join(", ")})`
      : "";
    setStatus(`RMS 추출 완료 (${extracted.extractSeconds}s 소요)${skippedNote}. 파라미터를 조정한 뒤 "3. 파라미터 적용"을 눌러주세요.`);
  } catch (error) {
    setStatus(`RMS 추출 실패: ${error.message}`, true);
  } finally {
    stopLoading();
    extractBtn.disabled = false;
  }
}

async function buildPlan(overrides = {}) {
  if (!state.extracted) {
    setStatus("먼저 RMS를 추출해주세요.", true);
    return;
  }
  const trackNames = Object.keys(state.extracted.tracks);
  const params = { ...state.params, ...overrides };
  const isTest = params.rmsGateMode === "pre";
  buildPlanBtn.disabled = true;
  buildPlanTestBtn.disabled = true;
  setStatus("");
  startLoading(trackNames.length, BUILD_PLAN_LOADING_MESSAGES);
  try {
    const rmsByTrack = {};
    for (const name of trackNames) rmsByTrack[name] = state.extracted.tracks[name].rmsValues;

    const response = await fetch("./api/build-plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        trackNames,
        rmsByTrack,
        starts: state.extracted.starts,
        hopSeconds: state.extracted.hopSeconds,
        duration: state.extracted.duration,
        params,
      }),
    });
    const plan = await response.json();
    if (!response.ok) throw new Error(plan.error || `분석 실패 (${response.status})`);

    for (const name of trackNames) {
      const extractedTrack = state.extracted.tracks[name];
      plan.tracks[name].waveform = extractedTrack.waveform;
      plan.tracks[name].filePath = extractedTrack.filePath;
      plan.tracks[name].durationSeconds = extractedTrack.durationSeconds;
    }

    state.lastPlan = plan;
    renderResults(plan);
    resultsPanelEl.hidden = false;
    setStatus(
      isTest
        ? "테스트 분석 완료 (Original RMS Min을 정규화 이전에 적용해 무음 구간을 제외했습니다). Pro Tools 적용 전에 결과를 확인해주세요."
        : "분석 완료. Pro Tools 적용 전에 결과를 확인해주세요."
    );
  } catch (error) {
    setStatus(`분석 실패: ${error.message}`, true);
  } finally {
    stopLoading();
    buildPlanBtn.disabled = false;
    buildPlanTestBtn.disabled = false;
  }
}

function openConfirmModal() {
  if (!state.lastPlan) return;
  const names = Object.keys(state.lastPlan.tracks);
  confirmBodyEl.innerHTML = "";
  const intro = document.createElement("p");
  intro.textContent = "다음 트랙에 대해 디스포저블 대상 트랙을 만들고(이미 있으면 비우고) 게이트 구간대로 클립을 분리/음소거합니다:";
  const list = document.createElement("ul");
  for (const name of names) {
    const item = document.createElement("li");
    const stats = state.lastPlan.tracks[name].stats;
    item.textContent = `${name} → ${name}_APPA_GATE (${stats.mutedIntervalCount + stats.enabledIntervalCount}개 클립, ${stats.mutedIntervalCount}개 음소거)`;
    list.appendChild(item);
  }
  confirmBodyEl.append(intro, list);
  confirmModalEl.hidden = false;
}

async function applyToProTools() {
  confirmModalEl.hidden = true;
  applyBtn.disabled = true;
  const trackNames = Object.keys(state.lastPlan.tracks);
  setStatus(`${trackNames.length}개 트랙을 Pro Tools에 적용하는 중입니다...`);
  try {
    const response = await fetch("./api/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan: state.lastPlan, trackNames, confirm: true }),
    });
    const report = await response.json();
    if (!response.ok && response.status !== 207) throw new Error(report.error || `적용 실패 (${response.status})`);

    const succeeded = Object.keys(report.tracks || {});
    const failed = Object.keys(report.errors || {});
    let message = `적용 완료: ${succeeded.join(", ") || "없음"}`;
    if (failed.length) message += ` · 실패: ${failed.map((name) => `${name} (${report.errors[name]})`).join("; ")}`;
    setStatus(message, failed.length > 0);
  } catch (error) {
    setStatus(`적용 실패: ${error.message}`, true);
  } finally {
    applyBtn.disabled = false;
  }
}

recognizeBtn.addEventListener("click", recognizeTracks);
extractBtn.addEventListener("click", extractTracks);
buildPlanBtn.addEventListener("click", () => buildPlan());
buildPlanTestBtn.addEventListener("click", () => buildPlan({ rmsGateMode: "pre" }));
applyBtn.addEventListener("click", openConfirmModal);
confirmCancelEl.addEventListener("click", () => {
  confirmModalEl.hidden = true;
});
confirmOkEl.addEventListener("click", applyToProTools);
