import logging
from typing import Any, Dict, List, Optional
import numpy as np

logger = logging.getLogger(__name__)

def compute_conditional_line_probabilities(cdf: np.ndarray, line: float) -> Dict[str, float]:
    """
    Computes conditional probabilities q_O, q_U, q_P given player participates (A_i = 1)
    as defined in §12:
    q_O = 1 - F(floor(line))
    If integer: q_U = F(line - 1), q_P = F(line) - F(line - 1)
    If half-line: q_U = F(floor(line)), q_P = 0
    """
    is_integer = float(line).is_integer()
    k_floor = int(np.floor(line))

    # Helper to get CDF value safely
    def get_cdf(k: int) -> float:
        if k < 0:
            return 0.0
        if k >= len(cdf):
            return 1.0
        return float(cdf[k])

    if is_integer:
        f_floor = get_cdf(k_floor)
        f_prev = get_cdf(k_floor - 1)
        q_over = float(1.0 - f_floor)
        q_push = float(f_floor - f_prev)
        q_under = float(f_prev)
    else:
        f_floor = get_cdf(k_floor)
        q_over = float(1.0 - f_floor)
        q_push = 0.0
        q_under = float(f_floor)

    # Normalize to exact 1.0 sum
    tot = q_over + q_under + q_push
    if tot > 0:
        q_over /= tot
        q_under /= tot
        q_push /= tot

    return {
        "line": float(line),
        "q_over": round(float(q_over), 5),
        "q_under": round(float(q_under), 5),
        "q_push": round(float(q_push), 5),
    }

def compute_unconditional_settlement(
    conditional_probs: Dict[str, float],
    pi_participate: float,
) -> Dict[str, float]:
    """
    Computes unconditional settlement probabilities under standard DNP-void rules (§12):
    p_O = pi_i * q_O
    p_U = pi_i * q_U
    p_P = pi_i * q_P
    p_void = 1 - pi_i
    Guaranteed: p_O + p_U + p_P + p_void = 1.0.
    """
    pi = float(np.clip(pi_participate, 0.0, 1.0))
    q_o = conditional_probs["q_over"]
    q_u = conditional_probs["q_under"]
    q_p = conditional_probs["q_push"]

    p_over = pi * q_o
    p_under = pi * q_u
    p_push = pi * q_p
    p_void = 1.0 - pi

    return {
        "pi_participate": round(pi, 4),
        "p_over": round(p_over, 5),
        "p_under": round(p_under, 5),
        "p_push": round(p_push, 5),
        "p_void": round(p_void, 5),
        "settlement_rule": "Standard DNP Void (Player must play >= 1 second to settle action)",
    }

def evaluate_injury_readiness(
    player_status: str,
    n_games_history: int,
    days_since_last: int,
    is_stale_report: bool = False,
    has_minute_limit: bool = False,
) -> Dict[str, Any]:
    """
    Evaluates system readiness state (§14):
    - 'ready': All integrity checks pass, snapshot valid, model in support.
    - 'scenario_only': Questionable status, minute restrictions, or long absence return.
    - 'insufficient_data': Zero history or unresolvable player.
    """
    status_lower = player_status.lower().strip()

    if n_games_history < 3:
        return {
            "status": "INSUFFICIENT_DATA",
            "action": "Insufficient historical games to establish reliable baseline.",
            "support_level": "none",
        }

    if status_lower in ("out", "suspended"):
        return {
            "status": "OUT",
            "action": "Player is officially ruled OUT on the injury report.",
            "support_level": "ruled_out",
        }

    if is_stale_report:
        return {
            "status": "SCENARIO_ONLY",
            "action": "Injury report is stale (>6 hours old). Outputting scenario forecast.",
            "support_level": "stale_report",
        }

    if has_minute_limit:
        return {
            "status": "SCENARIO_ONLY",
            "action": "Player is on a reported minutes restriction. Outputting scenario forecast.",
            "support_level": "minute_restriction",
        }

    if status_lower in ("questionable", "doubtful", "day-to-day"):
        return {
            "status": "SCENARIO_ONLY",
            "action": f"Player listed as {player_status.upper()}. Participation uncertainty active.",
            "support_level": "game_time_decision",
        }

    if days_since_last >= 14:
        return {
            "status": "SCENARIO_ONLY",
            "action": f"Returning from long absence ({days_since_last} days). Rotation uncertainty active.",
            "support_level": "long_absence_return",
        }

    return {
        "status": "READY",
        "action": "Full calibrated conditional forecast ready.",
        "support_level": "full",
    }
