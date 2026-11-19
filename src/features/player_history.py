"""
Player History Reference Service
================================
Pure read service for player reference history (recent games & H2H vs opponent).
Implements NBA_HOME_PLAYER_HISTORY_REFERENCE_SPEC.md.

CRITICAL:
- Pure read-only service.
- DOES NOT touch feature engineering, rolling model features, shrinkage,
  prediction models, ModelBundle, EV/Kelly calculations.
- Zero impact on inference.
"""

from __future__ import annotations

import glob
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from src.config import settings

logger = logging.getLogger("player_history")


def to_int_or_none(val: Any) -> Optional[int]:
    """Safely convert a pandas/numpy value to int, preserving real 0 and converting NaN/None to None."""
    if pd.isna(val) or val is None:
        return None
    try:
        return int(round(float(val)))
    except (ValueError, TypeError):
        return None


class PlayerHistoryService:
    """Singleton service to query player game logs for reference display."""

    _instance: Optional[PlayerHistoryService] = None
    _lock = threading.Lock()

    def __init__(self, parquet_dir: Optional[Path] = None):
        self.parquet_dir = parquet_dir or settings.PARQUET_DIR
        self._gamelogs_df: Optional[pd.DataFrame] = None
        self._teams_ref_df: Optional[pd.DataFrame] = None
        self._schedule_df: Optional[pd.DataFrame] = None
        self._abbr_to_team: Dict[str, Dict[str, Any]] = {}
        self._id_to_team: Dict[int, Dict[str, Any]] = {}
        self._seasons_available: List[str] = []
        self._data_updated_at: Optional[str] = None
        self._loaded = False
        self._team_scores: Dict[Tuple[str, int], int] = {}

    @classmethod
    def get_instance(cls, parquet_dir: Optional[Path] = None) -> PlayerHistoryService:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(parquet_dir=parquet_dir)
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """For testing: reset singleton state."""
        with cls._lock:
            cls._instance = None

    def load_data(self, force_reload: bool = False) -> None:
        """Load and prepare all gamelogs and team reference data."""
        with self._lock:
            if self._loaded and not force_reload:
                return

            logger.info("Loading player gamelogs and team reference data...")

            from src.storage.datasets import dataset_view
            view = dataset_view(self.parquet_dir, self.parquet_dir.parent)

            # 1. Load teams reference
            teams_ref_path = view.path("teams_reference.parquet")
            if teams_ref_path.exists():
                self._teams_ref_df = pd.read_parquet(teams_ref_path)
                for _, r in self._teams_ref_df.iterrows():
                    tid = int(r["team_id"])
                    abbr = str(r["abbreviation"]).strip()
                    fname = str(r["full_name"]).strip()
                    nname = str(r.get("nickname", "")).strip()
                    info = {
                        "team_id": tid,
                        "abbreviation": abbr,
                        "full_name": fname,
                        "nickname": nname,
                    }
                    self._abbr_to_team[abbr] = info
                    self._id_to_team[tid] = info
            else:
                logger.warning(f"teams_reference.parquet not found at {teams_ref_path}")

            # 2. Load all player gamelogs
            pattern = str(self.parquet_dir / "player_gamelogs_*.parquet")
            gamelog_files = view.glob("player_gamelogs_*.parquet")
            if not gamelog_files:
                logger.warning(f"No player_gamelogs_*.parquet found matching {pattern}")
                self._gamelogs_df = pd.DataFrame()
                self._loaded = True
                return

            dfs: List[pd.DataFrame] = []
            seasons_seen = set()
            for gf in gamelog_files:
                try:
                    df_chunk = pd.read_parquet(gf)
                    dfs.append(df_chunk)
                    if "season" in df_chunk.columns:
                        seasons_seen.update(df_chunk["season"].dropna().unique().tolist())
                except Exception as e:
                    logger.error(f"Error loading {gf}: {e}")

            if not dfs:
                self._gamelogs_df = pd.DataFrame()
                self._loaded = True
                return

            merged = pd.concat(dfs, ignore_index=True)
            self._seasons_available = sorted(list(seasons_seen))

            # 3. Clean & normalize gamelogs
            # Ensure game_id is str
            merged["game_id"] = merged["game_id"].astype(str)
            # Ensure player_id is int
            merged["player_id"] = pd.to_numeric(merged["player_id"], errors="coerce").fillna(0).astype(int)
            # Filter out DNP: min <= 0 or NaN (§3.1)
            # Note: real zeros in stats (pts, reb, ast) MUST be kept!
            merged["min_numeric"] = pd.to_numeric(merged["min"], errors="coerce")
            merged = merged[merged["min_numeric"] > 0].copy()

            # Date parsing
            merged["game_date_dt"] = pd.to_datetime(merged["game_date"])
            merged["game_date_str"] = merged["game_date_dt"].dt.strftime("%Y-%m-%d")

            # Matchup parsing for opponent & home/away
            matchup_str = merged["matchup"].astype(str).str.strip()
            merged["home_away"] = np.where(matchup_str.str.contains("@"), "away", "home")
            merged["opp_abbr_parsed"] = matchup_str.str.split().str[-1].str.strip()

            # Map opponent details from teams_reference
            def get_opp_id(abbr: str) -> Optional[int]:
                return self._abbr_to_team.get(abbr, {}).get("team_id")

            def get_opp_name(abbr: str) -> Optional[str]:
                return self._abbr_to_team.get(abbr, {}).get("full_name")

            merged["opponent_team_id"] = merged["opp_abbr_parsed"].map(get_opp_id)
            merged["opponent_team_name"] = merged["opp_abbr_parsed"].map(get_opp_name)
            merged["opponent_team_abbr"] = merged["opp_abbr_parsed"]

            # Season type default
            if "season_type" not in merged.columns:
                merged["season_type"] = "Regular Season"
            else:
                merged["season_type"] = merged["season_type"].fillna("Regular Season")

            # Deduplication: player_id + game_id (§3.1)
            merged = merged.drop_duplicates(subset=["player_id", "game_id"], keep="first")

            # Stable sort: newest game date first, secondary key game_id descending (§3.1)
            merged = merged.sort_values(
                by=["game_date_dt", "game_id"],
                ascending=[False, False],
            ).reset_index(drop=True)

            self._gamelogs_df = merged

            # Track latest data timestamp
            if not merged.empty:
                max_dt = merged["game_date_dt"].max()
                self._data_updated_at = max_dt.isoformat() if pd.notna(max_dt) else datetime.now(timezone.utc).isoformat()

            # 4. Load schedule for target_game_id cutoff lookup
            sched_pattern = str(self.parquet_dir / "schedule_*.parquet")
            sched_files = view.glob("schedule_*.parquet")
            if sched_files:
                sched_dfs = [pd.read_parquet(sf) for sf in sched_files]
                sched_merged = pd.concat(sched_dfs, ignore_index=True)
                sched_merged["game_id"] = sched_merged["game_id"].astype(str)
                self._schedule_df = sched_merged

            # Reference scores only: resolve from team totals, never a player's points.
            self._team_scores = {}
            for path in view.glob("team_gamelogs_*.parquet"):
                totals = pd.read_parquet(path)
                if not {"game_id", "team_id", "pts"}.issubset(totals.columns):
                    continue
                for game, team, points in totals[["game_id", "team_id", "pts"]].dropna().itertuples(index=False, name=None):
                    self._team_scores[(str(game), int(team))] = int(points)

            self._loaded = True
            logger.info(
                f"PlayerHistoryService loaded {len(merged)} valid appearances across {len(self._seasons_available)} seasons."
            )

    def resolve_team(self, team_id_or_abbr: Union[int, str]) -> Optional[Dict[str, Any]]:
        """Resolve a team by team_id or abbreviation."""
        self.load_data()
        if isinstance(team_id_or_abbr, int) or (isinstance(team_id_or_abbr, str) and team_id_or_abbr.isdigit()):
            tid = int(team_id_or_abbr)
            return self._id_to_team.get(tid)
        elif isinstance(team_id_or_abbr, str):
            abbr = team_id_or_abbr.strip().upper()
            return self._abbr_to_team.get(abbr)
        return None

    def get_player_history(
        self,
        player_id: int | str,
        opponent_team_id: Optional[int | str] = None,
        opponent_abbr: Optional[str] = None,
        target_game_id: Optional[str] = None,
        season_type: str = "Regular Season",
        limit: int = 10,
    ) -> Dict[str, Any]:
        """
        Query player reference history for 10 recent games and 10 games vs opponent.

        Returns raw dictionary matching §6 of NBA_HOME_PLAYER_HISTORY_REFERENCE_SPEC.md.
        """
        self.load_data()
        warnings: List[str] = []

        try:
            pid = int(player_id)
        except (ValueError, TypeError):
            pid = 0


        as_of = datetime.now(timezone.utc).isoformat()
        cutoff_dt: Optional[pd.Timestamp] = None

        # Resolve target_game_id cutoff if provided (§3.1)
        if target_game_id:
            target_gid_str = str(target_game_id).strip()
            # 1. Search in schedule
            if self._schedule_df is not None and not self._schedule_df.empty:
                s_match = self._schedule_df[self._schedule_df["game_id"] == target_gid_str]
                if not s_match.empty:
                    s_row = s_match.iloc[0]
                    # date extraction
                    date_col = "gameDate" if "gameDate" in s_row and pd.notna(s_row["gameDate"]) else "game_date_est"
                    raw_date = s_row.get(date_col)
                    if pd.notna(raw_date):
                        cutoff_dt = pd.to_datetime(raw_date)
                        as_of = cutoff_dt.isoformat()

                    # Auto-detect opponent if not specified
                    if not opponent_team_id and not opponent_abbr:
                        h_id = s_row.get("home_team_id")
                        a_id = s_row.get("away_team_id")
                        # Find player's most recent team
                        if self._gamelogs_df is not None and not self._gamelogs_df.empty:
                            p_logs = self._gamelogs_df[self._gamelogs_df["player_id"] == pid]
                            if not p_logs.empty:
                                p_team = p_logs.iloc[0]["team_id"]
                                if p_team == h_id:
                                    opponent_team_id = a_id
                                elif p_team == a_id:
                                    opponent_team_id = h_id

            # 2. If cutoff_dt not yet found from schedule, check gamelogs
            if cutoff_dt is None and self._gamelogs_df is not None and not self._gamelogs_df.empty:
                g_match = self._gamelogs_df[self._gamelogs_df["game_id"] == target_gid_str]
                if not g_match.empty:
                    cutoff_dt = g_match.iloc[0]["game_date_dt"]
                    as_of = cutoff_dt.isoformat()

            if cutoff_dt is None:
                warnings.append(
                    f"target_game_id '{target_game_id}' not found in schedule or gamelogs; excluded matching game_id only."
                )

        # Resolve opponent if specified
        resolved_opp: Optional[Dict[str, Any]] = None
        if opponent_team_id is not None:
            resolved_opp = self.resolve_team(opponent_team_id)
            if not resolved_opp:
                warnings.append(f"Opponent team ID {opponent_team_id} not found in reference teams.")
        elif opponent_abbr:
            resolved_opp = self.resolve_team(opponent_abbr)
            if not resolved_opp:
                warnings.append(f"Opponent abbreviation '{opponent_abbr}' not found in reference teams.")

        opp_id_resolved = resolved_opp["team_id"] if resolved_opp else None

        # Query gamelogs
        if self._gamelogs_df is None or self._gamelogs_df.empty:
            warnings.append("Gamelogs database is empty.")
            return {
                "player_id": pid,
                "opponent_team_id": opp_id_resolved,
                "as_of": as_of,
                "season_type": season_type,
                "reference_only": True,
                "affects_prediction": False,
                "recent": {"rows": [], "returned_count": 0},
                "vs_opponent": {"rows": [], "returned_count": 0},
                "coverage": {
                    "seasons_available": self._seasons_available,
                    "history_complete_for_requested_scope": False,
                    "backfill_pending": False,
                },
                "data_updated_at": self._data_updated_at,
                "warnings": warnings,
            }

        # Filter for player
        p_df = self._gamelogs_df[self._gamelogs_df["player_id"] == pid].copy()
        if p_df.empty:
            warnings.append(f"No game logs found for player_id {pid}.")

        # Season type filter (§3.1)
        if season_type:
            p_df_st = p_df[p_df["season_type"] == season_type]
            if p_df_st.empty and not p_df.empty:
                warnings.append(f"No games found with season_type='{season_type}'.")
                p_df = p_df_st
            else:
                p_df = p_df_st

        # Target game & cutoff filter (§3.1)
        if target_game_id:
            target_gid_str = str(target_game_id).strip()
            p_df = p_df[p_df["game_id"] != target_gid_str]
            if cutoff_dt is not None:
                p_df = p_df[p_df["game_date_dt"] < cutoff_dt]

        # 1. Recent games (Top `limit` appearances)
        recent_chunk = p_df.head(limit)
        recent_rows = [self._build_row(r) for _, r in recent_chunk.iterrows()]

        # 2. H2H vs Opponent
        # CRITICAL: Filter by opponent BEFORE limiting to `limit` games! (§3.3, §8)
        vs_opp_rows: List[Dict[str, Any]] = []
        history_complete = False

        if opp_id_resolved is not None:
            h2h_df = p_df[p_df["opponent_team_id"] == opp_id_resolved]
            h2h_chunk = h2h_df.head(limit)
            vs_opp_rows = [self._build_row(r) for _, r in h2h_chunk.iterrows()]
            h2h_count = len(vs_opp_rows)

            if h2h_count >= limit:
                history_complete = True
            else:
                history_complete = False
                min_s = self._seasons_available[0] if self._seasons_available else "N/A"
                max_s = self._seasons_available[-1] if self._seasons_available else "N/A"
                warnings.append(
                    f"Chỉ có {h2h_count}/{limit} trận đối đầu trong dữ liệu hiện có ({min_s} đến {max_s}). "
                    f"Lịch sử đối đầu có thể chưa đầy đủ cho các mùa giải trước đó."
                )
        else:
            warnings.append("No opponent specified; vs_opponent table is empty.")

        coverage = {
            "seasons_available": self._seasons_available,
            "history_complete_for_requested_scope": history_complete,
            "backfill_pending": False,
        }

        return {
            "player_id": pid,
            "opponent_team_id": opp_id_resolved,
            "as_of": as_of,
            "season_type": season_type,
            "reference_only": True,
            "affects_prediction": False,
            "recent": {
                "rows": recent_rows,
                "returned_count": len(recent_rows),
            },
            "vs_opponent": {
                "rows": vs_opp_rows,
                "returned_count": len(vs_opp_rows),
            },
            "coverage": coverage,
            "data_updated_at": self._data_updated_at,
            "warnings": warnings,
        }

    def _build_row(self, r: pd.Series) -> Dict[str, Any]:
        """Convert a pandas row to the standardized reference history row dictionary."""
        tid = int(r["team_id"])
        t_info = self._id_to_team.get(tid, {})
        t_name = str(r.get("team_name") or t_info.get("full_name") or "")
        t_abbr = str(r.get("team_abbreviation") or t_info.get("abbreviation") or "")

        opp_id = int(r["opponent_team_id"]) if pd.notna(r.get("opponent_team_id")) else 0
        opp_name = str(r.get("opponent_team_name") or "")
        opp_abbr = str(r.get("opponent_team_abbr") or "")
        team_score = self._team_scores.get((str(r["game_id"]), tid))
        opponent_score = self._team_scores.get((str(r["game_id"]), opp_id))
        result = str(r.get("wl", "")).upper()
        if result not in ("W", "L"):
            result = ("W" if team_score > opponent_score else "L") if team_score is not None and opponent_score is not None and team_score != opponent_score else None

        def shooting_pct(made, attempted):
            makes, attempts = to_int_or_none(r.get(made)), to_int_or_none(r.get(attempted))
            return round(makes / attempts, 6) if makes is not None and attempts is not None and attempts > 0 else None

        return {
            "game_id": str(r["game_id"]),
            "game_date": str(r["game_date_str"]),
            "season": str(r.get("season", "")),
            "season_type": str(r.get("season_type", "Regular Season")),
            "player_team_id": tid,
            "player_team_name": t_name if t_name else None,
            "player_team_abbr": t_abbr if t_abbr else None,
            "opponent_team_id": opp_id,
            "opponent_team_name": opp_name if opp_name else None,
            "opponent_team_abbr": opp_abbr if opp_abbr else None,
            "home_away": str(r["home_away"]),
            "matchup": str(r["matchup"]) if pd.notna(r.get("matchup")) else None,
            "minutes": round(float(r["min_numeric"]), 1) if pd.notna(r.get("min_numeric")) else None,
            "participation_status": "PLAYED",
            "result": result,
            "team_score": team_score,
            "opponent_score": opponent_score,
            "fg3_pct": shooting_pct("fg3m", "fg3a"),
            "ft_pct": shooting_pct("ftm", "fta"),
            "fg_pct": shooting_pct("fgm", "fga"),
            "pts": to_int_or_none(r.get("pts")),
            "reb": to_int_or_none(r.get("reb")),
            "ast": to_int_or_none(r.get("ast")),
            "stl": to_int_or_none(r.get("stl")),
            "blk": to_int_or_none(r.get("blk")),
            "tov": to_int_or_none(r.get("tov")),
            "fg3m": to_int_or_none(r.get("fg3m")),
            "fgm": to_int_or_none(r.get("fgm")),
            "fga": to_int_or_none(r.get("fga")),
            "fg3a": to_int_or_none(r.get("fg3a")),
            "ftm": to_int_or_none(r.get("ftm")),
            "fta": to_int_or_none(r.get("fta")),
            "plus_minus": to_int_or_none(r.get("plus_minus")),
        }


# Convenience function for API endpoint
def get_player_history(
    player_id: int | str,
    opponent_team_id: Optional[int | str] = None,
    opponent_abbr: Optional[str] = None,
    target_game_id: Optional[str] = None,
    season_type: str = "Regular Season",
    limit: int = 10,
    parquet_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    service = PlayerHistoryService.get_instance(parquet_dir=parquet_dir)
    return service.get_player_history(
        player_id=player_id,
        opponent_team_id=opponent_team_id,
        opponent_abbr=opponent_abbr,
        target_game_id=target_game_id,
        season_type=season_type,
        limit=limit,
    )
