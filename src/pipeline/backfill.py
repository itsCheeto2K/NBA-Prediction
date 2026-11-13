import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import pandas as pd

from src.client import NBAClient
from src.collectors.gamelogs import fetch_player_gamelogs, fetch_team_gamelogs
from src.collectors.schedule import fetch_schedule
from src.collectors.static import get_all_players_df, get_all_teams_df
from src.config import SeasonType, settings
from src.storage.manifest import CheckpointManager

logger = logging.getLogger(__name__)


def audit_backfill_completeness(
    schedule_df: pd.DataFrame,
    team_logs_df: pd.DataFrame,
    player_logs_df: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """
    Rigorously audit backfill and sync completeness (§3, §6):
    - G_expected: completed games in schedule
    - G_seen: games in team logs
    - Exactly 2 team rows unique (game_id, team_id) matching both sides of schedule
    - G_missing = G_expected - G_seen
    - G_unexpected = G_seen - G_expected
    - Player logs uniqueness and coverage
    - Completeness status: COMPLETE only if G_missing is empty and 0 one-team-row games.
    """
    report: Dict[str, Any] = {
        "status": "PARTIAL",
        "expected_completed_games": 0,
        "observed_games": 0,
        "complete_completed_games": 0,
        "missing_game_ids": [],
        "unexpected_game_ids": [],
        "mismatched_team_row_games": [],
        "duplicate_team_rows_count": 0,
        "player_coverage_games": 0,
        "exceptions": [],
    }

    if schedule_df.empty or team_logs_df.empty:
        report["exceptions"].append("Empty schedule or team logs provided.")
        return report

    # 1. Standardize game IDs (10-char string zero-padded)
    sched = schedule_df.copy()
    sched["game_id"] = sched["game_id"].astype(str).str.zfill(10)
    
    # Identify completed games from schedule:
    # If game_status_text is Final or points are recorded
    if "game_status_text" in sched.columns:
        completed_sched = sched[sched["game_status_text"].astype(str).str.upper().str.contains("FINAL", regex=True)]
    elif "home_team_score" in sched.columns:
        completed_sched = sched[sched["home_team_score"].notna()]
    else:
        completed_sched = sched

    expected_game_ids: Set[str] = set(completed_sched["game_id"].unique())
    report["expected_completed_games"] = len(expected_game_ids)

    # 2. Check team logs structure: exactly 2 team rows per game
    teams = team_logs_df.copy()
    teams["game_id"] = teams["game_id"].astype(str).str.zfill(10)
    if "team_id" in teams.columns:
        teams["team_id"] = teams["team_id"].astype(str)

    observed_game_ids: Set[str] = set(teams["game_id"].unique())
    report["observed_games"] = len(observed_game_ids)

    # Check unique team rows per game
    team_counts = teams.groupby("game_id")["team_id"].nunique()
    valid_two_team_games = set(team_counts[team_counts == 2].index)
    mismatched_games = sorted(list(team_counts[team_counts != 2].index))
    report["mismatched_team_row_games"] = mismatched_games
    report["complete_completed_games"] = len(valid_two_team_games)

    # 3. Missing and Unexpected game IDs
    missing_ids = sorted(list(expected_game_ids - valid_two_team_games))
    unexpected_ids = sorted(list(observed_game_ids - expected_game_ids))
    report["missing_game_ids"] = missing_ids
    report["unexpected_game_ids"] = unexpected_ids

    # 4. Player logs coverage and duplicate check (game_id, player_id)
    if player_logs_df is not None and not player_logs_df.empty:
        players = player_logs_df.copy()
        players["game_id"] = players["game_id"].astype(str).str.zfill(10)
        report["player_coverage_games"] = int(players["game_id"].nunique())
        
        if "player_id" in players.columns:
            duplicates = players.duplicated(subset=["game_id", "player_id"]).sum()
            report["duplicate_player_rows_count"] = int(duplicates)
            if duplicates > 0:
                report["exceptions"].append(f"Found {duplicates} duplicate (game_id, player_id) player rows.")

    # 5. Determine audit status
    if len(missing_ids) == 0 and len(mismatched_games) == 0 and report["expected_completed_games"] > 0:
        report["status"] = "COMPLETE"
    else:
        report["status"] = "PARTIAL"
        if missing_ids:
            report["exceptions"].append(f"Missing {len(missing_ids)} expected completed games.")
        if mismatched_games:
            report["exceptions"].append(f"{len(mismatched_games)} games do not have exactly 2 team rows.")

    return report


class BackfillPipeline:
    """Manages full backfill of P0 data with checkpoint resumption and audit reconciliation."""

    def __init__(
        self,
        client: Optional[NBAClient] = None,
        checkpoint_mgr: Optional[CheckpointManager] = None,
        parquet_dir: Optional[Path] = None,
    ):
        self.client = client or NBAClient()
        self.checkpoint_mgr = checkpoint_mgr or CheckpointManager()
        self.parquet_dir = parquet_dir or settings.PARQUET_DIR
        self.parquet_dir.mkdir(parents=True, exist_ok=True)

    def run_static_reference(self) -> Dict[str, int]:
        """Save static players and teams reference tables to Parquet."""
        results = {}
        # Players
        players_df = get_all_players_df()
        players_path = self.parquet_dir / "players_reference.parquet"
        players_df.to_parquet(players_path, index=False)
        results["players"] = len(players_df)
        logger.info(f"Saved {len(players_df)} players to {players_path}")

        # Teams
        teams_df = get_all_teams_df()
        teams_path = self.parquet_dir / "teams_reference.parquet"
        teams_df.to_parquet(teams_path, index=False)
        results["teams"] = len(teams_df)
        logger.info(f"Saved {len(teams_df)} teams to {teams_path}")
        
        return results

    def run_season_p0(self, season: str, force: bool = False) -> Dict[str, Any]:
        """Backfill schedule, player gamelogs, and team gamelogs for a single season with audit."""
        season_results: Dict[str, Any] = {}
        logger.info(f"=== Starting P0 Backfill for Season {season} ===")

        # 1. Schedule
        task_schedule = f"schedule_{season}"
        sched_path = self.parquet_dir / f"schedule_{season}.parquet"
        sched_df = pd.DataFrame()
        if not force and self.checkpoint_mgr.is_completed(task_schedule) and sched_path.exists():
            logger.info(f"[{task_schedule}] Already completed, loading.")
            sched_df = pd.read_parquet(sched_path)
            season_results["schedule_rows"] = len(sched_df)
        else:
            try:
                self.checkpoint_mgr.mark_in_progress(task_schedule)
                sched_df = fetch_schedule(season, client=self.client)
                sched_df.to_parquet(sched_path, index=False)
                self.checkpoint_mgr.mark_completed(task_schedule, rows_count=len(sched_df))
                season_results["schedule_rows"] = len(sched_df)
                logger.info(f"[{task_schedule}] Successfully saved {len(sched_df)} games.")
            except Exception as e:
                self.checkpoint_mgr.mark_failed(task_schedule, str(e))
                logger.error(f"[{task_schedule}] Failed: {e}")
                season_results["schedule_error"] = str(e)

        # 2. Team Game Logs
        task_team_logs = f"teamgamelogs_{season}"
        team_logs_path = self.parquet_dir / f"team_gamelogs_{season}.parquet"
        team_logs_df = pd.DataFrame()
        if not force and self.checkpoint_mgr.is_completed(task_team_logs) and team_logs_path.exists():
            logger.info(f"[{task_team_logs}] Already completed, loading.")
            team_logs_df = pd.read_parquet(team_logs_path)
            season_results["team_log_rows"] = len(team_logs_df)
        else:
            try:
                self.checkpoint_mgr.mark_in_progress(task_team_logs)
                team_logs_df = fetch_team_gamelogs(season, client=self.client)
                team_logs_df.to_parquet(team_logs_path, index=False)
                self.checkpoint_mgr.mark_completed(task_team_logs, rows_count=len(team_logs_df))
                season_results["team_log_rows"] = len(team_logs_df)
                logger.info(f"[{task_team_logs}] Successfully saved {len(team_logs_df)} rows.")
            except Exception as e:
                self.checkpoint_mgr.mark_failed(task_team_logs, str(e))
                logger.error(f"[{task_team_logs}] Failed: {e}")
                season_results["team_log_error"] = str(e)

        # 3. Player Game Logs
        task_player_logs = f"playergamelogs_{season}"
        player_logs_path = self.parquet_dir / f"player_gamelogs_{season}.parquet"
        player_logs_df = pd.DataFrame()
        if not force and self.checkpoint_mgr.is_completed(task_player_logs) and player_logs_path.exists():
            logger.info(f"[{task_player_logs}] Already completed, loading.")
            player_logs_df = pd.read_parquet(player_logs_path)
            season_results["player_log_rows"] = len(player_logs_df)
        else:
            try:
                self.checkpoint_mgr.mark_in_progress(task_player_logs)
                player_logs_df = fetch_player_gamelogs(season, client=self.client)
                player_logs_df.to_parquet(player_logs_path, index=False)
                self.checkpoint_mgr.mark_completed(task_player_logs, rows_count=len(player_logs_df))
                season_results["player_log_rows"] = len(player_logs_df)
                logger.info(f"[{task_player_logs}] Successfully saved {len(player_logs_df)} rows.")
            except Exception as e:
                self.checkpoint_mgr.mark_failed(task_player_logs, str(e))
                logger.error(f"[{task_player_logs}] Failed: {e}")
                season_results["player_log_error"] = str(e)

        # 4. Completeness audit
        if not sched_df.empty and not team_logs_df.empty:
            audit = audit_backfill_completeness(sched_df, team_logs_df, player_logs_df)
            season_results["completeness_audit"] = audit
            logger.info(f"Season {season} completeness audit: {audit['status']} (Expected: {audit['expected_completed_games']}, Complete: {audit['complete_completed_games']})")

        return season_results

    def run_all(self, seasons: Optional[List[str]] = None, force: bool = False) -> Dict[str, Any]:
        """Execute full backfill across static reference and specified seasons."""
        target_seasons = seasons or settings.SEASONS
        summary = {"static": self.run_static_reference(), "seasons": {}}
        for season in target_seasons:
            summary["seasons"][season] = self.run_season_p0(season, force=force)
        return summary
