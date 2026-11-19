const TEAM_LOGO_IDS = {"ATL": 1610612737, "BKN": 1610612751, "BOS": 1610612738, "CHA": 1610612766, "CHI": 1610612741, "CLE": 1610612739, "DAL": 1610612742, "DEN": 1610612743, "DET": 1610612765, "GSW": 1610612744, "HOU": 1610612745, "IND": 1610612754, "LAC": 1610612746, "LAL": 1610612747, "MEM": 1610612763, "MIA": 1610612748, "MIL": 1610612749, "MIN": 1610612750, "NOP": 1610612740, "NYK": 1610612752, "OKC": 1610612760, "ORL": 1610612753, "PHI": 1610612755, "PHX": 1610612756, "POR": 1610612757, "SAC": 1610612758, "SAS": 1610612759, "TOR": 1610612761, "UTA": 1610612762, "WAS": 1610612764};
let selectedPlayerId = 1628378; // Donovan Mitchell by default
let selectedPlayerName = "Donovan Mitchell";
let selectedStat = "pts";
let pmfChartInstance = null;
let historyChartInstance = null;

// Player History Reference State (§4, §5, §7)
const playerHistoryCache = new Map();
let currentHistoryRequestId = 0;
let historyAbortController = null;
let currentHistoryData = null;
let currentHistoryTab = "recent"; // last5 | recent (10) | last20 | last30 | season | h2h
let currentHistoryVenue = "all";
let currentHistorySide = "over";   // "over" | "under"
let currentResolvedOpponentAbbr = null;

// Prediction & Search In-flight State (Issue 16)
let predictionAbortController = null;
let currentPredictionRequestId = 0;
let appSyncPollingTimer = null;
let predictionDebounceTimer = null;
let seasonStatsRequestId = 0;
let seasonStatsAbortController = null;

document.addEventListener("DOMContentLoaded", () => {
  // 1. Parse URL deep link parameters from FastCheck FIRST before rendering
  const urlParams = new URLSearchParams(window.location.search);
  const pIdParam = urlParams.get("player_id");
  const pNameParam = urlParams.get("player_name");
  const lineParam = urlParams.get("line");
  const overParam = urlParams.get("odds_over");
  const underParam = urlParams.get("odds_under");

  if (pIdParam) {
    selectedPlayerId = parseInt(pIdParam);
    if (pNameParam) {
      selectedPlayerName = decodeURIComponent(pNameParam);
      const nameHeading = document.getElementById("current-player-name");
      if (nameHeading) nameHeading.textContent = selectedPlayerName;
    }
  }

  initSyncStatus();
  setupEventListeners();
  fetchSeasonStats(selectedPlayerId);

  if (pIdParam) {
    if (lineParam && document.getElementById("input-line")) {
      document.getElementById("input-line").value = lineParam;
    }
    if (overParam && document.getElementById("input-odds-over")) {
      document.getElementById("input-odds-over").value = overParam;
    }
    if (underParam && document.getElementById("input-odds-under")) {
      document.getElementById("input-odds-under").value = underParam;
    }

  }

  fetchPlayerHistory(selectedPlayerId, getActiveOpponent());
  runPrediction(); // Initial prediction
});

function initSyncStatus() {
  fetch("/api/sync/status")
    .then(r => r.json())
    .then(data => {
      const el = document.getElementById("sync-status-text");
      if (el) el.textContent = `Latest: ${data.latest_game_date || '—'}`;
    })
    .catch(() => {});
}

function triggerManualSync() {
  const btn = document.getElementById("btn-sync-now");
  const text = document.getElementById("sync-button-text");
  const icon = document.getElementById("sync-icon");
  const statusEl = document.getElementById("sync-status-text");

  btn.disabled = true;
  text.textContent = "Syncing...";
  icon.classList.add("animate-spin");

  // Issue 17: Stop existing polling if any
  if (appSyncPollingTimer) {
    clearInterval(appSyncPollingTimer);
    appSyncPollingTimer = null;
  }

  fetch("/api/sync", { method: "POST" })
    .then(r => r.json())
    .then(data => {
      const jobId = data.job_id;
      if (!jobId) {
        btn.disabled = false;
        text.textContent = "Sync";
        icon.classList.remove("animate-spin");
        initSyncStatus();
        fetchSeasonStats(selectedPlayerId);
        runPrediction();
        return;
      }

      let attempts = 0;
      // Issue 17: Polling interval 1.5s, max window 240 seconds (160 attempts)
      const pollIntervalMs = 1500;
      const maxAttempts = Math.ceil(240000 / pollIntervalMs);
      appSyncPollingTimer = setInterval(async () => {
        attempts++;
        try {
          const statusRes = await fetch(`/api/sync/status/${jobId}`);
          if (!statusRes.ok) throw new Error(`HTTP ${statusRes.status}`);
          const job = await statusRes.json();
          const jobStatus = (job.status || "").toUpperCase();

          text.textContent = `Syncing (${jobStatus.toLowerCase()})...`;

          if (jobStatus === "SUCCESS") {
            clearInterval(appSyncPollingTimer);
            appSyncPollingTimer = null;
            btn.disabled = false;
            text.textContent = "Sync";
            icon.classList.remove("animate-spin");
            initSyncStatus();
            fetchSeasonStats(selectedPlayerId);
            runPrediction();
          } else if (jobStatus === "PARTIAL") {
            clearInterval(appSyncPollingTimer);
            appSyncPollingTimer = null;
            btn.disabled = false;
            text.textContent = "Sync Partial";
            icon.classList.remove("animate-spin");
            if (statusEl) statusEl.textContent = `Sync Partial: ${job.message || "Hoàn tất một phần"}`;
            fetchSeasonStats(selectedPlayerId);
            runPrediction();
          } else if (jobStatus === "FAILED") {
            clearInterval(appSyncPollingTimer);
            appSyncPollingTimer = null;
            btn.disabled = false;
            text.textContent = "Sync Failed";
            icon.classList.remove("animate-spin");
            if (statusEl) statusEl.textContent = `Sync Thất Bại: ${job.error || "Lỗi không xác định"}`;
          } else if (attempts >= maxAttempts) {
            clearInterval(appSyncPollingTimer);
            appSyncPollingTimer = null;
            btn.disabled = false;
            text.textContent = "Sync Timeout";
            icon.classList.remove("animate-spin");
            if (statusEl) statusEl.textContent = "Sync Timeout (chưa hoàn thành sau 240s)";
          }
        } catch (pollErr) {
          console.warn("Polling sync job error:", pollErr);
          if (attempts >= maxAttempts) {
            clearInterval(appSyncPollingTimer);
            appSyncPollingTimer = null;
            btn.disabled = false;
            text.textContent = "Sync Error";
            icon.classList.remove("animate-spin");
            if (statusEl) statusEl.textContent = "Sync Error (mất kết nối polling)";
          }
        }
      }, pollIntervalMs);
    })
    .catch(err => {
      console.error("Sync error:", err);
      btn.disabled = false;
      text.textContent = "Sync Failed";
      icon.classList.remove("animate-spin");
    });
}

function setupEventListeners() {
  const statSelect = document.getElementById("select-stat");
  if (statSelect) statSelect.addEventListener("change", () => {
    selectedStat = statSelect.value;
    const line = document.getElementById("input-line");
    if (line) line.value = {pts: "24.5", reb: "6.5", ast: "5.5"}[selectedStat];
    schedulePrediction();
  });
  for (const id of ["input-line", "input-odds-over", "input-odds-under"]) {
    const input = document.getElementById(id);
    if (input) input.addEventListener("input", schedulePrediction);
  }

  const historyRange = document.getElementById("select-history-range");
  if (historyRange) {
    historyRange.addEventListener("change", () => {
      currentHistoryTab = historyRange.value;
      renderPlayerHistory();
    });
  }
  const historyVenue = document.getElementById("select-history-venue");
  if (historyVenue) historyVenue.addEventListener("change", () => {
    currentHistoryVenue = historyVenue.value;
    renderPlayerHistory();
  });


  // Sync Live button
  const syncBtn = document.getElementById("btn-sync-now");
  if (syncBtn) {
    syncBtn.addEventListener("click", triggerManualSync);
  }

}

