"""
Feature & Shrinkage Engine for NBA Player Props Prediction
Implements NBA_FEATURE_SHRINKAGE_SPEC.md v1.0 (§4 - §16)
"""

from dataclasses import dataclass, field
import logging
import math
from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# §5 V1 Default Parameters
@dataclass
class ShrinkageConfig:
    recipe_version: str = "v1.0"
    personal_count_window_appearances: int = 20
    personal_count_window_days: float = 365.0
    half_life_days: float = 20.0  # H_rate in calendar days (§5)
    personal_accuracy_window_appearances: int = 100
    personal_accuracy_window_days: float = 730.0
    half_life_shoot_days: float = 90.0  # H_shoot in calendar days (§5)
    beta_rate: float = 200.0  # beta_rate pseudo-exposure minutes (§5)
    kappa_shoot: float = 100.0  # kappa_shoot concentration attempts (§5)
    prior_pool_window_days: float = 730.0
    tau_group_minutes: float = 2000.0  # tau for group count rate pooling (§5)
    tau_shoot_attempts: float = 1000.0  # tau_shoot for group accuracy pooling (§5)
    league_count_coverage_min_minutes: float = 5000.0
    league_count_coverage_min_players: int = 30
    group_count_coverage_min_minutes: float = 1000.0
    group_count_coverage_min_players: int = 10
    league_shoot_coverage_min_attempts: float = 500.0
    group_shoot_coverage_min_attempts: float = 200.0
    prior_warmup_dates: int = 28
    prior_block_dates: int = 28

    def validate(self) -> None:
        if self.half_life_days is not None and self.half_life_days <= 0:
            raise ValueError(f"half_life_days must be > 0, got {self.half_life_days}")
        if self.half_life_shoot_days is not None and self.half_life_shoot_days <= 0:
            raise ValueError(f"half_life_shoot_days must be > 0, got {self.half_life_shoot_days}")
        if self.beta_rate <= 0:
            raise ValueError(f"beta_rate must be > 0, got {self.beta_rate}")
        if self.kappa_shoot <= 0:
            raise ValueError(f"kappa_shoot must be > 0, got {self.kappa_shoot}")
        if self.tau_group_minutes <= 0:
            raise ValueError(f"tau_group_minutes must be > 0, got {self.tau_group_minutes}")


# §6.1 Normalized Position Mapping
POSITION_MAPPING = {
    "PG": "guard", "SG": "guard", "G": "guard", "POINT GUARD": "guard", "SHOOTING GUARD": "guard",
    "SF": "wing", "F": "wing", "G-F": "wing", "F-G": "wing", "SMALL FORWARD": "wing",
    "PF": "big", "C": "big", "F-C": "big", "C-F": "big", "POWER FORWARD": "big", "CENTER": "big",
}

def map_position(raw_pos: Optional[str]) -> str:
    """Deterministic normalized position mapping following §6.1."""
    if not raw_pos or pd.isna(raw_pos):
        return "unknown"
    p = str(raw_pos).upper().strip()
    return POSITION_MAPPING.get(p, "unknown")


# §6.2 Rotation Role Context
@dataclass
class RoleContext:
    position: str  # 'guard', 'wing', 'big', 'unknown'
    rotation: str  # 'starter', 'bench', 'unknown'
    leaf_group: Tuple[str, str]  # (position, rotation)
    start_share: Optional[float] = None
    games_evaluated: int = 0


def assign_role(
    player_history: pd.DataFrame,
    current_team: Any,
    cutoff_time: pd.Timestamp,
    position_hint: Optional[str] = None,
) -> RoleContext:
    """
    Assigns role hierarchy (position, rotation) following §6.
    Evaluates up to 10 most recent appearances for current_team strictly prior to cutoff.
    """
    p = map_position(position_hint)

    if player_history.empty:
        return RoleContext(position=p, rotation="unknown", leaf_group=(p, "unknown"), start_share=None, games_evaluated=0)

    df = player_history.copy()
    if "game_end_dt" not in df.columns:
        if "game_date_dt" in df.columns:
            df["game_end_dt"] = df["game_date_dt"]
        elif "game_date" in df.columns:
            df["game_end_dt"] = pd.to_datetime(df["game_date"])

    mask = df["game_end_dt"] < cutoff_time
    if current_team is not None:
        if "team_id_at_game" in df.columns:
            mask = mask & (df["team_id_at_game"] == current_team)
        elif "team_abbreviation" in df.columns:
            mask = mask & (df["team_abbreviation"] == current_team)

    sub = df[mask].sort_values("game_end_dt").tail(10)

    if "started" in sub.columns:
        valid_starts = sub["started"].dropna()
        if len(valid_starts) >= 5:
            s_sum = float(valid_starts.astype(int).sum())
            s_share = s_sum / float(len(valid_starts))
            r = "starter" if s_share >= 0.5 else "bench"
            return RoleContext(position=p, rotation=r, leaf_group=(p, r), start_share=round(s_share, 4), games_evaluated=len(valid_starts))

    return RoleContext(position=p, rotation="unknown", leaf_group=(p, "unknown"), start_share=None, games_evaluated=len(sub))


