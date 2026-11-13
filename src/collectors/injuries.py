import json
import logging
import time
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config import settings

logger = logging.getLogger(__name__)

ESPN_INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
INJURY_CACHE_PATH = settings.DATA_DIR / "raw" / "injuries" / "espn_injuries.json"

ESPN_TEAM_TO_TRICODE = {
    "Atlanta Hawks": "ATL",
    "Boston Celtics": "BOS",
    "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL",
    "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW",
    "Houston Rockets": "HOU",
    "Indiana Pacers": "IND",
    "LA Clippers": "LAC",
    "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA",
    "Washington Wizards": "WAS",
}

def normalize_text(text: str) -> str:
    """Normalize unicode accents and lowercase (e.g. 'Dončić' -> 'doncic')."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = nfkd.encode("ASCII", "ignore").decode("utf-8")
    return ascii_text.lower().strip()

def fetch_espn_injuries(force_refresh: bool = False, cache_ttl_seconds: int = 900) -> Dict[str, Any]:
    """
    Fetch live NBA injury reports from ESPN public API.
    Caches on disk with a default 15-minute TTL.
    """
    INJURY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not force_refresh and INJURY_CACHE_PATH.exists():
        try:
            with open(INJURY_CACHE_PATH, "r", encoding="utf-8") as f:
                cached = json.load(f)
            cached_time = datetime.fromisoformat(cached.get("fetched_at", "2000-01-01T00:00:00+00:00"))
            age_sec = (datetime.now(timezone.utc) - cached_time).total_seconds()
            if age_sec < cache_ttl_seconds:
                return cached
        except Exception as e:
            logger.warning(f"Failed to read injury cache: {e}")

    logger.info("Fetching real-time NBA injury report from ESPN...")
    req = urllib.request.Request(
        ESPN_INJURIES_URL,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    )

    raw_data = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw_data = json.loads(resp.read().decode("utf-8"))
                break
        except Exception as e:
            logger.warning(f"Attempt {attempt}/3 fetching ESPN injuries failed: {e}")
            if attempt < 3:
                time.sleep(1.0 * attempt)

    if raw_data is None:
        logger.error("All 3 attempts to fetch ESPN injuries failed.")
        # Fallback to expired cache if available
        if INJURY_CACHE_PATH.exists():
            with open(INJURY_CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"fetched_at": datetime.now(timezone.utc).isoformat(), "teams": {}, "players": {}}

    teams_dict: Dict[str, List[Dict[str, Any]]] = {}
    players_dict: Dict[str, Dict[str, Any]] = {}

    for team_entry in raw_data.get("injuries", []):
        team_name = team_entry.get("displayName", "")
        tricode = ESPN_TEAM_TO_TRICODE.get(team_name, team_name[:3].upper())
        team_injuries = []

        for item in team_entry.get("injuries", []):
            athlete = item.get("athlete", {})
            full_name = athlete.get("displayName", "")
            status = item.get("status", "Day-To-Day")
            short_desc = item.get("shortComment", "")
            long_desc = item.get("longComment", "")
            inj_date = item.get("date", "")
            position = athlete.get("position", {}).get("name", "Player")

            record = {
                "player_name": full_name,
                "team_abbr": tricode,
                "team_name": team_name,
                "status": status,
                "short_comment": short_desc,
                "long_comment": long_desc,
                "date": inj_date,
                "position": position,
            }

            team_injuries.append(record)
            norm_name = normalize_text(full_name)
            players_dict[norm_name] = record

        teams_dict[tricode] = team_injuries

    result = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total_injuries": sum(len(v) for v in teams_dict.values()),
        "teams": teams_dict,
        "players": players_dict,
    }

    with open(INJURY_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    logger.info(f"Loaded {result['total_injuries']} active injuries across {len(teams_dict)} teams.")
    return result

def get_player_injury(player_name: str, injuries_data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Look up injury report for a specific player name with accent normalization."""
    data = injuries_data or fetch_espn_injuries()
    players = data.get("players", {})
    norm_name = normalize_text(player_name)
    if norm_name in players:
        return players[norm_name]
    
    # Partial match
    for k, v in players.items():
        if norm_name in k or k in norm_name:
            return v
    return None

def get_team_injuries(team_abbr: str, injuries_data: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Return all active injuries for a team."""
    data = injuries_data or fetch_espn_injuries()
    teams = data.get("teams", {})
    return teams.get(team_abbr.upper(), [])

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    inj = fetch_espn_injuries(force_refresh=True)
    print("ESPN Injuries Summary:")
    print("Total injuries:", inj["total_injuries"])
    print("Sample Lakers (LAL) injuries:", get_team_injuries("LAL", inj))
    print("Sample Hawks (ATL) injuries:", get_team_injuries("ATL", inj))