function selectPlayer(id, name) {
  selectedPlayerId = id;
  selectedPlayerName = name;
  currentResolvedOpponentAbbr = null;
  updatePlayerHeading(name);
  fetchSeasonStats(id);
  fetchPlayerHistory(selectedPlayerId, getActiveOpponent());
  runPrediction();
}

function renderSeasonStats(data) {
  const grid = document.getElementById("season-stats-grid");
  const context = document.getElementById("season-stats-context");
  const season = document.getElementById("season-stats-season");
  if (!grid || !context || !season) return;
  season.textContent = data.season;
  context.textContent = `League Comparison · ${data.games_played} GP`;
  context.title = "So với toàn giải trong cùng mùa, không phân vị trí. Khoảng trung bình: mean ± 0.25 độ lệch chuẩn; tối thiểu 5 trận và 5 cầu thủ đủ điều kiện. TOV thấp hơn là tốt hơn.";
  grid.replaceChildren();
  const columns = Math.max(1, Math.ceil(data.stats.length / 3));
  grid.style.gridTemplateColumns = `repeat(${columns}, minmax(36px, 1fr))`;
  grid.style.minWidth = `${columns * 36 + (columns - 1) * 2}px`;
  const colors = {
    above:"border-emerald-700/40 bg-emerald-900/60 text-white",
    average:"border-amber-700/40 bg-amber-900/60 text-white",
    below:"border-rose-700/40 bg-rose-900/60 text-white",
    unrated:"border-neutral-800 bg-neutral-900/40 text-gray-400",
    descriptive:"border-neutral-700/60 bg-neutral-800/70 text-white",
  };
  const labels = {above:"Above Average",average:"Average",below:"Below Average",unrated:"Insufficient Sample"};
  data.stats.forEach(stat => {
    const cell = document.createElement("div");
    cell.className = "min-w-0 text-center";
    const suffix = stat.unit === "percent" ? "%" : "";
    cell.title = stat.ranked === false ? (stat.description || stat.label) : `${labels[stat.tier] || labels.unrated} · League Average: ${stat.league_average ?? "—"}${suffix} · ${stat.peer_count} qualified players` +
      (stat.lower_is_better ? " · Lower is better" : "") +
      (stat.min_attempts ? ` · Minimum ${stat.min_attempts} season attempts` : "");
    if (stat.rank != null) cell.title += ` · League Rank #${stat.rank}/${stat.rank_out_of}`;
    const label = document.createElement("div");label.className = "text-[9px] text-gray-400 font-semibold leading-tight mb-1";label.textContent = stat.label;
    const box = document.createElement("div");
    box.className = `h-[46px] border flex flex-col items-center justify-center gap-1 ${colors[stat.tier] || colors.unrated}`;
    const value = document.createElement("div");value.className = "font-mono text-[13px] font-bold leading-none whitespace-nowrap";
    value.textContent = stat.value == null ? "—" : stat.unit === "percent"
      ? `${(stat.ranked === false ? Number(stat.value) : Math.round(Number(stat.value))).toFixed(1)}%`
      : Number(stat.value).toFixed(stat.unit === "total" ? 0 : stat.unit === "ratio" ? 2 : 1);
    const rank = document.createElement("div");rank.className = "font-mono text-[12px] font-semibold leading-none";
    rank.textContent = stat.rank == null ? "—" : `#${stat.rank}`;
    box.appendChild(value);if (stat.ranked !== false) box.appendChild(rank);cell.appendChild(label);cell.appendChild(box);grid.appendChild(cell);
  });
}

async function fetchSeasonStats(playerId) {
  const grid = document.getElementById("season-stats-grid");
  const context = document.getElementById("season-stats-context");
  if (!grid || !context) return;
  const requestId = ++seasonStatsRequestId;
  if (seasonStatsAbortController) seasonStatsAbortController.abort();
  const controller = new AbortController();seasonStatsAbortController = controller;
  grid.replaceChildren();context.textContent = "Đang tải thống kê mùa giải…";
  const season = document.getElementById("season-stats-season");if (season) season.textContent = "—";
  try {
    const data = await readApiResponse(await fetch(`/api/players/${playerId}/season-stats`, {signal:controller.signal}));
    if (requestId !== seasonStatsRequestId || controller.signal.aborted) return;
    renderSeasonStats(data);
  } catch (error) {
    if (error.name === "AbortError" || requestId !== seasonStatsRequestId) return;
    context.textContent = "Chưa tải được thống kê mùa giải.";
  }
}

function predictionInputsValid() {
  const line = document.getElementById("input-line");
  if (!line || line.value.trim() === "" || !Number.isFinite(Number(line.value)) || Number(line.value) < 0) return false;
  return ["input-odds-over", "input-odds-under"].every(id => {
    const input = document.getElementById(id);
    return !input || input.value.trim() === "" || (Number.isFinite(Number(input.value)) && Number(input.value) > 1);
  });
}

function schedulePrediction() {
  clearTimeout(predictionDebounceTimer);
  predictionDebounceTimer = null;
  if (predictionAbortController) predictionAbortController.abort();
  currentPredictionRequestId++;
  resetPredictionOutputs("—");
  renderPlayerHistory();
  const status = document.getElementById("prediction-status");
  if (!predictionInputsValid()) {
    if (status) status.textContent = "Nhập line hợp lệ và odds lớn hơn 1.";
    return;
  }
  if (status) status.textContent = "Đang cập nhật…";
  predictionDebounceTimer = setTimeout(() => {
    predictionDebounceTimer = null;
    runPrediction();
  }, 350);
}

function updatePlayerHeading(name, team) {
  const heading = document.getElementById("current-player-name");
  if (heading) heading.textContent = name;
  const logo = document.getElementById("current-player-team-logo");
  if (logo) {
    const teamId = TEAM_LOGO_IDS[team];
    logo.hidden = !teamId;
    if (teamId) {
      logo.alt = `${team} logo`;
      logo.onerror = () => { logo.hidden = true; };
      logo.src = `https://cdn.nba.com/logos/nba/${teamId}/global/L/logo.svg`;
    } else {
      logo.removeAttribute("src");
      logo.alt = "";
    }
  }
}

// Issue 18: Distinguish empty input from line 0 with Number.isFinite
function parseNumericInput(inputEl) {
  if (!inputEl) return null;
  const val = inputEl.value.trim();
  if (val === "") return null;
  const parsed = parseFloat(val);
  return Number.isFinite(parsed) ? parsed : null;
}

