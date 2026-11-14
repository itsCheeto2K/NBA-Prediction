let selectedPlayerId = 1628378; // Donovan Mitchell by default
let selectedPlayerName = "Donovan Mitchell";
let selectedStat = "pts";
let pmfChartInstance = null;

// Player History Reference State (§4, §5, §7)
const playerHistoryCache = new Map();
let currentHistoryRequestId = 0;
let historyAbortController = null;
let currentHistoryData = null;
let currentHistoryTab = "recent"; // "recent" | "h2h"
let currentHistorySide = "over";   // "over" | "under"
let currentResolvedOpponentAbbr = null;

const STAR_PLAYERS = [
  { id: 1628378, name: "Donovan Mitchell" },
  { id: 1628369, name: "Jayson Tatum" },
  { id: 2544, name: "LeBron James" },
  { id: 203999, name: "Nikola Jokic" },
  { id: 1629029, name: "Luka Doncic" },
  { id: 203507, name: "Giannis Antetokounmpo" },
  { id: 201939, name: "Stephen Curry" },
];

const NBA_TEAMS = [
  { abbr: "ATL", name: "Atlanta Hawks" },
  { abbr: "BOS", name: "Boston Celtics" },
  { abbr: "BKN", name: "Brooklyn Nets" },
  { abbr: "CHA", name: "Charlotte Hornets" },
  { abbr: "CHI", name: "Chicago Bulls" },
  { abbr: "CLE", name: "Cleveland Cavaliers" },
  { abbr: "DAL", name: "Dallas Mavericks" },
  { abbr: "DEN", name: "Denver Nuggets" },
  { abbr: "DET", name: "Detroit Pistons" },
  { abbr: "GSW", name: "Golden State Warriors" },
  { abbr: "HOU", name: "Houston Rockets" },
  { abbr: "IND", name: "Indiana Pacers" },
  { abbr: "LAC", name: "LA Clippers" },
  { abbr: "LAL", name: "Los Angeles Lakers" },
  { abbr: "MEM", name: "Memphis Grizzlies" },
  { abbr: "MIA", name: "Miami Heat" },
  { abbr: "MIL", name: "Milwaukee Bucks" },
  { abbr: "MIN", name: "Minnesota Timberwolves" },
  { abbr: "NOP", name: "New Orleans Pelicans" },
  { abbr: "NYK", name: "New York Knicks" },
  { abbr: "OKC", name: "Oklahoma City Thunder" },
  { abbr: "ORL", name: "Orlando Magic" },
  { abbr: "PHI", name: "Philadelphia 76ers" },
  { abbr: "PHX", name: "Phoenix Suns" },
  { abbr: "POR", name: "Portland Trail Blazers" },
  { abbr: "SAC", name: "Sacramento Kings" },
  { abbr: "SAS", name: "San Antonio Spurs" },
  { abbr: "TOR", name: "Toronto Raptors" },
  { abbr: "UTA", name: "Utah Jazz" },
  { abbr: "WAS", name: "Washington Wizards" },
];

document.addEventListener("DOMContentLoaded", () => {
  // 1. Parse URL deep link parameters from FastCheck FIRST before rendering
  const urlParams = new URLSearchParams(window.location.search);
  const pIdParam = urlParams.get("player_id");
  const pNameParam = urlParams.get("player_name");
  const lineParam = urlParams.get("line");
  const overParam = urlParams.get("odds_over");
  const underParam = urlParams.get("odds_under");
  const oppParam = urlParams.get("opp");

  if (pIdParam) {
    selectedPlayerId = parseInt(pIdParam);
    if (pNameParam) {
      selectedPlayerName = decodeURIComponent(pNameParam);
      const nameHeading = document.getElementById("current-player-name");
      if (nameHeading) nameHeading.textContent = selectedPlayerName;
    }
  }

  initHealthCheck();
  initSyncStatus();
  renderQuickStars();
  populateOpponentDropdown();
  setupEventListeners();

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
    if (oppParam && document.getElementById("select-opponent")) {
      document.getElementById("select-opponent").value = oppParam;
    }
  }

  fetchPlayerHistory(selectedPlayerId, getActiveOpponent());
  runPrediction(); // Initial prediction
});

function populateOpponentDropdown() {
  const select = document.getElementById("select-opponent");
  if (!select) return;
  NBA_TEAMS.forEach(t => {
    const opt = document.createElement("option");
    opt.value = t.abbr;
    opt.textContent = `${t.abbr} - ${t.name}`;
    select.appendChild(opt);
  });
  select.addEventListener("change", (e) => {
    fetchPlayerHistory(selectedPlayerId, e.target.value);
    runPrediction();
  });
}

function initSyncStatus() {
  fetch("/api/sync/status")
    .then(r => r.json())
    .then(data => {
      const el = document.getElementById("sync-status-text");
      if (data.latest_game_date) {
        const now = new Date();
        const vnHour = (now.getUTCHours() + 7) % 24;
        const isPost1PM = vnHour >= 13;
        const slateDesc = isPost1PM ? "Auto-Rolled to Next Slate" : "Morning Round Active";
        el.textContent = `2026-27 Active • Latest: ${data.latest_game_date} • ${slateDesc}`;
        el.parentElement.title = `Các trận ngày ${data.latest_game_date} (giờ Mỹ) đã kết thúc. Sau 13:00 VN, hệ thống tự động nhảy sang phân tích lượt trận tiếp theo của ngày mai.`;
      } else {
        el.textContent = "Season 2026-27 Synced";
      }
    })
    .catch(() => {});
}

