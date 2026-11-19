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

let team1Roster = [];
let team2Roster = [];
let debounceTimers = {};
let playerAbortControllers = {};
let batchAbortController = null;
let matchupAbortController = null;
let syncPollingTimer = null;
let rowVersions = {}; // Issue 16: Monotonic per-player request version counter
let currentRosterGeneration = 0; // Issue 16: Monotonic roster load generation counter

document.addEventListener("DOMContentLoaded", () => {
  populateDropdowns();
  initSyncStatus();
  resetMatchupState();
  initOcrModal();

  const btnCalcAll = document.getElementById("btn-calc-all");
  if (btnCalcAll) {
    btnCalcAll.addEventListener("click", calculateAll);
  }
});

function resetMatchupState() {
  const s1 = document.getElementById("team1-select");
  const s2 = document.getElementById("team2-select");
  if (s1) s1.value = "";
  if (s2) s2.value = "";

  document.getElementById("team1-badge").textContent = "---";
  document.getElementById("team2-badge").textContent = "---";
  document.getElementById("team1-title").textContent = "Đội 1";
  document.getElementById("team2-title").textContent = "Đội 2";
  document.getElementById("team1-status-pill").textContent = "Chưa chọn";
  document.getElementById("team2-status-pill").textContent = "Chưa chọn";

  const tipText = document.getElementById("matchup-tipoff-text");
  if (tipText) {
    tipText.textContent = "Chọn một đội bất kỳ để tự động khớp đối thủ theo lịch NBA";
  }

  const def1 = document.getElementById("team1-def-badge");
  const def2 = document.getElementById("team2-def-badge");
  if (def1) def1.innerHTML = `<span class="text-gray-500">Toàn bộ đội hình & dàn bench (Points - PTS)</span>`;
  if (def2) def2.innerHTML = `<span class="text-gray-500">Toàn bộ đội hình & dàn bench (Points - PTS)</span>`;

  const list1 = document.getElementById("team1-roster-list");
  const list2 = document.getElementById("team2-roster-list");
  if (list1) {
    list1.innerHTML = `<div class="text-center py-12 text-xs text-gray-500">Vui lòng chọn đội để hiển thị danh sách cầu thủ.</div>`;
  }
  if (list2) {
    list2.innerHTML = `<div class="text-center py-12 text-xs text-gray-500">Vui lòng chọn đội để hiển thị danh sách cầu thủ.</div>`;
  }

  team1Roster = [];
  team2Roster = [];

  // Issue 15 & 16: Cancel pending operations, clear timers, bump versions
  Object.values(debounceTimers).forEach(t => clearTimeout(t));
  debounceTimers = {};
  Object.values(playerAbortControllers).forEach(c => c.abort());
  playerAbortControllers = {};
  rowVersions = {};
  currentRosterGeneration++;
  if (batchAbortController) {
    batchAbortController.abort();
    batchAbortController = null;
  }
  if (matchupAbortController) {
    matchupAbortController.abort();
    matchupAbortController = null;
  }
}

function populateDropdowns() {
  const s1 = document.getElementById("team1-select");
  const s2 = document.getElementById("team2-select");
  if (!s1 || !s2) return;

  s1.innerHTML = `<option value="">--- Chọn Đội 1 ---</option>`;
  s2.innerHTML = `<option value="">--- Chọn Đội 2 ---</option>`;

  NBA_TEAMS.forEach(t => {
    const o1 = document.createElement("option");
    o1.value = t.abbr;
    o1.textContent = `${t.abbr} - ${t.name}`;
    s1.appendChild(o1);

    const o2 = document.createElement("option");
    o2.value = t.abbr;
    o2.textContent = `${t.abbr} - ${t.name}`;
    s2.appendChild(o2);
  });

  s1.addEventListener("change", onTeam1Change);
  s2.addEventListener("change", onTeam2Change);
}

function initSyncStatus() {
  fetch("/api/sync/status")
    .then(r => r.json())
    .then(data => {
      const el = document.getElementById("sync-status-text");
      if (el) el.textContent = `Latest: ${data.latest_game_date || '—'}`;
    })
    .catch(() => {});
}

async function onTeam1Change() {
  const s1 = document.getElementById("team1-select");
  const s2 = document.getElementById("team2-select");
  if (!s1 || !s2) return;

  const t1 = s1.value;
  if (!t1) {
    resetMatchupState();
    return;
  }

  // Issue 16: Cancel prior debounce timers, in-flight player/batch/matchup requests
  Object.values(debounceTimers).forEach(t => clearTimeout(t));
  debounceTimers = {};
  Object.values(playerAbortControllers).forEach(c => c.abort());
  playerAbortControllers = {};
  rowVersions = {};
  currentRosterGeneration++;
  if (batchAbortController) {
    batchAbortController.abort();
    batchAbortController = null;
  }
  if (matchupAbortController) {
    matchupAbortController.abort();
  }
  matchupAbortController = new AbortController();
  const signal = matchupAbortController.signal;

  document.getElementById("team1-badge").textContent = t1;
  const t1Obj = NBA_TEAMS.find(t => t.abbr === t1);
  document.getElementById("team1-title").textContent = t1Obj ? `${t1Obj.name} (${t1})` : t1;

  try {
    const matchupRes = await fetch(`/api/teams/${t1}/matchup`, { signal });
    const matchup = await matchupRes.json();

    if (matchup.has_game && matchup.opponent_abbr) {
      const opp = matchup.opponent_abbr;
      s2.value = opp;
      document.getElementById("team2-badge").textContent = opp;
      const t2Obj = NBA_TEAMS.find(t => t.abbr === opp);
      document.getElementById("team2-title").textContent = t2Obj ? `${t2Obj.name} (${opp})` : opp;

      // Update center VS text
      const tipText = document.getElementById("matchup-tipoff-text");
      const timeStr = matchup.tipoff_vn || matchup.game_date;
      const homeAway = matchup.is_home ? `vs ${opp} (Home)` : `@ ${opp} (Away)`;
      tipText.textContent = `${homeAway} • ${timeStr}`;

      document.getElementById("team1-status-pill").textContent = matchup.is_home ? "Sân nhà" : "Sân khách";
      document.getElementById("team2-status-pill").textContent = matchup.is_home ? "Sân khách" : "Sân nhà";

      await loadBothRosters(t1, opp, signal);
    } else {
      document.getElementById("matchup-tipoff-text").textContent = "Không tìm thấy lịch đấu kế tiếp";
      await loadBothRosters(t1, s2.value || "OPP", signal);
    }
  } catch (err) {
    if (err.name === "AbortError") return;
    console.error("Error updating matchup:", err);
  }
}