# §7 Prior Snapshot & Hierarchical Leave-Player-Out Pooling
class PriorSnapshot:
    """
    Holds pool totals and allows fast leave-player-out empirical prior calculation (§7).
    """

    def __init__(self, config: ShrinkageConfig, origin_utc: pd.Timestamp):
        self.config = config
        self.origin_utc = origin_utc
        # Totals mapping: {group_key: {stat: [sum_X, sum_M, player_id_set]}}
        self.league_counts: Dict[str, Dict[str, Any]] = {}
        self.position_counts: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self.leaf_counts: Dict[Tuple[str, str], Dict[str, Dict[str, Any]]] = {}
        self.player_counts: Dict[int, Dict[str, List[float]]] = {}

        # Shooting totals: {group_key: {shot_type: [makes, attempts, player_id_set]}}
        self.league_shooting: Dict[str, Dict[str, Any]] = {}
        self.position_shooting: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self.leaf_shooting: Dict[Tuple[str, str], Dict[str, Dict[str, Any]]] = {}
        self.player_shooting: Dict[int, Dict[str, List[float]]] = {}

    def get_count_prior(
        self,
        player_id: int,
        position: str,
        rotation: str,
        stat: str,
    ) -> Tuple[float, float, float, str]:
        """
        Computes leave-player-out prior parameters (alpha_g, beta_g, prior_mean, fallback_level) (§7.2).
        """
        # 1. Player's historical totals to subtract
        p_sub = self.player_counts.get(player_id, {}).get(stat, [0.0, 0.0])
        p_x, p_m = p_sub[0], p_sub[1]

        # Helper to get subtracted pool totals
        def get_pool_data(pool_dict: Dict[str, Any]) -> Tuple[float, float, int]:
            if stat not in pool_dict:
                return 0.0, 0.0, 0
            d = pool_dict[stat]
            tot_x = d["x"] - p_x
            tot_m = d["m"] - p_m
            p_set = d["players"]
            n_players = len(p_set - {player_id})
            return max(0.0, tot_x), max(0.0, tot_m), n_players

        # A. League Level
        l_x, l_m, l_n = get_pool_data(self.league_counts)
        if l_m < self.config.league_count_coverage_min_minutes or l_n < self.config.league_count_coverage_min_players:
            return 0.0, 0.0, 0.0, "PRIOR_UNAVAILABLE"
        mu_league = l_x / l_m if l_m > 0 else 0.0

        # B. Position Level
        pos_dict = self.position_counts.get(position, {})
        pos_x, pos_m, pos_n = get_pool_data(pos_dict)
        if pos_m >= self.config.group_count_coverage_min_minutes and pos_n >= self.config.group_count_coverage_min_players:
            tau = self.config.tau_group_minutes
            mu_pos = (pos_x + tau * mu_league) / (pos_m + tau)
        else:
            mu_pos = mu_league

        # C. Leaf Level
        leaf_key = (position, rotation)
        leaf_dict = self.leaf_counts.get(leaf_key, {})
        leaf_x, leaf_m, leaf_n = get_pool_data(leaf_dict)

        if leaf_m >= self.config.group_count_coverage_min_minutes and leaf_n >= self.config.group_count_coverage_min_players:
            tau = self.config.tau_group_minutes
            mu_final = (leaf_x + tau * mu_pos) / (leaf_m + tau)
            fallback = "leaf"
        elif pos_m >= self.config.group_count_coverage_min_minutes and pos_n >= self.config.group_count_coverage_min_players:
            mu_final = mu_pos
            fallback = "position"
        else:
            mu_final = mu_league
            fallback = "league"

        beta = self.config.beta_rate
        alpha = beta * mu_final
        return alpha, beta, mu_final, fallback

    def get_shooting_prior(
        self,
        player_id: int,
        position: str,
        rotation: str,
        shot_type: str,
    ) -> Tuple[float, float, float, str]:
        """
        Computes leave-player-out accuracy prior (a_gj, b_gj, p_gj, fallback_level) (§9.1).
        """
        p_sub = self.player_shooting.get(player_id, {}).get(shot_type, [0.0, 0.0])
        p_makes, p_att = p_sub[0], p_sub[1]

        def get_shoot_data(pool_dict: Dict[str, Any]) -> Tuple[float, float, int]:
            if shot_type not in pool_dict:
                return 0.0, 0.0, 0
            d = pool_dict[shot_type]
            tot_makes = max(0.0, d["makes"] - p_makes)
            tot_att = max(0.0, d["attempts"] - p_att)
            n_players = len(d["players"] - {player_id})
            return tot_makes, tot_att, n_players

        l_makes, l_att, l_n = get_shoot_data(self.league_shooting)
        if l_att < self.config.league_shoot_coverage_min_attempts or l_n < 10:
            return 0.0, 0.0, 0.0, "PRIOR_UNAVAILABLE"
        p_league = l_makes / l_att if l_att > 0 else 0.35

        pos_dict = self.position_shooting.get(position, {})
        pos_makes, pos_att, pos_n = get_shoot_data(pos_dict)
        if pos_att >= self.config.group_shoot_coverage_min_attempts and pos_n >= self.config.group_count_coverage_min_players:
            tau = self.config.tau_shoot_attempts
            p_pos = (pos_makes + tau * p_league) / (pos_att + tau)
        else:
            p_pos = p_league

        leaf_key = (position, rotation)
        leaf_dict = self.leaf_shooting.get(leaf_key, {})
        leaf_makes, leaf_att, leaf_n = get_shoot_data(leaf_dict)

        if leaf_att >= self.config.group_shoot_coverage_min_attempts and leaf_n >= self.config.group_count_coverage_min_players:
            tau = self.config.tau_shoot_attempts
            p_final = (leaf_makes + tau * p_pos) / (leaf_att + tau)
            fallback = "leaf"
        elif pos_att >= self.config.group_shoot_coverage_min_attempts and pos_n >= self.config.group_count_coverage_min_players:
            p_final = p_pos
            fallback = "position"
        else:
            p_final = p_league
            fallback = "league"

        # Clip interior
        p_final = float(np.clip(p_final, 0.01, 0.99))
        kappa = self.config.kappa_shoot
        a = kappa * p_final
        b = kappa * (1.0 - p_final)
        return a, b, p_final, fallback


