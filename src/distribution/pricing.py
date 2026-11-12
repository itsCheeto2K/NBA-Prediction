import math
from typing import Any, Dict, Optional

def american_to_decimal(american_odds: int | float) -> float:
    """
    Convert American odds to decimal odds (§9.1):
    - For a > 0: d = 1 + a / 100
    - For a < 0: d = 1 + 100 / |a|
    - Standard American odds must satisfy |a| >= 100. a = 0 or |a| < 100 is invalid.
    """
    try:
        a = float(american_odds)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid American odds: {american_odds}. Must be numeric.")

    if math.isnan(a) or math.isinf(a):
        raise ValueError("American odds must be finite.")

    if abs(a) < 100:
        raise ValueError(f"Invalid American odds: {a}. Must satisfy |odds| >= 100.")

    if a > 0:
        d = 1.0 + (a / 100.0)
    else:
        d = 1.0 + (100.0 / abs(a))

    if d <= 1.0 or not math.isfinite(d):
        raise ValueError(f"Resulting decimal odds {d} is not valid (> 1.0).")

    return round(float(d), 6)


def decimal_to_american(decimal_odds: float) -> int:
    """
    Convert decimal odds to American odds integer (§9.1).
    - d >= 2.0: round((d - 1) * 100)
    - 1.0 < d < 2.0: round(-100 / (d - 1))
    """
    if decimal_odds <= 1.0 or not math.isfinite(decimal_odds):
        raise ValueError(f"Decimal odds must be finite and > 1.0, got: {decimal_odds}")

    if decimal_odds >= 2.0:
        return int(round((decimal_odds - 1.0) * 100.0))
    else:
        return int(round(-100.0 / (decimal_odds - 1.0)))


def remove_vig_multiplicative(
    odds_over: float,
    odds_under: float,
    line_over: Optional[float] = None,
    line_under: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Remove sportsbook vigorish using standard multiplicative normalization (§9.1, §12.3):
    u_O = 1 / d_O, u_U = 1 / d_U
    fair_O = u_O / (u_O + u_U), fair_U = u_U / (u_O + u_U)
    
    Validates matching lines/market quotes.
    """
    if line_over is not None and line_under is not None and line_over != line_under:
        raise ValueError(
            f"Mismatched lines for de-vig: line_over={line_over} != line_under={line_under}. "
            "Both sides must match the same market line."
        )

    if odds_over <= 1.0 or odds_under <= 1.0:
        return {
            "fair_over": 0.5,
            "fair_under": 0.5,
            "overround": 0.0,
            "is_underround": False,
        }

    u_over = 1.0 / odds_over
    u_under = 1.0 / odds_under
    total_implied = u_over + u_under

    fair_over = u_over / total_implied
    fair_under = u_under / total_implied
    overround = total_implied - 1.0
    is_underround = total_implied < 1.0

    return {
        "fair_over": round(fair_over, 4),
        "fair_under": round(fair_under, 4),
        "overround": round(overround, 4),
        "is_underround": is_underround,
    }


def calculate_ev(
    prob_win: float,
    prob_loss: float,
    decimal_odds: float,
    stake: float = 1.0,
) -> float:
    """
    Calculate Model-Implied Expected Value (EV) per unit stake (§9.2):
    EV = prob_win * (decimal_odds - 1) * stake - prob_loss * stake
    (Assuming push/void returns full stake: prob_push * 0 = 0)
    """
    profit_if_win = (decimal_odds - 1.0) * stake
    loss_if_loss = stake
    ev = (prob_win * profit_if_win) - (prob_loss * loss_if_loss)
    return round(float(ev), 4)


def calculate_break_even_prob(decimal_odds: float) -> float:
    """Calculate break-even win rate required for decimal odds."""
    if decimal_odds <= 1.0:
        return 1.0
    return round(1.0 / decimal_odds, 4)


def calculate_kelly_fraction(
    prob_win: float,
    prob_loss: float,
    decimal_odds: float,
    allow_recommendation: bool = False,
) -> Dict[str, Any]:
    """
    Calculate Kelly criterion fraction with push/void refund (§9.3):
    
    Return win b = d - 1, loss -1, refund 0.
    r = p_win / (p_win + p_loss)
    f* = (d * r - 1) / (d - 1)
    
    Production safety guard (§9.3):
    - By default, allow_recommendation is False.
    - Staking recommendations are hidden: kelly_recommendation = None.
    - reason = "STAKING_POLICY_UNVALIDATED"
    - Mathematical unconstrained f* is provided in 'math_optimal_f' for diagnostic purposes only.
    """
    if decimal_odds <= 1.0 or not math.isfinite(decimal_odds):
        return {
            "kelly_recommendation": None,
            "math_optimal_f": 0.0,
            "reason": "INVALID_ODDS",
            "is_validated": False,
        }

    denom = prob_win + prob_loss
    if denom <= 0.0 or not math.isfinite(denom):
        return {
            "kelly_recommendation": None,
            "math_optimal_f": 0.0,
            "reason": "ZERO_NON_REFUND_PROBABILITY",
            "is_validated": False,
        }

    r = prob_win / denom
    b = decimal_odds - 1.0
    # f* = (b * p_win - p_loss) / (b * (p_win + p_loss)) = (decimal_odds * r - 1.0) / (decimal_odds - 1.0)
    f_star = (decimal_odds * r - 1.0) / b

    # Mathematical optimal f can be negative (no edge)
    math_f = round(float(f_star), 4)

    if not allow_recommendation:
        return {
            "kelly_recommendation": None,
            "math_optimal_f": math_f,
            "reason": "STAKING_POLICY_UNVALIDATED",
            "is_validated": False,
        }

    # If policy is validated, recommendation is bounded in [0, 1]
    recommendation = max(0.0, min(1.0, math_f)) if math_f > 0 else 0.0
    return {
        "kelly_recommendation": recommendation,
        "math_optimal_f": math_f,
        "reason": "VALIDATED_POLICY",
        "is_validated": True,
    }