async function onTeam2Change() {
  const s1 = document.getElementById("team1-select");
  const s2 = document.getElementById("team2-select");
  if (!s1 || !s2) return;

  const t2 = s2.value;
  if (!t2) {
    resetMatchupState();
    return;
  }

  // Issue 16: Cancel prior debounce timers, in-flight player/batch/matchup requests
  Object.values(debounceTimers).forEach(t => clearTimeout(t));
  debounceTimers = {};
  Object.values(playerAbortControllers).forEach(c => c.abort());
  playerAbortControllers = {};
  rowVersions = {};
  currentRosterGeneration++;
  if (batchAbortController) {
    batchAbortController.abort();
    batchAbortController = null;
  }
  if (matchupAbortController) {
    matchupAbortController.abort();
  }
  matchupAbortController = new AbortController();
  const signal = matchupAbortController.signal;

  document.getElementById("team2-badge").textContent = t2;
  const t2Obj = NBA_TEAMS.find(t => t.abbr === t2);
  document.getElementById("team2-title").textContent = t2Obj ? `${t2Obj.name} (${t2})` : t2;

  try {
    const matchupRes = await fetch(`/api/teams/${t2}/matchup`, { signal });
    const matchup = await matchupRes.json();

    if (matchup.has_game && matchup.opponent_abbr) {
      const opp = matchup.opponent_abbr;
      s1.value = opp;
      document.getElementById("team1-badge").textContent = opp;
      const t1Obj = NBA_TEAMS.find(t => t.abbr === opp);
      document.getElementById("team1-title").textContent = t1Obj ? `${t1Obj.name} (${opp})` : opp;

      const tipText = document.getElementById("matchup-tipoff-text");
      const timeStr = matchup.tipoff_vn || matchup.game_date;
      const homeAway = matchup.is_home ? `vs ${opp} (Home)` : `@ ${opp} (Away)`;
      tipText.textContent = `${homeAway} • ${timeStr}`;

      document.getElementById("team2-status-pill").textContent = matchup.is_home ? "Sân nhà" : "Sân khách";
      document.getElementById("team1-status-pill").textContent = matchup.is_home ? "Sân khách" : "Sân nhà";

      await loadBothRosters(opp, t2, signal);
    } else {
      document.getElementById("matchup-tipoff-text").textContent = "Không tìm thấy lịch đấu kế tiếp";
      await loadBothRosters(s1.value || "OPP", t2, signal);
    }
  } catch (err) {
    if (err.name === "AbortError") return;
    console.error("Error updating matchup:", err);
  }
}

function renderTeamDefenseSummary(badgeContainerId, oppAbbr, oppDef) {
  const container = document.getElementById(badgeContainerId);
  if (!container) return;
  if (!oppDef || !oppAbbr || oppAbbr === "---" || oppAbbr === "OPP") {
    container.innerHTML = `<span class="text-gray-500">Toàn bộ đội hình & dàn bench (Points - PTS)</span>`;
    return;
  }

  const ptsR = oppDef.opp_pts_allowed_rank_asc_prev10 ? Math.round(oppDef.opp_pts_allowed_rank_asc_prev10) : null;
  const fg3mR = oppDef.opp_fg3m_allowed_rank_asc_prev10 ? Math.round(oppDef.opp_fg3m_allowed_rank_asc_prev10) : null;
  const blkR = oppDef.opp_blocks_made_rank_asc_prev10 ? Math.round(oppDef.opp_blocks_made_rank_asc_prev10) : null;

  let ptsClass = "bg-neutral-800 text-gray-300 border border-neutral-700/60";
  let ptsLabel = ptsR ? `#${ptsR}` : "-";
  let ptsHint = "Thủ TB";
  if (ptsR) {
    if (ptsR <= 10) {
      ptsClass = "bg-rose-950/80 text-rose-300 border border-rose-800/60";
      ptsHint = "Thủ chặt";
    } else if (ptsR >= 21) {
      ptsClass = "bg-emerald-950/80 text-emerald-300 border border-emerald-800/60";
      ptsHint = "Thủ lỏng";
    }
  }

  let fg3mClass = "bg-neutral-800 text-gray-300 border border-neutral-700/60";
  let fg3mLabel = fg3mR ? `#${fg3mR}` : "-";
  let fg3mHint = "3P TB";
  if (fg3mR) {
    if (fg3mR <= 10) {
      fg3mClass = "bg-rose-950/80 text-rose-300 border border-rose-800/60";
      fg3mHint = "Bọc 3P";
    } else if (fg3mR >= 21) {
      fg3mClass = "bg-emerald-950/80 text-emerald-300 border border-emerald-800/60";
      fg3mHint = "Hở 3P";
    }
  }

  let blkHtml = "";
  if (blkR) {
    let blkClass = "bg-neutral-800 text-gray-400 border border-neutral-700/60";
    if (blkR >= 21) blkClass = "bg-rose-950/70 text-rose-300 border border-rose-800/60";
    else if (blkR <= 10) blkClass = "bg-emerald-950/70 text-emerald-300 border border-emerald-800/60";
    blkHtml = `<span class="px-1.5 py-0.5 rounded ${blkClass}" title="Hạng Block cản phá rim">Rim: #${blkR}/30</span>`;
  }

  container.innerHTML = `
    <span class="text-indigo-300 font-semibold">Gặp ${oppAbbr}:</span>
    <span class="px-1.5 py-0.5 rounded ${ptsClass}" title="Hạng điểm đối thủ cho phép (1-10: Thủ chặt, 21-30: Thủ lỏng)">PTS: ${ptsLabel}/30 (${ptsHint})</span>
    <span class="px-1.5 py-0.5 rounded ${fg3mClass}" title="Hạng cho phép ném 3P (1-10: Bọc chặt, 21-30: Hở 3P)">3P: ${fg3mLabel}/30 (${fg3mHint})</span>
    ${blkHtml}
  `;
}

async function loadBothRosters(t1, t2, signal = null) {
  const rosterGen = ++currentRosterGeneration;
  if (signal && signal.aborted) return;

  const list1 = document.getElementById("team1-roster-list");
  const list2 = document.getElementById("team2-roster-list");

  if (list1) list1.innerHTML = `<div class="text-center py-8 text-xs text-gray-500 animate-pulse">Đang tải danh sách ${t1}...</div>`;
  if (list2) list2.innerHTML = `<div class="text-center py-8 text-xs text-gray-500 animate-pulse">Đang tải danh sách ${t2}...</div>`;

  const fetchOpts = signal ? { signal } : {};

  const fetchRoster = async (teamAbbr) => {
    if (!teamAbbr || teamAbbr === "---" || teamAbbr === "OPP") return [];
    if (signal && signal.aborted) {
      const err = new Error("Aborted");
      err.name = "AbortError";
      throw err;
    }
    try {
      const res = await fetch(`/api/teams/${teamAbbr}/roster?verified_only=true`, fetchOpts);
      return await readApiResponse(res);
    } catch (e) {
      if (e.name === "AbortError" || (signal && signal.aborted)) {
        throw e;
      }
      console.warn(`Could not load roster for ${teamAbbr}:`, e);
      return [];
    }
  };

  const fetchDefense = async (teamAbbr) => {
    if (!teamAbbr || teamAbbr === "---" || teamAbbr === "OPP") return null;
    if (signal && signal.aborted) {
      const err = new Error("Aborted");
      err.name = "AbortError";
      throw err;
    }
    try {
      const res = await fetch(`/api/teams/${teamAbbr}/defense-profile`, fetchOpts);
      if (!res.ok) return null;
      const data = await res.json();
      return data.profile || null;
    } catch (e) {
      if (e.name === "AbortError" || (signal && signal.aborted)) {
        throw e;
      }
      return null;
    }
  };

  try {
    const [r1, r2, def2, def1] = await Promise.all([
      fetchRoster(t1), 
      fetchRoster(t2),
      fetchDefense(t2), // Team 1 faces Team 2's defense
      fetchDefense(t1), // Team 2 faces Team 1's defense
    ]);

    // Issue 16: Ensure aborted or stale generation roster is NEVER rendered
    if ((signal && signal.aborted) || rosterGen !== currentRosterGeneration) {
      return;
    }

    team1Roster = r1 || [];
    team2Roster = r2 || [];

    const t1Obj = NBA_TEAMS.find(t => t.abbr === t1);
    const t2Obj = NBA_TEAMS.find(t => t.abbr === t2);
    if (document.getElementById("team1-title") && t1Obj) {
      document.getElementById("team1-title").textContent = `${t1Obj.name} (${team1Roster.length} cầu thủ)`;
    }
    if (document.getElementById("team2-title") && t2Obj) {
      document.getElementById("team2-title").textContent = `${t2Obj.name} (${team2Roster.length} cầu thủ)`;
    }

    renderTeamDefenseSummary("team1-def-badge", t2, def2);
    renderTeamDefenseSummary("team2-def-badge", t1, def1);

    renderRoster("team1-roster-list", team1Roster, t2);
    renderRoster("team2-roster-list", team2Roster, t1);
  } catch (err) {
    // Issue 16: Never render aborted state or stale generation
    if (err.name === "AbortError" || (signal && signal.aborted) || rosterGen !== currentRosterGeneration) {
      return;
    }
    console.error("Error loading rosters:", err);
    if (list1) list1.innerHTML = `<div class="text-center py-8 text-xs text-rose-400">Không thể tải danh sách cầu thủ.</div>`;
    if (list2) list2.innerHTML = `<div class="text-center py-8 text-xs text-rose-400">Không thể tải danh sách cầu thủ.</div>`;
  }
}

