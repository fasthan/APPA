const TRACKS = [
  { id: "track1", name: "1 서장훈", speaker: "A", audio: "./assets/audio/miuse-27m-33m/track1.mp3", waveform: "./assets/waveforms/miuse-27m-33m/track1.json", color: "#e8c15b" },
  { id: "track2", name: "2 박중훈", speaker: "B", audio: "./assets/audio/miuse-27m-33m/track2.mp3", waveform: "./assets/waveforms/miuse-27m-33m/track2.json", color: "#57c1a7" },
  { id: "track3", name: "3 신동엽", speaker: "C", audio: "./assets/audio/miuse-27m-33m/track3.mp3", waveform: "./assets/waveforms/miuse-27m-33m/track3.json", color: "#86a8e7" },
  { id: "track4", name: "4 희철맘", speaker: "D", audio: "./assets/audio/miuse-27m-33m/track4.mp3", waveform: "./assets/waveforms/miuse-27m-33m/track4.json", color: "#e36b5d" },
];

const TRACK_COLORS = ["#e8c15b", "#57c1a7", "#86a8e7", "#e36b5d", "#d98fd3", "#8bd36f", "#ef9f64", "#69c7df"];
const BSS_RESULTS = [
  {
    id: "local-rms",
    name: "Local RMS Activity",
    note: "브라우저에서 선택 파일의 RMS/activity를 직접 계산한 결과",
  },
  {
    id: "auxiva",
    name: "AuxIVA",
    note: "사전 계산된 CPU BSS 기준 결과",
  },
  {
    id: "ilrma",
    name: "ILRMA",
    note: "사전 계산된 모델 기반 BSS 결과",
  },
  {
    id: "fastmnmf",
    name: "FastMNMF",
    note: "사전 계산된 공격적 BSS 결과",
  },
];

const PROJECT_SOURCE_FILE_PATTERNS = ["서장훈_02", "박중훈_02", "신동엽_02", "희철맘_02"];
const SERVER_ANALYSIS_SIZE_THRESHOLD_BYTES = 250 * 1024 * 1024;
const BSS_SCALES = [
  {
    id: "raw",
    name: "Original BSS scale",
    note: "알고리즘이 복원한 원래 스케일",
  },
  {
    id: "active-rms",
    name: "Active RMS matched",
    note: "각 source를 매칭된 원본 트랙의 active RMS에 맞춘 보정 버전",
  },
  {
    id: "peak",
    name: "Peak normalized",
    note: "각 source의 최대 peak를 -1 dBFS로 맞춘 보정 버전",
  },
];

const state = {
  tracks: [],
  duration: 0,
  projectLoaded: false,
  analyzing: false,
  isPlaying: false,
  loop: false,
  zoom: 3,
  waveGain: 3,
  timelineWindowStart: 0,
  timelineWindowSeconds: 20 * 60,
  playhead: 0,
  selection: null,
  drag: null,
  suppressClick: false,
  segments: [],
  timelineWidth: 1200,
  sessionManifest: null,
  bssManifest: null,
  bssRange: null,
  bssAlgorithm: "auxiva",
  bssScale: "raw",
  bssTracks: [],
  bssReport: null,
  bssLevelMatch: null,
  bssPeakNormalize: null,
  bssActivity: null,
  originalRms: null,
  bssLoading: false,
  bssAnalyzing: false,
  bssError: null,
  bssIsPlaying: false,
  bssLoadRequestId: 0,
  activityScoringEnabled: true,
  thresholdGateEnabled: true,
  smoothingMode: "track-mask",
  smoothingEnabled: true,
  activityThreshold: 0.7,
  dominanceMargin: 0.15,
  fallbackGateEnabled: true,
  fallbackMinScore: 0,
  analysisRangeMode: "full",
  analysisRangeStart: 0,
  analysisRangeEnd: null,
  offGapFillSeconds: 2.0,
  minOnDurationSeconds: 0.6,
  rmsGateEnabled: true,
  rmsGateThresholdDb: -55,
  fadeDurationSeconds: 0.5,
  autoGatePreview: true,
  autoGateSegments: [],
};

const TRACK_LABEL_WIDTH = 176;
const DRAG_THRESHOLD_PX = 10;
const MIN_WAVEFORM_WIDTH = 900;
const BASE_PIXELS_PER_SECOND = 0.055;
const MAX_CANVAS_DRAW_WIDTH = 32000;
const WAVEFORM_WINDOW_SECONDS = 0.02;
const ACTIVITY_WINDOW_SECONDS = 0.2;
const ACTIVITY_HOP_SECONDS = 0.1;
const ACTIVITY_NOISE_PERCENTILE = 20;
const ACTIVITY_ACTIVE_PERCENTILE = 95;
const ACTIVITY_MIN_DYNAMIC_RANGE_DB = 12;
const AUTO_GATE_MIN_SECONDS = 0.5;
const AUTO_GATE_MERGE_GAP_SECONDS = 0.5;
const AUTO_GATE_PRE_ROLL_SECONDS = 0.1;
const AUTO_GATE_RELEASE_SECONDS = 0.25;
const AUTO_GATE_DOMINANCE_MARGIN = 0.15;
const AUTO_GATE_TIME_EPSILON = 0.001;
const AUDIO_GATE_MUTE_EPSILON = 0.001;
const DISABLED_GATE_KEY = "__disabled__";
const DEFAULT_BSS_SELECTION_SECONDS = 360;
const MAX_BSS_SELECTION_SECONDS = 600;
const FIRST_20_MINUTES_SECONDS = 20 * 60;
const TIMELINE_WINDOW_SECONDS = 20 * 60;

const $ = (selector) => document.querySelector(selector);
const sessionSubtitleEl = $("#sessionSubtitle");
const loaderPanelEl = $("#loaderPanel");
const workspaceEl = $("#workspace");
const timelineWindowBarEl = $("#timelineWindowBar");
const timelineWindowReadoutEl = $("#timelineWindowReadout");
const prevTimelineWindowEl = $("#prevTimelineWindow");
const nextTimelineWindowEl = $("#nextTimelineWindow");
const audioFileInputEl = $("#audioFileInput");
const loadFilesButtonEl = $("#loadFilesButton");
const loadProjectButtonEl = $("#loadProjectButton");
const chooseAudioFilesEl = $("#chooseAudioFiles");
const loadProjectSessionEl = $("#loadProjectSession");
const selectedFileHintEl = $("#selectedFileHint");
const analysisProgressBarEl = $("#analysisProgressBar");
const analysisStatusEl = $("#analysisStatus");
const timelineEl = $("#timeline");
const timelinePanelEl = $(".timeline-panel");
const playPauseEl = $("#playPause");
const stopEl = $("#stop");
const loopEl = $("#loop");
const zoomEl = $("#zoom");
const zoomValueEl = $("#zoomValue");
const waveGainEl = $("#waveGain");
const waveGainValueEl = $("#waveGainValue");
const loadingEl = $("#loading");
const trackControlsEl = $("#trackControls");
const segmentListEl = $("#segmentList");
const timecodeEl = $("#timecode");
const durationEl = $("#duration");
const selectionReadoutEl = $("#selectionReadout");
const bssAlgorithmEl = $("#bssAlgorithm");
const analysisRangeFullEl = $("#analysisRangeFull");
const analysisRangeFirst20El = $("#analysisRangeFirst20");
const analysisRangeSelectionEl = $("#analysisRangeSelection");
const analysisRangeValueEl = $("#analysisRangeValue");
const activityScoringEnabledEl = $("#activityScoringEnabled");
const thresholdGateEnabledEl = $("#thresholdGateEnabled");
const smoothingModeEl = $("#smoothingMode");
const smoothingEnabledEl = $("#smoothingEnabled");
const activityThresholdEl = $("#activityThreshold");
const activityThresholdValueEl = $("#activityThresholdValue");
const dominanceMarginEl = $("#dominanceMargin");
const dominanceMarginValueEl = $("#dominanceMarginValue");
const fallbackGateEnabledEl = $("#fallbackGateEnabled");
const fallbackMinScoreEl = $("#fallbackMinScore");
const fallbackMinScoreValueEl = $("#fallbackMinScoreValue");
const offGapFillEl = $("#offGapFill");
const offGapFillValueEl = $("#offGapFillValue");
const minOnDurationEl = $("#minOnDuration");
const minOnDurationValueEl = $("#minOnDurationValue");
const rmsGateEnabledEl = $("#rmsGateEnabled");
const rmsGateThresholdEl = $("#rmsGateThreshold");
const rmsGateThresholdValueEl = $("#rmsGateThresholdValue");
const fadeDurationEl = $("#fadeDuration");
const fadeDurationValueEl = $("#fadeDurationValue");
const autoGatePreviewEl = $("#autoGatePreview");
const applyAutoGatesEl = $("#applyAutoGates");
const clearAutoGatesEl = $("#clearAutoGates");
const bssInspectorNoteEl = $("#bssInspectorNote");
const bssPanelEl = $("#bssPanel");
const bssTimelineEl = $("#bssTimeline");
const bssStatusEl = $("#bssStatus");
const bssSummaryEl = $("#bssSummary");
const activityStatsEl = $("#activityStats");
const useRmsFilterEl = $("#useRmsFilter");
const runBssAnalysisEl = $("#runBssAnalysis");
const bssPlayPauseEl = $("#bssPlayPause");
const bssStopEl = $("#bssStop");

