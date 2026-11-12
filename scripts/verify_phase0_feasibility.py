import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from src.client import NBAClient
from src.collectors.schedule import fetch_schedule
from src.collectors.gamelogs import fetch_player_gamelogs
from src.collectors.boxscore import fetch_boxscores
from src.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("phase0_verification")

def run_phase0_feasibility_check(
    season: str = "2024-25",
    target_game_id: str = "0022400061",
) -> Path:
    """
    Execute Phase 0 Feasibility Verification:
    1. Connects to NBA.com using polite NBAClient.
    2. Fetches ScheduleLeagueV2 for season.
    3. Fetches PlayerGameLogs.
    4. Fetches BoxScoreTraditionalV3 and BoxScoreAdvancedV3 for target_game_id.
    5. Reconciles player stats between gamelogs and box score.
    6. Produces reports/phase0_feasibility_report.json.
    """
    settings.create_dirs()
    client = NBAClient()
    report = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "season": season,
        "target_game_id": target_game_id,
        "status": "IN_PROGRESS",
        "checks": {},
    }
    
    # Check 1: Static reference
    from src.collectors.static import get_all_players_df, get_all_teams_df
    players_df = get_all_players_df()
    teams_df = get_all_teams_df()
    report["checks"]["static_reference"] = {
        "pass": len(players_df) > 0 and len(teams_df) == 30,
        "player_count": len(players_df),
        "team_count": len(teams_df),
    }
    logger.info(f"Check 1 - Static reference: {len(players_df)} players, {len(teams_df)} teams")

    # Check 2: Schedule
    logger.info(f"Check 2 - Fetching schedule for {season}...")
    schedule_df = fetch_schedule(season, client=client)
    game_in_schedule = schedule_df[schedule_df["game_id"] == target_game_id]
    report["checks"]["schedule"] = {
        "pass": not game_in_schedule.empty,
        "total_games": len(schedule_df),
        "target_game_found": not game_in_schedule.empty,
    }
    logger.info(f"Check 2 - Schedule: Total {len(schedule_df)} games. Target game found: {not game_in_schedule.empty}")

    # Check 3: Box Scores V3
    logger.info(f"Check 3 - Fetching BoxScoreTraditionalV3 & AdvancedV3 for {target_game_id}...")
    trad_df, adv_df = fetch_boxscores(target_game_id, client=client)
    report["checks"]["boxscore_v3"] = {
        "pass": not trad_df.empty and not adv_df.empty,
        "traditional_rows": len(trad_df),
        "advanced_rows": len(adv_df),
        "columns_sample": list(trad_df.columns[:10]),
    }
    logger.info(f"Check 3 - Box scores: Traditional {len(trad_df)} rows, Advanced {len(adv_df)} rows")

    # Check 4: PlayerGameLogs and Reconciliation
    logger.info(f"Check 4 - Fetching PlayerGameLogs for {season} to reconcile...")
    gamelogs_df = fetch_player_gamelogs(season, client=client)
    game_logs = gamelogs_df[gamelogs_df["game_id"] == target_game_id]
    
    reconciliation_results = []
    reconciled = False
    
    if not game_logs.empty and not trad_df.empty:
        # Pick top scorer in game
        top_scorer_log = game_logs.sort_values(by="pts", ascending=False).iloc[0]
        player_id = top_scorer_log["player_id"]
        player_name = top_scorer_log["player_name"]
        
        box_row = trad_df[trad_df["player_id"] == player_id]
        if not box_row.empty:
            box_stat = box_row.iloc[0]
            pts_match = int(top_scorer_log["pts"]) == int(box_stat["pts"])
            reb_match = int(top_scorer_log["reb"]) == int(box_stat["reb"])
            ast_match = int(top_scorer_log["ast"]) == int(box_stat["ast"])
            
            reconciled = pts_match and reb_match and ast_match
            reconciliation_results.append({
                "player_id": int(player_id),
                "player_name": player_name,
                "gamelog": {"pts": int(top_scorer_log["pts"]), "reb": int(top_scorer_log["reb"]), "ast": int(top_scorer_log["ast"])},
                "boxscore": {"pts": int(box_stat["pts"]), "reb": int(box_stat["reb"]), "ast": int(box_stat["ast"])},
                "matches": {"pts": pts_match, "reb": reb_match, "ast": ast_match},
            })
            logger.info(f"Reconciliation for {player_name}: PTS={pts_match}, REB={reb_match}, AST={ast_match}")

    report["checks"]["reconciliation"] = {
        "pass": reconciled,
        "sample_reconciled_players": reconciliation_results,
    }

    # Final overall status
    all_passed = all(check.get("pass", False) for check in report["checks"].values())
    report["status"] = "PASSED" if all_passed else "FAILED"
    
    report_path = settings.REPORTS_DIR / "phase0_feasibility_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        
    logger.info(f"Phase 0 Feasibility Check completed with status: {report['status']}")
    logger.info(f"Report written to: {report_path}")
    return report_path

if __name__ == "__main__":
    run_phase0_feasibility_check()