function renderRoster(containerId, players, opponentAbbr) {
  const container = document.getElementById(containerId);
  if (!container) return;

  if (!players || players.length === 0) {
    container.innerHTML = `<div class="text-center py-8 text-xs text-gray-500">Chưa có dữ liệu danh sách cầu thủ.</div>`;
    return;
  }

  container.innerHTML = players.map(p => {
    const deepLink = `/?player_id=${p.player_id}&player_name=${encodeURIComponent(p.player_name)}&opp=${opponentAbbr}`;

    // Tag role: Chính (Starter/Core), Bench (Rotation), Dự bị (Reserve)
    let roleBadge = "";
    if (p.is_current) {
      if (p.min_avg >= 20.0) {
        roleBadge = `<span class="text-[9px] px-1.5 py-0.5 rounded font-mono font-medium bg-emerald-950/60 text-emerald-400 border border-emerald-800/40">Chính</span>`;
      } else {
        roleBadge = `<span class="text-[9px] px-1.5 py-0.5 rounded font-mono font-medium bg-amber-950/40 text-amber-400 border border-amber-800/40">Bench</span>`;
      }
    } else {
      roleBadge = `<span class="text-[9px] px-1.5 py-0.5 rounded font-mono font-medium bg-neutral-900 text-neutral-400 border border-neutral-800">Dự bị</span>`;
    }

    if (p.membership_verified === false) {
      roleBadge = `<span class="text-[9px] text-amber-300" title="Recent appearances; current team membership is unverified">Roster ?</span>`;
    }
    const posTag = p.position_raw ? `<span class="text-[9px] px-1.5 py-0.5 rounded font-mono font-bold bg-neutral-800 text-amber-300 border border-neutral-700/80" title="Vị trí: ${p.position_raw} (${p.position_group})">${p.position_raw}</span>` : "";

    return `
      <div class="p-2.5 rounded-lg border border-neutral-800/80 hover:border-neutral-700 transition" style="background-color: var(--surface-1);" id="row-${p.player_id}">
        <div class="grid grid-cols-12 gap-2 items-center">
          
          <!-- Col 1: Player Info (Clickable Deep Link) -->
          <div class="col-span-4 pr-1">
            <div class="flex items-center gap-1.5">
              <a 
                href="${deepLink}" 
                id="link-${p.player_id}"
                class="text-xs font-bold text-white hover:text-indigo-400 transition flex items-center gap-1 group truncate"
                title="Player: ${p.player_name}"
              >
                <span class="truncate">${p.player_name}</span>
                <span class="text-[10px] text-gray-400 group-hover:text-indigo-400">↗</span>
              </a>
              ${posTag}
              ${roleBadge}
            </div>
            <div class="flex items-center space-x-1.5 mt-0.5">
              <span class="text-[10px] text-gray-400 font-mono">${p.min_avg}m</span>
              <span class="text-[10px] text-gray-500">•</span>
              <span class="text-[10px] text-gray-400 font-mono">${p.pts_avg} pts</span>
              <span id="dvp-badge-${p.player_id}" class="hidden text-[9px] font-mono px-1.5 py-0.2 rounded font-semibold border"></span>
            </div>
          </div>

          <!-- Col 2: 3 Input Boxes (Line, Over Odds, Under Odds) - BLANK BY DEFAULT -->
          <div class="col-span-4 grid grid-cols-3 gap-1">
            <div>
              <input 
                type="number" 
                step="0.5" 
                id="line-${p.player_id}" 
                value="" 
                placeholder="Line"
                class="box-input" 
                title="Nhập Line điểm (PTS)"
                oninput="onPlayerInputChange(${p.player_id}, '${opponentAbbr}')"
              >
            </div>
            <div>
              <input 
                type="number" 
                step="0.01" 
                id="over-odds-${p.player_id}" 
                value="" 
                placeholder="1.91"
                class="box-input" 
                title="Tỷ lệ cược Over (Mặc định: 1.91)"
                oninput="onPlayerInputChange(${p.player_id}, '${opponentAbbr}')"
              >
            </div>
            <div>
              <input 
                type="number" 
                step="0.01" 
                id="under-odds-${p.player_id}" 
                value="" 
                placeholder="1.91"
                class="box-input" 
                title="Tỷ lệ cược Under (Mặc định: 1.91)"
                oninput="onPlayerInputChange(${p.player_id}, '${opponentAbbr}')"
              >
            </div>
          </div>

          <!-- Col 3: 3 Output Boxes (EV, Over %, Under %) - DASH BY DEFAULT -->
          <div class="col-span-4 grid grid-cols-3 gap-1">
            <div id="ev-${p.player_id}" class="box-output ev" title="Expected Value (EV)">
              -
            </div>
            <div id="over-pct-${p.player_id}" class="box-output neutral" title="Xác suất Over">
              -
            </div>
            <div id="under-pct-${p.player_id}" class="box-output neutral" title="Xác suất Under">
              -
            </div>
          </div>

        </div>
      </div>
    `;
  }).join("");
}

