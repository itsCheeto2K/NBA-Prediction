"""
Module: Decision & Futility State Machine (§6, §11.7.8 of Review Spec)
Provides:
- Pilot futility-only evaluation at 140/280 checkpoints (no early ADOPT)
- Final decision evaluation with practical equivalence and harm flags
"""

from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np

from src.simulation_gate.kernels import percentile_ci, final_decision


def evaluate_pilot_futility(
    sums_prefix: np.ndarray,
    counts_prefix: np.ndarray,
    seasons_prefix: Union[list, np.ndarray],
    checkpoint: int,
    reps: int = 1999,
    block_length: int = 14,
    margin: float = 0.001,
    min_pairs_per_stat: int = 100,
    seed: int = 20261109,
) -> Dict[str, Any]:
    """
    Evaluates pilot futility-only check at designated prefix checkpoints (§6, §11.7.8):
    Strict Rules:
    - Only allowed at registered checkpoints (140, 280).
    - Requires sum of counts >= 100 per stat; otherwise returns SKIP_INSUFFICIENT_DATA.
    - If U < delta: STOP_PILOT_FUTILITY.
    - Otherwise: CONTINUE (Never ADOPT early during pilot).
    """
    if checkpoint not in (140, 280):
        raise ValueError(f"Futility check only permitted at checkpoints [140, 280], got {checkpoint}")

    T = len(sums_prefix)
    if T != checkpoint:
        raise ValueError(f"Prefix length {T} does not match checkpoint {checkpoint}")

    total_counts = counts_prefix.sum(axis=0)
    if (total_counts < min_pairs_per_stat).any():
        return {
            "checkpoint": checkpoint,
            "status": "SKIP_INSUFFICIENT_PAIRS",
            "action": "CONTINUE",
            "ci_bounds": None,
            "reason": f"Stat observations {list(total_counts)} below minimum {min_pairs_per_stat}",
        }

    (lower, upper), estimates = percentile_ci(
        sums=sums_prefix,
        counts=counts_prefix,
        seasons=seasons_prefix,
        reps=reps,
        block_length=block_length,
        seed=seed,
    )

    if upper < margin:
        return {
            "checkpoint": checkpoint,
            "status": "STOP_PILOT_FUTILITY",
            "action": "STOP",
            "ci_bounds": (lower, upper),
            "reason": f"Upper CI bound {upper:.6f} < delta ({margin})",
        }

    return {
        "checkpoint": checkpoint,
        "status": "PILOT_CONTINUE",
        "action": "CONTINUE",
        "ci_bounds": (lower, upper),
        "reason": f"Upper CI bound {upper:.6f} >= delta ({margin}). Research continues.",
    }


def evaluate_final_decision(
    sums: np.ndarray,
    counts: np.ndarray,
    seasons: Union[list, np.ndarray],
    reps: int = 10000,
    block_length: int = 14,
    margin: float = 0.001,
    seed: int = 20261109,
) -> Dict[str, Any]:
    """
    Executes final hypothesis test on the confirmatory window T (§6, §12):
    - [L, U] percentile 95% CI
    - L > margin -> ADOPT
    - U < margin -> DO_NOT_ADOPT
    - Otherwise -> INCONCLUSIVE
    - Diagnostics: practical equivalence (-margin < L and U < margin), harm (U < 0).
    """
    (lower, upper), estimates = percentile_ci(
        sums=sums,
        counts=counts,
        seasons=seasons,
        reps=reps,
        block_length=block_length,
        seed=seed,
    )

    decision = final_decision(lower=lower, upper=upper, margin=margin)

    # Diagnostic annotations (§6)
    is_practical_equiv = (-margin < lower) and (upper < margin)
    is_harm = upper < 0.0
    half_width = (upper - lower) / 2.0

    return {
        "decision": decision,
        "ci_bounds": (lower, upper),
        "half_width": round(half_width, 6),
        "practical_equivalence": is_practical_equiv,
        "harm": is_harm,
        "point_estimate": round(float(np.mean(estimates)), 6),
    }