function formatTime(seconds) {
  const safe = Math.max(0, seconds || 0);
  const h = Math.floor(safe / 3600);
  const m = Math.floor((safe % 3600) / 60);
  const s = Math.floor(safe % 60);
  const ms = Math.floor((safe % 1) * 1000);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${String(ms).padStart(3, "0")}`;
}

function waitForPaint() {
  return new Promise((resolve) => requestAnimationFrame(resolve));
}

function setAnalysisStatus(message, progress = null) {
  if (analysisStatusEl) analysisStatusEl.textContent = message;
  if (analysisProgressBarEl && progress !== null) {
    analysisProgressBarEl.style.width = `${Math.max(0, Math.min(100, progress))}%`;
  }
}

function enterLoadingShell(showInitialLoader, message) {
  setProjectShellVisible(false);
  if (showInitialLoader) return;

  if (loaderPanelEl) loaderPanelEl.hidden = true;
  if (workspaceEl) workspaceEl.hidden = false;
  if (bssPanelEl) bssPanelEl.hidden = false;
  if (loadingEl) {
    loadingEl.textContent = message;
    loadingEl.hidden = false;
  }
}

function getTrackColor(indexOrTrackId) {
  if (typeof indexOrTrackId === "string") {
    const track = state.tracks.find((item) => item.id === indexOrTrackId);
    if (track) return track.color;
  }
  const index = Number(indexOrTrackId) || 0;
  return TRACK_COLORS[index % TRACK_COLORS.length];
}

function dbfs(value) {
  return 20 * Math.log10(Math.max(Number(value) || 0, 1e-12));
}

function percentile(values, percentileValue) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const position = (Math.max(0, Math.min(100, percentileValue)) / 100) * (sorted.length - 1);
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  if (lower === upper) return sorted[lower];
  const ratio = position - lower;
  return sorted[lower] * (1 - ratio) + sorted[upper] * ratio;
}

function getDownmixedSamples(audioBuffer, duration) {
  const length = Math.min(audioBuffer.length, Math.max(1, Math.floor(duration * audioBuffer.sampleRate)));
  const output = new Float32Array(length);
  const channelCount = audioBuffer.numberOfChannels;

  for (let channelIndex = 0; channelIndex < channelCount; channelIndex += 1) {
    const channel = audioBuffer.getChannelData(channelIndex);
    for (let sampleIndex = 0; sampleIndex < length; sampleIndex += 1) {
      output[sampleIndex] += channel[sampleIndex] / channelCount;
    }
  }

  return output;
}

function buildFrameStarts(duration, windowSeconds = ACTIVITY_WINDOW_SECONDS, hopSeconds = ACTIVITY_HOP_SECONDS) {
  if (duration <= 0) return [];
  if (duration <= windowSeconds) return [0];
  const frameCount = 1 + Math.floor((duration - windowSeconds) / hopSeconds);
  return Array.from({ length: frameCount }, (_, index) => Number((index * hopSeconds).toFixed(3)));
}

function generateWaveform(samples, sampleRate, duration) {
  const windowSamples = Math.max(1, Math.round(WAVEFORM_WINDOW_SECONDS * sampleRate));
  const frameCount = Math.max(1, Math.ceil(samples.length / windowSamples));
  const mins = [];
  const maxs = [];

  for (let frameIndex = 0; frameIndex < frameCount; frameIndex += 1) {
    const start = frameIndex * windowSamples;
    const end = Math.min(samples.length, start + windowSamples);
    let min = 0;
    let max = 0;
    for (let sampleIndex = start; sampleIndex < end; sampleIndex += 1) {
      const value = samples[sampleIndex] || 0;
      if (value < min) min = value;
      if (value > max) max = value;
    }
    mins.push(Number(min.toFixed(4)));
    maxs.push(Number(max.toFixed(4)));
  }

  return {
    source: "local-file",
    duration,
    sampleRate,
    windowSeconds: WAVEFORM_WINDOW_SECONDS,
    mins,
    maxs,
  };
}

function analyzeActivity(samples, sampleRate, starts) {
  const windowSamples = Math.max(1, Math.round(ACTIVITY_WINDOW_SECONDS * sampleRate));
  const rmsValues = [];
  const rmsDbfs = [];

  for (const startSeconds of starts) {
    const start = Math.min(samples.length - 1, Math.max(0, Math.round(startSeconds * sampleRate)));
    const end = Math.min(samples.length, start + windowSamples);
    let energy = 0;
    const length = Math.max(1, end - start);

    for (let sampleIndex = start; sampleIndex < end; sampleIndex += 1) {
      const value = samples[sampleIndex] || 0;
      energy += value * value;
    }

    const rms = Math.sqrt(energy / length + 1e-12);
    rmsValues.push(rms);
    rmsDbfs.push(Number(dbfs(rms).toFixed(2)));
  }

  const noiseDb = percentile(rmsDbfs, ACTIVITY_NOISE_PERCENTILE);
  const activeDb = percentile(rmsDbfs, ACTIVITY_ACTIVE_PERCENTILE);
  const dynamicRangeDb = Math.max(ACTIVITY_MIN_DYNAMIC_RANGE_DB, activeDb - noiseDb);
  const scores = rmsDbfs.map((value) => Number(Math.max(0, Math.min(1, (value - noiseDb) / dynamicRangeDb)).toFixed(4)));

  return {
    rmsDbfs,
    scores,
    normalization: {
      noiseDbfs: Number(noiseDb.toFixed(3)),
      activeDbfs: Number(activeDb.toFixed(3)),
      dynamicRangeDb: Number(dynamicRangeDb.toFixed(3)),
    },
  };
}

function clampWaveX(x) {
  return Math.max(0, Math.min(state.timelineWidth, x));
}

function getTimelineWindowStart() {
  return Math.max(0, Math.min(state.duration, Number(state.timelineWindowStart) || 0));
}

function getTimelineWindowEnd() {
  return Math.min(state.duration, getTimelineWindowStart() + state.timelineWindowSeconds);
}

function getTimelineWindowDuration() {
  return Math.max(0.001, getTimelineWindowEnd() - getTimelineWindowStart());
}

function isTimeInTimelineWindow(time) {
  return time >= getTimelineWindowStart() && time <= getTimelineWindowEnd();
}

function localXToTime(x) {
  if (!state.duration) return 0;
  return Math.min(getTimelineWindowEnd(), getTimelineWindowStart() + (clampWaveX(x) / state.timelineWidth) * getTimelineWindowDuration());
}

function timeToLocalX(time) {
  if (!state.duration) return 0;
  return ((time - getTimelineWindowStart()) / getTimelineWindowDuration()) * state.timelineWidth;
}

function getWaveOriginX(container, wrapSelector) {
  const wrap = container.querySelector(wrapSelector);
  if (!wrap) return TRACK_LABEL_WIDTH;

  const containerRect = container.getBoundingClientRect();
  const wrapRect = wrap.getBoundingClientRect();
  return wrapRect.left - containerRect.left;
}

function timeToTimelineX(time) {
  return getWaveOriginX(timelineEl, ".wave-wrap") + timeToLocalX(time);
}

function timeToBssTimelineX(time) {
  return getWaveOriginX(bssTimelineEl, ".activity-wrap") + timeToLocalX(time);
}

function updateZoomReadout() {
  zoomEl.value = String(state.zoom);
  if (!zoomValueEl) return;
  const pixelsPerSecond = state.duration ? state.timelineWidth / getTimelineWindowDuration() : 0;
  zoomValueEl.textContent = `${state.zoom}x · ${pixelsPerSecond.toFixed(1)} px/s`;
}

function updateWaveGainReadout() {
  waveGainEl.value = String(state.waveGain);
  if (!waveGainValueEl) return;
  waveGainValueEl.textContent = `${state.waveGain}x`;
}

function getMaxTimelineWindowStart() {
  return Math.max(0, state.duration - Math.min(state.duration, state.timelineWindowSeconds));
}

function updateTimelineWindowReadout() {
  const start = getTimelineWindowStart();
  const end = getTimelineWindowEnd();
  if (timelineWindowReadoutEl) {
    timelineWindowReadoutEl.textContent = `${formatTime(start)} - ${formatTime(end)}`;
  }
  if (prevTimelineWindowEl) prevTimelineWindowEl.disabled = !state.projectLoaded || start <= 0;
  if (nextTimelineWindowEl) nextTimelineWindowEl.disabled = !state.projectLoaded || end >= state.duration - AUTO_GATE_TIME_EPSILON;
}

function setTimelineWindowStart(start, options = {}) {
  const nextStart = Math.max(0, Math.min(getMaxTimelineWindowStart(), Number(start) || 0));
  state.timelineWindowStart = nextStart;
  const shouldSeek = options.seekToStart !== false;
  if (shouldSeek) {
    state.playhead = nextStart;
    for (const track of state.tracks) {
      track.audio.currentTime = state.playhead;
    }
    syncBssAudioTo(state.playhead);
  }

  if (state.bssActivity && state.bssAlgorithm === "local-rms") {
    state.analysisRangeMode = "window";
    state.analysisRangeStart = getTimelineWindowStart();
    state.analysisRangeEnd = getTimelineWindowEnd();
    recomputeAutoGateSegments();
  }

  timelinePanelEl.scrollLeft = 0;
  render();
  updateAudioGates();
  updateBssAudioGates();
}

function shiftTimelineWindow(direction) {
  setTimelineWindowStart(getTimelineWindowStart() + direction * state.timelineWindowSeconds);
}

function ensureTimelineWindowContains(time) {
  if (!state.duration || isTimeInTimelineWindow(time)) return;
  const targetStart = Math.floor(time / state.timelineWindowSeconds) * state.timelineWindowSeconds;
  setTimelineWindowStart(targetStart, { seekToStart: false });
}

function getPlayheadAnchorX() {
  const panelRect = timelinePanelEl.getBoundingClientRect();
  const cursor = $("#cursor");
  if (!cursor) return panelRect.width / 2;

  const cursorRect = cursor.getBoundingClientRect();
  const x = cursorRect.left - panelRect.left;
  if (x >= 0 && x <= panelRect.width) return x;
  return panelRect.width / 2;
}

function scrollPlayheadToAnchor(anchorX) {
  const panelRect = timelinePanelEl.getBoundingClientRect();
  const cursor = $("#cursor");
  if (!cursor) return;

  const cursorRect = cursor.getBoundingClientRect();
  const currentX = cursorRect.left - panelRect.left;
  const maxScroll = Math.max(0, timelinePanelEl.scrollWidth - timelinePanelEl.clientWidth);
  timelinePanelEl.scrollLeft = Math.max(0, Math.min(maxScroll, timelinePanelEl.scrollLeft + currentX - anchorX));
}

function setZoom(nextZoom, options = {}) {
  const min = Number(zoomEl.min);
  const max = Number(zoomEl.max);
  const zoom = Math.max(min, Math.min(max, Number(nextZoom)));
  if (!Number.isFinite(zoom) || zoom === state.zoom) return;

  const anchorX = options.anchorX === undefined ? getPlayheadAnchorX() : options.anchorX;
  state.zoom = zoom;
  zoomEl.value = String(zoom);
  render();
  scrollPlayheadToAnchor(anchorX);
}

function getZoomButtonStep() {
  if (state.zoom >= 100) return 20;
  if (state.zoom >= 40) return 10;
  if (state.zoom >= 12) return 4;
  return 1;
}

function setWaveGain(nextGain) {
  const min = Number(waveGainEl.min);
  const max = Number(waveGainEl.max);
  const gain = Math.max(min, Math.min(max, Number(nextGain)));
  if (!Number.isFinite(gain) || gain === state.waveGain) return;

  state.waveGain = gain;
  updateWaveGainReadout();
  redrawWaveforms();
}

function getTimelineWidth() {
  const baseWidth = Math.max(MIN_WAVEFORM_WIDTH, Math.round(getTimelineWindowDuration() * BASE_PIXELS_PER_SECOND));
  return Math.round(baseWidth * state.zoom);
}

function getCanvasDrawWidth() {
  return Math.max(1, Math.min(MAX_CANVAS_DRAW_WIDTH, state.timelineWidth));
}

function redrawWaveforms() {
  for (const canvas of timelineEl.querySelectorAll("canvas.waveform")) {
    const row = canvas.closest(".track-row");
    const trackId = row ? row.dataset.trackId : null;
    const track = state.tracks.find((item) => item.id === trackId);
    if (track) drawWaveform(canvas, track);
  }
  redrawBssWaveforms();
}

function setProjectShellVisible(loaded) {
  state.projectLoaded = loaded;
  if (loaderPanelEl) loaderPanelEl.hidden = loaded;
  if (workspaceEl) workspaceEl.hidden = !loaded;
  if (timelineWindowBarEl) timelineWindowBarEl.hidden = !loaded;
  if (bssPanelEl) bssPanelEl.hidden = !loaded;
  playPauseEl.disabled = !loaded;
  stopEl.disabled = !loaded;
  loopEl.disabled = !loaded;
  zoomEl.disabled = !loaded;
  waveGainEl.disabled = !loaded;
  if (useRmsFilterEl) useRmsFilterEl.disabled = !loaded || !state.originalRms || state.bssAnalyzing;
  if (runBssAnalysisEl) runBssAnalysisEl.disabled = !loaded || !state.sessionManifest || state.bssAnalyzing;
}

function setAnalysisControlsEnabled(enabled) {
  const hasBss = Boolean(enabled && state.bssActivity);
  bssAlgorithmEl.disabled = !hasBss;
  if (analysisRangeFullEl) analysisRangeFullEl.disabled = !hasBss;
  if (analysisRangeFirst20El) analysisRangeFirst20El.disabled = !hasBss;
  if (analysisRangeSelectionEl) analysisRangeSelectionEl.disabled = !hasBss;
  if (activityScoringEnabledEl) activityScoringEnabledEl.disabled = !hasBss;
  if (thresholdGateEnabledEl) thresholdGateEnabledEl.disabled = !hasBss || !state.activityScoringEnabled;
  if (fallbackGateEnabledEl) fallbackGateEnabledEl.disabled = !hasBss || !state.activityScoringEnabled;
  if (smoothingEnabledEl) smoothingEnabledEl.disabled = !hasBss || !state.activityScoringEnabled;
  smoothingModeEl.disabled = !hasBss || !state.activityScoringEnabled || !state.smoothingEnabled;
  activityThresholdEl.disabled = !hasBss || !state.activityScoringEnabled || !state.thresholdGateEnabled;
  if (dominanceMarginEl) dominanceMarginEl.disabled = !hasBss || !state.activityScoringEnabled || !state.thresholdGateEnabled;
  if (fallbackMinScoreEl) fallbackMinScoreEl.disabled = !hasBss || !state.activityScoringEnabled || !state.fallbackGateEnabled;
  offGapFillEl.disabled = !hasBss || !state.activityScoringEnabled || !state.smoothingEnabled;
  minOnDurationEl.disabled = !hasBss || !state.activityScoringEnabled || !state.smoothingEnabled;
  rmsGateEnabledEl.disabled = !hasBss || !state.activityScoringEnabled;
  rmsGateThresholdEl.disabled = !hasBss || !state.activityScoringEnabled || !state.rmsGateEnabled;
  fadeDurationEl.disabled = !hasBss;
  autoGatePreviewEl.disabled = !hasBss || !state.activityScoringEnabled;
  if (applyAutoGatesEl) applyAutoGatesEl.disabled = !hasBss || !state.activityScoringEnabled || !state.autoGateSegments.length;
  if (useRmsFilterEl) useRmsFilterEl.disabled = !state.projectLoaded || !state.originalRms || state.bssAnalyzing;
  if (runBssAnalysisEl) runBssAnalysisEl.disabled = !state.projectLoaded || !state.sessionManifest || state.bssAnalyzing;
}

function setLoadingBusy(busy) {
  state.analyzing = busy;
  if (loadFilesButtonEl) loadFilesButtonEl.disabled = busy;
  if (loadProjectButtonEl) loadProjectButtonEl.disabled = busy;
  if (chooseAudioFilesEl) chooseAudioFilesEl.disabled = busy;
  if (loadProjectSessionEl) loadProjectSessionEl.disabled = busy;
  if (useRmsFilterEl) useRmsFilterEl.disabled = busy || !state.projectLoaded || !state.originalRms || state.bssAnalyzing;
  if (runBssAnalysisEl) runBssAnalysisEl.disabled = busy || !state.projectLoaded || !state.sessionManifest || state.bssAnalyzing;
}

function resetProjectState() {
  pause();
  pauseBss();
  for (const track of state.tracks) {
    if (track.objectUrl) URL.revokeObjectURL(track.objectUrl);
  }
  for (const track of state.bssTracks) {
    if (track.objectUrl) URL.revokeObjectURL(track.objectUrl);
  }

  state.tracks = [];
  state.duration = 0;
  state.playhead = 0;
  state.timelineWindowStart = 0;
  state.timelineWindowSeconds = TIMELINE_WINDOW_SECONDS;
  state.selection = null;
  state.drag = null;
  state.segments = [];
  state.sessionManifest = null;
  state.bssManifest = null;
  state.bssRange = null;
  state.bssTracks = [];
  state.bssReport = null;
  state.bssLevelMatch = null;
  state.bssPeakNormalize = null;
  state.bssActivity = null;
  state.originalRms = null;
  state.bssError = null;
  state.bssLoading = false;
  state.bssAnalyzing = false;
  state.bssAlgorithm = "auxiva";
  state.analysisRangeMode = "full";
  state.analysisRangeStart = 0;
  state.analysisRangeEnd = null;
  state.autoGateSegments = [];
  state.autoGatePreview = true;
  if (autoGatePreviewEl) autoGatePreviewEl.checked = true;
  timelineEl.innerHTML = "";
  trackControlsEl.innerHTML = "";
  segmentListEl.innerHTML = "";
  bssTimelineEl.innerHTML = "";
  updateReadouts();
}

function readFileWithFileReader(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(reader.result));
    reader.addEventListener("error", () => reject(reader.error || new Error(`Failed to read ${file.name}`)));
    reader.readAsArrayBuffer(file);
  });
}

async function readFileAsArrayBuffer(file) {
  if (file.arrayBuffer) {
    try {
      return await file.arrayBuffer();
    } catch (error) {
      console.warn(`file.arrayBuffer() failed for ${file.name}; retrying with FileReader.`, error);
    }
  }
  return readFileWithFileReader(file);
}

async function decodeAudioFile(audioContext, file) {
  const arrayBuffer = await readFileAsArrayBuffer(file);
  return audioContext.decodeAudioData(arrayBuffer.slice(0));
}

function normalizeComparableName(name) {
  return name.normalize("NFC").replace(/\.[^.]+$/, "").toLowerCase();
}

function matchesProjectSourceFiles(files) {
  const names = files.map((file) => normalizeComparableName(file.name));
  return PROJECT_SOURCE_FILE_PATTERNS.every((pattern) => {
    const normalizedPattern = pattern.normalize("NFC").toLowerCase();
    return names.some((name) => name.includes(normalizedPattern));
  });
}

function shouldUseServerPreparation(files) {
  return matchesProjectSourceFiles(files) || files.some((file) => file.size >= SERVER_ANALYSIS_SIZE_THRESHOLD_BYTES);
}

function formatPreparedSessionStatus(manifest) {
  const status = manifest.status || {};
  return `proxy ${status.proxy || "unknown"} · waveform ${status.waveform || "unknown"} · BSS ${status.analysis || "not-run"}`;
}

async function fetchServerJson(url, options, actionName) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    throw new Error(`${actionName} 서버에 연결할 수 없습니다. serve_web.py가 실행 중인지 확인해주세요.`);
  }

  const responseText = await response.text();
  let payload = {};
  try {
    payload = responseText ? JSON.parse(responseText) : {};
  } catch (error) {
    throw new Error(`${actionName} 서버 응답을 해석할 수 없습니다. APPA 전용 웹 서버로 접속했는지 확인해주세요.`);
  }

  if (!response.ok) throw new Error(payload.error || `${actionName} failed (${response.status})`);
  return payload;
}

async function prepareServerSession(files = []) {
  const fileNames = files.map((file) => file.name);
  return fetchServerJson("./api/session/prepare", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fileNames }),
  }, "프로젝트 준비");
}

async function loadServerTrack(track) {
  const audio = new Audio(track.audio);
  audio.preload = "metadata";
  const waveform = await fetch(track.waveform).then((res) => {
    if (!res.ok) throw new Error(`Missing waveform: ${track.waveform}`);
    return res.json();
  });
  await loadAudioMetadata(audio, track.audio);
  return {
    ...track,
    audioSrc: track.audio,
    audio,
    waveform,
    enabled: true,
    solo: false,
    volume: 1,
  };
}

async function loadPreparedSession(manifest, options = {}) {
  const showInitialLoader = Object.prototype.hasOwnProperty.call(options, "showInitialLoader") ? options.showInitialLoader : !state.projectLoaded;
  setLoadingBusy(true);
  enterLoadingShell(showInitialLoader, `${manifest.name} 로드 중...`);
  resetProjectState();
  setAnalysisStatus(`${manifest.name} 로드 중... (${formatPreparedSessionStatus(manifest)})`, 72);
  if (selectedFileHintEl) selectedFileHintEl.textContent = "서버가 준비한 프록시/분석 자산을 로드합니다.";
  await waitForPaint();

  try {
    const [tracks, originalRmsResponse] = await Promise.all([
      Promise.all(manifest.tracks.map(loadServerTrack)),
      manifest.originalRmsUrl ? fetch(manifest.originalRmsUrl) : Promise.resolve(null),
    ]);

    if (originalRmsResponse && !originalRmsResponse.ok) throw new Error(`Failed to load ${manifest.originalRmsUrl}`);

    state.sessionManifest = manifest;
    state.tracks = tracks;
    state.duration = Math.min(...tracks.map((track) => track.waveform.duration || track.audio.duration));
    state.bssActivity = null;
    state.originalRms = originalRmsResponse ? await originalRmsResponse.json() : null;
    state.bssAlgorithm = "auxiva";
    state.bssLoading = false;
    state.bssError = null;

    populateBssAlgorithmOptions();
    setAnalysisControlsEnabled(false);
    recomputeAutoGateSegments();
    setProjectShellVisible(true);
    if (loadingEl) loadingEl.hidden = true;
    if (sessionSubtitleEl) sessionSubtitleEl.textContent = manifest.subtitle;
    setAnalysisStatus(`프로젝트 세션 로드 완료. BSS 분석은 아직 실행되지 않았습니다.`, 100);
    render();
    updateAudioGates();
  } catch (error) {
    resetProjectState();
    if (showInitialLoader) {
      setProjectShellVisible(false);
    } else {
      enterLoadingShell(false, `프로젝트 세션 로드 실패: ${error.message}`);
    }
    setAnalysisStatus(`프로젝트 세션 로드 실패: ${error.message}`, 0);
    console.error(error);
  } finally {
    setLoadingBusy(false);
  }
}

function getBssAnalysisRange() {
  let start = state.playhead || 0;
  let duration = Math.min(DEFAULT_BSS_SELECTION_SECONDS, Math.max(1, state.duration - start));
  let source = "playhead";

  if (state.selection && state.selection.start !== state.selection.end) {
    start = Math.min(state.selection.start, state.selection.end);
    const end = Math.max(state.selection.start, state.selection.end);
    duration = Math.max(1, end - start);
    source = "selection";
  }

  const cappedDuration = Math.min(duration, MAX_BSS_SELECTION_SECONDS, Math.max(1, state.duration - start));
  return {
    start,
    duration: cappedDuration,
    end: start + cappedDuration,
    source,
    capped: cappedDuration < duration,
  };
}

async function requestBssAnalysis(range) {
  return fetchServerJson("./api/bss/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sessionId: state.sessionManifest ? state.sessionManifest.id : "miuse-full",
      start: range.start,
      duration: range.duration,
      algorithms: ["auxiva"],
    }),
  }, "BSS 분석");
}

async function loadBssAnalysisManifest(manifest) {
  const [activityResponse, reportResponse] = await Promise.all([
    fetch(manifest.activityUrl),
    fetch(manifest.reportUrl),
  ]);
  if (!activityResponse.ok) throw new Error(`Failed to load ${manifest.activityUrl}`);
  if (!reportResponse.ok) throw new Error(`Failed to load ${manifest.reportUrl}`);

  state.bssManifest = manifest;
  state.bssRange = manifest.range || null;
  state.bssActivity = await activityResponse.json();
  state.bssReport = await reportResponse.json();
  state.bssAlgorithm = Object.keys(state.bssActivity.algorithms || {})[0] || "auxiva";
  state.bssTracks = [];
  populateBssAlgorithmOptions();
  recomputeAutoGateSegments();

  const algorithm = getBssAlgorithmById(state.bssAlgorithm);
  state.bssTracks = await Promise.all([1, 2, 3, 4].map((index) => loadBssTrack(algorithm, index)));
  setAnalysisControlsEnabled(true);
  render();
  updateAudioGates();
}

function normalizeRmsDbfsToScores(rmsDbfs) {
  const values = rmsDbfs.map((value) => Number(value)).filter(Number.isFinite);
  if (values.length === 0) {
    return {
      scores: [],
      normalization: {
        noiseDbfs: -80,
        activeDbfs: -40,
        dynamicRangeDb: ACTIVITY_MIN_DYNAMIC_RANGE_DB,
      },
    };
  }

  const noiseDb = percentile(values, ACTIVITY_NOISE_PERCENTILE);
  const activeDb = percentile(values, ACTIVITY_ACTIVE_PERCENTILE);
  const dynamicRangeDb = Math.max(ACTIVITY_MIN_DYNAMIC_RANGE_DB, activeDb - noiseDb);
  const scores = rmsDbfs.map((value) => {
    const db = Number(value);
    if (!Number.isFinite(db)) return 0;
    return Number(Math.max(0, Math.min(1, (db - noiseDb) / dynamicRangeDb)).toFixed(4));
  });

  return {
    scores,
    normalization: {
      noiseDbfs: Number(noiseDb.toFixed(3)),
      activeDbfs: Number(activeDb.toFixed(3)),
      dynamicRangeDb: Number(dynamicRangeDb.toFixed(3)),
    },
  };
}

function buildOriginalRmsActivityPayload() {
  if (!state.originalRms || !state.originalRms.series) return null;
  const rmsSettings = state.originalRms.settings || {};
  const settings = {
    windowSeconds: rmsSettings.windowSeconds || ACTIVITY_WINDOW_SECONDS,
    hopSeconds: rmsSettings.hopSeconds || ACTIVITY_HOP_SECONDS,
    noisePercentile: ACTIVITY_NOISE_PERCENTILE,
    activePercentile: ACTIVITY_ACTIVE_PERCENTILE,
    minDynamicRangeDb: ACTIVITY_MIN_DYNAMIC_RANGE_DB,
  };
  const sources = [];

  for (let index = 0; index < state.tracks.length; index += 1) {
    const track = state.tracks[index];
    const series = state.originalRms.series[track.id];
    const rmsDbfs = series && Array.isArray(series.rmsDbfs) ? series.rmsDbfs : [];
    const { scores, normalization } = normalizeRmsDbfsToScores(rmsDbfs);
    sources.push({
      source: index + 1,
      matchedTrack: track.id,
      matchedLabel: track.name,
      matchConfidence: 1,
      matchMargin: 1,
      normalization,
      scores,
    });
  }

  return {
    version: 1,
    kind: "local_rms_filter_activity",
    settings,
    duration: state.originalRms.duration || state.duration,
    range: {
      start: 0,
      end: state.duration,
      duration: state.duration,
    },
    starts: state.originalRms.starts || [],
    times: state.originalRms.times || [],
    algorithms: {
      "local-rms": {
        sources,
      },
    },
  };
}

function useRmsFilter() {
  if (!state.projectLoaded || !state.originalRms) return;
  pauseBss();
  state.bssManifest = null;
  state.bssRange = { start: 0, end: state.duration, duration: state.duration };
  state.bssTracks = [];
  state.bssReport = null;
  state.bssLevelMatch = null;
  state.bssPeakNormalize = null;
  state.bssActivity = buildOriginalRmsActivityPayload();
  state.bssAlgorithm = "local-rms";
  state.analysisRangeMode = "window";
  state.analysisRangeStart = getTimelineWindowStart();
  state.analysisRangeEnd = getTimelineWindowEnd();
  state.bssLoading = false;
  state.bssError = null;
  populateBssAlgorithmOptions();
  setAnalysisControlsEnabled(true);
  recomputeAutoGateSegments();
  render();
  updateAudioGates();
  setAnalysisStatus("Local RMS 필터가 적용되었습니다. Threshold와 smoothing 값을 조정해볼 수 있습니다.", 100);
}

async function runBssAnalysis() {
  if (!state.projectLoaded || !state.sessionManifest || state.bssAnalyzing) return;
  const range = getBssAnalysisRange();
  if (!Number.isFinite(range.duration) || range.duration <= 0) return;

  pause();
  pauseBss();
  state.bssAnalyzing = true;
  state.bssLoading = true;
  state.bssError = null;
  setAnalysisControlsEnabled(false);
  const capText = range.capped ? " · 10분으로 제한" : "";
  setAnalysisStatus(`AuxIVA BSS 분석 중: ${formatTime(range.start)} - ${formatTime(range.end)}${capText}`, 18);
  renderBssPanel();
  await waitForPaint();

  try {
    const manifest = await requestBssAnalysis(range);
    setAnalysisStatus(`BSS 캐시 로드 중... (${manifest.status})`, 88);
    await loadBssAnalysisManifest(manifest);
    setAnalysisStatus(`BSS 분석 준비 완료: ${formatTime(range.start)} - ${formatTime(range.end)} · ${manifest.status}`, 100);
  } catch (error) {
    state.bssError = error.message;
    state.bssActivity = null;
    state.bssTracks = [];
    setAnalysisControlsEnabled(false);
    renderBssPanel();
    setAnalysisStatus(`BSS 분석 실패: ${error.message}`, 0);
    console.error(error);
  } finally {
    state.bssLoading = false;
    state.bssAnalyzing = false;
    setAnalysisControlsEnabled(Boolean(state.bssActivity));
    renderBssPanel();
  }
}

async function loadPrecomputedSession(files = [], options = {}) {
  const showInitialLoader = Object.prototype.hasOwnProperty.call(options, "showInitialLoader") ? options.showInitialLoader : !state.projectLoaded;
  setLoadingBusy(true);
  enterLoadingShell(showInitialLoader, "서버에서 프록시/파형 자산을 확인하는 중입니다...");
  setAnalysisStatus("서버에서 프록시/파형 자산을 확인하는 중입니다...", 12);
  if (selectedFileHintEl) selectedFileHintEl.textContent = "기존 프록시가 있으면 재사용하고, 없으면 ffmpeg로 생성합니다.";
  await waitForPaint();

  try {
    const manifest = await prepareServerSession(files);
    await loadPreparedSession(manifest, { showInitialLoader });
  } catch (error) {
    resetProjectState();
    if (showInitialLoader) {
      setProjectShellVisible(false);
    } else {
      enterLoadingShell(false, `프로젝트 세션 준비 실패: ${error.message}`);
    }
    setAnalysisStatus(`프로젝트 세션 준비 실패: ${error.message}`, 0);
    console.error(error);
  } finally {
    setLoadingBusy(false);
  }
}

function buildLocalAnalysisPayload(tracks, analyses, starts, duration) {
  const series = {};
  const sources = [];

  for (let index = 0; index < tracks.length; index += 1) {
    const track = tracks[index];
    const analysis = analyses[index];
    series[track.id] = {
      trackId: track.id,
      name: track.name,
      rmsDbfs: analysis.rmsDbfs,
      summary: {
        minDbfs: Number(Math.min(...analysis.rmsDbfs).toFixed(2)),
        p20Dbfs: Number(percentile(analysis.rmsDbfs, 20).toFixed(2)),
        p50Dbfs: Number(percentile(analysis.rmsDbfs, 50).toFixed(2)),
        p80Dbfs: Number(percentile(analysis.rmsDbfs, 80).toFixed(2)),
        maxDbfs: Number(Math.max(...analysis.rmsDbfs).toFixed(2)),
      },
    };
    sources.push({
      source: index + 1,
      matchedTrack: track.id,
      matchedLabel: track.name,
      matchConfidence: 1,
      matchMargin: 1,
      normalization: analysis.normalization,
      scores: analysis.scores,
    });
  }

  const settings = {
    windowSeconds: ACTIVITY_WINDOW_SECONDS,
    hopSeconds: ACTIVITY_HOP_SECONDS,
    noisePercentile: ACTIVITY_NOISE_PERCENTILE,
    activePercentile: ACTIVITY_ACTIVE_PERCENTILE,
    minDynamicRangeDb: ACTIVITY_MIN_DYNAMIC_RANGE_DB,
  };

  return {
    originalRms: {
      version: 1,
      kind: "local_original_track_rms",
      settings,
      duration,
      starts,
      times: starts.map((start) => Number((start + ACTIVITY_WINDOW_SECONDS / 2).toFixed(3))),
      series,
    },
    bssActivity: {
      version: 1,
      kind: "local_source_activity",
      settings,
      duration,
      starts,
      times: starts.map((start) => Number((start + ACTIVITY_WINDOW_SECONDS / 2).toFixed(3))),
      algorithms: {
        "local-rms": {
          sources,
        },
      },
    },
  };
}

async function loadLocalAudioFiles(fileList) {
  const files = [...fileList].filter((file) => file.type.startsWith("audio/") || /\.(wav|mp3|m4a|aac|aiff?|flac|ogg)$/i.test(file.name));
  const showInitialLoader = !state.projectLoaded;
  if (files.length === 0) {
    setAnalysisStatus("오디오 파일을 하나 이상 선택해주세요.", 0);
    return;
  }

  if (shouldUseServerPreparation(files)) {
    setAnalysisStatus("대용량/프로젝트 원본을 감지했습니다. 서버에서 프록시와 분석 자산을 준비합니다.", 5);
    if (selectedFileHintEl) selectedFileHintEl.textContent = files.map((file) => file.name).join(" · ");
    await waitForPaint();
    await loadPrecomputedSession(files, { showInitialLoader });
    return;
  }

  setLoadingBusy(true);
  enterLoadingShell(showInitialLoader, `${files.length}개 파일을 읽는 중입니다...`);
  resetProjectState();
  setAnalysisStatus(`${files.length}개 파일을 읽는 중입니다...`, 4);
  if (selectedFileHintEl) selectedFileHintEl.textContent = files.map((file) => file.name).join(" · ");
  await waitForPaint();

  const decoded = [];
  try {
    const AudioContextConstructor = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextConstructor) throw new Error("이 브라우저는 Web Audio API를 지원하지 않습니다.");
    const audioContext = new AudioContextConstructor();

    for (let index = 0; index < files.length; index += 1) {
      const file = files[index];
      setAnalysisStatus(`Decoding ${index + 1}/${files.length}: ${file.name}`, 8 + (index / files.length) * 34);
      await waitForPaint();
      const audioBuffer = await decodeAudioFile(audioContext, file);
      decoded.push({ file, audioBuffer, objectUrl: URL.createObjectURL(file) });
    }

    const duration = Math.min(...decoded.map((item) => item.audioBuffer.duration));
    if (!Number.isFinite(duration) || duration <= 0) throw new Error("분석 가능한 오디오 길이를 찾지 못했습니다.");
    const starts = buildFrameStarts(duration);
    const tracks = [];
    const analyses = [];

    for (let index = 0; index < decoded.length; index += 1) {
      const item = decoded[index];
      const trackId = `track${index + 1}`;
      const trackName = `${index + 1} ${item.file.name.replace(/\.[^.]+$/, "")}`;
      setAnalysisStatus(`Analyzing ${index + 1}/${decoded.length}: waveform/RMS/activity`, 44 + (index / decoded.length) * 48);
      await waitForPaint();

      const samples = getDownmixedSamples(item.audioBuffer, duration);
      const waveform = generateWaveform(samples, item.audioBuffer.sampleRate, duration);
      const analysis = analyzeActivity(samples, item.audioBuffer.sampleRate, starts);
      const audio = new Audio(item.objectUrl);
      audio.preload = "metadata";
      await loadAudioMetadata(audio, item.file.name);

      tracks.push({
        id: trackId,
        name: trackName,
        speaker: "Loaded file",
        audioSrc: item.file.name,
        objectUrl: item.objectUrl,
        audio,
        waveform,
        enabled: true,
        solo: false,
        volume: 1,
        color: getTrackColor(index),
      });
      analyses.push(analysis);
    }

    const payload = buildLocalAnalysisPayload(tracks, analyses, starts, duration);
    state.tracks = tracks;
    state.duration = duration;
    state.originalRms = payload.originalRms;
    state.bssActivity = payload.bssActivity;
    state.bssAlgorithm = "local-rms";
    state.bssLoading = false;
    state.bssError = null;

    populateBssAlgorithmOptions();
    setAnalysisControlsEnabled(true);
    recomputeAutoGateSegments();
    setProjectShellVisible(true);
    if (loadingEl) loadingEl.hidden = true;
    if (sessionSubtitleEl) sessionSubtitleEl.textContent = `${files.length} tracks loaded · ${formatTime(duration)}`;
    setAnalysisStatus("분석 완료. 게이트 제안을 확인할 수 있습니다.", 100);
    render();
    updateAudioGates();
  } catch (error) {
    for (const item of decoded) {
      if (item.objectUrl) URL.revokeObjectURL(item.objectUrl);
    }
    resetProjectState();
    if (showInitialLoader) {
      setProjectShellVisible(false);
    } else {
      enterLoadingShell(false, `분석 실패: ${error.message}`);
    }
    setAnalysisStatus(`분석 실패: ${error.message}`, 0);
    console.error(error);
  } finally {
    setLoadingBusy(false);
  }
}

async function loadTrack(track) {
  const audio = new Audio(track.audio);
  audio.preload = "metadata";
  const waveform = await fetch(track.waveform).then((res) => {
    if (!res.ok) throw new Error(`Missing waveform: ${track.waveform}`);
    return res.json();
  });
  await new Promise((resolve, reject) => {
    audio.addEventListener("loadedmetadata", resolve, { once: true });
    audio.addEventListener("error", reject, { once: true });
  });
  return {
    ...track,
    audioSrc: track.audio,
    audio,
    waveform,
    enabled: true,
    solo: false,
    volume: 1,
  };
}

function render() {
  timelineEl.innerHTML = "";
  trackControlsEl.innerHTML = "";
  state.timelineWidth = getTimelineWidth();
  timelineEl.style.width = `${state.timelineWidth + 176 + 36}px`;
  updateZoomReadout();
  updateWaveGainReadout();
  updateTimelineWindowReadout();

  for (const track of state.tracks) {
    renderTrack(track);
    renderTrackControl(track);
  }

  renderCursor();
  renderSelection();
  renderSegments();
  renderSegmentList();
  renderBssPanel();
  updateReadouts();
}

function renderTrack(track) {
  const row = document.createElement("div");
  row.className = "track-row";
  row.dataset.trackId = track.id;

  const label = document.createElement("div");
  label.className = "track-label";
  label.innerHTML = `<strong>${track.name}</strong><span>${track.speaker}</span>`;

  const wrap = document.createElement("div");
  wrap.className = "wave-wrap";
  wrap.style.width = `${state.timelineWidth}px`;

  const canvas = document.createElement("canvas");
  canvas.className = "waveform";
  canvas.width = getCanvasDrawWidth();
  canvas.height = 116;
  wrap.appendChild(canvas);

  row.append(label, wrap);
  timelineEl.appendChild(row);

  drawWaveform(canvas, track);

  wrap.addEventListener("mousedown", (event) => {
    const rect = wrap.getBoundingClientRect();
    const startX = clampWaveX(event.clientX - rect.left);
    const start = localXToTime(startX);
    state.drag = { start, end: start, startX, moved: false };
  });
}

function drawWaveform(canvas, track) {
  const ctx = canvas.getContext("2d");
  const { mins, maxs } = track.waveform;
  const width = canvas.width;
  const height = canvas.height;
  const mid = height / 2;
  const sampleCount = Math.min(mins.length, maxs.length);
  const scaleY = (value) => mid - value * mid * 0.92;
  const clampSample = (value) => Math.max(-1, Math.min(1, value * state.waveGain));

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#141719";
  ctx.fillRect(0, 0, width, height);

  if (sampleCount === 0) return;

  const top = [];
  const bottom = [];
  const viewStart = getTimelineWindowStart();
  const viewEnd = getTimelineWindowEnd();
  const waveformDuration = track.waveform.duration || state.duration || viewEnd;
  const timeToSampleIndex = (time) => Math.max(0, Math.min(sampleCount, Math.floor((Math.max(0, time) / waveformDuration) * sampleCount)));

  for (let x = 0; x < width; x += 1) {
    const timeStart = viewStart + (x / width) * (viewEnd - viewStart);
    const timeEnd = viewStart + ((x + 1) / width) * (viewEnd - viewStart);
    const start = timeToSampleIndex(timeStart);
    const end = Math.max(start + 1, timeToSampleIndex(timeEnd));
    let min = 0;
    let max = 0;

    for (let i = start; i < end && i < sampleCount; i += 1) {
      min = Math.min(min, mins[i] === undefined ? 0 : mins[i]);
      max = Math.max(max, maxs[i] === undefined ? 0 : maxs[i]);
    }

    top.push(scaleY(clampSample(max)));
    bottom.push(scaleY(clampSample(min)));
  }

  ctx.save();
  ctx.strokeStyle = track.color;
  ctx.globalAlpha = 0.18;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, mid + 0.5);
  ctx.lineTo(width, mid + 0.5);
  ctx.stroke();

  ctx.fillStyle = track.color;
  ctx.globalAlpha = 0.26;
  ctx.beginPath();
  ctx.moveTo(0.5, top[0]);
  for (let x = 1; x < width; x += 1) {
    ctx.lineTo(x + 0.5, top[x]);
  }
  for (let x = width - 1; x >= 0; x -= 1) {
    ctx.lineTo(x + 0.5, bottom[x]);
  }
  ctx.closePath();
  ctx.fill();

  ctx.globalAlpha = 0.9;
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.moveTo(0.5, top[0]);
  for (let x = 1; x < width; x += 1) {
    ctx.lineTo(x + 0.5, top[x]);
  }
  ctx.stroke();

  ctx.beginPath();
  ctx.moveTo(0.5, bottom[0]);
  for (let x = 1; x < width; x += 1) {
    ctx.lineTo(x + 0.5, bottom[x]);
  }
  ctx.stroke();
  ctx.restore();
}

function renderTrackControl(track) {
  const row = document.createElement("div");
  row.className = "track-control";
  row.innerHTML = `
    <div><strong>${track.name}</strong><br><small>${track.audioSrc}</small></div>
    <label class="toggle"><input type="checkbox" data-action="enabled" ${track.enabled ? "checked" : ""}>On</label>
    <label class="toggle"><input type="checkbox" data-action="solo" ${track.solo ? "checked" : ""}>Solo</label>
  `;
  row.querySelector('[data-action="enabled"]').addEventListener("change", (event) => {
    track.enabled = event.target.checked;
    updateAudioGates();
  });
  row.querySelector('[data-action="solo"]').addEventListener("change", (event) => {
    track.solo = event.target.checked;
    updateAudioGates();
  });
  trackControlsEl.appendChild(row);
}

function renderCursor() {
  const cursor = document.createElement("div");
  cursor.className = "cursor";
  const localX = timeToLocalX(state.playhead);
  cursor.style.left = `${getWaveOriginX(timelineEl, ".wave-wrap") + localX}px`;
  cursor.hidden = localX < 0 || localX > state.timelineWidth;
  cursor.id = "cursor";
  timelineEl.appendChild(cursor);
}

function renderSelection() {
  document.querySelectorAll(".selection").forEach((el) => el.remove());
  if (!state.selection || state.selection.start === state.selection.end) return;
  const start = Math.min(state.selection.start, state.selection.end);
  const end = Math.max(state.selection.start, state.selection.end);
  const clippedStart = Math.max(start, getTimelineWindowStart());
  const clippedEnd = Math.min(end, getTimelineWindowEnd());
  if (clippedEnd <= clippedStart) return;
  for (const wrap of timelineEl.querySelectorAll(".wave-wrap")) {
    const selection = document.createElement("div");
    selection.className = "selection";
    selection.style.left = `${timeToLocalX(clippedStart)}px`;
    selection.style.width = `${Math.max(2, timeToLocalX(clippedEnd) - timeToLocalX(clippedStart))}px`;
    wrap.appendChild(selection);
  }
}

function mergeContinuousRanges(ranges) {
  const sorted = ranges
    .filter((range) => range.end - range.start > AUTO_GATE_TIME_EPSILON)
    .sort((a, b) => a.start - b.start);
  const merged = [];

  for (const range of sorted) {
    const previous = merged[merged.length - 1];
    if (previous && range.start - previous.end <= AUTO_GATE_TIME_EPSILON) {
      previous.end = Math.max(previous.end, range.end);
    } else {
      merged.push({ ...range });
    }
  }

  return merged;
}

function getTrackGateRanges(segments, trackId, enabled) {
  const ranges = [];
  for (const segment of segments) {
    if (Boolean(segment.enabled[trackId]) !== enabled) continue;
    ranges.push({ start: segment.start, end: segment.end });
  }
  return mergeContinuousRanges(ranges);
}

function appendTimedOverlay(wrap, className, start, end, minWidth = 0) {
  const clippedStart = Math.max(start, getTimelineWindowStart());
  const clippedEnd = Math.min(end, getTimelineWindowEnd());
  if (clippedEnd <= clippedStart) return;
  const overlay = document.createElement("div");
  overlay.className = className;
  overlay.style.left = `${timeToLocalX(clippedStart)}px`;
  overlay.style.width = `${Math.max(minWidth, timeToLocalX(clippedEnd) - timeToLocalX(clippedStart))}px`;
  wrap.appendChild(overlay);
}

function renderSegments() {
  document.querySelectorAll(".segment-overlay").forEach((el) => el.remove());
  document.querySelectorAll(".auto-gate-overlay").forEach((el) => el.remove());
  for (const row of timelineEl.querySelectorAll(".track-row")) {
    const trackId = row.dataset.trackId;
    const wrap = row.querySelector(".wave-wrap");
    for (const segment of state.segments) {
      appendTimedOverlay(wrap, `segment-overlay ${segment.enabled[trackId] ? "" : "disabled"}`, segment.start, segment.end, 2);
    }
    if (state.autoGatePreview) {
      for (const range of getTrackGateRanges(state.autoGateSegments, trackId, false)) {
        appendTimedOverlay(wrap, "auto-gate-overlay disabled", range.start, range.end);
      }
      for (const range of getTrackGateRanges(state.autoGateSegments, trackId, true)) {
        appendTimedOverlay(wrap, "auto-gate-overlay enabled", range.start, range.end);
      }
    }
  }
}

function renderSegmentList() {
  segmentListEl.innerHTML = "";
  if (state.segments.length === 0) {
    segmentListEl.innerHTML = `<div class="segment-card"><strong>No segments yet</strong></div>`;
    return;
  }
  for (const segment of state.segments) {
    const card = document.createElement("div");
    card.className = "segment-card";
    card.innerHTML = `
      <header>
        <strong>${formatTime(segment.start)} - ${formatTime(segment.end)}</strong>
        <button type="button" data-delete>Delete</button>
      </header>
      <div class="segment-tracks"></div>
    `;
    const tracks = card.querySelector(".segment-tracks");
    for (const track of state.tracks) {
      const label = document.createElement("label");
      label.innerHTML = `<input type="checkbox" ${segment.enabled[track.id] ? "checked" : ""}>${track.name}`;
      label.querySelector("input").addEventListener("change", (event) => {
        segment.enabled[track.id] = event.target.checked;
        renderSegments();
        updateAudioGates();
      });
      tracks.appendChild(label);
    }
    card.querySelector("[data-delete]").addEventListener("click", () => {
      state.segments = state.segments.filter((item) => item.id !== segment.id);
      renderSegments();
      renderSegmentList();
      updateAudioGates();
    });
    segmentListEl.appendChild(card);
  }
}

function getTrackById(trackId) {
  return state.tracks.find((track) => track.id === trackId);
}

function getBssAlgorithmById(algorithmId) {
  return BSS_RESULTS.find((algorithm) => algorithm.id === algorithmId) || BSS_RESULTS[0];
}

function getBssScaleById(scaleId) {
  return BSS_SCALES.find((scale) => scale.id === scaleId) || BSS_SCALES[0];
}

function getAvailableAlgorithms() {
  if (!state.bssActivity || !state.bssActivity.algorithms) return [];
  return Object.keys(state.bssActivity.algorithms).map((algorithmId) => {
    const known = getBssAlgorithmById(algorithmId);
    return known.id === algorithmId ? known : { id: algorithmId, name: algorithmId, note: "" };
  });
}

function getBssReportForAlgorithm(algorithmId) {
  if (!state.bssReport || !state.bssReport.algorithms) return null;
  return state.bssReport.algorithms.find((item) => item.name === algorithmId) || null;
}

function getBssMapping(algorithmId, sourceIndex) {
  const report = getBssReportForAlgorithm(algorithmId);
  if (!report || !report.mapping) return null;
  return report.mapping.find((item) => item.source === sourceIndex) || null;
}

function getBssLevelMatch(algorithmId, sourceIndex) {
  if (!state.bssLevelMatch || !state.bssLevelMatch.algorithms) return null;
  const algorithm = state.bssLevelMatch.algorithms[algorithmId];
  if (!algorithm || !algorithm.sources) return null;
  return algorithm.sources.find((item) => item.source === sourceIndex) || null;
}

function getBssPeakNormalize(algorithmId, sourceIndex) {
  if (!state.bssPeakNormalize || !state.bssPeakNormalize.algorithms) return null;
  const algorithm = state.bssPeakNormalize.algorithms[algorithmId];
  if (!algorithm || !algorithm.sources) return null;
  return algorithm.sources.find((item) => item.source === sourceIndex) || null;
}

function getBssCachedSourceAsset(algorithmId, sourceIndex) {
  const algorithm = state.bssManifest && state.bssManifest.algorithms ? state.bssManifest.algorithms[algorithmId] : null;
  if (!algorithm || !algorithm.sources) return null;
  return algorithm.sources.find((item) => item.source === sourceIndex) || null;
}

function getBssAssetFolders(algorithm) {
  const cachedSource = getBssCachedSourceAsset(algorithm.id, 1);
  if (cachedSource && cachedSource.audioUrl && cachedSource.waveformUrl) {
    return {
      audio: cachedSource.audioUrl.replace(/\/source1\.wav$/, ""),
      waveform: cachedSource.waveformUrl.replace(/\/track1\.json$/, ""),
    };
  }

  if (state.bssScale === "active-rms") {
    return {
      audio: `./assets/analysis/miuse-27m-33m/bss/active-rms/${algorithm.id}`,
      waveform: `./assets/waveforms/miuse-27m-33m/bss/active-rms/${algorithm.id}`,
    };
  }

  if (state.bssScale === "peak") {
    return {
      audio: `./assets/analysis/miuse-27m-33m/bss/peak/${algorithm.id}`,
      waveform: `./assets/waveforms/miuse-27m-33m/bss/peak/${algorithm.id}`,
    };
  }

  return {
    audio: algorithm.folder,
    waveform: algorithm.waveformFolder,
  };
}

function populateBssAlgorithmOptions() {
  bssAlgorithmEl.innerHTML = "";
  const algorithms = getAvailableAlgorithms();
  if (algorithms.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Run BSS first";
    bssAlgorithmEl.appendChild(option);
    bssAlgorithmEl.value = "";
    bssAlgorithmEl.disabled = true;
    return;
  }

  if (!algorithms.some((algorithm) => algorithm.id === state.bssAlgorithm)) {
    state.bssAlgorithm = algorithms[0].id;
  }

  for (const algorithm of algorithms) {
    const option = document.createElement("option");
    option.value = algorithm.id;
    option.textContent = algorithm.name;
    bssAlgorithmEl.appendChild(option);
  }
  bssAlgorithmEl.value = state.bssAlgorithm;
  bssAlgorithmEl.disabled = false;
}

async function loadBssReport() {
  throw new Error("Precomputed BSS assets are not loaded in local file mode.");
}

function loadAudioMetadata(audio, src) {
  return new Promise((resolve, reject) => {
    if (audio.readyState >= HTMLMediaElement.HAVE_METADATA) {
      resolve();
      return;
    }

    const timeout = window.setTimeout(() => {
      cleanup();
      reject(new Error(`Timed out loading audio metadata: ${src}`));
    }, 10000);

    const cleanup = () => {
      window.clearTimeout(timeout);
      audio.removeEventListener("loadedmetadata", onLoaded);
      audio.removeEventListener("error", onError);
    };

    const onLoaded = () => {
      cleanup();
      resolve();
    };

    const onError = () => {
      cleanup();
      reject(new Error(`Failed to load audio metadata: ${src}`));
    };

    audio.addEventListener("loadedmetadata", onLoaded, { once: true });
    audio.addEventListener("error", onError, { once: true });
    audio.load();
  });
}

async function loadBssTrack(algorithm, index) {
  const cachedSource = getBssCachedSourceAsset(algorithm.id, index);
  const folders = getBssAssetFolders(algorithm);
  const audioSrc = cachedSource ? cachedSource.audioUrl : `${folders.audio}/source${index}.wav`;
  const waveformSrc = cachedSource ? cachedSource.waveformUrl : `${folders.waveform}/track${index}.json`;
  const audio = new Audio();
  audio.preload = "metadata";
  audio.src = audioSrc;

  const metadataReady = loadAudioMetadata(audio, audioSrc);
  const waveformReady = fetch(waveformSrc).then((res) => {
    if (!res.ok) throw new Error(`Missing BSS waveform: ${waveformSrc}`);
    return res.json();
  });

  const [waveform] = await Promise.all([waveformReady, metadataReady]);

  const baseTrack = TRACKS[index - 1];
  const mapping = getBssMapping(algorithm.id, index);
  const levelMatch = getBssLevelMatch(algorithm.id, index);
  const peakNormalize = getBssPeakNormalize(algorithm.id, index);
  return {
    id: `${algorithm.id}-source${index}`,
    sourceIndex: index,
    name: `Source ${index}`,
    audioSrc,
    waveform,
    audio,
    enabled: true,
    solo: false,
    volume: 1,
    color: baseTrack ? baseTrack.color : "#e8c15b",
    mapping,
    levelMatch,
    peakNormalize,
  };
}

function setBssAlgorithm(algorithmId) {
  const algorithm = getBssAlgorithmById(algorithmId);
  pauseBss();
  state.bssAlgorithm = algorithm.id;
  state.bssError = null;
  state.bssTracks = [];
  state.bssLoading = !state.bssActivity;
  refreshAutoGatePipeline();
}

function refreshAutoGatePipeline() {
  setAnalysisControlsEnabled(Boolean(state.bssActivity));
  recomputeAutoGateSegments();
  renderBssPanel();
  renderSegments();
  updateAudioGates();
}

function setActivityScoringEnabled(enabled) {
  state.activityScoringEnabled = Boolean(enabled);
  updatePipelineReadouts();
  refreshAutoGatePipeline();
}

function setThresholdGateEnabled(enabled) {
  state.thresholdGateEnabled = Boolean(enabled);
  updatePipelineReadouts();
  refreshAutoGatePipeline();
}

function setSmoothingMode(mode) {
  state.smoothingMode = mode === "combination-runs" ? "combination-runs" : "track-mask";
  refreshAutoGatePipeline();
}

function setSmoothingEnabled(enabled) {
  state.smoothingEnabled = Boolean(enabled);
  updatePipelineReadouts();
  refreshAutoGatePipeline();
}

function setActivityThreshold(value) {
  const threshold = Math.max(0.1, Math.min(0.95, Number(value)));
  if (!Number.isFinite(threshold)) return;
  state.activityThreshold = threshold;
  updateActivityThresholdReadout();
  refreshAutoGatePipeline();
}

function setDominanceMargin(value) {
  const margin = Math.max(0, Math.min(0.5, Number(value)));
  if (!Number.isFinite(margin)) return;
  state.dominanceMargin = margin;
  updateDominanceMarginReadout();
  refreshAutoGatePipeline();
}

function setFallbackGateEnabled(enabled) {
  state.fallbackGateEnabled = Boolean(enabled);
  updatePipelineReadouts();
  refreshAutoGatePipeline();
}

function setFallbackMinScore(value) {
  const score = Math.max(0, Math.min(0.95, Number(value)));
  if (!Number.isFinite(score)) return;
  state.fallbackMinScore = score;
  updateFallbackMinScoreReadout();
  refreshAutoGatePipeline();
}

function getConfiguredAnalysisRange(duration = state.duration) {
  const safeDuration = Math.max(0, Number(duration) || 0);
  let start = 0;
  let end = safeDuration;

  if (state.analysisRangeMode === "first-20") {
    end = Math.min(safeDuration, FIRST_20_MINUTES_SECONDS);
  } else if (state.analysisRangeMode === "window") {
    start = Math.max(0, Math.min(safeDuration, Number(state.analysisRangeStart) || 0));
    end = Math.max(0, Math.min(safeDuration, Number(state.analysisRangeEnd) || 0));
    if (end <= start) {
      start = getTimelineWindowStart();
      end = getTimelineWindowEnd();
    }
  } else if (state.analysisRangeMode === "selection") {
    start = Math.max(0, Math.min(safeDuration, Number(state.analysisRangeStart) || 0));
    end = Math.max(0, Math.min(safeDuration, Number(state.analysisRangeEnd) || 0));
    if (end <= start) {
      start = 0;
      end = safeDuration;
    }
  }

  return { start, end };
}

function getAnalysisRangeLabel() {
  const range = getConfiguredAnalysisRange();
  if (state.analysisRangeMode === "full") return "Full timeline";
  if (state.analysisRangeMode === "first-20") return `First 20m · ${formatTime(range.start)} - ${formatTime(range.end)}`;
  if (state.analysisRangeMode === "window") return `Visible window · ${formatTime(range.start)} - ${formatTime(range.end)}`;
  return `Selection · ${formatTime(range.start)} - ${formatTime(range.end)}`;
}

function updateAnalysisRangeReadout() {
  if (analysisRangeValueEl) analysisRangeValueEl.textContent = getAnalysisRangeLabel();
  if (analysisRangeFullEl) analysisRangeFullEl.setAttribute("aria-pressed", String(state.analysisRangeMode === "full"));
  if (analysisRangeFirst20El) analysisRangeFirst20El.setAttribute("aria-pressed", String(state.analysisRangeMode === "first-20"));
  if (analysisRangeSelectionEl) analysisRangeSelectionEl.setAttribute("aria-pressed", String(state.analysisRangeMode === "selection"));
}

function setAnalysisRange(mode, start = 0, end = null) {
  state.analysisRangeMode = mode;
  state.analysisRangeStart = start;
  state.analysisRangeEnd = end;
  updateAnalysisRangeReadout();
  refreshAutoGatePipeline();
}

function setAnalysisRangeFromSelection() {
  if (!state.selection || state.selection.start === state.selection.end) {
    setAnalysisStatus("먼저 waveform에서 20분 등 분석할 구간을 드래그로 선택해주세요.", 0);
    return;
  }

  const start = Math.min(state.selection.start, state.selection.end);
  const end = Math.max(state.selection.start, state.selection.end);
  setAnalysisRange("selection", start, end);
}

function setOffGapFillSeconds(value) {
  const seconds = Math.max(0, Math.min(5, Number(value)));
  if (!Number.isFinite(seconds)) return;
  state.offGapFillSeconds = seconds;
  updateOffGapFillReadout();
  refreshAutoGatePipeline();
}

function setMinOnDurationSeconds(value) {
  const seconds = Math.max(0, Math.min(2, Number(value)));
  if (!Number.isFinite(seconds)) return;
  state.minOnDurationSeconds = seconds;
  updateMinOnDurationReadout();
  refreshAutoGatePipeline();
}

function setRmsGateEnabled(enabled) {
  state.rmsGateEnabled = Boolean(enabled);
  updateRmsGateReadout();
  refreshAutoGatePipeline();
}

function setRmsGateThresholdDb(value) {
  const db = Math.max(-80, Math.min(-25, Number(value)));
  if (!Number.isFinite(db)) return;
  state.rmsGateThresholdDb = db;
  updateRmsGateReadout();
  refreshAutoGatePipeline();
}

function setFadeDurationSeconds(value) {
  const seconds = Math.max(0, Math.min(2, Number(value)));
  if (!Number.isFinite(seconds)) return;
  state.fadeDurationSeconds = seconds;
  updateFadeDurationReadout();
  renderBssPanel();
  updateAudioGates();
}

function updateActivityThresholdReadout() {
  if (!activityThresholdEl || !activityThresholdValueEl) return;
  activityThresholdEl.value = String(state.activityThreshold);
  activityThresholdValueEl.textContent = state.activityThreshold.toFixed(2);
}

function updateDominanceMarginReadout() {
  if (!dominanceMarginEl || !dominanceMarginValueEl) return;
  dominanceMarginEl.value = String(state.dominanceMargin);
  dominanceMarginValueEl.textContent = state.dominanceMargin.toFixed(2);
}

function updateFallbackMinScoreReadout() {
  if (!fallbackMinScoreEl || !fallbackMinScoreValueEl) return;
  fallbackMinScoreEl.value = String(state.fallbackMinScore);
  fallbackMinScoreValueEl.textContent = state.fallbackMinScore.toFixed(2);
}

function updatePipelineReadouts() {
  updateAnalysisRangeReadout();
  if (activityScoringEnabledEl) activityScoringEnabledEl.checked = state.activityScoringEnabled;
  if (thresholdGateEnabledEl) thresholdGateEnabledEl.checked = state.thresholdGateEnabled;
  if (fallbackGateEnabledEl) fallbackGateEnabledEl.checked = state.fallbackGateEnabled;
  if (smoothingEnabledEl) smoothingEnabledEl.checked = state.smoothingEnabled;
  updateActivityThresholdReadout();
  updateDominanceMarginReadout();
  updateFallbackMinScoreReadout();
  updateOffGapFillReadout();
  updateMinOnDurationReadout();
  updateRmsGateReadout();
}

function updateOffGapFillReadout() {
  if (!offGapFillEl || !offGapFillValueEl) return;
  offGapFillEl.value = String(state.offGapFillSeconds);
  offGapFillValueEl.textContent = `${state.offGapFillSeconds.toFixed(1)}s`;
}

function updateMinOnDurationReadout() {
  if (!minOnDurationEl || !minOnDurationValueEl) return;
  minOnDurationEl.value = String(state.minOnDurationSeconds);
  minOnDurationValueEl.textContent = `${state.minOnDurationSeconds.toFixed(1)}s`;
}

function updateRmsGateReadout() {
  if (rmsGateEnabledEl) rmsGateEnabledEl.checked = state.rmsGateEnabled;
  if (!rmsGateThresholdEl || !rmsGateThresholdValueEl) return;
  rmsGateThresholdEl.value = String(state.rmsGateThresholdDb);
  rmsGateThresholdEl.disabled = !state.activityScoringEnabled || !state.rmsGateEnabled || !state.bssActivity;
  rmsGateThresholdValueEl.textContent = `${state.rmsGateThresholdDb.toFixed(0)} dBFS`;
}

function updateFadeDurationReadout() {
  if (!fadeDurationEl || !fadeDurationValueEl) return;
  fadeDurationEl.value = String(state.fadeDurationSeconds);
  fadeDurationValueEl.textContent = `${state.fadeDurationSeconds.toFixed(1)}s`;
}

function getCurrentActivitySources() {
  if (!state.bssActivity || !state.bssActivity.algorithms) return [];
  const algorithm = state.bssActivity.algorithms[state.bssAlgorithm];
  return algorithm ? algorithm.sources : [];
}

function enabledMapFromTrackIds(trackIds) {
  const enabled = Object.fromEntries(state.tracks.map((track) => [track.id, false]));
  for (const trackId of trackIds) {
    if (enabled[trackId] !== undefined) enabled[trackId] = true;
  }
  return enabled;
}

function enabledKeyFromTrackIds(trackIds) {
  return [...new Set(trackIds)].sort().join("|");
}

function gateKeyFromTrackIds(trackIds) {
  return enabledKeyFromTrackIds(trackIds) || DISABLED_GATE_KEY;
}

function cloneGateRun(segment) {
  return { ...segment, trackIds: [...segment.trackIds] };
}

function getOriginalRmsDb(trackId, frameIndex, frameStart = null) {
  const series = state.originalRms && state.originalRms.series ? state.originalRms.series[trackId] : null;
  const values = series ? series.rmsDbfs : null;
  if (!values) return null;
  let valueIndex = frameIndex;
  if (Number.isFinite(frameStart) && state.originalRms && Array.isArray(state.originalRms.starts)) {
    const starts = state.originalRms.starts;
    const hop = state.originalRms.settings ? state.originalRms.settings.hopSeconds : null;
    if (Number.isFinite(hop) && hop > 0 && starts.length > 0) {
      valueIndex = Math.round((frameStart - starts[0]) / hop);
    }
  }
  if (values[valueIndex] === undefined) return null;
  const value = Number(values[valueIndex]);
  return Number.isFinite(value) ? value : null;
}

function passesOriginalRmsGate(trackId, frameIndex, frameStart = null) {
  if (!state.rmsGateEnabled) return true;
  const rmsDb = getOriginalRmsDb(trackId, frameIndex, frameStart);
  if (rmsDb === null) return true;
  return rmsDb >= state.rmsGateThresholdDb;
}

function getFallbackTrackId(sources, frameScores) {
  if (!sources.length) return null;
  let bestIndex = 0;
  let bestScore = frameScores[0] || 0;
  for (let index = 1; index < sources.length; index += 1) {
    const score = frameScores[index] || 0;
    if (score > bestScore) {
      bestIndex = index;
      bestScore = score;
    }
  }
  if (bestScore < state.fallbackMinScore) return null;
  return sources[bestIndex].matchedTrack;
}

function getFrameActiveTrackIds(sources, frameScores, frameIndex, frameStart = null) {
  const maxScore = frameScores.reduce((max, score) => Math.max(max, score), 0);
  const activeTrackIds = [];

  if (state.thresholdGateEnabled) {
    for (let sourceIndex = 0; sourceIndex < sources.length; sourceIndex += 1) {
      const source = sources[sourceIndex];
      const score = frameScores[sourceIndex];
      if (score >= state.activityThreshold && score >= maxScore - state.dominanceMargin) {
        activeTrackIds.push(source.matchedTrack);
      }
    }
  }

  if (activeTrackIds.length === 0 && state.fallbackGateEnabled) {
    const fallbackTrackId = getFallbackTrackId(sources, frameScores);
    if (fallbackTrackId) activeTrackIds.push(fallbackTrackId);
  }

  return [...new Set(activeTrackIds)].filter((trackId) => passesOriginalRmsGate(trackId, frameIndex, frameStart)).sort();
}

function buildFrameDecisions(sources, starts, hopSeconds, duration) {
  return starts.map((start, index) => {
    const frameScores = sources.map((source) => source.scores[index] || 0);
    const trackIds = getFrameActiveTrackIds(sources, frameScores, index, start);
    return {
      start,
      end: Math.min(duration, start + hopSeconds),
      trackIds,
      key: gateKeyFromTrackIds(trackIds),
    };
  });
}

function buildSegmentsFromFrameDecisions(frames) {
  const segments = [];
  let current = null;

  for (const frame of frames) {
    if (current && current.key === frame.key && frame.start - current.end <= AUTO_GATE_TIME_EPSILON) {
      current.end = frame.end;
    } else {
      if (current) segments.push(current);
      current = {
        key: frame.key,
        start: frame.start,
        end: frame.end,
        trackIds: [...frame.trackIds],
      };
    }
  }

  if (current) segments.push(current);
  return segments;
}

function mergeGateRuns(segments) {
  const merged = [];
  for (const segment of segments) {
    const previous = merged[merged.length - 1];
    if (previous && previous.key === segment.key && segment.start - previous.end <= AUTO_GATE_MERGE_GAP_SECONDS) {
      previous.end = segment.end;
    } else {
      merged.push(cloneGateRun(segment));
    }
  }
  return merged;
}

function smoothShortGateRuns(segments) {
  let smoothed = mergeGateRuns(segments);
  let changed = true;
  while (changed && smoothed.length > 1) {
    changed = false;
    const next = [];
    for (let index = 0; index < smoothed.length; index += 1) {
      const segment = cloneGateRun(smoothed[index]);
      if (segment.end - segment.start >= AUTO_GATE_MIN_SECONDS) {
        next.push(segment);
        continue;
      }

      const previous = next[next.length - 1];
      const following = smoothed[index + 1];
      if (previous && following) {
        const previousDuration = previous.end - previous.start;
        const followingDuration = following.end - following.start;
        if (followingDuration > previousDuration) {
          following.start = segment.start;
        } else {
          previous.end = segment.end;
        }
      } else if (previous) {
        previous.end = segment.end;
      } else if (following) {
        following.start = segment.start;
      } else {
        next.push(segment);
      }
      changed = true;
    }
    smoothed = mergeGateRuns(next);
  }

  return smoothed;
}

function setMaskRange(mask, startIndex, endIndex, value) {
  for (let index = startIndex; index < endIndex; index += 1) {
    mask[index] = value;
  }
}

function smoothInactiveMaskGaps(mask, frames) {
  const smoothed = [...mask];
  let runStart = 0;

  while (runStart < mask.length) {
    const value = mask[runStart];
    let runEnd = runStart + 1;
    while (runEnd < mask.length && mask[runEnd] === value) runEnd += 1;

    const duration = frames[runEnd - 1].end - frames[runStart].start;
    const hasEnabledBefore = runStart > 0 && mask[runStart - 1];
    const hasEnabledAfter = runEnd < mask.length && mask[runEnd];
    if (!value && hasEnabledBefore && hasEnabledAfter && duration <= state.offGapFillSeconds) {
      setMaskRange(smoothed, runStart, runEnd, true);
    }

    runStart = runEnd;
  }

  return smoothed;
}

function removeShortActiveMaskRuns(mask, frames) {
  const smoothed = [...mask];
  let runStart = 0;

  while (runStart < mask.length) {
    const value = mask[runStart];
    let runEnd = runStart + 1;
    while (runEnd < mask.length && mask[runEnd] === value) runEnd += 1;

    const duration = frames[runEnd - 1].end - frames[runStart].start;
    if (value && duration < state.minOnDurationSeconds) {
      setMaskRange(smoothed, runStart, runEnd, false);
    }

    runStart = runEnd;
  }

  return smoothed;
}

function smoothTrackMask(mask, frames) {
  let smoothed = smoothInactiveMaskGaps(mask, frames);
  smoothed = removeShortActiveMaskRuns(smoothed, frames);
  return smoothInactiveMaskGaps(smoothed, frames);
}

function buildCombinationRunSegments(frames, duration) {
  const smoothed = smoothShortGateRuns(buildSegmentsFromFrameDecisions(frames));
  return smoothed;
}

function buildTrackMaskSegments(frames, duration) {
  const masksByTrack = Object.fromEntries(
    state.tracks.map((track) => [track.id, frames.map((frame) => frame.trackIds.includes(track.id))])
  );

  for (const track of state.tracks) {
    masksByTrack[track.id] = smoothTrackMask(masksByTrack[track.id], frames);
  }

  for (let frameIndex = 0; frameIndex < frames.length; frameIndex += 1) {
    const hasEnabledTrack = state.tracks.some((track) => masksByTrack[track.id][frameIndex]);
    if (!hasEnabledTrack) {
      for (const trackId of frames[frameIndex].trackIds) {
        masksByTrack[trackId][frameIndex] = true;
      }
    }
  }

  const smoothedFrames = frames.map((frame, frameIndex) => {
    const trackIds = state.tracks
      .filter((track) => masksByTrack[track.id][frameIndex])
      .map((track) => track.id);
    return {
      start: frame.start,
      end: frame.end,
      trackIds,
      key: gateKeyFromTrackIds(trackIds),
    };
  });

  const segments = buildSegmentsFromFrameDecisions(smoothedFrames);
  return segments;
}

function mergeTimeIntervals(intervals) {
  const sorted = intervals
    .filter((interval) => interval.end - interval.start > AUTO_GATE_TIME_EPSILON)
    .sort((a, b) => a.start - b.start);
  const merged = [];

  for (const interval of sorted) {
    const previous = merged[merged.length - 1];
    if (previous && interval.start <= previous.end + AUTO_GATE_TIME_EPSILON) {
      previous.end = Math.max(previous.end, interval.end);
    } else {
      merged.push({ ...interval });
    }
  }

  return merged;
}

function buildPaddedTrackIntervals(segments, duration) {
  const intervalsByTrack = Object.fromEntries(state.tracks.map((track) => [track.id, []]));

  for (const segment of segments) {
    for (const trackId of segment.trackIds) {
      intervalsByTrack[trackId].push({
        start: Math.max(0, segment.start - AUTO_GATE_PRE_ROLL_SECONDS),
        end: Math.min(duration, segment.end + AUTO_GATE_RELEASE_SECONDS),
      });
    }
  }

  for (const track of state.tracks) {
    intervalsByTrack[track.id] = mergeTimeIntervals(intervalsByTrack[track.id]);
  }

  return intervalsByTrack;
}

function isTimeInIntervals(time, intervals) {
  return intervals.some((interval) => time >= interval.start && time < interval.end);
}

function normalizeAutoGateSegments(segments, duration, rangeStart = 0, rangeEnd = duration) {
  const intervalsByTrack = buildPaddedTrackIntervals(segments, duration);
  const boundaries = [rangeStart, rangeEnd];

  for (const intervals of Object.values(intervalsByTrack)) {
    for (const interval of intervals) {
      boundaries.push(interval.start, interval.end);
    }
  }

  boundaries.sort((a, b) => a - b);
  const uniqueBoundaries = [];
  for (const boundary of boundaries) {
    const clamped = Math.max(rangeStart, Math.min(rangeEnd, boundary));
    const previous = uniqueBoundaries[uniqueBoundaries.length - 1];
    if (previous === undefined || clamped - previous > AUTO_GATE_TIME_EPSILON) {
      uniqueBoundaries.push(clamped);
    }
  }

  const normalized = [];
  for (let index = 0; index < uniqueBoundaries.length - 1; index += 1) {
    const start = uniqueBoundaries[index];
    const end = uniqueBoundaries[index + 1];
    if (end - start <= AUTO_GATE_TIME_EPSILON) continue;

    const midpoint = (start + end) / 2;
    const trackIds = state.tracks
      .filter((track) => isTimeInIntervals(midpoint, intervalsByTrack[track.id]))
      .map((track) => track.id);
    const key = gateKeyFromTrackIds(trackIds);

    const previous = normalized[normalized.length - 1];
    if (previous && previous.key === key && start - previous.end <= AUTO_GATE_TIME_EPSILON) {
      previous.end = end;
    } else {
      normalized.push({ key, start, end, trackIds });
    }
  }

  return normalized.map((segment) => ({
    id: `auto-${segment.start.toFixed(3)}-${segment.key}`,
    kind: "auto",
    start: segment.start,
    end: segment.end,
    enabled: enabledMapFromTrackIds(segment.trackIds),
  }));
}

function recomputeAutoGateSegments() {
  if (!state.activityScoringEnabled || !state.bssActivity || state.tracks.length === 0) {
    state.autoGateSegments = [];
    return;
  }

  const sources = getCurrentActivitySources();
  const starts = state.bssActivity.starts || [];
  if (sources.length === 0 || starts.length === 0) {
    state.autoGateSegments = [];
    return;
  }
  const hopSeconds = state.bssActivity.settings ? state.bssActivity.settings.hopSeconds : 0.1;

  const duration = state.duration || state.bssActivity.duration;
  const availableStart = starts[0] || 0;
  const availableEnd = Math.min(duration, (starts[starts.length - 1] || availableStart) + hopSeconds);
  const configuredRange = getConfiguredAnalysisRange(duration);
  const rangeStart = Math.max(availableStart, configuredRange.start);
  const rangeEnd = Math.min(availableEnd, configuredRange.end);
  if (rangeEnd <= rangeStart) {
    state.autoGateSegments = [];
    return;
  }

  const frames = buildFrameDecisions(sources, starts, hopSeconds, duration)
    .filter((frame) => frame.end > rangeStart && frame.start < rangeEnd)
    .map((frame) => ({
      ...frame,
      start: Math.max(frame.start, rangeStart),
      end: Math.min(frame.end, rangeEnd),
    }))
    .filter((frame) => frame.end - frame.start > AUTO_GATE_TIME_EPSILON);
  if (frames.length === 0) {
    state.autoGateSegments = [];
    return;
  }
  const decisionSegments = buildSegmentsFromFrameDecisions(frames);
  const smoothedSegments =
    !state.smoothingEnabled
      ? decisionSegments
      : state.smoothingMode === "combination-runs"
      ? buildCombinationRunSegments(frames, duration)
      : buildTrackMaskSegments(frames, duration);

  state.autoGateSegments = normalizeAutoGateSegments(smoothedSegments, duration, rangeStart, rangeEnd);
}

function applyAutoGatesToSegments() {
  if (!state.autoGateSegments.length) return;
  state.segments = state.segments.filter((segment) => segment.kind !== "auto");
  state.segments.push(
    ...state.autoGateSegments.map((segment) => ({
      ...segment,
      id: crypto.randomUUID(),
      kind: "auto",
    }))
  );
  state.segments.sort((a, b) => a.start - b.start);
  state.autoGatePreview = false;
  if (autoGatePreviewEl) autoGatePreviewEl.checked = false;
  renderSegments();
  renderSegmentList();
  renderBssPanel();
  updateAudioGates();
}

function clearAutoGates() {
  state.segments = state.segments.filter((segment) => segment.kind !== "auto");
  state.autoGatePreview = false;
  if (autoGatePreviewEl) autoGatePreviewEl.checked = false;
  recomputeAutoGateSegments();
  renderSegments();
  renderSegmentList();
  renderBssPanel();
  updateAudioGates();
}

function redrawBssWaveforms() {
  for (const canvas of bssTimelineEl.querySelectorAll("canvas.bss-waveform")) {
    const row = canvas.closest(".bss-row");
    const sourceIndex = row ? Number(row.dataset.sourceIndex) : null;
    const track = state.bssTracks.find((item) => item.sourceIndex === sourceIndex);
    if (track) drawWaveform(canvas, track);
  }
  for (const canvas of bssTimelineEl.querySelectorAll("canvas.activity-canvas")) {
    const row = canvas.closest(".activity-row");
    const sourceIndex = row ? Number(row.dataset.sourceIndex) : null;
    const source = getCurrentActivitySources().find((item) => item.source === sourceIndex);
    if (source) drawActivityCanvas(canvas, source);
  }
}

function getBssRangeText() {
  if (!state.bssRange) return "No BSS cache loaded.";
  return `${formatTime(state.bssRange.start)} - ${formatTime(state.bssRange.end)} (${Math.round(state.bssRange.duration)}s)`;
}

function getBssSummaryText() {
  if (!state.bssActivity) {
    return "분석이 아직 없습니다. RMS 기반으로 바로 필터링하려면 Use RMS Filter, 선택 구간 BSS를 만들려면 Run AuxIVA를 누르세요.";
  }
  const algorithm = getBssAlgorithmById(state.bssAlgorithm);
  const settings = state.bssActivity ? state.bssActivity.settings : null;
  if (!settings) return "Loading source activity analysis...";
  if (!state.activityScoringEnabled) {
    return `${algorithm.name} · activity score disabled · no auto gate proposals · ${settings.windowSeconds}s window / ${settings.hopSeconds}s hop`;
  }
  const rangeLabel = getAnalysisRangeLabel();
  const thresholdLabel = state.thresholdGateEnabled
    ? `threshold ${state.activityThreshold.toFixed(2)} · margin ${state.dominanceMargin.toFixed(2)}`
    : "threshold off";
  const fallbackLabel = state.fallbackGateEnabled
    ? `fallback on >= ${state.fallbackMinScore.toFixed(2)}`
    : "fallback off";
  const smoothingLabel = state.smoothingEnabled
    ? `${state.smoothingMode === "combination-runs" ? "combination runs" : "track mask"} smoothing · off gap ${state.offGapFillSeconds.toFixed(1)}s · min on ${state.minOnDurationSeconds.toFixed(1)}s`
    : "smoothing off";
  const rmsLabel = state.rmsGateEnabled ? `original RMS >= ${state.rmsGateThresholdDb.toFixed(0)} dBFS` : "original RMS off";
  if (state.bssAlgorithm === "local-rms") {
    return `${algorithm.name} · ${rangeLabel} · ${thresholdLabel} · ${fallbackLabel} · ${rmsLabel} · ${smoothingLabel} · ${state.fadeDurationSeconds.toFixed(1)}s linear fade · ${settings.windowSeconds}s window / ${settings.hopSeconds}s hop`;
  }
  return `${algorithm.name} BSS cache ${getBssRangeText()} · gate ${rangeLabel} · ${thresholdLabel} · ${fallbackLabel} · ${rmsLabel} · ${smoothingLabel} · ${state.fadeDurationSeconds.toFixed(1)}s linear fade · ${settings.windowSeconds}s window / ${settings.hopSeconds}s hop`;
}

function getAutoGateStats() {
  const muted = state.autoGateSegments.filter((segment) => !Object.values(segment.enabled).some(Boolean)).length;
  return {
    enabled: state.autoGateSegments.length - muted,
    muted,
  };
}

function renderBssPanel() {
  if (!bssPanelEl) return;

  const algorithm = state.bssActivity ? getBssAlgorithmById(state.bssAlgorithm) : null;
  if (algorithm && bssAlgorithmEl.value !== algorithm.id) bssAlgorithmEl.value = algorithm.id;
  if (smoothingModeEl.value !== state.smoothingMode) smoothingModeEl.value = state.smoothingMode;
  updatePipelineReadouts();
  updateFadeDurationReadout();
  bssInspectorNoteEl.textContent = getBssSummaryText();
  bssSummaryEl.textContent = getBssSummaryText();
  bssTimelineEl.innerHTML = "";
  bssTimelineEl.style.width = `${state.timelineWidth + TRACK_LABEL_WIDTH + 36}px`;
  if (runBssAnalysisEl) {
    runBssAnalysisEl.disabled = !state.projectLoaded || !state.sessionManifest || state.bssAnalyzing;
    runBssAnalysisEl.textContent = state.bssAnalyzing ? "Running..." : "Run AuxIVA";
  }
  if (useRmsFilterEl) {
    useRmsFilterEl.disabled = !state.projectLoaded || !state.originalRms || state.bssAnalyzing;
    useRmsFilterEl.textContent = state.bssAlgorithm === "local-rms" ? "RMS Active" : "Use RMS Filter";
  }
  if (bssPlayPauseEl) {
    bssPlayPauseEl.disabled = state.bssTracks.length === 0;
    bssPlayPauseEl.textContent = "Play BSS";
  }
  if (bssStopEl) bssStopEl.disabled = state.bssTracks.length === 0;
  if (applyAutoGatesEl) applyAutoGatesEl.disabled = !state.activityScoringEnabled || !state.autoGateSegments.length;
  if (activityStatsEl) {
    const stats = getAutoGateStats();
    activityStatsEl.textContent = state.bssActivity
      ? `${stats.enabled} enabled proposals · ${stats.muted} muted gaps · preview ${state.autoGatePreview ? "on" : "off"}`
      : "BSS not generated";
  }

  if (state.bssLoading) {
    bssStatusEl.hidden = false;
    bssStatusEl.textContent = "Loading activity analysis...";
    return;
  }

  if (state.bssError) {
    bssStatusEl.hidden = false;
    bssStatusEl.textContent = `Failed to load activity analysis: ${state.bssError}`;
    return;
  }

  const sources = getCurrentActivitySources();
  if (sources.length === 0) {
    bssStatusEl.hidden = false;
    bssStatusEl.textContent = "No analysis loaded. Use RMS Filter for instant gating, or Run AuxIVA for BSS.";
    return;
  }

  bssStatusEl.hidden = true;
  for (const track of state.bssTracks) {
    renderBssTrackRow(track);
  }
  for (const source of sources) {
    renderActivityRow(source);
  }
  renderBssCursor();
}

function renderBssTrackRow(track) {
  const row = document.createElement("div");
  row.className = "bss-row";
  row.dataset.sourceIndex = String(track.sourceIndex);

  const label = document.createElement("div");
  label.className = "bss-label";
  const mapping = track.mapping;
  const mappedLabel = mapping ? mapping.best_label : "unmapped";
  const confidence = mapping ? `corr ${mapping.envelope_corr.toFixed(2)} · margin ${mapping.margin_to_second.toFixed(2)}` : "mapping pending";
  label.innerHTML = `
    <strong>${track.name}</strong>
    <span>${mappedLabel}</span>
    <small>${confidence}</small>
  `;

  const wrap = document.createElement("div");
  wrap.className = "bss-wave-wrap";
  wrap.style.width = `${state.timelineWidth}px`;
  const range = state.bssRange || { start: 0, end: state.duration };
  const rangeStart = Math.max(range.start, getTimelineWindowStart());
  const rangeEnd = Math.min(range.end, getTimelineWindowEnd());
  const left = timeToLocalX(rangeStart);
  const width = rangeEnd > rangeStart ? Math.max(2, timeToLocalX(rangeEnd) - timeToLocalX(rangeStart)) : 0;
  const segment = document.createElement("div");
  segment.className = "bss-wave-segment";
  segment.style.left = `${left}px`;
  segment.style.width = `${width}px`;

  const canvas = document.createElement("canvas");
  canvas.className = "bss-waveform";
  canvas.width = Math.max(1, Math.min(MAX_CANVAS_DRAW_WIDTH, Math.round(width)));
  canvas.height = 92;
  if (width > 0) {
    segment.appendChild(canvas);
    wrap.appendChild(segment);
    drawWaveform(canvas, track);
  }

  for (const rangeItem of getTrackGateRanges(state.autoGateSegments, mapping ? `track${mapping.best_input}` : "", true)) {
    appendTimedOverlay(wrap, "activity-proposal-overlay", rangeItem.start, rangeItem.end, 2);
  }

  wrap.addEventListener("click", (event) => {
    const rect = wrap.getBoundingClientRect();
    seek(localXToTime(event.clientX - rect.left));
  });

  row.append(label, wrap);
  bssTimelineEl.appendChild(row);
}

function renderActivityRow(source) {
  const row = document.createElement("div");
  row.className = "activity-row";
  row.dataset.sourceIndex = String(source.source);

  const label = document.createElement("div");
  label.className = "activity-label";
  label.innerHTML = `
    <strong>${source.matchedLabel}</strong>
    <span>Source ${source.source} -> ${source.matchedTrack}</span>
    <small>match ${source.matchConfidence.toFixed(2)} · margin ${source.matchMargin.toFixed(2)}</small>
    <small>noise ${source.normalization.noiseDbfs.toFixed(1)} · active ${source.normalization.activeDbfs.toFixed(1)} dBFS</small>
  `;

  const wrap = document.createElement("div");
  wrap.className = "activity-wrap";
  wrap.style.width = `${state.timelineWidth}px`;

  const canvas = document.createElement("canvas");
  canvas.className = "activity-canvas";
  canvas.width = getCanvasDrawWidth();
  canvas.height = 76;
  wrap.appendChild(canvas);
  drawActivityCanvas(canvas, source);

  for (const range of getTrackGateRanges(state.autoGateSegments, source.matchedTrack, true)) {
    appendTimedOverlay(wrap, "activity-proposal-overlay", range.start, range.end, 2);
  }

  wrap.addEventListener("click", (event) => {
    const rect = wrap.getBoundingClientRect();
    seek(localXToTime(event.clientX - rect.left));
  });

  row.append(label, wrap);
  bssTimelineEl.appendChild(row);
}

function renderBssCursor() {
  const cursor = document.createElement("div");
  cursor.className = "bss-cursor";
  cursor.id = "bssCursor";
  const localX = timeToLocalX(state.playhead);
  cursor.style.left = `${getWaveOriginX(bssTimelineEl, ".activity-wrap") + localX}px`;
  cursor.hidden = localX < 0 || localX > state.timelineWidth;
  bssTimelineEl.appendChild(cursor);
}

function drawActivityCanvas(canvas, source) {
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const scores = source.scores;
  const thresholdY = height - state.activityThreshold * height;
  const starts = state.bssActivity && Array.isArray(state.bssActivity.starts) ? state.bssActivity.starts : [];
  const hopSeconds = state.bssActivity && state.bssActivity.settings ? state.bssActivity.settings.hopSeconds || ACTIVITY_HOP_SECONDS : ACTIVITY_HOP_SECONDS;
  const firstStart = starts.length ? starts[0] : 0;
  const viewStart = getTimelineWindowStart();
  const viewEnd = getTimelineWindowEnd();
  const scoreIndexAtTime = (time) => Math.max(0, Math.min(scores.length - 1, Math.round((time - firstStart) / hopSeconds)));

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#121617";
  ctx.fillRect(0, 0, width, height);
  if (!scores.length) return;

  for (let x = 0; x < width; x += 1) {
    const timeStart = viewStart + (x / width) * (viewEnd - viewStart);
    const timeEnd = viewStart + ((x + 1) / width) * (viewEnd - viewStart);
    const start = scoreIndexAtTime(timeStart);
    const end = Math.max(start + 1, scoreIndexAtTime(timeEnd));
    let value = 0;
    for (let index = start; index < end && index < scores.length; index += 1) {
      value = Math.max(value, scores[index] || 0);
    }
    ctx.fillStyle = `rgba(232, 193, 91, ${0.08 + value * 0.5})`;
    ctx.fillRect(x, 0, 1, height);
  }

  ctx.strokeStyle = "rgba(255,255,255,0.12)";
  ctx.lineWidth = 1;
  for (const value of [0.25, 0.5, 0.75]) {
    const y = height - value * height;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }

  if (state.activityScoringEnabled && state.thresholdGateEnabled) {
    ctx.strokeStyle = "#e36b5d";
    ctx.setLineDash([5, 4]);
    ctx.beginPath();
    ctx.moveTo(0, thresholdY);
    ctx.lineTo(width, thresholdY);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  ctx.strokeStyle = getTrackColor(source.matchedTrack);
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  for (let x = 0; x < width; x += 1) {
    const time = viewStart + (x / width) * (viewEnd - viewStart);
    const index = scoreIndexAtTime(time);
    const y = height - (scores[index] || 0) * height;
    if (x === 0) ctx.moveTo(x + 0.5, y);
    else ctx.lineTo(x + 0.5, y);
  }
  ctx.stroke();
}

function updateReadouts() {
  timecodeEl.textContent = formatTime(state.playhead);
  durationEl.textContent = formatTime(state.duration);
  if (state.selection && state.selection.start !== state.selection.end) {
    const start = Math.min(state.selection.start, state.selection.end);
    const end = Math.max(state.selection.start, state.selection.end);
    selectionReadoutEl.textContent = `${formatTime(start)} - ${formatTime(end)}`;
  } else {
    selectionReadoutEl.textContent = "none";
  }
}

function findSegmentAt(segments, time) {
  for (let index = segments.length - 1; index >= 0; index -= 1) {
    const segment = segments[index];
    if (time >= segment.start && time < segment.end) return segment;
  }
  return null;
}

function getActiveSegment(time) {
  if (state.autoGatePreview) {
    const autoSegment = findSegmentAt(state.autoGateSegments, time);
    if (autoSegment) return autoSegment;
  }
  return findSegmentAt(state.segments, time);
}

function getPlaybackGateSegments() {
  if (state.autoGatePreview && state.autoGateSegments.length > 0) return state.autoGateSegments;
  return state.segments;
}

function getTrackGateGain(trackId, time) {
  const segments = getPlaybackGateSegments();
  if (segments.length === 0) return 1;
  const fadeSeconds = state.fadeDurationSeconds;

  const activeSegment = findSegmentAt(segments, time);
  let gain = activeSegment ? (activeSegment.enabled[trackId] ? 1 : 0) : 1;
  if (fadeSeconds <= AUDIO_GATE_MUTE_EPSILON) return gain;

  for (const segment of segments) {
    if (!segment.enabled[trackId]) continue;
    if (time >= segment.start && time < segment.end) {
      gain = Math.max(gain, 1);
    } else if (time >= segment.start - fadeSeconds && time < segment.start) {
      gain = Math.max(gain, (time - (segment.start - fadeSeconds)) / fadeSeconds);
    } else if (time >= segment.end && time < segment.end + fadeSeconds) {
      gain = Math.max(gain, 1 - (time - segment.end) / fadeSeconds);
    }
  }

  return Math.max(0, Math.min(1, gain));
}

function updateAudioGates() {
  const hasSolo = state.tracks.some((track) => track.solo);
  for (const track of state.tracks) {
    const gateGain = getTrackGateGain(track.id, state.playhead);
    const audible = track.enabled && gateGain > AUDIO_GATE_MUTE_EPSILON && (!hasSolo || track.solo);
    track.audio.muted = !audible;
    track.audio.volume = audible ? track.volume * gateGain : 0;
  }
}

function updateBssAudioGates() {
  const hasSolo = state.bssTracks.some((track) => track.solo);
  for (const track of state.bssTracks) {
    const audible = track.enabled && (!hasSolo || track.solo);
    track.audio.muted = !audible;
    track.audio.volume = audible ? track.volume : 0;
  }
}

function syncAudioTo(time) {
  for (const track of state.tracks) {
    if (Math.abs(track.audio.currentTime - time) > 0.08) {
      track.audio.currentTime = time;
    }
  }
}

function syncBssAudioTo(time) {
  const rangeStart = state.bssRange ? state.bssRange.start : 0;
  const rangeEnd = state.bssRange ? state.bssRange.end : state.duration;
  const localTime = Math.max(0, Math.min(rangeEnd - rangeStart, time - rangeStart));
  for (const track of state.bssTracks) {
    if (Math.abs(track.audio.currentTime - localTime) > 0.08) {
      track.audio.currentTime = localTime;
    }
  }
}

async function play() {
  pauseBss();
  syncAudioTo(state.playhead);
  updateAudioGates();
  try {
    await Promise.all(state.tracks.map((track) => track.audio.play()));
    state.isPlaying = true;
    playPauseEl.textContent = "Pause";
  } catch (error) {
    pause();
    console.warn("Original playback was blocked or failed.", error);
  }
}

function pause() {
  for (const track of state.tracks) track.audio.pause();
  state.isPlaying = false;
  playPauseEl.textContent = "Play";
}

function stop() {
  pause();
  pauseBss();
  seek(0);
}

function togglePlayback() {
  if (state.isPlaying) pause();
  else play();
}

function seek(time) {
  state.playhead = Math.max(0, Math.min(state.duration, time));
  ensureTimelineWindowContains(state.playhead);
  for (const track of state.tracks) {
    track.audio.currentTime = state.playhead;
  }
  syncBssAudioTo(state.playhead);
  updateAudioGates();
  updateBssAudioGates();
  updateCursorOnly();
  updateReadouts();
}

function updateCursorOnly() {
  const cursor = $("#cursor");
  if (cursor) {
    const localX = timeToLocalX(state.playhead);
    cursor.style.left = `${getWaveOriginX(timelineEl, ".wave-wrap") + localX}px`;
    cursor.hidden = localX < 0 || localX > state.timelineWidth;
  }
  const bssCursor = $("#bssCursor");
  if (bssCursor) {
    const localX = timeToLocalX(state.playhead);
    bssCursor.style.left = `${getWaveOriginX(bssTimelineEl, ".activity-wrap") + localX}px`;
    bssCursor.hidden = localX < 0 || localX > state.timelineWidth;
  }
}

async function playBss() {
  if (state.bssTracks.length === 0 || state.bssError) return;
  if (state.bssRange && (state.playhead < state.bssRange.start || state.playhead >= state.bssRange.end)) {
    seek(state.bssRange.start);
  }
  pause();
  syncBssAudioTo(state.playhead);
  updateBssAudioGates();
  try {
    await Promise.all(state.bssTracks.map((track) => track.audio.play()));
    state.bssIsPlaying = true;
    if (bssPlayPauseEl) bssPlayPauseEl.textContent = "Pause BSS";
  } catch (error) {
    pauseBss();
    console.warn("BSS playback was blocked or failed.", error);
  }
}

function pauseBss() {
  for (const track of state.bssTracks) track.audio.pause();
  state.bssIsPlaying = false;
  if (bssPlayPauseEl) bssPlayPauseEl.textContent = "Play BSS";
}

function stopBss() {
  pauseBss();
  seek(state.bssRange ? state.bssRange.start : 0);
}

function toggleBssPlayback() {
  if (state.bssIsPlaying) pauseBss();
  else playBss();
}

function tick() {
  if (state.isPlaying) {
    state.playhead = state.tracks[0].audio.currentTime;
    ensureTimelineWindowContains(state.playhead);
    if (state.loop && state.selection && state.selection.start !== state.selection.end) {
      const start = Math.min(state.selection.start, state.selection.end);
      const end = Math.max(state.selection.start, state.selection.end);
      if (state.playhead >= end) seek(start);
    }
    if (state.playhead >= state.duration - 0.05) {
      stop();
    }
    updateAudioGates();
    updateCursorOnly();
    updateReadouts();
  } else if (state.bssIsPlaying) {
    const rangeStart = state.bssRange ? state.bssRange.start : 0;
    const rangeEnd = state.bssRange ? state.bssRange.end : state.duration;
    state.playhead = rangeStart + state.bssTracks[0].audio.currentTime;
    ensureTimelineWindowContains(state.playhead);
    if (state.loop && state.selection && state.selection.start !== state.selection.end) {
      const start = Math.min(state.selection.start, state.selection.end);
      const end = Math.max(state.selection.start, state.selection.end);
      if (state.playhead >= end) seek(start);
    }
    if (state.playhead >= rangeEnd - 0.05) {
      stopBss();
    }
    updateBssAudioGates();
    updateCursorOnly();
    updateReadouts();
  }
  requestAnimationFrame(tick);
}

function createSegmentFromSelection() {
  if (!state.selection || state.selection.start === state.selection.end) return;
  const start = Math.min(state.selection.start, state.selection.end);
  const end = Math.max(state.selection.start, state.selection.end);
  const enabled = Object.fromEntries(state.tracks.map((track) => [track.id, true]));
  state.segments.push({
    id: crypto.randomUUID(),
    start,
    end,
    enabled,
  });
  state.segments.sort((a, b) => a.start - b.start);
  renderSegments();
  renderSegmentList();
}

function downloadSegments() {
  const payload = {
    duration: state.duration,
    tracks: state.tracks.map(({ id, name, speaker, audioSrc }) => ({ id, name, speaker, audio: audioSrc })),
    segments: state.segments,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "appa-gate-segments.json";
  link.click();
  URL.revokeObjectURL(url);
}

window.addEventListener("mousemove", (event) => {
  if (!state.drag) return;
  const trackRow = timelineEl.querySelector(".track-row");
  const wrap = trackRow ? trackRow.querySelector(".wave-wrap") : null;
  if (!wrap) return;
  const rect = wrap.getBoundingClientRect();
  const endX = clampWaveX(event.clientX - rect.left);
  state.drag.moved = state.drag.moved || Math.abs(endX - state.drag.startX) > DRAG_THRESHOLD_PX;
  state.drag.end = localXToTime(endX);
  if (state.drag.moved) {
    state.selection = { start: state.drag.start, end: state.drag.end };
    renderSelection();
    updateReadouts();
  }
});

window.addEventListener("mouseup", () => {
  if (state.drag && state.drag.moved) {
    state.suppressClick = true;
    window.setTimeout(() => {
      state.suppressClick = false;
    }, 0);
  }
  state.drag = null;
});

timelineEl.addEventListener("click", (event) => {
  if (state.drag || state.suppressClick) return;
  const wrap = event.target.closest(".wave-wrap");
  if (!wrap) return;
  const rect = wrap.getBoundingClientRect();
  state.selection = null;
  renderSelection();
  seek(localXToTime(event.clientX - rect.left));
});

playPauseEl.addEventListener("click", togglePlayback);
if (prevTimelineWindowEl) prevTimelineWindowEl.addEventListener("click", () => shiftTimelineWindow(-1));
if (nextTimelineWindowEl) nextTimelineWindowEl.addEventListener("click", () => shiftTimelineWindow(1));

window.addEventListener("keydown", (event) => {
  if (event.code !== "Space" && event.key !== " ") return;

  const target = event.target;
  const isTextInput =
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement ||
    (target instanceof HTMLInputElement && !["button", "checkbox", "range"].includes(target.type)) ||
    (target && target.isContentEditable);

  if (isTextInput) return;

  event.preventDefault();
  if (!event.repeat) togglePlayback();
});

stopEl.addEventListener("click", stop);

loopEl.addEventListener("click", () => {
  state.loop = !state.loop;
  loopEl.setAttribute("aria-pressed", String(state.loop));
});

zoomEl.addEventListener("input", (event) => {
  setZoom(event.target.value);
});

$("#zoomOut").addEventListener("click", () => {
  setZoom(state.zoom - getZoomButtonStep());
});

$("#zoomIn").addEventListener("click", () => {
  setZoom(state.zoom + getZoomButtonStep());
});

waveGainEl.addEventListener("input", (event) => {
  setWaveGain(event.target.value);
});

function openAudioFilePicker() {
  if (!audioFileInputEl || state.analyzing) return;
  audioFileInputEl.value = "";
  audioFileInputEl.click();
}

if (loadFilesButtonEl) loadFilesButtonEl.addEventListener("click", openAudioFilePicker);
if (loadProjectButtonEl) loadProjectButtonEl.addEventListener("click", () => loadPrecomputedSession([], { showInitialLoader: false }));
if (chooseAudioFilesEl) chooseAudioFilesEl.addEventListener("click", openAudioFilePicker);
if (loadProjectSessionEl) loadProjectSessionEl.addEventListener("click", () => loadPrecomputedSession());
if (audioFileInputEl) {
  audioFileInputEl.addEventListener("change", (event) => {
    loadLocalAudioFiles(event.target.files);
  });
}

bssAlgorithmEl.addEventListener("change", (event) => {
  setBssAlgorithm(event.target.value);
});

if (analysisRangeFullEl) analysisRangeFullEl.addEventListener("click", () => setAnalysisRange("full"));
if (analysisRangeFirst20El) {
  analysisRangeFirst20El.addEventListener("click", () => setAnalysisRange("first-20", 0, FIRST_20_MINUTES_SECONDS));
}
if (analysisRangeSelectionEl) analysisRangeSelectionEl.addEventListener("click", setAnalysisRangeFromSelection);

activityScoringEnabledEl.addEventListener("change", (event) => {
  setActivityScoringEnabled(event.target.checked);
});

thresholdGateEnabledEl.addEventListener("change", (event) => {
  setThresholdGateEnabled(event.target.checked);
});

smoothingModeEl.addEventListener("change", (event) => {
  setSmoothingMode(event.target.value);
});

smoothingEnabledEl.addEventListener("change", (event) => {
  setSmoothingEnabled(event.target.checked);
});

activityThresholdEl.addEventListener("input", (event) => {
  setActivityThreshold(event.target.value);
});

dominanceMarginEl.addEventListener("input", (event) => {
  setDominanceMargin(event.target.value);
});

fallbackGateEnabledEl.addEventListener("change", (event) => {
  setFallbackGateEnabled(event.target.checked);
});

fallbackMinScoreEl.addEventListener("input", (event) => {
  setFallbackMinScore(event.target.value);
});

offGapFillEl.addEventListener("input", (event) => {
  setOffGapFillSeconds(event.target.value);
});

minOnDurationEl.addEventListener("input", (event) => {
  setMinOnDurationSeconds(event.target.value);
});

rmsGateEnabledEl.addEventListener("change", (event) => {
  setRmsGateEnabled(event.target.checked);
});

rmsGateThresholdEl.addEventListener("input", (event) => {
  setRmsGateThresholdDb(event.target.value);
});

fadeDurationEl.addEventListener("input", (event) => {
  setFadeDurationSeconds(event.target.value);
});

autoGatePreviewEl.addEventListener("change", (event) => {
  state.autoGatePreview = event.target.checked;
  if (state.autoGatePreview && state.autoGateSegments.length === 0) {
    recomputeAutoGateSegments();
  }
  renderSegments();
  renderBssPanel();
  updateAudioGates();
});

applyAutoGatesEl.addEventListener("click", applyAutoGatesToSegments);
clearAutoGatesEl.addEventListener("click", clearAutoGates);

if (bssPlayPauseEl) bssPlayPauseEl.addEventListener("click", toggleBssPlayback);
if (bssStopEl) bssStopEl.addEventListener("click", stopBss);
if (useRmsFilterEl) useRmsFilterEl.addEventListener("click", useRmsFilter);
if (runBssAnalysisEl) runBssAnalysisEl.addEventListener("click", runBssAnalysis);

window.addEventListener("resize", renderBssPanel);

$("#createSegment").addEventListener("click", createSegmentFromSelection);
$("#clearSelection").addEventListener("click", () => {
  state.selection = null;
  renderSelection();
  updateReadouts();
});
$("#downloadJson").addEventListener("click", downloadSegments);

async function init() {
  if (window.location.protocol === "file:") return;
  populateBssAlgorithmOptions();
  updatePipelineReadouts();
  updateFadeDurationReadout();
  setAnalysisControlsEnabled(false);
  setProjectShellVisible(false);
  updateReadouts();
  setAnalysisStatus("아직 로드된 세션이 없습니다.", 0);
  requestAnimationFrame(tick);
}

init().catch((error) => {
  loadingEl.textContent = `Failed to load assets: ${error.message}`;
  console.error(error);
});