function onPlayerInputChange(playerId, opponentAbbr, schedulePrediction = true) {
  const lineInput = document.getElementById(`line-${playerId}`);
  const overInput = document.getElementById(`over-odds-${playerId}`);
  const underInput = document.getElementById(`under-odds-${playerId}`);
  const linkEl = document.getElementById(`link-${playerId}`);

  const evEl = document.getElementById(`ev-${playerId}`);
  const overEl = document.getElementById(`over-pct-${playerId}`);
  const underEl = document.getElementById(`under-pct-${playerId}`);

  const lineVal = lineInput ? lineInput.value.trim() : "";
  
  const player = (team1Roster.concat(team2Roster)).find(p => p.player_id === playerId);
  const pName = player ? player.player_name : "";

  // Issue 18: Properly handle line 0 using Number.isFinite
  const isLineFinite = lineVal !== "" && Number.isFinite(parseFloat(lineVal));

  // Invalidate at edit time, before the debounce: an old response can arrive
  // while a new valid value is waiting to start its request.
  rowVersions[playerId] = (rowVersions[playerId] || 0) + 1;
  clearTimeout(debounceTimers[playerId]);
  delete debounceTimers[playerId];
  if (playerAbortControllers[playerId]) {
    playerAbortControllers[playerId].abort();
    delete playerAbortControllers[playerId];
  }

  // Issue 15: If user cleared the line or entered invalid number, cancel pending debounce timers,
  // abort in-flight requests immediately, bump row version, and reset outputs to dash.
  if (!isLineFinite) {
    if (debounceTimers[playerId]) {
      clearTimeout(debounceTimers[playerId]);
      delete debounceTimers[playerId];
    }
    if (playerAbortControllers[playerId]) {
      playerAbortControllers[playerId].abort();
      delete playerAbortControllers[playerId];
    }
    // Issue 16: Advance row version so lingering in-flight or older batch cannot repopulate
    rowVersions[playerId] = (rowVersions[playerId] || 0) + 1;

    if (evEl) evEl.textContent = "-";
    if (overEl) {
      overEl.textContent = "-";
      overEl.className = "box-output neutral";
      overEl.title = "";
    }
    if (underEl) {
      underEl.textContent = "-";
      underEl.className = "box-output neutral";
      underEl.title = "";
    }
    if (linkEl) {
      linkEl.href = `/?player_id=${playerId}&player_name=${encodeURIComponent(pName)}&opp=${opponentAbbr}`;
    }
    return;
  }

  const line = parseFloat(lineVal);
  const oddsOver = overInput && overInput.value.trim() && Number.isFinite(parseFloat(overInput.value)) ? parseFloat(overInput.value) : 1.91;
  const oddsUnder = underInput && underInput.value.trim() && Number.isFinite(parseFloat(underInput.value)) ? parseFloat(underInput.value) : 1.91;

  if (linkEl) {
    linkEl.href = `/?player_id=${playerId}&player_name=${encodeURIComponent(pName)}&line=${line}&odds_over=${oddsOver}&odds_under=${oddsUnder}&opp=${opponentAbbr}`;
  }

  if (!schedulePrediction) return;

  // Issue 16: Debounced predict call with cancellation
  clearTimeout(debounceTimers[playerId]);
  debounceTimers[playerId] = setTimeout(() => {
    delete debounceTimers[playerId];
    calculateSinglePlayer(playerId, line, oddsOver, oddsUnder, opponentAbbr);
  }, 350);
}

async function calculateSinglePlayer(playerId, line, oddsOver, oddsUnder, opponentAbbr) {
  const evEl = document.getElementById(`ev-${playerId}`);
  const overEl = document.getElementById(`over-pct-${playerId}`);
  const underEl = document.getElementById(`under-pct-${playerId}`);

  // Issue 16: Monotonic request version counter per row
  const currentReqVersion = (rowVersions[playerId] = (rowVersions[playerId] || 0) + 1);

  // Issue 15: Fully clear old displays before starting new calculation
  if (evEl) evEl.textContent = "...";
  if (overEl) {
    overEl.textContent = "...";
    overEl.className = "box-output neutral";
    overEl.title = "Đang tính toán...";
  }
  if (underEl) {
    underEl.textContent = "...";
    underEl.className = "box-output neutral";
    underEl.title = "Đang tính toán...";
  }

  // Issue 16: Cancel previous in-flight request for this player
  if (playerAbortControllers[playerId]) {
    playerAbortControllers[playerId].abort();
  }
  const ctrl = new AbortController();
  playerAbortControllers[playerId] = ctrl;

  try {
    // Issue 12: Contract fix - send odds_over and odds_under matching PredictRequest
    const res = await fetch("/api/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: ctrl.signal,
      body: JSON.stringify({
        player_id: playerId,
        stat: "pts",
        line: line,
        odds_over: oddsOver,
        odds_under: oddsUnder,
        opponent_override: opponentAbbr || null,
      }),
    });

    const data = await readApiResponse(res);

    // Issue 16: Version check prevents stale responses from overwriting newer single or batch requests
    if (rowVersions[playerId] !== currentReqVersion) return;

    applyPredictionToRow(playerId, data, oddsOver, oddsUnder);
  } catch (err) {
    if (err.name === "AbortError") return;
    if (rowVersions[playerId] !== currentReqVersion) return;
    console.error(`Error calculating for player ${playerId}:`, err);
    // Issue 15: Clear and reset to error state on failure
    if (evEl) { evEl.textContent = "Err"; evEl.title = err.message || "Lỗi kết nối"; }
    if (overEl) {
      overEl.textContent = "--";
      overEl.className = "box-output neutral";
      overEl.title = err.message || "Lỗi kết nối";
    }
    if (underEl) {
      underEl.textContent = "--";
      underEl.className = "box-output neutral";
      underEl.title = err.message || "Lỗi kết nối";
    }
  }
}

function applyPredictionToRow(playerId, data, oddsOver, oddsUnder) {
  const evEl = document.getElementById(`ev-${playerId}`);
  const overEl = document.getElementById(`over-pct-${playerId}`);
  const underEl = document.getElementById(`under-pct-${playerId}`);

  // Issue 15: Check expected_value presence
  if (evEl) {
    evEl.textContent = data.expected_value != null ? data.expected_value.toFixed(1) : "--";
  }

  // Issue 14 & Issue 15: Color row opportunities based on actual positive EV, reset if missing
  if (data.line_probabilities && data.line_probabilities.q_over != null && data.line_probabilities.q_under != null) {
    const qOverPct = (data.line_probabilities.q_over * 100).toFixed(1);
    const qUnderPct = (data.line_probabilities.q_under * 100).toFixed(1);
    const qPushPct = data.line_probabilities.q_push != null ? (data.line_probabilities.q_push * 100) : 0.0;

    const overInput = document.getElementById(`over-odds-${playerId}`);
    const underInput = document.getElementById(`under-odds-${playerId}`);
    const oOdds = (overInput && overInput.value.trim() && Number.isFinite(parseFloat(overInput.value)))
      ? parseFloat(overInput.value)
      : (Number.isFinite(oddsOver) ? oddsOver : 1.91);
    const uOdds = (underInput && underInput.value.trim() && Number.isFinite(parseFloat(underInput.value)))
      ? parseFloat(underInput.value)
      : (Number.isFinite(oddsUnder) ? oddsUnder : 1.91);

    // Issue 14: Fallback EV incorporating push probability:
    // EV = (q_win * odds + q_push * 1.0) / 100 - 1.0
    const fallbackEvOver = ((parseFloat(qOverPct) * oOdds + qPushPct * 1.0) / 100.0) - 1.0;
    const fallbackEvUnder = ((parseFloat(qUnderPct) * uOdds + qPushPct * 1.0) / 100.0) - 1.0;

    const evOver = data.pricing?.ev_over != null ? data.pricing.ev_over : fallbackEvOver;
    const evUnder = data.pricing?.ev_under != null ? data.pricing.ev_under : fallbackEvUnder;

    // Issue 14: Strictly positive EV (> 0)
    const isOverPositive = evOver > 0;
    const isUnderPositive = evUnder > 0;

    if (overEl) {
      overEl.textContent = `${qOverPct}%`;
      overEl.className = "box-output " + (isOverPositive ? "over-high" : "neutral");
      overEl.title = `EV: ${(evOver * 100).toFixed(1)}% | Win Rate: ${qOverPct}%`;
    }
    if (underEl) {
      underEl.textContent = `${qUnderPct}%`;
      underEl.className = "box-output " + (isUnderPositive ? "under-high" : "neutral");
      underEl.title = `EV: ${(evUnder * 100).toFixed(1)}% | Win Rate: ${qUnderPct}%`;
    }
  } else {
    // Response lacks valid line probabilities (e.g. conditional scenario not issued)
    if (overEl) {
      overEl.textContent = "--";
      overEl.className = "box-output neutral";
      overEl.title = "Không có xác suất kèo hoặc chưa phát hành";
    }
    if (underEl) {
      underEl.textContent = "--";
      underEl.className = "box-output neutral";
      underEl.title = "Không có xác suất kèo hoặc chưa phát hành";
    }
  }

  const dvpRank = data.dvp_context?.pts?.rank_asc ?? data.dvp_pts_rank;
  renderDvpBadge(playerId, dvpRank);
}