// Issue 15: Clear and reset stale probabilities, fair odds, and EV displays
function resetPredictionOutputs(statusText = "--") {
  const playingTimeCard = document.getElementById("playing-time-card");
  if (playingTimeCard) playingTimeCard.style.display = "none";
  const shotProjection = document.getElementById("shot-volume-projection");
  if (shotProjection) shotProjection.style.display = "none";
  const gameContextCard = document.getElementById("game-context-card");
  if (gameContextCard) gameContextCard.style.display = "none";
  const roleCard = document.getElementById("role-context-card");
  if (roleCard) roleCard.style.display = "none";
  const conditionCard = document.getElementById("condition-card");
  if (conditionCard) conditionCard.style.display = "none";
  const scheduleCard = document.getElementById("schedule-card");
  if (scheduleCard) scheduleCard.style.display = "none";
  const opponentCard = document.getElementById("opponent-card");
  if (opponentCard) opponentCard.style.display = "none";
  const setEl = (id, text, className) => {
    const el = document.getElementById(id);
    if (el) {
      if (text !== undefined) el.textContent = text;
      if (className !== undefined) el.className = className;
    }
  };

  setEl("metric-ev", statusText);
  setEl("metric-median", statusText);
  setEl("metric-interval", statusText);

  setEl("over-line-val", "--");
  setEl("under-line-val", "--");
  setEl("prob-over", "--%");
  setEl("prob-under", "--%");

  const settleCard = document.getElementById("settlement-breakdown-card");
  if (settleCard) settleCard.style.display = "none";
}

function runPrediction() {
  clearTimeout(predictionDebounceTimer);
  predictionDebounceTimer = null;
  const status = document.getElementById("prediction-status");
  if (status) status.textContent = "Đang tính…";
  const lineInput = document.getElementById("input-line");
  const line = parseNumericInput(lineInput);
  const oddsOverInput = document.getElementById("input-odds-over");
  const oddsOver = parseNumericInput(oddsOverInput);
  const oddsUnderInput = document.getElementById("input-odds-under");
  const oddsUnder = parseNumericInput(oddsUnderInput);
  // Issue 15: Fully reset old results before starting
  resetPredictionOutputs("...");

  // Issue 16: Cancel previous in-flight prediction request using AbortController
  if (predictionAbortController) {
    predictionAbortController.abort();
  }
  predictionAbortController = new AbortController();
  const requestId = ++currentPredictionRequestId;

  const payload = {
    player_id: selectedPlayerId,
    stat: selectedStat,
    line: line,
    odds_over: oddsOver,
    odds_under: oddsUnder,
    opponent_override: null,
  };

  const controller = predictionAbortController;
  // Also validate old bookmarks and the default selection before inference.
  return fetch(`/api/players?active_only=true&player_id=${payload.player_id}`, {signal:controller.signal})
    .then(async response => {
      let players;
      try { players = await readApiResponse(response); }
      catch (error) { error.eligibilityError = true; throw error; }
      if (controller.signal.aborted || requestId !== currentPredictionRequestId) {
        const error = new Error("Aborted"); error.name = "AbortError"; throw error;
      }
      if (!players.some(player => player.player_id === payload.player_id && player.membership_verified)) {
        const error = new Error("Cầu thủ không còn trong roster hiện tại. Chọn cầu thủ khác bằng kính lúp.");
        error.eligibilityError = true;
        throw error;
      }
      return fetch("/api/predict", {
        method: "POST", headers: {"Content-Type": "application/json"},
        signal: controller.signal, body: JSON.stringify(payload),
      });
    })
    .then(readApiResponse)
    .then(data => {
      // Issue 16: Check request ID to avoid race conditions
      if (requestId === currentPredictionRequestId) {
        if (status) status.textContent = "";
        updateDashboard(data);
      }
    })
    .catch(err => {
      if (err.name === "AbortError") return;
      if (requestId !== currentPredictionRequestId) return;
      console.error("Prediction error:", err);
      // Issue 15: Reset to error on failure
      resetPredictionOutputs(err.eligibilityError ? "—" : "Error");
      if (err.eligibilityError) {
        if (status) status.textContent = err.message;
        return;
      }
      if (status) status.textContent = `Prediction request failed: ${err.message}`;
    });
}

function renderProbabilityMetrics(probabilities) {
  const values = probabilities && probabilities.q_over != null ? {
    "over-line-val": probabilities.line,
    "under-line-val": probabilities.line,
    "prob-over": (probabilities.q_over * 100).toFixed(1) + "%",
    "prob-under": (probabilities.q_under * 100).toFixed(1) + "%",
  } : {"over-line-val":"--", "under-line-val":"--", "prob-over":"--%", "prob-under":"--%"};
  for (const [id, value] of Object.entries(values)) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  }
}

function formatStatusLabel(status) {
  if (!status) return "Pending Review";
  const labels = {
    READY: "Ready for Analysis",
    SCENARIO_ONLY: "Conditional Scenario",
    INSUFFICIENT_DATA: "Insufficient Data",
    NOT_READY: "Pending Validation",
    OUT: "Unavailable",
    NOT_ISSUED: "Forecast Unavailable",
    CONDITIONAL_SCENARIO: "Conditional Scenario",
  };
  return labels[String(status).toUpperCase()] || String(status).replace(/_/g, " ").toLowerCase()
    .replace(/\b\w/g, char => char.toUpperCase());
}

function renderPlayingTime(data) {
  const card = document.getElementById("playing-time-card");
  if (!card) return;
  card.style.display = data ? "block" : "none";
  if (!data) return;
  const set = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };
  set("playing-time-minutes", Number.isFinite(data.expected_minutes) ? data.expected_minutes.toFixed(1) : "—");
  const band = data.interval_80;
  set("playing-time-interval", band && Number.isFinite(band.lower) && Number.isFinite(band.upper)
    ? `80% interval: ${band.lower.toFixed(1)}–${band.upper.toFixed(1)} MIN` : "");
  set("playing-time-risks", data.reason || (data.risk_flags || []).join(" · "));
}

function renderShotVolume(data) {
  const el = document.getElementById("shot-volume-projection");
  if (!el) return;
  el.style.display = data?.status === "estimated" && Number.isFinite(data.expected_fga) ? "block" : "none";
  if (el.style.display === "block") el.textContent = `Expected shots: ${data.expected_fga.toFixed(1)} FGA (if plays)`;
}

function renderGameContext(data) {
  const card = document.getElementById("game-context-card");
  if (!card) return;
  card.style.display = data?.status === "estimated" ? "block" : "none";
  if (card.style.display !== "block") return;
  document.getElementById("game-context-details").textContent = `Projected total ${data.game_total.toFixed(1)} · Pace ${data.pace.toFixed(1)} possessions`;
}

function renderRoleContext(data) {
  const card = document.getElementById("role-context-card");
  if (!card) return;
  card.style.display = data ? "block" : "none";
  if (!data) return;
  const set = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };
  const number = value => Number.isFinite(value) ? value.toFixed(1) : "—";
  const list = document.getElementById("role-context-teammates");
  if (list) list.replaceChildren();
  if (!["available", "partial"].includes(data.status)) {
    set("role-context-summary", data.reason || "Availability Unknown");
    set("role-context-volume", "");
    set("role-context-notice", "");
    return;
  }
  set("role-context-summary", `${data.out_count} Reported Out · ${data.uncertain_count} Uncertain`);
  const missing = data.missing || {};
  set("role-context-volume", `Missing role: ${number(missing.min)} MIN · ${number(missing.fga)} FGA${Number.isFinite(data.missing_fga_share) ? ` · ${(100 * data.missing_fga_share).toFixed(1)}% Team FGA` : ""}`);
  set("role-context-notice", data.unmapped_count || data.unknown_profile_count ? "Some teammate roles are unknown." : "");
  if (!list) return;
  const node = (tag, className, text) => { const el = document.createElement(tag); el.className = className; if (text !== undefined) el.textContent = text; return el; };
  for (const mate of data.teammates || []) {
    const detail = node("details", "rounded bg-gray-800/50 p-2");
    const summary = node("summary", "cursor-pointer text-[11px] text-gray-200");
    summary.appendChild(node("span", "font-semibold", mate.player_name));
    summary.appendChild(node("span", mate.status === "out" ? "ml-2 text-rose-300" : "ml-2 text-amber-300", formatStatusLabel(mate.status)));
    detail.appendChild(summary);
    const profile = mate.profile || {};
    detail.appendChild(node("p", "text-[10px] text-gray-400 mt-1", `L10 role: ${number(profile.min)} MIN · ${number(profile.fga)} FGA · ${number(profile.fta)} FTA (${profile.games || 0} games)`));
    const comparison = mate.comparison || {};
    const grid = node("div", "grid grid-cols-5 gap-1 text-[10px] text-gray-300 mt-2");
    for (const label of ["", "N", "MIN", "FGA", "PTS"]) grid.appendChild(node("span", "text-gray-400", label));
    for (const [key, label] of [["with", "With"], ["without", "Without"]]) {
      const values = comparison[key] || {};
      for (const text of [label, String(comparison[key + "_games"] || 0), number(values.min), number(values.fga), number(values.pts)]) grid.appendChild(node("span", "font-mono", text));
    }
    detail.appendChild(grid);
    if (comparison.delta) {
      const delta = value => Number.isFinite(value) ? `${value > 0 ? "+" : ""}${value.toFixed(1)}` : "—";
      detail.appendChild(node("p", "text-[10px] text-gray-300 mt-2", `Observed Δ: ${delta(comparison.delta.min)} MIN · ${delta(comparison.delta.fga)} FGA · ${delta(comparison.delta.pts)} PTS`));
    }
    detail.appendChild(node("p", "text-[9px] text-gray-400 mt-1", comparison.supported ? "Verified participation samples" : comparison.delta ? "Small Sample" : "No verified absence comparison yet"));
    list.appendChild(detail);
  }
  for (const mate of data.unmapped || []) list.appendChild(node("p", "text-[10px] text-amber-300", `${mate.player_name} · Roster Match Needed`));
}

