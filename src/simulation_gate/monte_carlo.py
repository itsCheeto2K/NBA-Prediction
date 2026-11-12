"""
Module: Monte Carlo Outer Study Simulation Runner (§7, §10, §11 of Review Spec)
Provides:
- Independent outer study path generation with stochastic pilot checkpoints (140, 280)
- Tracking of overall vs conditional ADOPT rates
- Unconditional vs conditional CI coverage
- Wilson 95% confidence interval computations across all metrics
"""

from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np

from src.simulation_gate.config import GateConfig
from src.simulation_gate.kernels import percentile_ci, wilson, final_decision
from src.simulation_gate.decision import evaluate_pilot_futility, evaluate_final_decision
from src.simulation_gate.dgp_score import BaseScoreDGP


class MonteCarloStudyRunner:
    """
    Executes Section 10 Full-Study Outer Monte Carlo Simulation:
    Each outer run simulates a full longitudinal study:
    - Pilot window: 280 scheduled game dates with futility checks at 140 and 280.
    - Confirmatory window: T scheduled game dates (default T=200).
    - Unconditional vs conditional denominator tracking (§7).
    """

    def __init__(self, config: Optional[GateConfig] = None):
        self.config = config or GateConfig()

    def run_scenario(
        self,
        dgp: BaseScoreDGP,
        template_counts: np.ndarray,
        theta: float,
        n_outer: int = 200,
        inner_reps: int = 199,
        b5_budget: int = 200,
        pilot_checkpoints: Optional[List[int]] = None,
        seed: int = 20261110,
    ) -> Dict[str, Any]:
        """Runs outer simulation under a specific DGP and true effect theta (§10, §11)."""
        counts = np.asarray(template_counts, dtype=np.float64)
        total_T = len(counts)
        checkpoints = pilot_checkpoints or self.config.pilot_checkpoints
        pilot_len = max(checkpoints) if checkpoints else 0
        conf_len = b5_budget

        if total_T < (pilot_len + conf_len):
            raise ValueError(
                f"Template counts length {total_T} must be >= pilot ({pilot_len}) + conf ({conf_len})"
            )

        rng = np.random.default_rng(seed)
        delta_margin = self.config.delta_margin

        # Tracking counters
        n_stop_140 = 0
        n_stop_280 = 0
        n_continued = 0
        n_adopt_overall = 0
        n_adopt_conditional = 0

        n_covered_unconditional = 0
        n_covered_conditional = 0

        ci_widths = []

        for out_idx in range(n_outer):
            out_seed = int(rng.integers(1, 1000000000))
            study_rng = np.random.default_rng(out_seed)

            # Generate synthetic daily sums for entire timeline
            sums = dgp.generate_scores(
                template_counts=counts,
                theta=theta,
                rng=study_rng,
            )

            stopped_early = False
            stop_reason = None

            # 1. Pilot futility check at 140
            if 140 in checkpoints:
                res_140 = evaluate_pilot_futility(
                    sums_prefix=sums[:140],
                    counts_prefix=counts[:140],
                    seasons_prefix=[1] * 140,
                    checkpoint=140,
                    reps=inner_reps,
                    margin=delta_margin,
                    seed=int(study_rng.integers(1, 100000000)),
                )
                if res_140["action"] == "STOP":
                    n_stop_140 += 1
                    stopped_early = True
                    stop_reason = "STOP_PILOT_FUTILITY_140"

            # 2. Pilot futility check at 280 (if continued past 140)
            if not stopped_early and 280 in checkpoints:
                res_280 = evaluate_pilot_futility(
                    sums_prefix=sums[:280],
                    counts_prefix=counts[:280],
                    seasons_prefix=[1] * 280,
                    checkpoint=280,
                    reps=inner_reps,
                    margin=delta_margin,
                    seed=int(study_rng.integers(1, 100000000)),
                )
                if res_280["action"] == "STOP":
                    n_stop_280 += 1
                    stopped_early = True
                    stop_reason = "STOP_PILOT_FUTILITY_280"

            # 3. Confirmatory B5 window (days from pilot_len to pilot_len + conf_len)
            b5_sums = sums[pilot_len : pilot_len + conf_len]
            b5_counts = counts[pilot_len : pilot_len + conf_len]

            (lower_conf, upper_conf), _ = percentile_ci(
                sums=b5_sums,
                counts=b5_counts,
                seasons=[1] * conf_len,
                reps=inner_reps,
                block_length=self.config.block_length_default,
                seed=int(study_rng.integers(1, 100000000)),
            )

            # Check coverage of true theta
            covers_truth = (lower_conf <= theta) and (theta <= upper_conf)
            if covers_truth:
                n_covered_unconditional += 1

            dec = final_decision(lower_conf, upper_conf, margin=delta_margin)
            ci_widths.append((upper_conf - lower_conf) / 2.0)

            # Record decision conditional on continuation
            if not stopped_early:
                n_continued += 1
                if covers_truth:
                    n_covered_conditional += 1
                if dec == "ADOPT":
                    n_adopt_overall += 1
                    n_adopt_conditional += 1

        # Summary proportions and Wilson score intervals
        p_adopt_overall = n_adopt_overall / n_outer
        wilson_adopt = wilson(n_adopt_overall, n_outer)

        p_cov_uncond = n_covered_unconditional / n_outer
        wilson_cov_uncond = wilson(n_covered_unconditional, n_outer)

        p_cov_cond = (n_covered_conditional / n_continued) if n_continued > 0 else 0.0
        wilson_cov_cond = wilson(n_covered_conditional, n_continued) if n_continued > 0 else (0.0, 0.0)

        p_adopt_cond = (n_adopt_conditional / n_continued) if n_continued > 0 else 0.0
        wilson_adopt_cond = wilson(n_adopt_conditional, n_continued) if n_continued > 0 else (0.0, 0.0)

        return {
            "theta_true": theta,
            "n_outer": n_outer,
            "inner_reps": inner_reps,
            "b5_budget": b5_budget,
            "p_adopt_overall": round(p_adopt_overall, 4),
            "wilson_adopt_overall": (round(wilson_adopt[0], 4), round(wilson_adopt[1], 4)),
            "p_adopt_conditional": round(p_adopt_cond, 4),
            "wilson_adopt_conditional": (round(wilson_adopt_cond[0], 4), round(wilson_adopt_cond[1], 4)),
            "unconditional_coverage": round(p_cov_uncond, 4),
            "wilson_unconditional_coverage": (round(wilson_cov_uncond[0], 4), round(wilson_cov_uncond[1], 4)),
            "conditional_coverage": round(p_cov_cond, 4),
            "wilson_conditional_coverage": (round(wilson_cov_cond[0], 4), round(wilson_cov_cond[1], 4)),
            "n_continued": n_continued,
            "n_stop_140": n_stop_140,
            "n_stop_280": n_stop_280,
            "p_stop_futility": round((n_stop_140 + n_stop_280) / n_outer, 4),
            "mean_ci_half_width": round(float(np.mean(ci_widths)), 6),
        }