function renderDvpBadge(playerId, rankVal) {
  const dvpEl = document.getElementById(`dvp-badge-${playerId}`);
  if (!dvpEl) return;
  if (rankVal != null && !isNaN(rankVal)) {
    const r = Math.round(rankVal);
    dvpEl.textContent = `DvP #${r}/30`;
    dvpEl.classList.remove("hidden");
    if (r <= 10) {
      dvpEl.className = "text-[9px] font-mono px-1.5 py-0.5 rounded font-bold bg-rose-950/80 text-rose-300 border border-rose-800/60";
      dvpEl.title = `DvP #${r}/30 (Thủ chặt vs vị trí)`;
    } else if (r >= 21) {
      dvpEl.className = "text-[9px] font-mono px-1.5 py-0.5 rounded font-bold bg-emerald-950/80 text-emerald-300 border border-emerald-800/60";
      dvpEl.title = `DvP #${r}/30 (Thủ lỏng vs vị trí)`;
    } else {
      dvpEl.className = "text-[9px] font-mono px-1.5 py-0.5 rounded font-medium bg-neutral-800 text-gray-300 border border-neutral-700/60";
      dvpEl.title = `DvP #${r}/30 (Trung bình)`;
    }
  } else {
    dvpEl.classList.add("hidden");
  }
}

