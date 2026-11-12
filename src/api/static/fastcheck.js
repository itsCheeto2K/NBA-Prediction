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

document.addEventListener("DOMContentLoaded", () => {
  populateDropdowns();
  initSyncStatus();
  resetMatchupState();

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
      if (el && data.latest_game_date) {
        el.textContent = `2026-27 Active • Latest: ${data.latest_game_date}`;
      }
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

  document.getElementById("team1-badge").textContent = t1;
  const t1Obj = NBA_TEAMS.find(t => t.abbr === t1);
  document.getElementById("team1-title").textContent = t1Obj ? `${t1Obj.name} (${t1})` : t1;

  try {
    const matchupRes = await fetch(`/api/teams/${t1}/matchup`);
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

      await loadBothRosters(t1, opp);
    } else {
      document.getElementById("matchup-tipoff-text").textContent = "Không tìm thấy lịch đấu kế tiếp";
      await loadBothRosters(t1, s2.value || "OPP");
    }
  } catch (err) {
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

  document.getElementById("team2-badge").textContent = t2;
  const t2Obj = NBA_TEAMS.find(t => t.abbr === t2);
  document.getElementById("team2-title").textContent = t2Obj ? `${t2Obj.name} (${t2})` : t2;

  try {
    const matchupRes = await fetch(`/api/teams/${t2}/matchup`);
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

      await loadBothRosters(opp, t2);
    } else {
      document.getElementById("matchup-tipoff-text").textContent = "Không tìm thấy lịch đấu kế tiếp";
      await loadBothRosters(s1.value || "OPP", t2);
    }
  } catch (err) {
    console.error("Error updating matchup:", err);
  }
}

async function loadBothRosters(t1, t2) {
  const list1 = document.getElementById("team1-roster-list");
  const list2 = document.getElementById("team2-roster-list");

  if (list1) list1.innerHTML = `<div class="text-center py-8 text-xs text-gray-500 animate-pulse">Đang tải danh sách ${t1}...</div>`;
  if (list2) list2.innerHTML = `<div class="text-center py-8 text-xs text-gray-500 animate-pulse">Đang tải danh sách ${t2}...</div>`;

  const fetchRoster = async (teamAbbr) => {
    if (!teamAbbr || teamAbbr === "---" || teamAbbr === "OPP") return [];
    try {
      const res = await fetch(`/api/teams/${teamAbbr}/roster`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) {
      console.warn(`Could not load roster for ${teamAbbr}:`, e);
      return [];
    }
  };

  try {
    const [r1, r2] = await Promise.all([fetchRoster(t1), fetchRoster(t2)]);

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

    renderRoster("team1-roster-list", team1Roster, t2);
    renderRoster("team2-roster-list", team2Roster, t1);
  } catch (err) {
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
                title="Click để chuyển sang Oracle chi tiết cho ${p.player_name}"
              >
                <span class="truncate">${p.player_name}</span>
                <span class="text-[10px] text-gray-400 group-hover:text-indigo-400">↗</span>
              </a>
              ${roleBadge}
            </div>
            <div class="flex items-center space-x-1.5 mt-0.5">
              <span class="text-[10px] text-gray-400 font-mono">${p.min_avg}m</span>
              <span class="text-[10px] text-gray-500">•</span>
              <span class="text-[10px] text-gray-400 font-mono">${p.pts_avg} pts</span>
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

function onPlayerInputChange(playerId, opponentAbbr) {
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

  // If user cleared the line, reset outputs to dash
  if (!lineVal || isNaN(parseFloat(lineVal))) {
    if (evEl) evEl.textContent = "-";
    if (overEl) {
      overEl.textContent = "-";
      overEl.className = "box-output neutral";
    }
    if (underEl) {
      underEl.textContent = "-";
      underEl.className = "box-output neutral";
    }
    if (linkEl) {
      linkEl.href = `/?player_id=${playerId}&player_name=${encodeURIComponent(pName)}&opp=${opponentAbbr}`;
    }
    return;
  }

  const line = parseFloat(lineVal);
  const oddsOver = overInput && overInput.value.trim() ? parseFloat(overInput.value) : 1.91;
  const oddsUnder = underInput && underInput.value.trim() ? parseFloat(underInput.value) : 1.91;

  if (linkEl) {
    linkEl.href = `/?player_id=${playerId}&player_name=${encodeURIComponent(pName)}&line=${line}&odds_over=${oddsOver}&odds_under=${oddsUnder}&opp=${opponentAbbr}`;
  }

  // Debounced predict call
  clearTimeout(debounceTimers[playerId]);
  debounceTimers[playerId] = setTimeout(() => {
    calculateSinglePlayer(playerId, line, oddsOver, oddsUnder, opponentAbbr);
  }, 350);
}

async function calculateSinglePlayer(playerId, line, oddsOver, oddsUnder, opponentAbbr) {
  const evEl = document.getElementById(`ev-${playerId}`);
  const overEl = document.getElementById(`over-pct-${playerId}`);
  const underEl = document.getElementById(`under-pct-${playerId}`);

  if (evEl) evEl.textContent = "...";

  try {
    const res = await fetch("/api/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        player_id: playerId,
        stat: "pts",
        line: line,
        over_odds: oddsOver,
        under_odds: oddsUnder,
        opponent_override: opponentAbbr,
      }),
    });

    const data = await res.json();
    if (res.ok) {
      applyPredictionToRow(playerId, data);
    } else {
      if (evEl) evEl.textContent = "Err";
    }
  } catch (err) {
    console.error(`Error calculating for player ${playerId}:`, err);
    if (evEl) evEl.textContent = "Err";
  }
}