function triggerManualSync() {
  const btn = document.getElementById("btn-sync-now");
  const text = document.getElementById("sync-button-text");
  const icon = document.getElementById("sync-icon");
  const statusEl = document.getElementById("sync-status-text");

  btn.disabled = true;
  text.textContent = "Syncing 2026-27...";
  icon.classList.add("animate-spin");

  fetch("/api/sync", { method: "POST" })
    .then(r => r.json())
    .then(data => {
      btn.disabled = false;
      text.textContent = "Sync Live Games";
      icon.classList.remove("animate-spin");
      if (data.latest_game_date) {
        statusEl.textContent = `2026-27 Active • Latest: ${data.latest_game_date}`;
      }
      // Re-run prediction with updated player states
      runPrediction();
    })
    .catch(err => {
      console.error("Sync error:", err);
      btn.disabled = false;
      text.textContent = "Sync Failed";
      icon.classList.remove("animate-spin");
    });
}

function initHealthCheck() {
  fetch("/api/health")
    .then(r => r.json())
    .then(data => {
      const el = document.getElementById("api-status");
      el.textContent = `Online • ${data.models_loaded.length} models loaded`;
    })
    .catch(() => {
      document.getElementById("api-status").textContent = "API Offline";
    });
}

function renderQuickStars() {
  const container = document.getElementById("quick-stars");
  if (!container) return;
  container.innerHTML = "";

  const isStar = STAR_PLAYERS.some(star => star.id === selectedPlayerId);
  if (!isStar && selectedPlayerId && selectedPlayerName && selectedPlayerName !== "Select a Player") {
    const customBtn = document.createElement("button");
    customBtn.className = "text-xs px-2.5 py-1 rounded-md hairline-border text-white transition bg-indigo-950 text-indigo-300 border-indigo-700 font-semibold";
    customBtn.textContent = selectedPlayerName.split(" ").slice(-1)[0] || selectedPlayerName;
    customBtn.title = selectedPlayerName;
    container.appendChild(customBtn);
  }

  STAR_PLAYERS.forEach(star => {
    const btn = document.createElement("button");
    btn.className = "text-xs px-2.5 py-1 rounded-md hairline-border text-gray-300 hover:text-white transition";
    btn.style.backgroundColor = star.id === selectedPlayerId ? "var(--surface-3)" : "var(--surface-2)";
    btn.textContent = star.name.split(" ")[1] || star.name;
    btn.title = star.name;
    btn.onclick = () => {
      selectPlayer(star.id, star.name);
    };
    container.appendChild(btn);
  });
}

function setupEventListeners() {
  // Stat selector pills
  document.querySelectorAll(".stat-pill").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".stat-pill").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      selectedStat = btn.dataset.stat;
      
      // Adjust default suggested lines based on stat
      const lineInput = document.getElementById("input-line");
      if (selectedStat === "pts") lineInput.value = "24.5";
      else if (selectedStat === "reb") lineInput.value = "6.5";
      else if (selectedStat === "ast") lineInput.value = "5.5";
      
      // Instant recalculation on client without network request (§7)
      renderPlayerHistory();
      runPrediction();
    });
  });

  // Calculate button
  document.getElementById("btn-calculate").addEventListener("click", runPrediction);

  // Line input live change -> instant recalculation for player history reference
  const lineInput = document.getElementById("input-line");
  if (lineInput) {
    lineInput.addEventListener("input", () => {
      renderPlayerHistory();
    });
  }

  // History Over/Under selector buttons (§5.1)
  const btnHistOver = document.getElementById("btn-history-side-over");
  const btnHistUnder = document.getElementById("btn-history-side-under");
  if (btnHistOver) {
    btnHistOver.addEventListener("click", () => {
      currentHistorySide = "over";
      renderPlayerHistory();
    });
  }
  if (btnHistUnder) {
    btnHistUnder.addEventListener("click", () => {
      currentHistorySide = "under";
      renderPlayerHistory();
    });
  }

  // History Tab buttons (§4)
  const tabRecent = document.getElementById("tab-history-recent");
  const tabH2H = document.getElementById("tab-history-h2h");
  if (tabRecent) {
    tabRecent.addEventListener("click", () => {
      currentHistoryTab = "recent";
      renderPlayerHistory();
    });
  }
  if (tabH2H) {
    tabH2H.addEventListener("click", () => {
      currentHistoryTab = "h2h";
      renderPlayerHistory();
    });
  }

  // Sync Live button
  const syncBtn = document.getElementById("btn-sync-now");
  if (syncBtn) {
    syncBtn.addEventListener("click", triggerManualSync);
  }

  // Search input debounce
  let debounceTimeout = null;
  document.getElementById("player-search").addEventListener("input", e => {
    clearTimeout(debounceTimeout);
    debounceTimeout = setTimeout(() => {
      searchPlayers(e.target.value);
    }, 250);
  });
}