def fit_prior_snapshot(
    training_prefix: pd.DataFrame,
    origin_utc: pd.Timestamp,
    config: Optional[ShrinkageConfig] = None,
) -> PriorSnapshot:
    """
    Fits hierarchical empirical prior parameters from valid historical prefix (§7.1).
    Pools data available up to origin_utc and within prior_pool_window_days.
    """
    cfg = config or ShrinkageConfig()
    cfg.validate()
    snapshot = PriorSnapshot(cfg, origin_utc)

    if training_prefix.empty:
        return snapshot

    df = training_prefix.copy()
    if "game_end_dt" not in df.columns:
        if "game_date_dt" in df.columns:
            df["game_end_dt"] = df["game_date_dt"]
        elif "game_date" in df.columns:
            df["game_end_dt"] = pd.to_datetime(df["game_date"])

    # Strict temporal filter: game_end_dt < origin_utc and within 730 days
    min_date = origin_utc - pd.Timedelta(days=cfg.prior_pool_window_days)
    mask = (df["game_end_dt"] < origin_utc) & (df["game_end_dt"] >= min_date) & (df["min"] > 0)
    valid_df = df[mask]

    if valid_df.empty:
        return snapshot

    quantities = ["pts", "reb", "ast", "fga", "fta", "fg3a", "oreb", "dreb"]
    # Initialize counts containers
    for q in quantities:
        snapshot.league_counts[q] = {"x": 0.0, "m": 0.0, "players": set()}

    # Initialize shooting containers
    for s in ["2pt", "3pt", "ft", "3pa_share"]:
        snapshot.league_shooting[s] = {"makes": 0.0, "attempts": 0.0, "players": set()}

    for _, row in valid_df.iterrows():
        pid = int(row["player_id"])
        m_val = float(row["min"])
        if np.isnan(m_val) or m_val <= 0:
            continue

        p_pos = map_position(row.get("position_snapshot", row.get("position")))
        started_val = row.get("started")
        p_rot = "starter" if started_val in (1, True, "1") else ("bench" if started_val in (0, False, "0") else "unknown")
        leaf = (p_pos, p_rot)

        # Count quantities
        for q in quantities:
            if q in row and not pd.isna(row[q]):
                x_val = float(row[q])
                if x_val < 0 or np.isnan(x_val):
                    continue

                # 1. League
                snapshot.league_counts[q]["x"] += x_val
                snapshot.league_counts[q]["m"] += m_val
                snapshot.league_counts[q]["players"].add(pid)

                # 2. Position
                if p_pos not in snapshot.position_counts:
                    snapshot.position_counts[p_pos] = {}
                if q not in snapshot.position_counts[p_pos]:
                    snapshot.position_counts[p_pos][q] = {"x": 0.0, "m": 0.0, "players": set()}
                snapshot.position_counts[p_pos][q]["x"] += x_val
                snapshot.position_counts[p_pos][q]["m"] += m_val
                snapshot.position_counts[p_pos][q]["players"].add(pid)

                # 3. Leaf
                if leaf not in snapshot.leaf_counts:
                    snapshot.leaf_counts[leaf] = {}
                if q not in snapshot.leaf_counts[leaf]:
                    snapshot.leaf_counts[leaf][q] = {"x": 0.0, "m": 0.0, "players": set()}
                snapshot.leaf_counts[leaf][q]["x"] += x_val
                snapshot.leaf_counts[leaf][q]["m"] += m_val
                snapshot.leaf_counts[leaf][q]["players"].add(pid)

                # 4. Player
                if pid not in snapshot.player_counts:
                    snapshot.player_counts[pid] = {}
                if q not in snapshot.player_counts[pid]:
                    snapshot.player_counts[pid][q] = [0.0, 0.0]
                snapshot.player_counts[pid][q][0] += x_val
                snapshot.player_counts[pid][q][1] += m_val

        # Shooting accuracy & shares (§9)
        fga = float(row.get("fga", 0.0)) if not pd.isna(row.get("fga")) else 0.0
        fgm = float(row.get("fgm", 0.0)) if not pd.isna(row.get("fgm")) else 0.0
        fg3a = float(row.get("fg3a", 0.0)) if not pd.isna(row.get("fg3a")) else 0.0
        fg3m = float(row.get("fg3m", 0.0)) if not pd.isna(row.get("fg3m")) else 0.0
        fta = float(row.get("fta", 0.0)) if not pd.isna(row.get("fta")) else 0.0
        ftm = float(row.get("ftm", 0.0)) if not pd.isna(row.get("ftm")) else 0.0

        fg2a = max(0.0, fga - fg3a)
        fg2m = max(0.0, fgm - fg3m)

        shoot_tuples = [
            ("2pt", fg2m, fg2a),
            ("3pt", fg3m, fg3a),
            ("ft", ftm, fta),
            ("3pa_share", fg3a, fga),
        ]

        for s_type, makes, att in shoot_tuples:
            if att > 0 and makes >= 0:
                # League
                snapshot.league_shooting[s_type]["makes"] += makes
                snapshot.league_shooting[s_type]["attempts"] += att
                snapshot.league_shooting[s_type]["players"].add(pid)

                # Position
                if p_pos not in snapshot.position_shooting:
                    snapshot.position_shooting[p_pos] = {}
                if s_type not in snapshot.position_shooting[p_pos]:
                    snapshot.position_shooting[p_pos][s_type] = {"makes": 0.0, "attempts": 0.0, "players": set()}
                snapshot.position_shooting[p_pos][s_type]["makes"] += makes
                snapshot.position_shooting[p_pos][s_type]["attempts"] += att
                snapshot.position_shooting[p_pos][s_type]["players"].add(pid)

                # Leaf
                if leaf not in snapshot.leaf_shooting:
                    snapshot.leaf_shooting[leaf] = {}
                if s_type not in snapshot.leaf_shooting[leaf]:
                    snapshot.leaf_shooting[leaf][s_type] = {"makes": 0.0, "attempts": 0.0, "players": set()}
                snapshot.leaf_shooting[leaf][s_type]["makes"] += makes
                snapshot.leaf_shooting[leaf][s_type]["attempts"] += att
                snapshot.leaf_shooting[leaf][s_type]["players"].add(pid)

                # Player
                if pid not in snapshot.player_shooting:
                    snapshot.player_shooting[pid] = {}
                if s_type not in snapshot.player_shooting[pid]:
                    snapshot.player_shooting[pid][s_type] = [0.0, 0.0]
                snapshot.player_shooting[pid][s_type][0] += makes
                snapshot.player_shooting[pid][s_type][1] += att

    return snapshot