function updateDashboard(data) {
  renderRoleContext(data.role_context);
  renderPlayingTime(data.playing_time_projection);
  renderShotVolume(data.shot_volume_projection);
  renderGameContext(data.game_context_projection);
  // Sync selected player state
  selectedPlayerId = data.player_id;
  selectedPlayerName = data.player_name;

  // Update header titles
  updatePlayerHeading(data.player_name, data.team_abbreviation);

  // Key metrics
  document.getElementById("metric-ev").textContent = data.expected_value.toFixed(2);
  document.getElementById("metric-median").textContent = data.median;
  document.getElementById("metric-interval").textContent = `[${data.prediction_interval.lower}, ${data.prediction_interval.upper}]`;

  // Condition card
  const condCard = document.getElementById("condition-card");
  condCard.style.display = "block";
  const badge = document.getElementById("condition-badge");
  badge.textContent = formatStatusLabel(data.condition.status);
  if (data.condition.status === "READY") {
    badge.className = "text-xs px-2.5 py-0.5 rounded-full font-semibold bg-emerald-950 text-emerald-400 border border-emerald-800";
  } else if (data.condition.status === "SCENARIO_ONLY") {
    badge.className = "text-xs px-2.5 py-0.5 rounded-full font-semibold bg-amber-950 text-amber-400 border border-amber-800";
  } else {
    badge.className = "text-xs px-2.5 py-0.5 rounded-full font-semibold bg-rose-950 text-rose-400 border border-rose-800";
  }
  document.getElementById("condition-action").textContent = data.condition.action;
  document.getElementById("meta-games").textContent = data.condition.metadata.n_games_history;

  // Live ESPN Player Injury Card
  const injCard = document.getElementById("injury-card");
  if (data.player_injury) {
    injCard.style.display = "block";
    const badge = document.getElementById("player-injury-badge");
    badge.textContent = formatStatusLabel(data.player_injury.status);
    if (data.player_injury.status.toLowerCase().includes("out")) {
      badge.className = "text-xs px-2.5 py-0.5 rounded-full font-bold bg-rose-950 text-rose-300 border border-rose-800";
    } else {
      badge.className = "text-xs px-2.5 py-0.5 rounded-full font-bold bg-amber-950 text-amber-300 border border-amber-800";
    }
    document.getElementById("player-injury-desc").textContent = data.player_injury.short_comment || data.player_injury.long_comment || "Listed on injury report.";
    document.getElementById("player-injury-date").textContent = `ESPN Update: ${data.player_injury.date ? data.player_injury.date.split("T")[0] : "Today"}`;
  } else {
    injCard.style.display = "none";
  }

  // Schedule & Fatigue Context Card (Supplement Plan §5)
  if (data.schedule_context) {
    const sc = data.schedule_context;
    document.getElementById("schedule-card").style.display = "block";

    // Only show congestion that is not already apparent from the rest-day values.
    const badgesContainer = document.getElementById("schedule-badges");
    badgesContainer.replaceChildren();

    if (sc.team_3in4) {
      badgesContainer.innerHTML += `<span class="text-[11px] px-2 py-0.5 rounded font-medium bg-rose-900/60 text-rose-300 border border-rose-700">3 Games in 4 Days</span>`;
    } else if (sc.team_4in6) {
      badgesContainer.innerHTML += `<span class="text-[11px] px-2 py-0.5 rounded font-medium bg-amber-900/60 text-amber-300 border border-amber-700">4 Games in 6 Days</span>`;
    }
    badgesContainer.style.display = badgesContainer.childElementCount ? "flex" : "none";

    document.getElementById("sched-team-rest").textContent = `${sc.team_rest_days}d`;
    document.getElementById("sched-opp-rest").textContent = `${sc.opp_rest_days}d`;
    document.getElementById("sched-workload").textContent = `${sc.player_minutes_last7days}m`;
  } else {
    document.getElementById("schedule-card").style.display = "none";
  }

  // Opponent Matchup Profile Card (Supplement Plan §6 & §8)
  if (data.opponent_context) {
    const oc = data.opponent_context;
    document.getElementById("opponent-card").style.display = "block";
    document.getElementById("opp-abbr-badge").textContent = oc.opponent_abbr || "OPP";
    document.getElementById("opp-def-rtg").textContent = `${oc.opp_def_rating_prev10.toFixed(1)}`;
    document.getElementById("opp-pace").textContent = `${oc.opp_pace_prev10.toFixed(1)}`;
    document.getElementById("opp-ast-allowed").textContent = `${oc.opp_ast_allowed_per100_prev10.toFixed(1)}`;
    document.getElementById("opp-dreb-share").textContent = `${(oc.opp_dreb_share_prev10 * 100).toFixed(1)}%`;
    document.getElementById("opp-fg3a-share").textContent = `${(oc.opp_fg3a_share_prev10 * 100).toFixed(1)}%`;

    // 1. PTS Allowed Rank
    const elPtsRank = document.getElementById("opp-pts-rank");
    const elPtsVal = document.getElementById("opp-pts-val");
    const elPtsStatus = document.getElementById("opp-pts-status");
    if (elPtsRank && elPtsVal && elPtsStatus) {
      if (oc.opp_pts_allowed_per100 != null) {
        elPtsVal.textContent = `${oc.opp_pts_allowed_per100.toFixed(1)} pts/100`;
      } else {
        elPtsVal.textContent = "-";
      }
      if (oc.opp_pts_rank_asc != null) {
        const r = Math.round(oc.opp_pts_rank_asc);
        elPtsRank.textContent = `#${r}/30`;
        if (r <= 10) {
          elPtsRank.className = "text-xs font-mono font-bold px-1.5 py-0.5 rounded bg-rose-950/80 text-rose-300 border border-rose-800/60";
          elPtsStatus.textContent = "Cho phép ít điểm";
          elPtsStatus.className = "text-[9px] mt-1 font-medium block text-rose-400";
        } else if (r >= 21) {
          elPtsRank.className = "text-xs font-mono font-bold px-1.5 py-0.5 rounded bg-emerald-950/80 text-emerald-300 border border-emerald-800/60";
          elPtsStatus.textContent = "Cho phép nhiều điểm";
          elPtsStatus.className = "text-[9px] mt-1 font-medium block text-emerald-400";
        } else {
          elPtsRank.className = "text-xs font-mono font-bold px-1.5 py-0.5 rounded bg-neutral-800 text-gray-300 border border-neutral-700/60";
          elPtsStatus.textContent = "Trung bình giải";
          elPtsStatus.className = "text-[9px] mt-1 font-medium block text-gray-400";
        }
      } else {
        elPtsRank.textContent = "—";
        elPtsRank.className = "text-xs font-mono font-bold px-1.5 py-0.5 rounded bg-neutral-800 text-gray-300";
        elPtsStatus.textContent = "Chưa có rank";
        elPtsStatus.className = "text-[9px] mt-1 font-medium block text-gray-400";
      }
    }

    // 2. 3PT Allowed Rank
    const elFg3mRank = document.getElementById("opp-fg3m-rank");
    const elFg3mVal = document.getElementById("opp-fg3m-val");
    const elFg3mStatus = document.getElementById("opp-fg3m-status");
    if (elFg3mRank && elFg3mVal && elFg3mStatus) {
      if (oc.opp_fg3m_allowed_per100 != null) {
        elFg3mVal.textContent = `${oc.opp_fg3m_allowed_per100.toFixed(1)} 3PM/100`;
      } else {
        elFg3mVal.textContent = "-";
      }
      if (oc.opp_fg3m_rank_asc != null) {
        const r = Math.round(oc.opp_fg3m_rank_asc);
        elFg3mRank.textContent = `#${r}/30`;
        if (r <= 10) {
          elFg3mRank.className = "text-xs font-mono font-bold px-1.5 py-0.5 rounded bg-rose-950/80 text-rose-300 border border-rose-800/60";
          elFg3mStatus.textContent = "Cho phép ít 3PM";
          elFg3mStatus.className = "text-[9px] mt-1 font-medium block text-rose-400";
        } else if (r >= 21) {
          elFg3mRank.className = "text-xs font-mono font-bold px-1.5 py-0.5 rounded bg-emerald-950/80 text-emerald-300 border border-emerald-800/60";
          elFg3mStatus.textContent = "Cho phép nhiều 3PM";
          elFg3mStatus.className = "text-[9px] mt-1 font-medium block text-emerald-400";
        } else {
          elFg3mRank.className = "text-xs font-mono font-bold px-1.5 py-0.5 rounded bg-neutral-800 text-gray-300 border border-neutral-700/60";
          elFg3mStatus.textContent = "3P Trung bình";
          elFg3mStatus.className = "text-[9px] mt-1 font-medium block text-gray-400";
        }
      } else {
        elFg3mRank.textContent = "—";
        elFg3mRank.className = "text-xs font-mono font-bold px-1.5 py-0.5 rounded bg-neutral-800 text-gray-300";
        elFg3mStatus.textContent = "Chưa có rank";
        elFg3mStatus.className = "text-[9px] mt-1 font-medium block text-gray-400";
      }
    }

    // 3. Rim Protection (Blocks) Rank
    const elBlkRank = document.getElementById("opp-blk-rank");
    const elBlkVal = document.getElementById("opp-blk-val");
    const elBlkStatus = document.getElementById("opp-blk-status");
    if (elBlkRank && elBlkVal && elBlkStatus) {
      if (oc.opp_blocks_made_per100 != null) {
        elBlkVal.textContent = `${oc.opp_blocks_made_per100.toFixed(1)} BLK/100`;
      } else {
        elBlkVal.textContent = "-";
      }
      if (oc.opp_blocks_rank_asc != null) {
        const r = Math.round(oc.opp_blocks_rank_asc);
        elBlkRank.textContent = `#${r}/30`;
        if (r >= 21) {
          elBlkRank.className = "text-xs font-mono font-bold px-1.5 py-0.5 rounded bg-rose-950/80 text-rose-300 border border-rose-800/60";
          elBlkStatus.textContent = "Nhiều blocks";
          elBlkStatus.className = "text-[9px] mt-1 font-medium block text-rose-400";
        } else if (r <= 10) {
          elBlkRank.className = "text-xs font-mono font-bold px-1.5 py-0.5 rounded bg-emerald-950/80 text-emerald-300 border border-emerald-800/60";
          elBlkStatus.textContent = "Ít blocks";
          elBlkStatus.className = "text-[9px] mt-1 font-medium block text-emerald-400";
        } else {
          elBlkRank.className = "text-xs font-mono font-bold px-1.5 py-0.5 rounded bg-neutral-800 text-gray-300 border border-neutral-700/60";
          elBlkStatus.textContent = "Block trung bình";
          elBlkStatus.className = "text-[9px] mt-1 font-medium block text-gray-400";
        }
      } else {
        elBlkRank.textContent = "—";
        elBlkRank.className = "text-xs font-mono font-bold px-1.5 py-0.5 rounded bg-neutral-800 text-gray-300";
        elBlkStatus.textContent = "Chưa có rank";
        elBlkStatus.className = "text-[9px] mt-1 font-medium block text-gray-400";
      }
    }

    // 4. Defense vs Position (DvP §12)
    const dvpBox = document.getElementById("dvp-box");
    if (data.dvp_context && dvpBox) {
      const dvp = data.dvp_context;
      dvpBox.style.display = "block";
      const grpEl = document.getElementById("dvp-player-group");
      const posBadge = document.getElementById("dvp-raw-pos-badge");
      if (grpEl) grpEl.textContent = dvp.position_group.toUpperCase();
      if (posBadge) posBadge.textContent = dvp.position_raw || "POS";
      const supported = dvp.dvp_supported === true;
      const dvpGrid = document.getElementById("dvp-stats-grid");
      const missingNote = document.getElementById("dvp-missing-note");
      if (dvpGrid) dvpGrid.style.display = supported ? "block" : "none";
      if (missingNote) missingNote.style.display = supported ? "none" : "block";
      for (const market of ["pts", "reb", "ast"]) {
        const card = document.getElementById(`dvp-${market}-card`);
        if (card) card.style.display = supported && market === String(data.stat || selectedStat).toLowerCase() ? "flex" : "none";
      }

      const renderDvpStat = (prefix, statObj) => {
        const elRank = document.getElementById(`dvp-${prefix}-rank`);
        const elVal = document.getElementById(`dvp-${prefix}-val`);
        const elStatus = document.getElementById(`dvp-${prefix}-status`);
        if (!elRank || !statObj) return;

        const r = Math.round(statObj.rank_asc);
        elRank.textContent = `#${r}/30`;
        elVal.textContent = `${statObj.volume_per100.toFixed(1)}/100`;

        if (r <= 10) {
          elRank.className = "text-xs font-mono font-bold px-1.5 py-0.5 rounded bg-rose-950/80 text-rose-300 border border-rose-800/60";
          elStatus.textContent = "Thủ chặt";
          elStatus.className = "text-[9px] font-medium block text-rose-400 mt-0.5";
        } else if (r >= 21) {
          elRank.className = "text-xs font-mono font-bold px-1.5 py-0.5 rounded bg-emerald-950/80 text-emerald-300 border border-emerald-800/60";
          elStatus.textContent = "Cho phép nhiều";
          elStatus.className = "text-[9px] font-medium block text-emerald-400 mt-0.5";
        } else {
          elRank.className = "text-xs font-mono font-bold px-1.5 py-0.5 rounded bg-neutral-800 text-gray-300 border border-neutral-700/60";
          elStatus.textContent = "Trung bình";
          elStatus.className = "text-[9px] font-medium block text-gray-400 mt-0.5";
        }
      };

      if (supported) {
        const market = String(data.stat || selectedStat).toLowerCase();
        if (["pts", "reb", "ast"].includes(market)) renderDvpStat(market, dvp[market]);
      }
    } else if (dvpBox) {
      dvpBox.style.display = "none";
    }

    // Opponent injuries
    const oppBox = document.getElementById("opp-injuries-box");
    const oppList = document.getElementById("opp-injuries-list");
    const oppVacBadge = document.getElementById("opp-vacancy-badge");
    if (data.opponent_injuries && data.opponent_injuries.length > 0) {
      oppBox.style.display = "block";
      const oppVac = data.injury_impact ? data.injury_impact.opp_missing_minutes : 0;
      if (oppVacBadge) {
        oppVacBadge.textContent = `${oppVac.toFixed(1)}m`;
      }
      oppList.replaceChildren();
      for (const inj of data.opponent_injuries.slice(0, 5)) {
        const line = document.createElement("div");
        line.className = "text-[11px] flex justify-between items-center text-gray-300";
        const name = document.createElement("span");
        name.textContent = `${inj.player_name} (${inj.position ? inj.position[0] : "P"}):`;
        const detail = document.createElement("div");
        detail.className = "flex items-center space-x-1.5";
        const status = document.createElement("span");
        status.className = `font-mono font-semibold ${String(inj.status).toLowerCase().includes("out") ? "text-rose-400" : "text-indigo-400"}`;
        status.textContent = inj.status;
        const minutes = document.createElement("span");
        minutes.className = "text-[10px] text-indigo-300 font-mono";
        minutes.textContent = `(${Number(inj.missing_minutes || 0).toFixed(1)}m)`;
        detail.append(status, minutes);
        line.append(name, detail);
        oppList.appendChild(line);
      }
    } else {
      oppBox.style.display = "none";
    }
  } else {
    document.getElementById("opponent-card").style.display = "none";
  }

  renderProbabilityMetrics(data.line_probabilities);

  // Settlement & Unconditional Probabilities (§12 & §14)
  const settleCard = document.getElementById("settlement-breakdown-card");
  if (data.unconditional_settlement && data.readiness) {
    settleCard.style.display = "block";
    const us = data.unconditional_settlement;
    const rd = data.readiness;
    
    document.getElementById("settle-pi").textContent = (us.pi_participate * 100).toFixed(1) + "%";
    document.getElementById("settle-void").textContent = (us.p_void * 100).toFixed(1) + "%";
    document.getElementById("settle-uncond-over").textContent = (us.p_over * 100).toFixed(1) + "%";
    document.getElementById("settle-uncond-under").textContent = (us.p_under * 100).toFixed(1) + "%";

    if (data.injury_impact) {
      const tmVacEl = document.getElementById("settle-tm-vac");
      const oppVacEl = document.getElementById("settle-opp-vac");
      if (tmVacEl) tmVacEl.textContent = `${data.injury_impact.teammate_missing_minutes.toFixed(1)}m`;
      if (oppVacEl) oppVacEl.textContent = `${data.injury_impact.opp_missing_minutes.toFixed(1)}m`;
    }

    const rBadge = document.getElementById("settlement-readiness-badge");
    rBadge.textContent = formatStatusLabel(rd.status);
    if (rd.status === "READY") {
      rBadge.className = "text-xs px-2.5 py-0.5 rounded-full font-bold font-mono bg-emerald-950 text-emerald-400 border border-emerald-800";
    } else if (rd.status === "SCENARIO_ONLY") {
      rBadge.className = "text-xs px-2.5 py-0.5 rounded-full font-bold font-mono bg-amber-950 text-amber-400 border border-amber-800";
    } else {
      rBadge.className = "text-xs px-2.5 py-0.5 rounded-full font-bold font-mono bg-rose-950 text-rose-400 border border-rose-800";
    }

    let note = rd.action;
    document.getElementById("settlement-note").textContent = note;
  } else {
    settleCard.style.display = "none";
  }

  // Trigger or update reference player history (§4, §5, §7)
  const activeOpp = (data.opponent_context && data.opponent_context.opponent_abbr) || 
                    (data.upcoming_game_info && (data.upcoming_game_info.active_opponent || data.upcoming_game_info.scheduled_opponent)) || 
                    null;
  if (activeOpp && activeOpp !== currentResolvedOpponentAbbr) {
    currentResolvedOpponentAbbr = activeOpp;
    fetchPlayerHistory(selectedPlayerId, activeOpp);
  } else if (!currentHistoryData) {
    fetchPlayerHistory(selectedPlayerId, activeOpp);
  } else {
    renderPlayerHistory();
  }

  // Render PMF Chart
  renderChart(data.pmf, data.line_probabilities ? data.line_probabilities.line : null);
}