async function calculateAll() {
  const s1 = document.getElementById("team1-select");
  const s2 = document.getElementById("team2-select");
  const t1 = s1 ? s1.value : "";
  const t2 = s2 ? s2.value : "";

  if (!t1 && !t2) {
    alert("Vui lòng chọn đội trước khi tính toán.");
    return;
  }

  const batchPayload = [];

  team1Roster.forEach(p => {
    const lineEl = document.getElementById(`line-${p.player_id}`);
    const overEl = document.getElementById(`over-odds-${p.player_id}`);
    const underEl = document.getElementById(`under-odds-${p.player_id}`);
    const lineVal = lineEl ? lineEl.value.trim() : "";

    // Issue 18: Support line 0 using Number.isFinite
    if (lineVal !== "" && Number.isFinite(parseFloat(lineVal))) {
      batchPayload.push({
        player_id: p.player_id,
        stat: "pts",
        line: parseFloat(lineVal),
        // Issue 12: Send odds_over and odds_under matching PredictRequest contract
        odds_over: overEl && overEl.value.trim() ? parseFloat(overEl.value) : 1.91,
        odds_under: underEl && underEl.value.trim() ? parseFloat(underEl.value) : 1.91,
        opponent_override: t2 || null,
      });
    }
  });

  team2Roster.forEach(p => {
    const lineEl = document.getElementById(`line-${p.player_id}`);
    const overEl = document.getElementById(`over-odds-${p.player_id}`);
    const underEl = document.getElementById(`under-odds-${p.player_id}`);
    const lineVal = lineEl ? lineEl.value.trim() : "";

    if (lineVal !== "" && Number.isFinite(parseFloat(lineVal))) {
      batchPayload.push({
        player_id: p.player_id,
        stat: "pts",
        line: parseFloat(lineVal),
        // Issue 12: Send odds_over and odds_under matching PredictRequest contract
        odds_over: overEl && overEl.value.trim() ? parseFloat(overEl.value) : 1.91,
        odds_under: underEl && underEl.value.trim() ? parseFloat(underEl.value) : 1.91,
        opponent_override: t1 || null,
      });
    }
  });

  if (batchPayload.length === 0) {
    alert("Vui lòng nhập Line điểm cho ít nhất 1 cầu thủ để tính toán.");
    return;
  }

  // Issue 16: Track monotonic row versions for all participating rows
  const batchRowVersions = {};
  batchPayload.forEach(req => {
    const pId = req.player_id;
    clearTimeout(debounceTimers[pId]);
    delete debounceTimers[pId];
    if (playerAbortControllers[pId]) {
      playerAbortControllers[pId].abort();
      delete playerAbortControllers[pId];
    }
    rowVersions[pId] = (rowVersions[pId] || 0) + 1;
    batchRowVersions[pId] = rowVersions[pId];

    const evEl = document.getElementById(`ev-${pId}`);
    const overEl = document.getElementById(`over-pct-${pId}`);
    const underEl = document.getElementById(`under-pct-${pId}`);
    if (evEl) { evEl.textContent = "..."; evEl.title = ""; }
    if (overEl) {
      overEl.textContent = "...";
      overEl.className = "box-output neutral";
      overEl.title = "Đang tính...";
    }
    if (underEl) {
      underEl.textContent = "...";
      underEl.className = "box-output neutral";
      underEl.title = "Đang tính...";
    }
  });

  const btn = document.getElementById("btn-calc-all");
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span>⏳ Đang tính (${batchPayload.length})...</span>`;
  }

  // Issue 16: Cancel previous batch request
  if (batchAbortController) {
    batchAbortController.abort();
  }
  batchAbortController = new AbortController();

  try {
    const res = await fetch("/api/fastcheck/predict-batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: batchAbortController.signal,
      body: JSON.stringify(batchPayload),
    });

    const results = await readApiResponse(res);
    results.forEach(r => {
      // Issue 16: Discard batch result if single-row calculation or clear was triggered since batch started
      if (rowVersions[r.player_id] !== batchRowVersions[r.player_id]) {
        return;
      }

      const evEl = document.getElementById(`ev-${r.player_id}`);
      const overEl = document.getElementById(`over-pct-${r.player_id}`);
      const underEl = document.getElementById(`under-pct-${r.player_id}`);

      // Issue 15: Handle row errors cleanly
      if (r.error) {
        console.error(`Prediction failed for player ${r.player_id}:`, r.error);
        if (evEl) { evEl.textContent = "Err"; evEl.title = r.error; }
        if (overEl) { overEl.textContent = "--"; overEl.className = "box-output neutral"; overEl.title = r.error; }
        if (underEl) { underEl.textContent = "--"; underEl.className = "box-output neutral"; underEl.title = r.error; }
        renderDvpBadge(r.player_id, null);
        return;
      }

      if (evEl) {
        evEl.textContent = r.expected_value != null ? r.expected_value.toFixed(1) : "--";
      }

      // Issue 14: Color opportunities based on actual positive EV with user-entered odds and push probability
      const sentReq = batchPayload.find(item => item.player_id === r.player_id);
      const overInput = document.getElementById(`over-odds-${r.player_id}`);
      const underInput = document.getElementById(`under-odds-${r.player_id}`);
      const oOdds = (overInput && overInput.value.trim() && Number.isFinite(parseFloat(overInput.value)))
        ? parseFloat(overInput.value)
        : (sentReq?.odds_over || 1.91);
      const uOdds = (underInput && underInput.value.trim() && Number.isFinite(parseFloat(underInput.value)))
        ? parseFloat(underInput.value)
        : (sentReq?.odds_under || 1.91);

      // EV = (q_win * odds + q_push * 1.0) / 100 - 1.0
      const qPush = r.q_push != null ? r.q_push : 0.0;
      const fallbackEvOver = r.q_over != null ? (((r.q_over * oOdds + qPush * 1.0) / 100.0) - 1.0) : null;
      const fallbackEvUnder = r.q_under != null ? (((r.q_under * uOdds + qPush * 1.0) / 100.0) - 1.0) : null;

      const evOver = r.ev_over != null ? r.ev_over : fallbackEvOver;
      const evUnder = r.ev_under != null ? r.ev_under : fallbackEvUnder;

      // Strictly positive EV (> 0)
      const isOverPositive = evOver !== null && evOver > 0;
      const isUnderPositive = evUnder !== null && evUnder > 0;

      if (overEl) {
        if (r.q_over != null) {
          overEl.textContent = `${r.q_over}%`;
          overEl.className = "box-output " + (isOverPositive ? "over-high" : "neutral");
          overEl.title = evOver != null ? `EV: ${(evOver * 100).toFixed(1)}% | Win Rate: ${r.q_over}%` : "";
        } else {
          overEl.textContent = "--";
          overEl.className = "box-output neutral";
          overEl.title = "Chưa phát hành / thiếu dữ liệu";
        }
      }

      if (underEl) {
        if (r.q_under != null) {
          underEl.textContent = `${r.q_under}%`;
          underEl.className = "box-output " + (isUnderPositive ? "under-high" : "neutral");
          underEl.title = evUnder != null ? `EV: ${(evUnder * 100).toFixed(1)}% | Win Rate: ${r.q_under}%` : "";
        } else {
          underEl.textContent = "--";
          underEl.className = "box-output neutral";
          underEl.title = "Chưa phát hành / thiếu dữ liệu";
        }
      }

      renderDvpBadge(r.player_id, r.dvp_pts_rank);
    });
  } catch (err) {
    if (err.name === "AbortError") return;
    console.error("Error running batch calculation:", err);
    // Issue 15 & 16: Clear and reset to Err only for rows still on this batch version
    batchPayload.forEach(req => {
      if (rowVersions[req.player_id] !== batchRowVersions[req.player_id]) {
        return;
      }
      const evEl = document.getElementById(`ev-${req.player_id}`);
      const overEl = document.getElementById(`over-pct-${req.player_id}`);
      const underEl = document.getElementById(`under-pct-${req.player_id}`);
      const message = err.message || "Lỗi tính toán";
      if (evEl) { evEl.textContent = "Err"; evEl.title = message; }
      if (overEl) { overEl.textContent = "--"; overEl.className = "box-output neutral"; overEl.title = message; }
      if (underEl) { underEl.textContent = "--"; underEl.className = "box-output neutral"; underEl.title = message; }
    });
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<span>⚡ Tính toán tất cả</span>`;
    }
  }
}

function triggerManualSync() {
  const btn = document.getElementById("btn-sync-now");
  const text = document.getElementById("sync-button-text");
  const icon = document.getElementById("sync-icon");
  const syncStatusEl = document.getElementById("sync-status-text");

  if (btn) btn.disabled = true;
  if (text) text.textContent = "Starting Sync...";
  if (icon) icon.classList.add("animate-spin");

  // Issue 17: Stop existing polling if any
  if (syncPollingTimer) {
    clearInterval(syncPollingTimer);
    syncPollingTimer = null;
  }

  fetch("/api/sync", { method: "POST" })
    .then(r => r.json())
    .then(data => {
      const jobId = data.job_id;
      if (!jobId) {
        initSyncStatus();
        onTeam1Change();
        if (btn) btn.disabled = false;
        if (text) text.textContent = "Sync";
        if (icon) icon.classList.remove("animate-spin");
        return;
      }

      let attempts = 0;
      // Issue 17: Polling interval 1.5s, max window 240 seconds (160 attempts)
      const pollIntervalMs = 1500;
      const maxAttempts = Math.ceil(240000 / pollIntervalMs);
      syncPollingTimer = setInterval(async () => {
        attempts++;
        try {
          const statusRes = await fetch(`/api/sync/status/${jobId}`);
          if (!statusRes.ok) throw new Error(`HTTP ${statusRes.status}`);
          const job = await statusRes.json();
          const jobStatus = (job.status || "").toUpperCase();

          if (text) text.textContent = `Syncing (${jobStatus.toLowerCase()})...`;

          if (jobStatus === "SUCCESS") {
            clearInterval(syncPollingTimer);
            syncPollingTimer = null;
            if (btn) btn.disabled = false;
            if (text) text.textContent = "Sync";
            if (icon) icon.classList.remove("animate-spin");
            initSyncStatus();
            onTeam1Change();
          } else if (jobStatus === "PARTIAL") {
            clearInterval(syncPollingTimer);
            syncPollingTimer = null;
            if (btn) btn.disabled = false;
            if (text) text.textContent = "Sync Partial";
            if (icon) icon.classList.remove("animate-spin");
            if (syncStatusEl) syncStatusEl.textContent = `Sync Partial: ${job.message || "Hoàn tất một phần"}`;
            onTeam1Change();
          } else if (jobStatus === "FAILED") {
            clearInterval(syncPollingTimer);
            syncPollingTimer = null;
            if (btn) btn.disabled = false;
            if (text) text.textContent = "Sync Failed";
            if (icon) icon.classList.remove("animate-spin");
            if (syncStatusEl) syncStatusEl.textContent = `Sync Thất Bại: ${job.error || "Lỗi không xác định"}`;
          } else if (attempts >= maxAttempts) {
            clearInterval(syncPollingTimer);
            syncPollingTimer = null;
            if (btn) btn.disabled = false;
            if (text) text.textContent = "Sync Timeout";
            if (icon) icon.classList.remove("animate-spin");
            if (syncStatusEl) syncStatusEl.textContent = "Sync Timeout (chưa hoàn thành sau 240s)";
          }
        } catch (pollErr) {
          console.warn("Polling sync job error:", pollErr);
          if (attempts >= maxAttempts) {
            clearInterval(syncPollingTimer);
            syncPollingTimer = null;
            if (btn) btn.disabled = false;
            if (text) text.textContent = "Sync Error";
            if (icon) icon.classList.remove("animate-spin");
            if (syncStatusEl) syncStatusEl.textContent = "Sync Error (mất kết nối polling)";
          }
        }
      }, pollIntervalMs);
    })
    .catch(err => {
      console.error("Sync trigger error:", err);
      if (btn) btn.disabled = false;
      if (text) text.textContent = "Sync Failed";
      if (icon) icon.classList.remove("animate-spin");
      if (syncStatusEl) syncStatusEl.textContent = `Sync Failed: ${err.message || "Lỗi mạng"}`;
    });
}