function searchPlayers(query) {
  if (!query || query.trim().length < 2) {
    document.getElementById("players-list").innerHTML = "";
    return;
  }
  fetch(`/api/players?query=${encodeURIComponent(query)}&limit=10`)
    .then(r => r.json())
    .then(players => {
      const list = document.getElementById("players-list");
      list.innerHTML = "";
      players.forEach(p => {
        const item = document.createElement("div");
        item.className = "p-2 rounded-lg cursor-pointer text-xs flex justify-between items-center hover:bg-neutral-800 transition";
        item.innerHTML = `
          <span class="font-medium text-white">${p.full_name}</span>
          <span class="text-[10px] text-gray-400 font-mono">ID: ${p.player_id}</span>
        `;
        item.onclick = () => selectPlayer(p.player_id, p.full_name);
        list.appendChild(item);
      });
    });
}

function selectPlayer(id, name) {
  selectedPlayerId = id;
  selectedPlayerName = name;
  document.getElementById("current-player-name").textContent = name;
  renderQuickStars();
  fetchPlayerHistory(selectedPlayerId, getActiveOpponent());
  runPrediction();
}

function runPrediction() {
  const lineInput = document.getElementById("input-line");
  const line = lineInput ? (parseFloat(lineInput.value) || null) : null;
  const oddsOverInput = document.getElementById("input-odds-over");
  const oddsOver = oddsOverInput ? (parseFloat(oddsOverInput.value) || null) : null;
  const oddsUnderInput = document.getElementById("input-odds-under");
  const oddsUnder = oddsUnderInput ? (parseFloat(oddsUnderInput.value) || null) : null;
  const oppSelect = document.getElementById("select-opponent");
  const oppOverride = oppSelect ? (oppSelect.value || null) : null;

  const btn = document.getElementById("btn-calculate");
  if (btn) {
    btn.disabled = true;
    btn.classList.add("opacity-75");
    btn.innerHTML = `<span>Calculating...</span>`;
  }

  const payload = {
    player_id: selectedPlayerId,
    stat: selectedStat,
    line: line,
    odds_over: oddsOver,
    odds_under: oddsUnder,
    opponent_override: oppOverride,
  };

  fetch("/api/predict", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
    .then(async r => {
      const data = await r.json();
      if (!r.ok) {
        throw new Error(data.detail || `Server returned HTTP ${r.status}`);
      }
      return data;
    })
    .then(data => {
      updateDashboard(data);
    })
    .catch(err => {
      console.error("Prediction error:", err);
      const metricEv = document.getElementById("metric-ev");
      if (metricEv) metricEv.textContent = "Error";
      alert(`Prediction request failed: ${err.message}`);
    })
    .finally(() => {
      if (btn) {
        btn.disabled = false;
        btn.classList.remove("opacity-75");
        btn.innerHTML = `<span>Calculate Distribution & Probabilities</span>`;
      }
    });
}

function updateDashboard(data) {
  // Sync selected player state
  selectedPlayerId = data.player_id;
  selectedPlayerName = data.player_name;
  renderQuickStars();

  // Update header titles
  document.getElementById("current-player-name").textContent = data.player_name;
  document.getElementById("current-player-team").textContent = `Team: ${data.team_abbreviation || "NBA"} • Market: ${data.stat}`;

  // Key metrics
  document.getElementById("metric-ev").textContent = data.expected_value.toFixed(2);
  document.getElementById("metric-median").textContent = data.median;
  document.getElementById("metric-interval").textContent = `[${data.prediction_interval.lower}, ${data.prediction_interval.upper}]`;

  // Condition card
  const condCard = document.getElementById("condition-card");
  condCard.style.display = "block";
  const badge = document.getElementById("condition-badge");
  badge.textContent = data.condition.status;
  if (data.condition.status === "READY") {
    badge.className = "text-xs px-2.5 py-0.5 rounded-full font-semibold bg-emerald-950 text-emerald-400 border border-emerald-800";
  } else if (data.condition.status === "SCENARIO_ONLY") {
    badge.className = "text-xs px-2.5 py-0.5 rounded-full font-semibold bg-amber-950 text-amber-400 border border-amber-800";
  } else {
    badge.className = "text-xs px-2.5 py-0.5 rounded-full font-semibold bg-rose-950 text-rose-400 border border-rose-800";
  }
  document.getElementById("condition-action").textContent = data.condition.action;
  document.getElementById("meta-games").textContent = data.condition.metadata.n_games_history;
  document.getElementById("meta-rest").textContent = data.condition.metadata.rest_days !== null ? `${data.condition.metadata.rest_days}d` : "N/A";
  document.getElementById("meta-min").textContent = data.condition.metadata.min_roll_mean_5;

  // Live ESPN Player Injury Card
  const injCard = document.getElementById("injury-card");
  if (data.player_injury) {
    injCard.style.display = "block";
    const badge = document.getElementById("player-injury-badge");
    badge.textContent = data.player_injury.status.toUpperCase();
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

    // Rest advantage badge
    const restAdvEl = document.getElementById("badge-rest-adv");
    if (sc.rest_advantage_days > 0) {
      restAdvEl.textContent = `+${sc.rest_advantage_days}d Advantage`;
      restAdvEl.className = "text-xs px-2.5 py-0.5 rounded-full font-mono font-semibold bg-emerald-950 text-emerald-400 border border-emerald-800";
    } else if (sc.rest_advantage_days < 0) {
      restAdvEl.textContent = `${sc.rest_advantage_days}d Deficit`;
      restAdvEl.className = "text-xs px-2.5 py-0.5 rounded-full font-mono font-semibold bg-amber-950 text-amber-400 border border-amber-800";
    } else {
      restAdvEl.textContent = "Even Rest (0d)";
      restAdvEl.className = "text-xs px-2.5 py-0.5 rounded-full font-mono font-semibold bg-neutral-800 text-gray-300 border border-neutral-700";
    }

    // Dynamic schedule badges
    const badgesContainer = document.getElementById("schedule-badges");
    badgesContainer.innerHTML = "";

    if (sc.team_b2b_but_player_rested) {
      badgesContainer.innerHTML += `<span class="text-[11px] px-2 py-0.5 rounded font-medium bg-emerald-900/60 text-emerald-300 border border-emerald-700">Team B2B (Player Rested)</span>`;
    } else if (sc.team_b2b) {
      badgesContainer.innerHTML += `<span class="text-[11px] px-2 py-0.5 rounded font-medium bg-amber-900/60 text-amber-300 border border-amber-700">Team B2B Active</span>`;
    }

    if (sc.opp_b2b) {
      badgesContainer.innerHTML += `<span class="text-[11px] px-2 py-0.5 rounded font-medium bg-emerald-900/60 text-emerald-300 border border-emerald-700">Opponent on B2B</span>`;
    }

    if (sc.team_3in4) {
      badgesContainer.innerHTML += `<span class="text-[11px] px-2 py-0.5 rounded font-medium bg-rose-900/60 text-rose-300 border border-rose-700">3 Games in 4 Days</span>`;
    } else if (sc.team_4in6) {
      badgesContainer.innerHTML += `<span class="text-[11px] px-2 py-0.5 rounded font-medium bg-amber-900/60 text-amber-300 border border-amber-700">4 Games in 6 Days</span>`;
    }

    document.getElementById("sched-team-rest").textContent = `${sc.team_rest_days}d`;
    document.getElementById("sched-opp-rest").textContent = `${sc.opp_rest_days}d`;
    document.getElementById("sched-workload").textContent = `${sc.player_minutes_last7days}m`;
    document.getElementById("sched-prev-played").textContent = sc.player_played_previous_team_game ? "Played" : "DNP/Rested";

    // Teammate injuries
    const tBox = document.getElementById("teammate-injuries-box");
    const tList = document.getElementById("teammate-injuries-list");
    const tVacBadge = document.getElementById("teammate-vacancy-badge");
    if (data.teammate_injuries && data.teammate_injuries.length > 0) {
      tBox.style.display = "block";
      const tmVac = data.injury_impact ? data.injury_impact.teammate_missing_minutes : 0;
      if (tVacBadge) {
        tVacBadge.textContent = `${tmVac.toFixed(1)}m`;
      }
      tList.innerHTML = data.teammate_injuries.slice(0, 5).map(inj => {
        const m = inj.missing_minutes != null ? inj.missing_minutes : 0;
        return `
          <div class="text-[11px] flex justify-between items-center text-gray-300">
            <span>${inj.player_name} (${inj.position ? inj.position[0] : 'P'}):</span>
            <div class="flex items-center space-x-1.5">
              <span class="font-mono font-semibold ${inj.status.toLowerCase().includes('out') ? 'text-rose-400' : 'text-amber-400'}">${inj.status}</span>
              <span class="text-[10px] text-amber-300 font-mono">(${m.toFixed(1)}m)</span>
            </div>
          </div>
        `;
      }).join("");
    } else {
      tBox.style.display = "none";
    }
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
          elPtsStatus.textContent = "Thủ chặt (Khó nổ PTS)";
          elPtsStatus.className = "text-[9px] mt-1 font-medium block text-rose-400";
        } else if (r >= 21) {
          elPtsRank.className = "text-xs font-mono font-bold px-1.5 py-0.5 rounded bg-emerald-950/80 text-emerald-300 border border-emerald-800/60";
          elPtsStatus.textContent = "Thủ lỏng (Dễ nổ Over)";
          elPtsStatus.className = "text-[9px] mt-1 font-medium block text-emerald-400";
        } else {
          elPtsRank.className = "text-xs font-mono font-bold px-1.5 py-0.5 rounded bg-neutral-800 text-gray-300 border border-neutral-700/60";
          elPtsStatus.textContent = "Trung bình giải";
          elPtsStatus.className = "text-[9px] mt-1 font-medium block text-gray-400";
        }
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
          elFg3mStatus.textContent = "Bọc 3P chặt";
          elFg3mStatus.className = "text-[9px] mt-1 font-medium block text-rose-400";
        } else if (r >= 21) {
          elFg3mRank.className = "text-xs font-mono font-bold px-1.5 py-0.5 rounded bg-emerald-950/80 text-emerald-300 border border-emerald-800/60";
          elFg3mStatus.textContent = "Hở 3P (Dễ Over)";
          elFg3mStatus.className = "text-[9px] mt-1 font-medium block text-emerald-400";
        } else {
          elFg3mRank.className = "text-xs font-mono font-bold px-1.5 py-0.5 rounded bg-neutral-800 text-gray-300 border border-neutral-700/60";
          elFg3mStatus.textContent = "3P Trung bình";
          elFg3mStatus.className = "text-[9px] mt-1 font-medium block text-gray-400";
        }
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
          elBlkStatus.textContent = "Khối cản mạnh (Khó đè)";
          elBlkStatus.className = "text-[9px] mt-1 font-medium block text-rose-400";
        } else if (r <= 10) {
          elBlkRank.className = "text-xs font-mono font-bold px-1.5 py-0.5 rounded bg-emerald-950/80 text-emerald-300 border border-emerald-800/60";
          elBlkStatus.textContent = "Ít Block (Dễ ăn rổ)";
          elBlkStatus.className = "text-[9px] mt-1 font-medium block text-emerald-400";
        } else {
          elBlkRank.className = "text-xs font-mono font-bold px-1.5 py-0.5 rounded bg-neutral-800 text-gray-300 border border-neutral-700/60";
          elBlkStatus.textContent = "Block trung bình";
          elBlkStatus.className = "text-[9px] mt-1 font-medium block text-gray-400";
        }
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
          elStatus.textContent = "Thủ lỏng (Dễ Over)";
          elStatus.className = "text-[9px] font-medium block text-emerald-400 mt-0.5";
        } else {
          elRank.className = "text-xs font-mono font-bold px-1.5 py-0.5 rounded bg-neutral-800 text-gray-300 border border-neutral-700/60";
          elStatus.textContent = "Trung bình";
          elStatus.className = "text-[9px] font-medium block text-gray-400 mt-0.5";
        }
      };

      renderDvpStat("pts", dvp.pts);
      renderDvpStat("reb", dvp.reb);
      renderDvpStat("ast", dvp.ast);
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
      oppList.innerHTML = data.opponent_injuries.slice(0, 5).map(inj => {
        const m = inj.missing_minutes != null ? inj.missing_minutes : 0;
        return `
          <div class="text-[11px] flex justify-between items-center text-gray-300">
            <span>${inj.player_name} (${inj.position ? inj.position[0] : 'P'}):</span>
            <div class="flex items-center space-x-1.5">
              <span class="font-mono font-semibold ${inj.status.toLowerCase().includes('out') ? 'text-rose-400' : 'text-indigo-400'}">${inj.status}</span>
              <span class="text-[10px] text-indigo-300 font-mono">(${m.toFixed(1)}m)</span>
            </div>
          </div>
        `;
      }).join("");
    } else {
      oppBox.style.display = "none";
    }
  }

  // Live Matchup & Schedule Resolver
  if (data.upcoming_game_info) {
    const info = data.upcoming_game_info;
    const badge = document.getElementById("matchup-context-badge");
    const tipText = document.getElementById("matchup-tipoff-text");

    const isOverride = Boolean(info.is_override || (info.active_opponent && info.scheduled_opponent && info.active_opponent !== info.scheduled_opponent));
    const activeOpp = info.active_opponent || info.opponent || (data.opponent_context ? data.opponent_context.opponent_abbr : "OPP");
    const schedOpp = info.scheduled_opponent || info.opponent || "TBD";
    const homeTeam = info.home_team || (info.is_home ? (data.team_abbreviation || "HOME") : schedOpp);
    const awayTeam = info.away_team || (info.is_home ? schedOpp : (data.team_abbreviation || "AWAY"));
    const statusText = info.game_status_text || "Scheduled";
    const gameDate = (info.game_date && info.game_date !== "None") ? info.game_date.split("T")[0] : "Upcoming";

    const slateLabel = info.slate_label || "Upcoming";
    const tipoffVn = info.tipoff_vn || "";

    if (badge) {
      if (isOverride) {
        badge.textContent = `Scenario vs ${activeOpp}`;
        badge.className = "text-xs px-2.5 py-0.5 rounded-full font-mono font-medium bg-indigo-950 text-indigo-300 border border-indigo-700";
      } else {
        const matchStr = info.is_home ? `vs ${schedOpp}` : `@ ${schedOpp}`;
        if (slateLabel === "Today") {
          badge.textContent = `Hôm nay: ${matchStr} (${statusText})`;
          badge.className = "text-xs px-2.5 py-0.5 rounded-full font-mono font-medium bg-emerald-950 text-emerald-400 border border-emerald-800";
        } else if (slateLabel === "Tomorrow") {
          badge.textContent = `Ngày mai (13/11): ${matchStr} (${statusText})`;
          badge.className = "text-xs px-2.5 py-0.5 rounded-full font-mono font-medium bg-indigo-950 text-indigo-300 border border-indigo-700";
        } else {
          badge.textContent = `Ngày ${slateLabel}: ${matchStr} (${statusText})`;
          badge.className = "text-xs px-2.5 py-0.5 rounded-full font-mono font-medium bg-neutral-800 text-gray-300 border border-neutral-700";
        }
      }
    }

    if (tipText) {
      if (isOverride) {
        tipText.textContent = `Testing custom scenario vs ${activeOpp} pace (${data.opponent_context ? data.opponent_context.opp_pace_prev10 : '-'}) & def rating (${data.opponent_context ? data.opponent_context.opp_def_rating_prev10 : '-'})`;
      } else {
        const timeDetail = tipoffVn ? `${tipoffVn}` : gameDate;
        tipText.textContent = `Lịch thi đấu NBA: ${awayTeam} @ ${homeTeam} • ${timeDetail}`;
      }
    }
  }

  // Probabilities
  if (data.line_probabilities) {
    const lp = data.line_probabilities;
    document.getElementById("over-line-val").textContent = lp.line;
    document.getElementById("under-line-val").textContent = lp.line;
    document.getElementById("prob-over").textContent = (lp.q_over * 100).toFixed(1) + "%";
    document.getElementById("prob-under").textContent = (lp.q_under * 100).toFixed(1) + "%";
    document.getElementById("prob-push").textContent = (lp.q_push * 100).toFixed(1) + "%";

    // Pricing & EV
    if (data.pricing) {
      document.getElementById("over-fair-odds").textContent = `Fair: ${(1 / data.pricing.fair_over).toFixed(2)}`;
      document.getElementById("under-fair-odds").textContent = `Fair: ${(1 / data.pricing.fair_under).toFixed(2)}`;

      const evOver = data.pricing.ev_over;
      const evUnder = data.pricing.ev_under;
      const evOverEl = document.getElementById("ev-over-val");
      const evUnderEl = document.getElementById("ev-under-val");

      evOverEl.textContent = (evOver >= 0 ? "+" : "") + (evOver * 100).toFixed(1) + "%";
      evOverEl.className = `font-mono font-semibold ${evOver >= 0 ? "text-emerald-400" : "text-rose-400"}`;

      evUnderEl.textContent = (evUnder >= 0 ? "+" : "") + (evUnder * 100).toFixed(1) + "%";
      evUnderEl.className = `font-mono font-semibold ${evUnder >= 0 ? "text-emerald-400" : "text-rose-400"}`;

      const edgeMetric = document.getElementById("metric-edge");
      edgeMetric.textContent = (evOver >= 0 ? "+" : "") + (evOver * 100).toFixed(1) + "%";
      edgeMetric.className = `text-2xl font-bold font-mono mt-1 ${evOver >= 0 ? "text-emerald-400" : "text-rose-400"}`;
    }
  }

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
    rBadge.textContent = rd.status;
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
  const oppSelect = document.getElementById("select-opponent");
  if (oppSelect && oppSelect.value) return oppSelect.value;
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
  const cacheKey = `${playerId}_${opp}`;
  if (playerHistoryCache.has(cacheKey)) {
    currentHistoryData = playerHistoryCache.get(cacheKey);
    renderPlayerHistory();
    return;
  }

  const requestId = ++currentHistoryRequestId;
  if (historyAbortController) {
    try { historyAbortController.abort(); } catch (e) {}
  }
  historyAbortController = new AbortController();

  let url = `/api/players/${playerId}/history?limit=10`;
  if (opp) {
    url += `&opponent_abbr=${encodeURIComponent(opp)}`;
  }

  const tbody = document.getElementById("hist-table-body");
  if (tbody && !currentHistoryData) {
    tbody.innerHTML = `<tr><td colspan="12" class="py-8 text-center text-gray-500 font-sans">Đang tải lịch sử thi đấu...</td></tr>`;
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
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="12" class="py-6 text-center text-gray-400 font-sans">Chưa có dữ liệu lịch sử thi đấu (${err.message || 'Lỗi kết nối'}).</td></tr>`;
      }
      resetHistorySummary();
    });
}

function resetHistorySummary() {
  const countsEl = document.getElementById("hist-summary-counts");
  const totalEl = document.getElementById("hist-summary-total");
  const rateTotEl = document.getElementById("hist-hit-rate-total");
  const rateNoPEl = document.getElementById("hist-hit-rate-nopush");
  if (countsEl) countsEl.textContent = "-- Hit · -- Miss · -- Push";
  if (totalEl) totalEl.textContent = "(0 trận)";
  if (rateTotEl) rateTotEl.textContent = "—";
  if (rateNoPEl) rateNoPEl.textContent = "—";
}

function renderPlayerHistory() {
  const lineInput = document.getElementById("input-line");
  const lineVal = lineInput ? parseFloat(lineInput.value) : null;
  const line = (lineVal !== null && !isNaN(lineVal) && lineVal >= 0) ? lineVal : null;

  // 1. Target badge in header
  const targetBadge = document.getElementById("history-target-badge");
  if (targetBadge) {
    const statUpper = (selectedStat || "pts").toUpperCase();
    const sideLabel = currentHistorySide === "over" ? "Over" : "Under";
    const lineLabel = line !== null ? line : "--";
    targetBadge.textContent = `${statUpper} · ${sideLabel} ${lineLabel}`;
  }

  // 2. Over/Under selector toggle styling
  const btnOver = document.getElementById("btn-history-side-over");
  const btnUnder = document.getElementById("btn-history-side-under");
  if (btnOver && btnUnder) {
    if (currentHistorySide === "over") {
      btnOver.style.backgroundColor = "var(--primary)";
      btnOver.style.color = "#ffffff";
      btnOver.className = "px-3 py-1 rounded-md text-xs font-semibold transition active cursor-pointer";
      btnUnder.style.backgroundColor = "transparent";
      btnUnder.style.color = "var(--ink-subtle)";
      btnUnder.className = "px-3 py-1 rounded-md text-xs font-medium text-gray-400 hover:text-white transition cursor-pointer";
    } else {
      btnUnder.style.backgroundColor = "var(--primary)";
      btnUnder.style.color = "#ffffff";
      btnUnder.className = "px-3 py-1 rounded-md text-xs font-semibold transition active cursor-pointer";
      btnOver.style.backgroundColor = "transparent";
      btnOver.style.color = "var(--ink-subtle)";
      btnOver.className = "px-3 py-1 rounded-md text-xs font-medium text-gray-400 hover:text-white transition cursor-pointer";
    }
  }

  // 3. Extract recent and H2H game logs
  const recentRows = (currentHistoryData && currentHistoryData.recent) 
    ? (currentHistoryData.recent.rows || (Array.isArray(currentHistoryData.recent) ? currentHistoryData.recent : [])) 
    : [];
  const h2hRows = (currentHistoryData && currentHistoryData.vs_opponent) 
    ? (currentHistoryData.vs_opponent.rows || (Array.isArray(currentHistoryData.vs_opponent) ? currentHistoryData.vs_opponent : [])) 
    : [];

  const badgeRecent = document.getElementById("badge-count-recent");
  const badgeH2H = document.getElementById("badge-count-h2h");
  if (badgeRecent) badgeRecent.textContent = `${recentRows.length}/10`;
  if (badgeH2H) badgeH2H.textContent = `${h2hRows.length}/10`;

  const activeOpp = getActiveOpponent();
  const tabH2HTitle = document.getElementById("tab-h2h-title");
  if (tabH2HTitle) {
    tabH2HTitle.textContent = activeOpp ? `Đối đầu ${activeOpp}` : "Đối đầu đối thủ";
  }

  // 4. Tab highlighting
  const tabRecent = document.getElementById("tab-history-recent");
  const tabH2H = document.getElementById("tab-history-h2h");
  if (tabRecent && tabH2H) {
    if (currentHistoryTab === "recent") {
      tabRecent.className = "px-4 py-2 text-xs font-semibold text-indigo-300 border-b-2 border-indigo-500 transition focus:outline-none flex items-center gap-1.5 cursor-pointer";
      tabH2H.className = "px-4 py-2 text-xs font-medium text-gray-400 hover:text-gray-200 border-b-2 border-transparent transition focus:outline-none flex items-center gap-1.5 cursor-pointer";
    } else {
      tabH2H.className = "px-4 py-2 text-xs font-semibold text-indigo-300 border-b-2 border-indigo-500 transition focus:outline-none flex items-center gap-1.5 cursor-pointer";
      tabRecent.className = "px-4 py-2 text-xs font-medium text-gray-400 hover:text-gray-200 border-b-2 border-transparent transition focus:outline-none flex items-center gap-1.5 cursor-pointer";
    }
  }

  const activeRows = currentHistoryTab === "recent" ? recentRows : h2hRows;

  // 5. Coverage / Incomplete Notice (§3.3 & §5)
  const noticeBox = document.getElementById("hist-coverage-notice");
  const noticeText = document.getElementById("hist-coverage-text");
  if (noticeBox && noticeText) {
    if (currentHistoryTab === "h2h") {
      const cov = currentHistoryData ? currentHistoryData.coverage : null;
      const isComplete = cov ? cov.history_complete_for_requested_scope : (activeRows.length >= 10);
      if (activeRows.length === 0) {
        noticeBox.style.display = "flex";
        noticeText.textContent = activeOpp ? `Chưa có dữ liệu đối đầu với ${activeOpp} trong các mùa giải đã tải.` : `Chọn đối thủ để xem lịch sử đối đầu.`;
      } else if (activeRows.length < 10 || (cov && !isComplete)) {
        noticeBox.style.display = "flex";
        noticeText.textContent = `${activeRows.length}/10 trận có dữ liệu. Dữ liệu đối đầu có thể chưa đầy đủ theo phạm vi mùa giải.`;
      } else {
        noticeBox.style.display = "none";
      }
    } else {
      if (activeRows.length < 10 && activeRows.length > 0) {
        noticeBox.style.display = "flex";
        noticeText.textContent = `${activeRows.length}/10 trận ra sân gần nhất có sẵn dữ liệu.`;
      } else {
        noticeBox.style.display = "none";
      }
    }
  }

  // 6. Summary metrics calculation (§5.3)
  let H = 0, M = 0, P = 0, validRows = 0;
  if (line !== null) {
    activeRows.forEach(r => {
      const val = getStatValue(r, selectedStat);
      const cmp = compareStat(val, line, currentHistorySide);
      if (cmp.outcome === "hit") { H++; validRows++; }
      else if (cmp.outcome === "miss") { M++; validRows++; }
      else if (cmp.outcome === "push") { P++; validRows++; }
    });
  }

  const totalEvaluated = H + M + P;
  const hitRateTotal = totalEvaluated > 0 ? ((H / totalEvaluated) * 100).toFixed(1) + "%" : "—";
  const hitRateNoPush = (H + M) > 0 ? ((H / (H + M)) * 100).toFixed(1) + "%" : "—";

  const countsEl = document.getElementById("hist-summary-counts");
  const totalEl = document.getElementById("hist-summary-total");
  const rateTotEl = document.getElementById("hist-hit-rate-total");
  const rateNoPEl = document.getElementById("hist-hit-rate-nopush");

  if (countsEl) {
    countsEl.textContent = line !== null ? `${H} Hit · ${M} Miss · ${P} Push` : "-- Hit · -- Miss · -- Push";
  }
  if (totalEl) {
    totalEl.textContent = `(${validRows}/${activeRows.length} trận)`;
  }
  if (rateTotEl) rateTotEl.textContent = hitRateTotal;
  if (rateNoPEl) rateNoPEl.textContent = hitRateNoPush;

  // 7. Render Table Rows
  const tbody = document.getElementById("hist-table-body");
  if (!tbody) return;

  if (!currentHistoryData) {
    tbody.innerHTML = `<tr><td colspan="12" class="py-8 text-center text-gray-500 font-sans">Đang tải lịch sử thi đấu...</td></tr>`;
    return;
  }

  if (activeRows.length === 0) {
    const emptyMsg = currentHistoryTab === "h2h" 
      ? `Không tìm thấy trận đối đầu nào với ${activeOpp || 'đối thủ này'}.`
      : `Không có dữ liệu 10 trận gần nhất.`;
    tbody.innerHTML = `<tr><td colspan="12" class="py-8 text-center text-gray-400 font-sans">${emptyMsg}</td></tr>`;
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

    // Compare active stat
    const activeVal = getStatValue(row, curStat);
    const cmp = compareStat(activeVal, line, currentHistorySide);

    // Styling helpers
    // Hit: #e8f5e9 / text #2e7d32
    // Miss: #ffebee / text #c62828
    // Push: #f5f5f5 / text #616161
    const getActiveStyle = (outcome) => {
      if (outcome === "hit") {
        return "background-color: #e8f5e9; color: #2e7d32; font-weight: 700; border-radius: 4px;";
      }
      if (outcome === "miss") {
        return "background-color: #ffebee; color: #c62828; font-weight: 700; border-radius: 4px;";
      }
      if (outcome === "push") {
        return "background-color: #f5f5f5; color: #616161; font-weight: 700; border-radius: 4px;";
      }
      return "";
    };

    const renderStatCell = (statKey, val) => {
      const isTarget = statKey === curStat;
      const valStr = val != null ? val : "—";
      if (!isTarget) {
        return `<td class="py-2.5 px-2 text-right text-gray-300 font-mono">${valStr}</td>`;
      }
      // Target stat cell gets highlighted according to hit/miss/push (§5.1)
      const cellStyle = getActiveStyle(cmp.outcome);
      if (cellStyle) {
        return `<td class="py-2.5 px-2 text-right font-mono" style="${cellStyle}">${valStr}</td>`;
      }
      return `<td class="py-2.5 px-2 text-right text-white font-bold font-mono">${valStr}</td>`;
    };

    // Render Badge
    let badgeHtml = `<span class="text-gray-500 font-mono">—</span>`;
    if (cmp.outcome === "hit") {
      badgeHtml = `<span class="px-2 py-0.5 rounded text-[11px] font-bold inline-block" style="background-color: #e8f5e9; color: #2e7d32;">Hit</span>`;
    } else if (cmp.outcome === "miss") {
      badgeHtml = `<span class="px-2 py-0.5 rounded text-[11px] font-bold inline-block" style="background-color: #ffebee; color: #c62828;">Miss</span>`;
    } else if (cmp.outcome === "push") {
      badgeHtml = `<span class="px-2 py-0.5 rounded text-[11px] font-bold inline-block" style="background-color: #f5f5f5; color: #616161;">Push</span>`;
    } else if (cmp.outcome === "missing") {
      badgeHtml = `<span class="text-gray-500 font-mono">—</span>`;
    }

    return `
      <tr class="hover:bg-neutral-800/40 transition">
        <td class="py-2.5 px-3 text-white font-medium whitespace-nowrap">${dateSeasonDisplay}</td>
        <td class="py-2.5 px-2.5 text-gray-300 font-semibold">${playerTeam}</td>
        <td class="py-2.5 px-2.5 text-indigo-300 font-medium">${matchIndicator}</td>
        <td class="py-2.5 px-2 text-right text-gray-400 font-mono">${minVal}</td>
        ${renderStatCell("pts", pts)}
        ${renderStatCell("reb", reb)}
        ${renderStatCell("ast", ast)}
        ${renderStatCell("fg3m", fg3m)}
        ${renderStatCell("stl", stl)}
        ${renderStatCell("blk", blk)}
        ${renderStatCell("tov", tov)}
        <td class="py-2.5 px-3 text-center whitespace-nowrap">${badgeHtml}</td>
      </tr>
    `;
  }).join("");
}