function renderChart(pmfList, targetLine) {
  const ctx = document.getElementById("pmfChart").getContext("2d");
  const labels = pmfList.map(p => p.value);
  const data = pmfList.map(p => (p.prob * 100).toFixed(2));

  // Determine bar background colors (highlight target line)
  const bgColors = labels.map(val => {
    if (targetLine !== null && Math.abs(val - targetLine) < 0.6) {
      return "#f43f5e"; // Rose for target line
    }
    return "#5e6ad2"; // Linear lavender
  });

  if (pmfChartInstance) {
    pmfChartInstance.destroy();
  }

  pmfChartInstance = new Chart(ctx, {
    type: "bar",
    data: {
      labels: labels,
      datasets: [
        {
          label: "Probability (%)",
          data: data,
          backgroundColor: bgColors,
          borderRadius: 4,
          borderSkipped: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#18191a",
          titleColor: "#f7f8f8",
          bodyColor: "#d0d6e0",
          borderColor: "#23252a",
          borderWidth: 1,
          callbacks: {
            title: items => `Stat: ${items[0].label}`,
            label: item => `Probability: ${item.raw}%`,
          },
        },
      },
      scales: {
        x: {
          grid: { color: "rgba(255, 255, 255, 0.05)" },
          ticks: { color: "#8a8f98", font: { size: 10 } },
        },
        y: {
          grid: { color: "rgba(255, 255, 255, 0.05)" },
          ticks: {
            color: "#8a8f98",
            font: { size: 10 },
            callback: v => `${v}%`,
          },
        },
      },
    },
  });
}