// ==========================================
// OCR ODDS SCREENSHOT AUTO-PARSER & AUTO-FILL
// ==========================================

let currentOcrData = null;

function initOcrModal() {
  const modal = document.getElementById("ocr-modal");
  const btnOpen = document.getElementById("btn-paste-odds");
  const btnClose = document.getElementById("btn-close-ocr-modal");
  const btnCancel = document.getElementById("btn-cancel-ocr");
  const fileInput = document.getElementById("odds-file-input");
  const dropzone = document.getElementById("ocr-dropzone");
  const btnReselect = document.getElementById("btn-reselect-image");
  const btnApply = document.getElementById("btn-apply-ocr");
  const btnApplyTeams = document.getElementById("btn-apply-suggested-teams");
  const selectAll = document.getElementById("ocr-select-all");

  const openModal = () => {
    if (modal) modal.classList.remove("hidden");
  };

  const closeModal = () => {
    if (modal) modal.classList.add("hidden");
  };

  if (btnOpen) btnOpen.addEventListener("click", () => {
    openModal();
    resetOcrModalState();
  });

  if (btnClose) btnClose.addEventListener("click", closeModal);
  if (btnCancel) btnCancel.addEventListener("click", closeModal);

  if (dropzone) {
    dropzone.addEventListener("click", () => fileInput && fileInput.click());
    dropzone.addEventListener("dragover", (e) => {
      e.preventDefault();
      dropzone.classList.add("border-indigo-500", "bg-indigo-950/20");
    });
    dropzone.addEventListener("dragleave", () => {
      dropzone.classList.remove("border-indigo-500", "bg-indigo-950/20");
    });
    dropzone.addEventListener("drop", (e) => {
      e.preventDefault();
      dropzone.classList.remove("border-indigo-500", "bg-indigo-950/20");
      if (e.dataTransfer.files && e.dataTransfer.files[0]) {
        handleOcrFile(e.dataTransfer.files[0]);
      }
    });
  }

  if (fileInput) {
    fileInput.addEventListener("change", (e) => {
      if (e.target.files && e.target.files[0]) {
        handleOcrFile(e.target.files[0]);
      }
    });
  }

  if (btnReselect) {
    btnReselect.addEventListener("click", () => {
      resetOcrModalState();
      if (fileInput) fileInput.click();
    });
  }

  // Global Ctrl + V listener
  window.addEventListener("paste", (e) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (const item of items) {
      if (item.type.indexOf("image") !== -1) {
        const file = item.getAsFile();
        if (file) {
          openModal();
          handleOcrFile(file);
        }
        break;
      }
    }
  });

  // Select all checkbox
  if (selectAll) {
    selectAll.addEventListener("change", (e) => {
      const cbs = document.querySelectorAll(".ocr-item-cb");
      cbs.forEach(cb => cb.checked = e.target.checked);
      updateApplyButtonState();
    });
  }

  if (btnApplyTeams) {
    btnApplyTeams.addEventListener("click", async () => {
      if (!currentOcrData || !currentOcrData.team_counts) return;
      const sortedTeams = Object.keys(currentOcrData.team_counts).sort((a, b) => currentOcrData.team_counts[b] - currentOcrData.team_counts[a]);
      if (sortedTeams.length >= 1) {
        const s1 = document.getElementById("team1-select");
        if (s1) {
          s1.value = sortedTeams[0];
          await onTeam1Change();
        }
      }
      btnApplyTeams.textContent = "✓ Đã chọn cặp đội";
      btnApplyTeams.disabled = true;
      // Re-render table status column
      renderOcrResultsTable();
    });
  }

  if (btnApply) {
    btnApply.addEventListener("click", applyOcrToFastcheck);
  }
}

function resetOcrModalState() {
  currentOcrData = null;
  const dropzone = document.getElementById("ocr-dropzone");
  const preview = document.getElementById("ocr-preview-container");
  const suggestion = document.getElementById("ocr-team-suggestion");
  const resultsContainer = document.getElementById("ocr-results-container");
  const btnApply = document.getElementById("btn-apply-ocr");
  const fileInput = document.getElementById("odds-file-input");

  if (dropzone) dropzone.classList.remove("hidden");
  if (preview) preview.classList.add("hidden");
  if (suggestion) suggestion.classList.add("hidden");
  if (resultsContainer) resultsContainer.classList.add("hidden");
  if (btnApply) btnApply.disabled = true;
  if (fileInput) fileInput.value = "";
}

function handleOcrFile(file) {
  if (!file || !file.type.startsWith("image/")) {
    alert("Vui lòng dán hoặc chọn một file ảnh hợp lệ.");
    return;
  }

  const reader = new FileReader();
  reader.onload = async (e) => {
    const dataUrl = e.target.result;

    const dropzone = document.getElementById("ocr-dropzone");
    const preview = document.getElementById("ocr-preview-container");
    const previewImg = document.getElementById("ocr-image-preview");
    const badge = document.getElementById("ocr-status-badge");
    const desc = document.getElementById("ocr-status-desc");

    if (dropzone) dropzone.classList.add("hidden");
    if (preview) preview.classList.remove("hidden");
    if (previewImg) previewImg.src = dataUrl;
    if (badge) {
      badge.textContent = "Đang nhận diện ký tự OCR...";
      badge.className = "text-xs px-2.5 py-0.5 rounded-full font-mono font-medium bg-indigo-950 text-indigo-300 border border-indigo-800 animate-pulse";
    }
    if (desc) desc.textContent = "Đang phân tích cấu trúc bảng kèo và tìm kiếm cầu thủ trong database...";

    try {
      const res = await fetch("/api/fastcheck/ocr-odds", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image_base64: dataUrl }),
      });

      const data = await readApiResponse(res);

      currentOcrData = data;
      if (badge) {
        badge.textContent = `Thành công: Nhận diện ${data.detected_count} kèo`;
        badge.className = "text-xs px-2.5 py-0.5 rounded-full font-mono font-medium bg-emerald-950 text-emerald-300 border border-emerald-800";
      }
      if (desc) desc.textContent = "Vui lòng xem lại danh sách bên dưới và bấm 'Áp dụng vào bảng'.";

      // Team suggestion check
      const suggestion = document.getElementById("ocr-team-suggestion");
      const suggestionText = document.getElementById("ocr-team-suggestion-text");
      const btnApplyTeams = document.getElementById("btn-apply-suggested-teams");

      if (data.team_counts && Object.keys(data.team_counts).length > 0) {
        const teams = Object.keys(data.team_counts).sort((a, b) => data.team_counts[b] - data.team_counts[a]);
        const teamDesc = teams.map(t => `${t} (${data.team_counts[t]})`).join(" & ");
        if (suggestion && suggestionText) {
          suggestionText.textContent = `Phát hiện cầu thủ thuộc các đội: ${teamDesc}`;
          suggestion.classList.remove("hidden");
          if (btnApplyTeams) {
            btnApplyTeams.textContent = `Tự động chọn ${teams[0]}`;
            btnApplyTeams.disabled = false;
          }
        }
      }

      renderOcrResultsTable();

      const resultsContainer = document.getElementById("ocr-results-container");
      if (resultsContainer) resultsContainer.classList.remove("hidden");

      updateApplyButtonState();

    } catch (err) {
      console.error("OCR Error:", err);
      if (badge) {
        badge.textContent = "Lỗi nhận diện";
        badge.className = "text-xs px-2.5 py-0.5 rounded-full font-mono font-medium bg-rose-950 text-rose-300 border border-rose-800";
      }
      if (desc) desc.textContent = `Đã xảy ra lỗi: ${err.message}`;
    }
  };
  reader.readAsDataURL(file);
}