function applyPredictionToRow(playerId, data) {
  const evEl = document.getElementById(`ev-${playerId}`);
  const overEl = document.getElementById(`over-pct-${playerId}`);
  const underEl = document.getElementById(`under-pct-${playerId}`);

  if (evEl && data.expected_value != null) {
    evEl.textContent = data.expected_value.toFixed(1);
  }

  if (data.line_probabilities) {
    const qOver = (data.line_probabilities.q_over * 100).toFixed(1);
    const qUnder = (data.line_probabilities.q_under * 100).toFixed(1);

    if (overEl) {
      overEl.textContent = `${qOver}%`;
      overEl.className = "box-output " + (parseFloat(qOver) >= 52.4 ? "over-high" : "neutral");
    }
    if (underEl) {
      underEl.textContent = `${qUnder}%`;
      underEl.className = "box-output " + (parseFloat(qUnder) >= 52.4 ? "under-high" : "neutral");
    }
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

    if (lineVal && !isNaN(parseFloat(lineVal))) {
      batchPayload.push({
        player_id: p.player_id,
        stat: "pts",
        line: parseFloat(lineVal),
        over_odds: overEl && overEl.value.trim() ? parseFloat(overEl.value) : 1.91,
        under_odds: underEl && underEl.value.trim() ? parseFloat(underEl.value) : 1.91,
        opponent_override: t2,
      });
    }
  });

  team2Roster.forEach(p => {
    const lineEl = document.getElementById(`line-${p.player_id}`);
    const overEl = document.getElementById(`over-odds-${p.player_id}`);
    const underEl = document.getElementById(`under-odds-${p.player_id}`);
    const lineVal = lineEl ? lineEl.value.trim() : "";

    if (lineVal && !isNaN(parseFloat(lineVal))) {
      batchPayload.push({
        player_id: p.player_id,
        stat: "pts",
        line: parseFloat(lineVal),
        over_odds: overEl && overEl.value.trim() ? parseFloat(overEl.value) : 1.91,
        under_odds: underEl && underEl.value.trim() ? parseFloat(underEl.value) : 1.91,
        opponent_override: t1,
      });
    }
  });

  if (batchPayload.length === 0) {
    alert("Vui lòng nhập Line điểm cho ít nhất 1 cầu thủ để tính toán.");
    return;
  }

  const btn = document.getElementById("btn-calc-all");
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span>⏳ Đang tính (${batchPayload.length})...</span>`;
  }

  try {
    const res = await fetch("/api/fastcheck/predict-batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(batchPayload),
    });

    const results = await res.json();
    results.forEach(r => {
      const evEl = document.getElementById(`ev-${r.player_id}`);
      const overEl = document.getElementById(`over-pct-${r.player_id}`);
      const underEl = document.getElementById(`under-pct-${r.player_id}`);

      if (evEl && r.expected_value != null) {
        evEl.textContent = r.expected_value.toFixed(1);
      }
      if (overEl && r.q_over != null) {
        overEl.textContent = `${r.q_over}%`;
        overEl.className = "box-output " + (r.q_over >= 52.4 ? "over-high" : "neutral");
      }
      if (underEl && r.q_under != null) {
        underEl.textContent = `${r.q_under}%`;
        underEl.className = "box-output " + (r.q_under >= 52.4 ? "under-high" : "neutral");
      }
    });
  } catch (err) {
    console.error("Error running batch calculation:", err);
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

  if (btn) btn.disabled = true;
  if (text) text.textContent = "Syncing...";
  if (icon) icon.classList.add("animate-spin");

  fetch("/api/sync", { method: "POST" })
    .then(r => r.json())
    .then(() => {
      onTeam1Change();
    })
    .finally(() => {
      if (btn) btn.disabled = false;
      if (text) text.textContent = "Sync Live";
      if (icon) icon.classList.remove("animate-spin");
    });
}