// ============================================================================
// Reference Player History & H2H Module (§4, §5, §7)
// Purely reference-only, does NOT impact prediction models or inference pipeline.
// ============================================================================

function getActiveOpponent() {
  return currentResolvedOpponentAbbr || null;
}

function compareStat(val, line, side) {
  if (val === null || val === undefined || isNaN(val)) {
    return { outcome: "missing", label: "—" };
  }
  if (line === null || line === undefined || isNaN(line) || line < 0) {
    return { outcome: "uncompared", label: "—" };
  }
  const x = Number(val);
  const L = Number(line);
  if (x === L) {
    return { outcome: "push", label: "Push" };
  }
  if (side === "over") {
    return x > L ? { outcome: "hit", label: "Hit" } : { outcome: "miss", label: "Miss" };
  } else {
    return x < L ? { outcome: "hit", label: "Hit" } : { outcome: "miss", label: "Miss" };
  }
}

function getStatValue(row, statKey) {
  if (!row) return null;
  const k = (statKey || "").toLowerCase();
  if (k === "pts" || k === "points") return row.pts ?? row.points ?? null;
  if (k === "reb" || k === "rebounds") return row.reb ?? row.rebounds ?? null;
  if (k === "ast" || k === "assists") return row.ast ?? row.assists ?? null;
  if (k === "fg3m" || k === "3pm" || k === "three_pm") return row.fg3m ?? row["3pm"] ?? row.three_pm ?? null;
  if (k === "stl" || k === "steals") return row.stl ?? row.steals ?? null;
  if (k === "blk" || k === "blocks") return row.blk ?? row.blocks ?? null;
  if (k === "tov" || k === "turnovers") return row.tov ?? row.turnovers ?? null;
  return row[k] ?? null;
}