function renderOcrResultsTable() {
  if (!currentOcrData || !currentOcrData.items) return;
  const tbody = document.getElementById("ocr-results-body");
  const countText = document.getElementById("ocr-count-text");
  if (!tbody) return;

  if (countText) countText.textContent = currentOcrData.items.length;

  tbody.innerHTML = currentOcrData.items.map((item, idx) => {
    const isPlayerOnBoard = !!document.getElementById(`line-${item.player_id}`);
    const conf = item.confidence != null ? item.confidence : 1.0;
    const confPct = Math.round(conf * 100);

    // Issue 13: Uncheck by default if low confidence (< 70%) or player_id missing
    const isChecked = (item.player_id != null && conf >= 0.70) ? "checked" : "";
    const rowBg = isPlayerOnBoard ? "bg-emerald-950/20" : "";

    let confBadge = "";
    if (conf >= 0.85) {
      confBadge = `<span class="text-[10px] font-mono text-emerald-400 font-semibold" title="Độ tin cậy khớp: ${confPct}%">${confPct}%</span>`;
    } else if (conf >= 0.70) {
      confBadge = `<span class="text-[10px] font-mono text-indigo-300 font-medium" title="Độ tin cậy khớp: ${confPct}%">${confPct}%</span>`;
    } else {
      confBadge = `<span class="text-[10px] font-mono text-amber-400 font-bold px-1 rounded bg-amber-950/60 border border-amber-800/60" title="Độ tin cậy thấp (${confPct}%), vui lòng đối chiếu">${confPct}% ⚠️</span>`;
    }

    let statusBadge = "";
    if (isPlayerOnBoard) {
      statusBadge = `<span class="text-[10px] text-emerald-400 font-semibold">✓ Đang trên bảng</span>`;
    } else if (item.team_abbreviation) {
      statusBadge = `<span class="text-[10px] text-gray-400">Đội ${item.team_abbreviation}</span>`;
    } else {
      statusBadge = `<span class="text-[10px] text-rose-400">Chưa xác định</span>`;
    }

    return `
      <tr class="hover:bg-neutral-800/40 ${rowBg}">
        <td class="p-2.5 text-center">
          <input type="checkbox" class="ocr-item-cb cursor-pointer" data-index="${idx}" ${isChecked}>
        </td>
        <td class="p-2.5 font-sans font-medium text-white">${item.raw_name}</td>
        <td class="p-2.5 font-sans ${item.player_id ? 'text-indigo-300' : 'text-gray-500'}">
          <div class="flex items-center gap-1.5">
            <span>${item.matched_name || '<i class="text-gray-500">Không tìm thấy</i>'}</span>
            ${confBadge}
          </div>
        </td>
        <td class="p-2.5 text-center text-gray-300">${item.team_abbreviation || '-'}</td>
        <td class="p-2.5 text-center font-bold text-white">${item.line != null ? item.line : '-'}</td>
        <td class="p-2.5 text-center text-emerald-400 font-bold">${item.odds_over != null ? item.odds_over : '-'}</td>
        <td class="p-2.5 text-center text-rose-400 font-bold">${item.odds_under != null ? item.odds_under : '-'}</td>
      </tr>
    `;
  }).join("");

  const cbs = document.querySelectorAll(".ocr-item-cb");
  cbs.forEach(cb => cb.addEventListener("change", updateApplyButtonState));
}

function updateApplyButtonState() {
  const btn = document.getElementById("btn-apply-ocr");
  if (!btn) return;
  const checkedCount = document.querySelectorAll(".ocr-item-cb:checked").length;
  btn.disabled = checkedCount === 0;
  btn.innerHTML = `<span>⚡ Áp dụng (${checkedCount}) & Tính toán</span>`;
}

function applyOcrToFastcheck() {
  if (!currentOcrData || !currentOcrData.items) return;
  const cbs = document.querySelectorAll(".ocr-item-cb:checked");
  if (cbs.length === 0) return;

  const s1 = document.getElementById("team1-select");
  const s2 = document.getElementById("team2-select");
  const t1 = s1 ? s1.value : "";
  const t2 = s2 ? s2.value : "";

  let filledCount = 0;

  cbs.forEach(cb => {
    const idx = parseInt(cb.dataset.index);
    const item = currentOcrData.items[idx];
    if (!item || !item.player_id) return;

    const pId = item.player_id;
    const lineEl = document.getElementById(`line-${pId}`);
    const overEl = document.getElementById(`over-odds-${pId}`);
    const underEl = document.getElementById(`under-odds-${pId}`);
    const rowEl = document.getElementById(`row-${pId}`);

    if (lineEl && item.line != null) {
      lineEl.value = item.line;
      if (overEl && item.odds_over != null) overEl.value = item.odds_over;
      if (underEl && item.odds_under != null) underEl.value = item.odds_under;

      const pInTeam1 = team1Roster.some(p => p.player_id === pId);
      const oppAbbr = pInTeam1 ? t2 : t1;

      // Fill and invalidate once; the batch below owns all predictions.
      onPlayerInputChange(pId, oppAbbr, false);
      filledCount++;

      if (rowEl) {
        rowEl.classList.add("ring-2", "ring-emerald-500", "bg-emerald-950/30");
        setTimeout(() => {
          rowEl.classList.remove("ring-2", "ring-emerald-500", "bg-emerald-950/30");
        }, 3000);
      }
    }
  });

  const modal = document.getElementById("ocr-modal");
  if (modal) modal.classList.add("hidden");

  if (filledCount > 0) {
    console.log(`Đã tự động điền thành công ${filledCount} cầu thủ từ ảnh OCR!`);
    return calculateAll();
  } else {
    alert("Không tìm thấy cầu thủ tương ứng trong 2 đội đang chọn trên bảng. Vui lòng chọn đúng đội của các cầu thủ này trước khi áp dụng.");
  }
}