# §8 & §10 Personal Count Rate & Rolling Form Features
def compute_count_features(
    history_df: pd.DataFrame,
    target_rows: pd.DataFrame,
    prior_snapshot: PriorSnapshot,
    config: Optional[ShrinkageConfig] = None,
    quantities: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Computes rate shrinkage and rolling form features following §8 and §10.
    Preserves exact target rows order and attaches row_id.
    Optimized for high-throughput temporal cross-fitting.
    """
    cfg = config or prior_snapshot.config
    cfg.validate()
    if quantities is None:
        quantities = ["pts", "reb", "ast"]

    if target_rows.empty:
        return pd.DataFrame()

    # Input validation (§4)
    if not history_df.empty:
        for q in quantities:
            if q in history_df.columns:
                vals = history_df[q].dropna().to_numpy()
                if np.any(np.isinf(vals)):
                    raise ValueError(f"History contains non-finite values in {q}")
                if np.any(vals < 0):
                    raise ValueError(f"History contains negative values in {q}")
        if "min" in history_df.columns:
            m_vals = history_df["min"].dropna().to_numpy()
            if np.any(np.isinf(m_vals)):
                raise ValueError("History contains non-finite values in min")
            if np.any(m_vals < 0):
                raise ValueError("History contains negative values in min")

    # Fast cache building for history by player_id
    hist_cache: Dict[int, Dict[str, Any]] = {}
    if not history_df.empty:
        h = history_df.copy()
        if "game_end_dt" not in h.columns:
            if "game_date_dt" in h.columns:
                h["game_end_dt"] = h["game_date_dt"]
            elif "game_date" in h.columns:
                h["game_end_dt"] = pd.to_datetime(h["game_date"])
        
        team_col = "team_id_at_game" if "team_id_at_game" in h.columns else ("team_abbreviation" if "team_abbreviation" in h.columns else None)
        pos_col = "position_snapshot" if "position_snapshot" in h.columns else ("position" if "position" in h.columns else None)
        start_col = "started" if "started" in h.columns else None

        h = h.sort_values(["player_id", "game_end_dt"])
        for pid, grp in h.groupby("player_id", sort=False):
            pid_int = int(pid)
            hist_cache[pid_int] = {
                "dates": grp["game_end_dt"].to_numpy(dtype="datetime64[ns]"),
                "min": grp["min"].to_numpy(dtype=float) if "min" in grp.columns else np.zeros(len(grp), dtype=float),
                "teams": grp[team_col].to_numpy() if team_col else None,
                "positions": grp[pos_col].to_numpy() if pos_col else None,
                "started": grp[start_col].to_numpy() if start_col else None,
                "quantities": {q: grp[q].to_numpy(dtype=float) for q in quantities if q in grp.columns},
            }

    # Extract target row inputs
    target_df = target_rows.reset_index(drop=True)
    N = len(target_df)
    
    if "player_id" not in target_df.columns:
        raise ValueError("target_rows must contain 'player_id'")
    target_pids = target_df["player_id"].to_numpy()
    if np.any(pd.isna(target_pids)):
        raise ValueError("Target rows contain null player_id")
    target_pids = target_pids.astype(int)

    if "prediction_cutoff_utc" in target_df.columns:
        cutoff_series = target_df["prediction_cutoff_utc"]
    elif "game_date_dt" in target_df.columns:
        cutoff_series = target_df["game_date_dt"]
    elif "game_date" in target_df.columns:
        cutoff_series = target_df["game_date"]
    else:
        raise ValueError("target_rows must contain prediction cutoff date column")
    
    target_cutoffs = pd.to_datetime(cutoff_series)
    target_cutoffs_dt64 = target_cutoffs.to_numpy(dtype="datetime64[ns]")

    pos_target_col = "position_snapshot" if "position_snapshot" in target_df.columns else ("position" if "position" in target_df.columns else None)
    target_pos = target_df[pos_target_col].to_numpy() if pos_target_col else np.full(N, None, dtype=object)

    team_target_col = "team_id_at_game" if "team_id_at_game" in target_df.columns else ("team_abbreviation" if "team_abbreviation" in target_df.columns else None)
    target_teams = target_df[team_target_col].to_numpy() if team_target_col else np.full(N, None, dtype=object)

    day_ns = np.timedelta64(1, "D").astype("timedelta64[ns]")
    window_count_ns = np.timedelta64(int(cfg.personal_count_window_days), "D").astype("timedelta64[ns]")
    half_life = cfg.half_life_days
    max_count_apps = cfg.personal_count_window_appearances

    out_records = []

    for i in range(N):
        pid = target_pids[i]
        c_dt64 = target_cutoffs_dt64[i]
        c_dt = target_cutoffs.iloc[i]
        pos_hint = target_pos[i]
        p_team = target_teams[i]

        p_data = hist_cache.get(pid)

        # 1. Determine role context (§6)
        if p_data is not None:
            p_dates = p_data["dates"]
            end_idx = int(np.searchsorted(p_dates, c_dt64))
        else:
            p_dates = np.array([], dtype="datetime64[ns]")
            end_idx = 0

        # Position mapping
        p_pos = map_position(pos_hint)
        if p_pos == "unknown" and end_idx > 0 and p_data["positions"] is not None:
            # Fall back to latest known position in history
            sub_pos = p_data["positions"][:end_idx]
            for pos_val in reversed(sub_pos):
                if pos_val is not None and not pd.isna(pos_val):
                    p_pos = map_position(pos_val)
                    if p_pos != "unknown":
                        break

        # Rotation mapping via last 10 appearances of current team (§6.2)
        s_share = np.nan
        p_rot = "unknown"
        if end_idx > 0 and p_data["started"] is not None:
            sub_starts = p_data["started"][:end_idx]
            if p_team is not None and p_data["teams"] is not None:
                team_mask = (p_data["teams"][:end_idx] == p_team)
                sub_starts = sub_starts[team_mask]
            
            valid_starts = sub_starts[~np.isnan(sub_starts)]
            if len(valid_starts) >= 5:
                tail_starts = valid_starts[-10:]
                s_sum = float(np.sum(tail_starts.astype(int)))
                s_share = round(s_sum / float(len(tail_starts)), 4)
                p_rot = "starter" if s_share >= 0.5 else "bench"

        record: Dict[str, Any] = {
            "row_id": i,
            "player_id": pid,
            "prediction_cutoff_utc": c_dt,
            "role_position": p_pos,
            "role_rotation": p_rot,
            "start_share_prev10_current_team": s_share,
        }

        # 2. Filter personal history within window (§8)
        if end_idx > 0:
            start_dt64 = c_dt64 - window_count_ns
            start_idx = int(np.searchsorted(p_dates[:end_idx], start_dt64))

            sub_min = p_data["min"][start_idx:end_idx]
            min_mask = sub_min > 0
            
            # Indices matching min > 0
            valid_indices = np.where(min_mask)[0] + start_idx
            if len(valid_indices) > max_count_apps:
                valid_indices = valid_indices[-max_count_apps:]

            n_apps = len(valid_indices)
        else:
            valid_indices = np.array([], dtype=int)
            n_apps = 0

        record["nba_games_observed"] = n_apps

        # Inactivity decay & Return episode tracking (§6)
        if n_apps > 0:
            last_date64 = p_dates[valid_indices[-1]]
            days_since = max(0.0, float((c_dt64 - last_date64) / day_ns))
            long_abs = bool(days_since >= 14.0)
            record["days_since_last_appearance"] = round(days_since, 2)
            record["long_absence_flag"] = int(long_abs)

            # Return episode state machine (§6.1, §6.2)
            if long_abs:
                record["return_candidate"] = 1
                record["return_games_observed"] = 0
                record["return_episode_active"] = 1
            else:
                record["return_candidate"] = 0
                if len(valid_indices) >= 2:
                    v_dates = p_dates[valid_indices]
                    gaps = (v_dates[1:] - v_dates[:-1]) / day_ns
                    gap_idx = np.where(gaps >= 14.0)[0]
                    if len(gap_idx) > 0:
                        last_gap = gap_idx[-1]
                        apps_since = len(valid_indices) - (last_gap + 1)
                        record["return_games_observed"] = int(apps_since)
                        record["return_episode_active"] = int(apps_since < 3)
                    else:
                        record["return_games_observed"] = 0
                        record["return_episode_active"] = 0
                else:
                    record["return_games_observed"] = 0
                    record["return_episode_active"] = 0
        else:
            record["days_since_last_appearance"] = np.nan
            record["long_absence_flag"] = 0
            record["return_candidate"] = 0
            record["return_games_observed"] = 0
            record["return_episode_active"] = 0

        # Current team & Continuous Stint tracking (§7)
        if n_apps > 0 and p_team is not None and p_data["teams"] is not None:
            team_history = p_data["teams"][valid_indices]
            c_team_games = int(np.sum(team_history == p_team))
            record["games_current_team_observed"] = c_team_games

            # Calculate continuous current stint appearances
            stint_count = 0
            for t_val in reversed(team_history):
                if t_val == p_team:
                    stint_count += 1
                else:
                    break
            record["games_current_stint_observed"] = stint_count

            # Has player played for another NBA team prior to this stint?
            prior_teams = team_history[: len(team_history) - stint_count]
            team_changed = any(t != p_team and t is not None for t in prior_teams)
            record["team_change_observed"] = int(team_changed)
            record["recent_transfer_flag"] = int(team_changed and stint_count < 10)
            record["transfer_flag"] = record["recent_transfer_flag"]
        else:
            record["games_current_team_observed"] = n_apps if p_team is None else 0
            record["games_current_stint_observed"] = n_apps if p_team is None else 0
            record["team_change_observed"] = 0
            record["recent_transfer_flag"] = 0
            record["transfer_flag"] = 0

        # Minutes form summaries (§10)
        if n_apps > 0:
            m_arr = p_data["min"][valid_indices]
            record["minutes_mean_prev5"] = float(np.mean(m_arr[-5:])) if len(m_arr) >= 1 else np.nan
            record["minutes_mean_prev10"] = float(np.mean(m_arr[-10:])) if len(m_arr) >= 1 else np.nan
            record["minutes_mean_prev20"] = float(np.mean(m_arr[-20:])) if len(m_arr) >= 1 else np.nan
            record["minutes_std_prev10"] = float(np.std(m_arr[-10:], ddof=0)) if len(m_arr) >= 2 else np.nan

            if len(m_arr) >= 20:
                trend = float(record["minutes_mean_prev5"] - record["minutes_mean_prev20"])
                record["minutes_trend_5v20"] = trend
                record["role_shift_candidate"] = int(abs(trend) >= 5.0)
            else:
                record["minutes_trend_5v20"] = np.nan
                record["role_shift_candidate"] = 0

            # Weights: w_n = 2^(-age_days / H_rate) (§8)
            age_days_arr = np.maximum(0.0, (c_dt64 - p_dates[valid_indices]) / day_ns)
            if half_life:
                weights = np.power(2.0, -age_days_arr / half_life)
            else:
                weights = np.ones(n_apps, dtype=float)

            sum_w = float(np.sum(weights))
            sum_w_sq = float(np.sum(weights ** 2))
            neff = (sum_w ** 2) / sum_w_sq if sum_w_sq > 0 else 0.0
            exposure_w = float(np.sum(weights * m_arr))
            raw_min_sum = float(np.sum(m_arr))
        else:
            record["minutes_mean_prev5"] = np.nan
            record["minutes_mean_prev10"] = np.nan
            record["minutes_mean_prev20"] = np.nan
            record["minutes_std_prev10"] = np.nan
            record["minutes_trend_5v20"] = np.nan
            record["role_shift_candidate"] = 0
            weights = np.array([])
            neff = 0.0
            exposure_w = 0.0
            raw_min_sum = 0.0

        # Quantities (§8 & §10)
        for q in quantities:
            alpha_g, beta_g, mu_g, fallback_lvl = prior_snapshot.get_count_prior(
                player_id=pid,
                position=p_pos,
                rotation=p_rot,
                stat=q,
            )
            record[f"{q}_prior_mean"] = mu_g
            record[f"{q}_prior_strength_minutes"] = beta_g
            record[f"{q}_prior_fallback"] = fallback_lvl

            if n_apps > 0 and q in p_data["quantities"]:
                q_arr = p_data["quantities"][q][valid_indices]
                s_w = float(np.sum(weights * q_arr))
                record[f"{q}_mean_prev5"] = float(np.mean(q_arr[-5:])) if len(q_arr) >= 1 else np.nan
                record[f"{q}_mean_prev10"] = float(np.mean(q_arr[-10:])) if len(q_arr) >= 1 else np.nan
                record[f"{q}_mean_prev20"] = float(np.mean(q_arr[-20:])) if len(q_arr) >= 1 else np.nan
                record[f"{q}_std_prev10"] = float(np.std(q_arr[-10:], ddof=0)) if len(q_arr) >= 2 else np.nan
            else:
                s_w = 0.0
                record[f"{q}_mean_prev5"] = np.nan
                record[f"{q}_mean_prev10"] = np.nan
                record[f"{q}_mean_prev20"] = np.nan
                record[f"{q}_std_prev10"] = np.nan

            denom = beta_g + exposure_w
            if denom > 0:
                shrunk_rate = (alpha_g + s_w) / denom
                p_wt = exposure_w / denom
                prior_wt = beta_g / denom
            else:
                shrunk_rate = mu_g
                p_wt = 0.0
                prior_wt = 1.0

            record[f"{q}_rate_shrunk"] = float(shrunk_rate)
            record[f"{q}_weighted_count"] = float(s_w)
            record[f"{q}_exposure_minutes"] = float(exposure_w)
            record[f"{q}_n_eff_games"] = float(neff)
            record[f"{q}_history_games"] = int(n_apps)
            record[f"{q}_history_minutes"] = float(raw_min_sum)
            record[f"{q}_personal_weight"] = float(p_wt)
            record[f"{q}_prior_weight"] = float(prior_wt)

        out_records.append(record)

    return pd.DataFrame(out_records)


# §9 Shooting Features & Accuracy Smoothing
def compute_shooting_features(
    history_df: pd.DataFrame,
    target_rows: pd.DataFrame,
    prior_snapshot: PriorSnapshot,
    config: Optional[ShrinkageConfig] = None,
) -> pd.DataFrame:
    """
    Computes Beta-smoothed shooting accuracy (2PT, 3PT, FT) and 3PA share (§9).
    Optimized for high-throughput temporal cross-fitting.
    """
    cfg = config or prior_snapshot.config
    cfg.validate()

    if target_rows.empty:
        return pd.DataFrame()

    hist_cache: Dict[int, Dict[str, Any]] = {}
    if not history_df.empty:
        h = history_df.copy()
        if "game_end_dt" not in h.columns:
            if "game_date_dt" in h.columns:
                h["game_end_dt"] = h["game_date_dt"]
            elif "game_date" in h.columns:
                h["game_end_dt"] = pd.to_datetime(h["game_date"])

        team_col = "team_id_at_game" if "team_id_at_game" in h.columns else ("team_abbreviation" if "team_abbreviation" in h.columns else None)
        pos_col = "position_snapshot" if "position_snapshot" in h.columns else ("position" if "position" in h.columns else None)
        start_col = "started" if "started" in h.columns else None

        h = h.sort_values(["player_id", "game_end_dt"])
        for pid, grp in h.groupby("player_id", sort=False):
            pid_int = int(pid)
            hist_cache[pid_int] = {
                "dates": grp["game_end_dt"].to_numpy(dtype="datetime64[ns]"),
                "min": grp["min"].to_numpy(dtype=float) if "min" in grp.columns else np.zeros(len(grp), dtype=float),
                "teams": grp[team_col].to_numpy() if team_col else None,
                "positions": grp[pos_col].to_numpy() if pos_col else None,
                "started": grp[start_col].to_numpy() if start_col else None,
                "fga": grp["fga"].to_numpy(dtype=float) if "fga" in grp.columns else np.zeros(len(grp), dtype=float),
                "fgm": grp["fgm"].to_numpy(dtype=float) if "fgm" in grp.columns else np.zeros(len(grp), dtype=float),
                "fg3a": grp["fg3a"].to_numpy(dtype=float) if "fg3a" in grp.columns else np.zeros(len(grp), dtype=float),
                "fg3m": grp["fg3m"].to_numpy(dtype=float) if "fg3m" in grp.columns else np.zeros(len(grp), dtype=float),
                "fta": grp["fta"].to_numpy(dtype=float) if "fta" in grp.columns else np.zeros(len(grp), dtype=float),
                "ftm": grp["ftm"].to_numpy(dtype=float) if "ftm" in grp.columns else np.zeros(len(grp), dtype=float),
            }

    target_df = target_rows.reset_index(drop=True)
    N = len(target_df)

    target_pids = target_df["player_id"].astype(int).to_numpy()
    if "prediction_cutoff_utc" in target_df.columns:
        cutoff_series = target_df["prediction_cutoff_utc"]
    elif "game_date_dt" in target_df.columns:
        cutoff_series = target_df["game_date_dt"]
    elif "game_date" in target_df.columns:
        cutoff_series = target_df["game_date"]
    else:
        raise ValueError("target_rows must contain prediction cutoff date column")

    target_cutoffs = pd.to_datetime(cutoff_series)
    target_cutoffs_dt64 = target_cutoffs.to_numpy(dtype="datetime64[ns]")

    pos_target_col = "position_snapshot" if "position_snapshot" in target_df.columns else ("position" if "position" in target_df.columns else None)
    target_pos = target_df[pos_target_col].to_numpy() if pos_target_col else np.full(N, None, dtype=object)

    team_target_col = "team_id_at_game" if "team_id_at_game" in target_df.columns else ("team_abbreviation" if "team_abbreviation" in target_df.columns else None)
    target_teams = target_df[team_target_col].to_numpy() if team_target_col else np.full(N, None, dtype=object)

    day_ns = np.timedelta64(1, "D").astype("timedelta64[ns]")
    window_shoot_ns = np.timedelta64(int(cfg.personal_accuracy_window_days), "D").astype("timedelta64[ns]")
    hl_shoot = cfg.half_life_shoot_days
    max_shoot_apps = cfg.personal_accuracy_window_appearances

    out_records = []

    for i in range(N):
        pid = target_pids[i]
        c_dt64 = target_cutoffs_dt64[i]
        pos_hint = target_pos[i]
        p_team = target_teams[i]

        p_data = hist_cache.get(pid)

        # 1. Role context (§6)
        if p_data is not None:
            p_dates = p_data["dates"]
            end_idx = int(np.searchsorted(p_dates, c_dt64))
        else:
            p_dates = np.array([], dtype="datetime64[ns]")
            end_idx = 0

        p_pos = map_position(pos_hint)
        if p_pos == "unknown" and end_idx > 0 and p_data["positions"] is not None:
            sub_pos = p_data["positions"][:end_idx]
            for pos_val in reversed(sub_pos):
                if pos_val is not None and not pd.isna(pos_val):
                    p_pos = map_position(pos_val)
                    if p_pos != "unknown":
                        break

        p_rot = "unknown"
        if end_idx > 0 and p_data["started"] is not None:
            sub_starts = p_data["started"][:end_idx]
            if p_team is not None and p_data["teams"] is not None:
                team_mask = (p_data["teams"][:end_idx] == p_team)
                sub_starts = sub_starts[team_mask]
            valid_starts = sub_starts[~np.isnan(sub_starts)]
            if len(valid_starts) >= 5:
                tail_starts = valid_starts[-10:]
                s_sum = float(np.sum(tail_starts.astype(int)))
                s_share = s_sum / float(len(tail_starts))
                p_rot = "starter" if s_share >= 0.5 else "bench"

        record: Dict[str, Any] = {"row_id": i, "player_id": pid}

        # 2. Filter personal shooting history up to 100 appearances within 730 days (§5)
        if end_idx > 0:
            start_dt64 = c_dt64 - window_shoot_ns
            start_idx = int(np.searchsorted(p_dates[:end_idx], start_dt64))

            sub_min = p_data["min"][start_idx:end_idx]
            min_mask = sub_min > 0
            valid_indices = np.where(min_mask)[0] + start_idx
            if len(valid_indices) > max_shoot_apps:
                valid_indices = valid_indices[-max_shoot_apps:]
            n_shoot_apps = len(valid_indices)
        else:
            valid_indices = np.array([], dtype=int)
            n_shoot_apps = 0

        # Weights: v_n = 2^(-age_days / H_shoot) (§9.1)
        if n_shoot_apps > 0:
            age_days_arr = np.maximum(0.0, (c_dt64 - p_dates[valid_indices]) / day_ns)
            v_weights = np.power(2.0, -age_days_arr / hl_shoot)
            fga = p_data["fga"][valid_indices]
            fgm = p_data["fgm"][valid_indices]
            fg3a = p_data["fg3a"][valid_indices]
            fg3m = p_data["fg3m"][valid_indices]
            fta = p_data["fta"][valid_indices]
            ftm = p_data["ftm"][valid_indices]
            fg2a = np.maximum(0.0, fga - fg3a)
            fg2m = np.maximum(0.0, fgm - fg3m)
        else:
            v_weights = np.array([])
            fga = np.array([])
            fg3a = np.array([])
            fg2a = np.array([])
            fg2m = np.array([])
            fg3m = np.array([])
            fta = np.array([])
            ftm = np.array([])

        shot_map = {
            "2pt": (fg2m, fg2a),
            "3pt": (fg3m, fg3a),
            "ft": (ftm, fta),
        }

        for s_type, (made_arr, att_arr) in shot_map.items():
            a_gj, b_gj, p_gj, fallback = prior_snapshot.get_shooting_prior(
                player_id=pid,
                position=p_pos,
                rotation=p_rot,
                shot_type=s_type,
            )
            record[f"{s_type}_accuracy_prior_mean"] = p_gj

            if n_shoot_apps > 0:
                w_made = float(np.sum(v_weights * made_arr))
                w_att = float(np.sum(v_weights * att_arr))
            else:
                w_made = 0.0
                w_att = 0.0

            denom = a_gj + b_gj + w_att
            p_hat = (a_gj + w_made) / denom if denom > 0 else p_gj
            record[f"{s_type}_accuracy_shrunk"] = float(p_hat)
            record[f"{s_type}_attempts_weighted"] = float(w_att)

        # 3PA share (§9.2)
        _, _, p_3share_g, _ = prior_snapshot.get_shooting_prior(
            player_id=pid,
            position=p_pos,
            rotation=p_rot,
            shot_type="3pa_share",
        )
        if n_shoot_apps > 0:
            w_3pa = float(np.sum(v_weights * fg3a))
            w_fga = float(np.sum(v_weights * fga))
        else:
            w_3pa = 0.0
            w_fga = 0.0

        kappa = cfg.kappa_shoot
        share_3pa = (kappa * p_3share_g + w_3pa) / (kappa + w_fga) if (kappa + w_fga) > 0 else p_3share_g
        record["three_pa_share_shrunk"] = float(share_3pa)

        out_records.append(record)

    return pd.DataFrame(out_records)


# §13 Temporal Training Features Builder
def build_temporal_training_features(
    dataset_df: pd.DataFrame,
    config: Optional[ShrinkageConfig] = None,
    quantities: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Builds temporal features block by block (28 dates per block) following §13.1.
    Strictly avoids future leakage: each block uses prior fitted on prefix before block.
    """
    cfg = config or ShrinkageConfig()
    cfg.validate()
    if quantities is None:
        quantities = ["pts", "reb", "ast"]

    df = dataset_df.copy()
    if "game_date_dt" not in df.columns:
        df["game_date_dt"] = pd.to_datetime(df["game_date"])

    unique_dates = sorted(df["game_date_dt"].unique())
    warmup_n = min(cfg.prior_warmup_dates, len(unique_dates) // 4)

    # 1. Warmup dates: strictly anti-leakage prefix prior for each date (§13.1, Issue 28)
    warmup_dates = unique_dates[:warmup_n] if warmup_n > 0 else unique_dates[:1]

    # Iterate over 28-day blocks
    remaining_dates = unique_dates[warmup_n:]
    block_size = cfg.prior_block_dates
    all_blocks_out = []

    # Evaluate warmup rows: each date uses prior fitted strictly on data prior to that date
    if warmup_n > 0:
        for w_date in warmup_dates:
            target_w = df[df["game_date_dt"] == w_date]
            if target_w.empty:
                continue
            prefix_w = df[df["game_date_dt"] < w_date]
            w_snapshot = fit_prior_snapshot(prefix_w, origin_utc=w_date, config=cfg)
            w_counts = compute_count_features(df, target_w, w_snapshot, cfg, quantities=quantities)
            w_shoot = compute_shooting_features(df, target_w, w_snapshot, cfg)
            merged_w = pd.merge(
                target_w.reset_index(drop=True),
                w_counts.drop(columns=["row_id", "player_id", "prediction_cutoff_utc"], errors="ignore"),
                left_index=True,
                right_index=True,
            )
            merged_w = pd.merge(
                merged_w,
                w_shoot.drop(columns=["row_id", "player_id"], errors="ignore"),
                left_index=True,
                right_index=True,
            )
            all_blocks_out.append(merged_w)

    for i in range(0, len(remaining_dates), block_size):
        b_dates = remaining_dates[i : i + block_size]
        b_start_date = b_dates[0]
        b_end_date = b_dates[-1]

        # Prior fitted strictly on prefix before block start
        prefix_df = df[df["game_date_dt"] < b_start_date]
        b_snapshot = fit_prior_snapshot(prefix_df, origin_utc=b_start_date, config=cfg)

        target_block = df[(df["game_date_dt"] >= b_start_date) & (df["game_date_dt"] <= b_end_date)]
        b_counts = compute_count_features(df, target_block, b_snapshot, cfg, quantities=quantities)
        b_shoot = compute_shooting_features(df, target_block, b_snapshot, cfg)

        merged_b = pd.merge(target_block.reset_index(drop=True), b_counts.drop(columns=["row_id", "player_id", "prediction_cutoff_utc"], errors="ignore"), left_index=True, right_index=True)
        merged_b = pd.merge(merged_b, b_shoot.drop(columns=["row_id", "player_id"], errors="ignore"), left_index=True, right_index=True)
        all_blocks_out.append(merged_b)

    return pd.concat(all_blocks_out, ignore_index=True)


# §16 Legacy Backward Compatibility
DEFAULT_PRIORS = {
    "pts": {"alpha": 25.0, "beta": 50.0},
    "reb": {"alpha": 7.5, "beta": 50.0},
    "ast": {"alpha": 6.0, "beta": 50.0},
}

def compute_gamma_poisson_rate(
    df: pd.DataFrame,
    stat: str = "pts",
    alpha_prior: Optional[float] = None,
    beta_prior: Optional[float] = None,
    decay_halflife: Optional[float] = 10.0,
) -> pd.DataFrame:
    """
    [Legacy Baseline Wrapper for reproduction]
    Computes game-decay Gamma-Poisson shrinkage.
    """
    res = df.copy()
    if stat not in res.columns or "min" not in res.columns:
        return res

    priors = DEFAULT_PRIORS.get(stat, {"alpha": 10.0, "beta": 50.0})
    alpha = alpha_prior if alpha_prior is not None else priors["alpha"]
    beta = beta_prior if beta_prior is not None else priors["beta"]
    prior_mean = alpha / beta

    if "game_date" in res.columns:
        res["game_date_dt"] = pd.to_datetime(res["game_date"])
        res = res.sort_values(by=["player_id", "game_date_dt", "game_id"]).reset_index(drop=True)
    else:
        res = res.sort_values(by=["player_id", "game_id"]).reset_index(drop=True)

    rates = []
    n_effs = []
    exposures = []

    decay_factor = math.log(2.0) / decay_halflife if decay_halflife else 0.0
    grouped = res.groupby("player_id", sort=False)

    for _, group in grouped:
        x_vals = group[stat].to_numpy()
        m_vals = group["min"].to_numpy()
        n = len(group)

        for i in range(n):
            if i == 0:
                rates.append(prior_mean)
                n_effs.append(0.0)
                exposures.append(0.0)
                continue

            past_x = x_vals[:i]
            past_m = m_vals[:i]

            valid_mask = (~np.isnan(past_m)) & (past_m > 0) & (~np.isnan(past_x))
            if not np.any(valid_mask):
                rates.append(prior_mean)
                n_effs.append(0.0)
                exposures.append(0.0)
                continue

            valid_x = past_x[valid_mask]
            valid_m = past_m[valid_mask]
            k = len(valid_x)

            if decay_factor > 0:
                lags = k - 1 - np.arange(k)
                weights = np.exp(-decay_factor * lags)
            else:
                weights = np.ones(k, dtype=np.float64)

            sum_w = np.sum(weights)
            sum_w_sq = np.sum(weights ** 2)
            w_exposure = np.sum(weights * valid_m)
            w_x = np.sum(weights * valid_x)

            post_rate = (alpha + w_x) / (beta + w_exposure)
            neff = (sum_w ** 2) / sum_w_sq if sum_w_sq > 0 else 0.0

            rates.append(round(float(post_rate), 4))
            n_effs.append(round(float(neff), 2))
            exposures.append(round(float(w_exposure), 2))

    res[f"{stat}_rate_shrinkage"] = rates
    res[f"{stat}_n_eff"] = n_effs
    res[f"{stat}_exposure"] = exposures

    if "game_date_dt" in res.columns:
        res = res.drop(columns=["game_date_dt"])

    return res