function fetchPlayerHistory(playerId, oppAbbr) {
  if (!playerId) return;

  const opp = oppAbbr || getActiveOpponent() || "";
  const cacheKey = `${playerId}_${opp}_200`;
  const requestId = ++currentHistoryRequestId;
  if (historyAbortController) historyAbortController.abort();
  if (playerHistoryCache.has(cacheKey)) {
    currentHistoryData = playerHistoryCache.get(cacheKey);
    renderPlayerHistory();
    return;
  }

  historyAbortController = new AbortController();

  currentHistoryData = null;
  renderPlayerHistory();
  let url = `/api/players/${playerId}/history?limit=200`;
  if (opp) {
    url += `&opponent_abbr=${encodeURIComponent(opp)}`;
  }

  const tbody = document.getElementById("hist-table-body");
  if (tbody && !currentHistoryData) {
    tbody.innerHTML = `<tr><td colspan="16" class="py-8 text-center text-gray-500 font-sans">Đang tải lịch sử thi đấu...</td></tr>`;
  }

  fetch(url, { signal: historyAbortController.signal })
    .then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    })
    .then(data => {
      if (requestId !== currentHistoryRequestId) return; // Discard stale response
      playerHistoryCache.set(cacheKey, data);
      currentHistoryData = data;
      renderPlayerHistory();
    })
    .catch(err => {
      if (err.name === "AbortError") return;
      if (requestId !== currentHistoryRequestId) return;
      console.warn("Player history fetch notice:", err);
      renderHistoryChart([], null, `Chưa tải được lịch sử: ${err.message || 'Lỗi kết nối'}`);
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="16" class="py-6 text-center text-gray-400 font-sans">Chưa có dữ liệu lịch sử thi đấu (${err.message || 'Lỗi kết nối'}).</td></tr>`;
      }
    });
}

function historyVenueForRow(row) {
  const venue = String(row.home_away || "").toLowerCase();
  if (venue === "away" || venue === "@") return "away";
  if (venue === "home" || venue === "vs") return "home";
  const matchup = String(row.matchup || "");
  if (matchup.includes("@")) return "away";
  if (/\bvs\.?\s/i.test(matchup)) return "home";
  return null;
}

function getHistoryRows(data, range, venue = "all") {
  const filterVenue = rows => venue === "all" ? rows : rows.filter(row => historyVenueForRow(row) === venue);
  const recent = filterVenue(data?.recent?.rows || (Array.isArray(data?.recent) ? data.recent : []));
  const h2h = filterVenue(data?.vs_opponent?.rows || (Array.isArray(data?.vs_opponent) ? data.vs_opponent : []));
  const newestFirst = rows => [...rows].sort((a, b) =>
    String(b.game_date).localeCompare(String(a.game_date)) || String(b.game_id).localeCompare(String(a.game_id)));
  if (range === "h2h") return newestFirst(h2h);
  if (range === "season") {
    // Dataset season, rather than the player's last season (which may be old).
    const season = [...(data?.coverage?.seasons_available || [])].sort().pop();
    return newestFirst(recent.filter(row => row.season === season));
  }
  const count = {last5: 5, recent: 10, last20: 20, last30: 30}[range] || 10;
  return newestFirst(recent).slice(0, count);
}

function historyOpponentLabel(row) {
  const opponent = row.opponent_team_abbr || row.opponent_abbr || row.opp_abbr || "--";
  const homeAway = String(row.home_away || "").toLowerCase();
  const away = homeAway === "away" || homeAway === "@" || String(row.matchup || "").includes("@");
  return `${away ? "@" : ""}${opponent}`;
}

function renderHistoryChart(rows, line, emptyMessage) {
  const canvas = document.getElementById("historyChart");
  if (!canvas) return;
  const empty = document.getElementById("history-chart-empty");
  const scroll = document.getElementById("history-chart-scroll");
  const container = document.getElementById("history-chart-container");
  if (empty) {
    empty.textContent = emptyMessage || "Chưa có dữ liệu trong phạm vi này.";
    empty.classList.toggle("hidden", rows.length > 0);
  }
  if (scroll) scroll.classList.toggle("hidden", rows.length === 0);
  if (!rows.length) {
    if (historyChartInstance) historyChartInstance.destroy();
    historyChartInstance = null;
    return;
  }
  // The table is newest first; the chart reads oldest to newest, left to right.
  const chartRows = [...rows].reverse();
  if (container) container.style.minWidth = `${chartRows.length * 44}px`;
  const values = chartRows.map(row => {
    const value = getStatValue(row, selectedStat);
    return value != null && Number.isFinite(Number(value)) ? Number(value) : null;
  });
  const data = {
    labels: chartRows.map(historyOpponentLabel),
    datasets: [{label: selectedStat.toUpperCase(), data: values,
      backgroundColor: values.map(value => compareStat(value, line, currentHistorySide).outcome === "hit" ? "#10b981" : "#ef4444"),
      borderRadius: 4, borderSkipped: false, maxBarThickness: 40}],
  };
  const options = {
    responsive: true, maintainAspectRatio: false, animation: false,
    plugins: {
      legend: {display: false},
      "history-line": {value: line},
      tooltip: {backgroundColor: "#18191a", titleColor: "#f7f8f8", bodyColor: "#d0d6e0",
        callbacks: {
          title: items => `${chartRows[items[0].dataIndex].game_date?.split("T")[0] || ""} · ${items[0].label}`,
          label: item => `${selectedStat.toUpperCase()}: ${item.raw}`,
        }},
    },
    scales: {
      x: {grid: {display: false}, ticks: {autoSkip: false, maxRotation: 0, color: "#8a8f98", font: {size: 10}}},
      y: {beginAtZero: true, suggestedMax: Math.max(line ?? 0, ...values.filter(value => value !== null), 1) + 1,
        title: {display: true, text: selectedStat.toUpperCase(), color: "#8a8f98"},
        ticks: {precision: 0, color: "#8a8f98"}, grid: {color: "rgba(255,255,255,0.05)"}},
    },
  };
  if (historyChartInstance) {
    historyChartInstance.data = data;
    historyChartInstance.options = options;
    historyChartInstance.update("none");
    return;
  }
  historyChartInstance = new Chart(canvas.getContext("2d"), {type: "bar", data, options,
    plugins: [{id: "history-line", afterDatasetsDraw(chart, args, pluginOptions) {
      const value = pluginOptions.value;
      if (value === null || value === undefined || !Number.isFinite(value)) return;
      const y = chart.scales.y.getPixelForValue(value);
      const {left, right, top, bottom} = chart.chartArea;
      if (y < top || y > bottom) return;
      chart.ctx.save();
      chart.ctx.strokeStyle = "#ffffff";
      chart.ctx.lineWidth = 2;
      chart.ctx.beginPath();
      chart.ctx.moveTo(left, y);
      chart.ctx.lineTo(right, y);
      chart.ctx.stroke();
      chart.ctx.restore();
    }}],
  });
}

function historyTeamLabel(teamId, label) {
  const text = String(label).replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  const id = Number(teamId);
  const logo = Number.isSafeInteger(id) && id > 0
    ? `<img src="https://cdn.nba.com/logos/nba/${id}/global/L/logo.svg" width="18" height="18" loading="lazy" alt="" class="inline-block shrink-0" onerror="this.hidden=true">` : "";
  return `<span class="inline-flex items-center gap-1.5">${logo}<span>${text}</span></span>`;
}

function renderHistoricalHitRates(rows, line) {
  // Counts use actual, non-missing stat observations. Pushes stay in the
  // denominator, and count as neither Over nor Under hits.
  const values = rows.map(row => getStatValue(row, selectedStat))
    .filter(value => value !== null && value !== undefined && Number.isFinite(Number(value)))
    .map(Number);
  const validLine = line !== null && Number.isFinite(line) && line >= 0;
  for (const side of ["over", "under"]) {
    const hits = validLine ? values.filter(value => side === "over" ? value > line : value < line).length : 0;
    const rate = document.getElementById(`history-hit-${side}-rate`);
    const count = document.getElementById(`history-hit-${side}-count`);
    if (rate) rate.textContent = validLine && values.length ? `${Number((100 * hits / values.length).toFixed(1))}%` : "--%";
    if (count) count.textContent = validLine && values.length ? `${hits}/${values.length}` : "--/--";
  }
}

function renderPlayerHistory() {
  const lineInput = document.getElementById("input-line");
  const lineVal = lineInput ? parseFloat(lineInput.value) : null;
  const line = (lineVal !== null && !isNaN(lineVal) && lineVal >= 0) ? lineVal : null;

  const activeOpp = getActiveOpponent();
  const activeRows = getHistoryRows(currentHistoryData, currentHistoryTab, currentHistoryVenue);
  renderHistoricalHitRates(activeRows, line);
  const historyRange = document.getElementById("select-history-range");
  if (historyRange) historyRange.value = currentHistoryTab;
  const historyVenue = document.getElementById("select-history-venue");
  if (historyVenue) historyVenue.value = currentHistoryVenue;
  renderHistoryChart(activeRows, line, currentHistoryData ? null : "Đang tải lịch sử thi đấu...");

  // 5. Coverage / Incomplete Notice (§3.3 & §5)
  const noticeBox = document.getElementById("hist-coverage-notice");
  const noticeText = document.getElementById("hist-coverage-text");
  if (noticeBox && noticeText) {
    const requestedCount = {last5: 5, recent: 10, last20: 20, last30: 30}[currentHistoryTab];
    let message = "";
    if (currentHistoryTab === "h2h" && !activeRows.length) {
      message = activeOpp ? `Chưa có dữ liệu đối đầu với ${activeOpp}.` : "Chọn đối thủ để xem H2H.";
    } else if (requestedCount && currentHistoryData && activeRows.length < requestedCount) {
      message = `${activeRows.length}/${requestedCount} trận ra sân có sẵn dữ liệu.`;
    }

    noticeBox.style.display = message ? "flex" : "none";
    noticeText.textContent = message;
  }

  // 7. Render Table Rows
  const tbody = document.getElementById("hist-table-body");
  if (!tbody) return;

  if (!currentHistoryData) {
    tbody.innerHTML = `<tr><td colspan="16" class="py-8 text-center text-gray-500 font-sans">Đang tải lịch sử thi đấu...</td></tr>`;
    return;
  }

  if (activeRows.length === 0) {
    const emptyMsg = currentHistoryTab === "h2h" 
      ? `Không tìm thấy trận đối đầu nào với ${activeOpp || 'đối thủ này'}.`
      : `Không có dữ liệu trong phạm vi đang chọn.`;
    tbody.innerHTML = `<tr><td colspan="16" class="py-8 text-center text-gray-400 font-sans">${emptyMsg}</td></tr>`;
    return;
  }

  const curStat = (selectedStat || "pts").toLowerCase();

  tbody.innerHTML = activeRows.map(row => {
    // Format Date / Season
    const dateStr = row.game_date ? row.game_date.split("T")[0] : "--";
    const season = row.season ? (row.season.length > 5 ? row.season.slice(2) : row.season) : "";
    const dateSeasonDisplay = season ? `${dateStr} <span class="text-[10px] text-gray-500">(${season})</span>` : dateStr;

    // Team
    const playerTeam = row.player_team_abbr || row.player_team_name || row.team_abbr || "--";

    // Opponent indicator @ / vs
    const oppAbbr = row.opponent_team_abbr || row.opponent_abbr || row.opponent_name || row.opp_abbr || "--";
    const rawHomeAway = (row.home_away || "").toLowerCase();
    const isAway = rawHomeAway === "@" || rawHomeAway === "away" || (row.matchup && row.matchup.includes("@"));
    const matchIndicator = isAway ? `@ ${oppAbbr}` : `vs ${oppAbbr}`;

    // Minutes
    const minVal = row.minutes != null ? Number(row.minutes).toFixed(1) : (row.min != null ? row.min : "—");

    // Stats
    const pts = getStatValue(row, "pts");
    const reb = getStatValue(row, "reb");
    const ast = getStatValue(row, "ast");
    const fg3m = getStatValue(row, "fg3m");
    const stl = getStatValue(row, "stl");
    const blk = getStatValue(row, "blk");
    const tov = getStatValue(row, "tov");

    const activeVal = getStatValue(row, curStat);
    const isHighlighted = line !== null && activeVal !== null && activeVal > line;

    const trClass = isHighlighted 
      ? "transition border-l-[3px] border-emerald-500 hover:bg-emerald-950/40"
      : "hover:bg-neutral-800/40 transition border-l-[3px] border-transparent";
    const trStyle = isHighlighted 
      ? 'style="background-color: rgba(16, 185, 129, 0.12);"' 
      : '';

    const renderStatCell = (statKey, val) => {
      const isTarget = statKey === curStat;
      const valStr = val != null ? val : "—";
      if (!isTarget) {
        return `<td class="py-2.5 px-2 text-right text-gray-300 font-mono">${valStr}</td>`;
      }
      // Target stat cell: bold text without separate block background
      const textClass = isHighlighted 
        ? "text-emerald-300 font-bold" 
        : "text-white font-bold";
      return `<td class="py-2.5 px-2 text-right font-mono ${textClass}">${valStr}</td>`;
    };

    const score = row.team_score != null && row.opponent_score != null
      ? `${row.team_score}:${row.opponent_score}` : "--";
    const result = `${row.result || "--"} - ${score}`;
    const pctCell = value => value != null && Number.isFinite(Number(value))
      ? `${(Number(value) * 100).toFixed(1)}%` : "--";

    return `
      <tr class="${trClass}" ${trStyle}>
        <td class="py-2.5 px-3 text-white font-medium whitespace-nowrap">${dateSeasonDisplay}</td>
        <td class="py-2.5 px-2.5 text-gray-300 font-semibold">${historyTeamLabel(row.player_team_id, playerTeam)}</td>
        <td class="py-2.5 px-2.5 text-indigo-300 font-medium">${historyTeamLabel(row.opponent_team_id, matchIndicator)}</td>
        <td class="py-2.5 px-2 font-mono ${row.result === "W" ? "text-emerald-300" : "text-gray-400"}" title="Team - Opponent">${result}</td>
        ${renderStatCell("pts", pts)}
        ${renderStatCell("ast", ast)}
        ${renderStatCell("reb", reb)}
        <td class="py-2.5 px-2 text-right text-gray-400 font-mono">${minVal}</td>
        ${renderStatCell("fg3m", fg3m)}
        ${renderStatCell("fg3_pct", pctCell(row.fg3_pct))}
        ${renderStatCell("ft_pct", pctCell(row.ft_pct))}
        ${renderStatCell("fg_pct", pctCell(row.fg_pct))}
        ${renderStatCell("fga", row.fga)}
        ${renderStatCell("fgm", row.fgm)}
        ${renderStatCell("fta", row.fta)}
        ${renderStatCell("ftm", row.ftm)}
      </tr>
    `;
  }).join("");
}
