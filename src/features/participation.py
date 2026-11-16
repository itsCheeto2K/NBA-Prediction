import logging
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Standardized injury status levels defined in §3.3
VALID_STATUSES = {
    "available",
    "probable",
    "questionable",
    "doubtful",
    "out",
    "day-to-day",
    "not_listed",
    "unknown",
}

# Empirical baseline participation rates from historical NBA distributions (§5.1)
DEFAULT_PARTICIPATION_PRIORS: Dict[str, float] = {
    "available": 0.99,
    "probable": 0.93,
    "day-to-day": 0.65,
    "questionable": 0.54,
    "doubtful": 0.12,
    "out": 0.00,
    "not_listed": 0.99,
    "unknown": 0.50,
}

def normalize_injury_status(raw_status: Optional[str]) -> str:
    """Normalize raw injury report string into standard status category.
    
    Guarantees idempotence: normalize_injury_status(normalize_injury_status(s)) == normalize_injury_status(s).
    Treats HEALTHY, not_listed, active, and empty as 'available' (p=0.99).
    """
    if not raw_status:
        return "available"
    s = str(raw_status).lower().strip()
    if s in ("available", "probable", "questionable", "doubtful", "out", "day-to-day", "unknown"):
        return s
    if s in ("not_listed", "not listed", "none", "clear", "healthy") or "health" in s or "avail" in s or "active" in s:
        return "available"
    if "out" in s or "suspended" in s:
        return "out"
    if "doubt" in s:
        return "doubtful"
    if "quest" in s:
        return "questionable"
    if "day-to-day" in s or "gtd" in s or "d2d" in s:
        return "day-to-day"
    if "prob" in s:
        return "probable"
    return "unknown"

class ParticipationModel:
    """
    Estimates probability of entering the game pi = P(A_i = 1 | C)
    following NBA_INJURY_MODEL_SUPPLEMENT_PLAN.md §5.
    """

    def __init__(self, kappa: float = 20.0, global_prior: float = 0.85):
        self.kappa = kappa
        self.global_prior = global_prior
        self.status_rates: Dict[str, float] = dict(DEFAULT_PARTICIPATION_PRIORS)

    def fit_baseline_pooling(self, df_history: pd.DataFrame) -> None:
        """
        Fit Beta-Bernoulli baseline per status category on historical participation labels (§5.1).
        pi_hat_h = (a_h + sum(A_n * 1{h_n=h})) / (a_h + b_h + sum(1{h_n=h}))
        """
        if df_history.empty or "status" not in df_history.columns or "played" not in df_history.columns:
            return

        a_h = self.kappa * self.global_prior
        b_h = self.kappa * (1.0 - self.global_prior)

        for status in VALID_STATUSES:
            sub = df_history[df_history["status"] == status]
            n_obs = len(sub)
            if n_obs > 0:
                n_played = sub["played"].sum()
                rate = (a_h + n_played) / (a_h + b_h + n_obs)
                self.status_rates[status] = float(np.clip(rate, 0.0, 1.0))

    def predict_p_play(
        self,
        status: Optional[str],
        baseline_min: float = 30.0,
        days_rest: int = 1,
        is_b2b: bool = False,
    ) -> float:
        """
        Predict participation probability pi_i in [0.0, 1.0].
        Adjusts baseline status rate with role depth and schedule context.
        """
        norm_status = normalize_injury_status(status)
        base_rate = self.status_rates.get(norm_status, 0.50)

        # Out is zero participation
        if norm_status == "out":
            return 0.0

        # Adjust for rotational role (end-of-bench players have lower participation)
        role_mult = 1.0
        if norm_status in ("not_listed", "available"):
            if baseline_min >= 25.0:
                role_mult = 1.0
            elif baseline_min < 12.0:
                role_mult = 0.90

        # B2B fatigue penalty for questionable/day-to-day players
        sched_penalty = 0.0
        if is_b2b and norm_status in ("questionable", "day-to-day"):
            sched_penalty = 0.08

        final_prob = float(np.clip(base_rate * role_mult - sched_penalty, 0.01, 0.999))
        return round(final_prob, 4)

    # Alias for API compatibility
    predict_p_active = predict_p_play

def calculate_roster_participation(
    roster_players: List[Dict[str, Any]],
    participation_model: Optional[ParticipationModel] = None,
) -> Dict[str, float]:
    """
    Computes participation probability pi_j for every player on a roster.
    Returns mapping {player_name_or_id: pi}.
    """
    model = participation_model or ParticipationModel()
    results: Dict[str, float] = {}

    for p in roster_players:
        pid = str(p.get("player_id", p.get("player_name", "")))
        status = p.get("status", "not_listed")
        b_min = float(p.get("baseline_minutes", 20.0))
        is_b2b = bool(p.get("is_b2b", False))
        pi = model.predict_p_play(status=status, baseline_min=b_min, is_b2b=is_b2b)
        results[pid] = pi

    return results
