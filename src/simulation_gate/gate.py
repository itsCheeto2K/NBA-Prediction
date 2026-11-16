"""
Module: Simulation Gate Evaluator & Release Guards (§11, §13 of Review Spec)
Provides:
- Comprehensive multi-scenario gate evaluation across DGP1, DGP2, DGP3
- Size control check: Wilson upper <= 0.035 at theta=0 and theta=delta
- Unconditional coverage check: Wilson lower >= 0.93
- Overall power check: Wilson lower >= 0.80 at theta=0.002
- T-grid search for T_min_grid (§11.3)
- Export of formal Simulation Gate validation report
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np

from src.config import settings
from src.simulation_gate.config import GateConfig, GateStatus
from src.simulation_gate.monte_carlo import MonteCarloStudyRunner
from src.simulation_gate.dgp_score import DGP1ResidualMBB, DGP2VectorVAR, DGP3VarianceStress

logger = logging.getLogger(__name__)


class SimulationGate:
    """
    Coordinates Section 11 Simulation Gate Assessment:
    - Runs mandatory score-surrogate DGP scenarios (DGP1, DGP2, DGP3).
    - Verifies Wilson criteria across null (theta=0), boundary (theta=delta), and alt (theta=delta_alt).
    - Determines Gate status (SCORE_KERNEL_VALIDATED, GATE_UNVALIDATED, etc.).
    - Evaluates T-grid discovery for optimal future study duration.
    """

    def __init__(
        self,
        config: Optional[GateConfig] = None,
        reports_dir: Optional[Path] = None,
    ):
        self.config = config or GateConfig()
        self.reports_dir = reports_dir or (settings.BASE_DIR / "reports")
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.runner = MonteCarloStudyRunner(config=self.config)

    def evaluate_gate_scenario(
        self,
        scenario_name: str,
        dgp_instance: Any,
        template_counts: np.ndarray,
        theta_levels: Optional[List[float]] = None,
        n_outer: int = 50,
        inner_reps: int = 200,
        b5_budget: int = 200,
        is_smoke: bool = False,
    ) -> Dict[str, Any]:
        """Runs the three mandatory effect levels (null=0, boundary=0.001, alt=0.002) for a given DGP (§11.1)."""
        thetas = theta_levels or [0.0, self.config.delta_margin, self.config.delta_alt]
        results_by_theta = {}

        for th in thetas:
            logger.info(f"Running Gate Scenario '{scenario_name}' at theta={th}...")
            res = self.runner.run_scenario(
                dgp=dgp_instance,
                template_counts=template_counts,
                theta=th,
                n_outer=n_outer,
                inner_reps=inner_reps,
                b5_budget=b5_budget,
            )
            results_by_theta[str(th)] = res

        # Check acceptance criteria for this scenario across all three effect levels
        null_res = results_by_theta[str(0.0)]
        boundary_res = results_by_theta[str(self.config.delta_margin)]
        alt_res = results_by_theta[str(self.config.delta_alt)]

        if is_smoke:
            # Smoke criteria based on empirical point rates rather than small-sample Wilson intervals
            size_null_pass = null_res["p_adopt_overall"] <= self.config.smoke_size_upper_tol
            size_boundary_pass = boundary_res["p_adopt_overall"] <= self.config.smoke_size_upper_tol
            cov_null_pass = null_res["unconditional_coverage"] >= self.config.smoke_coverage_lower_tol
            cov_boundary_pass = boundary_res["unconditional_coverage"] >= self.config.smoke_coverage_lower_tol
            cov_alt_pass = alt_res["unconditional_coverage"] >= self.config.smoke_coverage_lower_tol
            power_pass = alt_res["p_adopt_overall"] >= self.config.smoke_power_lower_tol
        else:
            # Full Certification criteria using 95% Wilson score bounds (§11.1)
            # 1. Size control: Wilson upper <= 0.035 at theta=0 and theta=delta
            size_null_pass = null_res["wilson_adopt_overall"][1] <= self.config.wilson_size_upper_tol
            size_boundary_pass = boundary_res["wilson_adopt_overall"][1] <= self.config.wilson_size_upper_tol

            # 2. Unconditional coverage: Wilson lower >= 0.93 across all three thetas (including boundary)
            cov_null_pass = null_res["wilson_unconditional_coverage"][0] >= self.config.wilson_coverage_lower_tol
            cov_boundary_pass = boundary_res["wilson_unconditional_coverage"][0] >= self.config.wilson_coverage_lower_tol
            cov_alt_pass = alt_res["wilson_unconditional_coverage"][0] >= self.config.wilson_coverage_lower_tol

            # 3. Overall power: Wilson lower >= 0.80 at theta_alt=0.002
            power_pass = alt_res["wilson_adopt_overall"][0] >= self.config.wilson_power_lower_tol

        coverage_pass = cov_null_pass and cov_boundary_pass and cov_alt_pass
        scenario_passed = (
            size_null_pass and size_boundary_pass and coverage_pass and power_pass
        )

        return {
            "scenario_name": scenario_name,
            "passed": scenario_passed,
            "size_null_pass": size_null_pass,
            "size_boundary_pass": size_boundary_pass,
            "coverage_pass": coverage_pass,
            "cov_null_pass": cov_null_pass,
            "cov_boundary_pass": cov_boundary_pass,
            "cov_alt_pass": cov_alt_pass,
            "power_pass": power_pass,
            "results_by_theta": results_by_theta,
        }

    def run_comprehensive_suite(
        self,
        template_counts: np.ndarray,
        donor_residuals: np.ndarray,
        donor_seasons: List[Any],
        n_outer: int = 50,
        inner_reps: int = 200,
        b5_budget: int = 200,
        mode: str = "smoke",
    ) -> Dict[str, Any]:
        """
        Executes the comprehensive multi-scenario suite across DGP1, DGP2, DGP3 (§8, §11).
        """
        # 1. Instantiate DGPs
        dgp1 = DGP1ResidualMBB(
            donor_residuals=donor_residuals,
            donor_seasons=donor_seasons,
            block_length=self.config.block_length_default,
        )
        dgp2 = DGP2VectorVAR.fit_from_residuals(donor_residuals)
        dgp3 = DGP3VarianceStress(base_dgp2=dgp2, persistence_mult=1.05, omega_target_scale=1.5)

        scenarios = {
            "DGP1_Residual_MBB": dgp1,
            "DGP2_Vector_VAR": dgp2,
            "DGP3_Variance_Stress": dgp3,
        }

        all_scenario_results = {}
        all_passed = True

        is_smoke = (mode == "smoke")

        for name, dgp_inst in scenarios.items():
            sc_res = self.evaluate_gate_scenario(
                scenario_name=name,
                dgp_instance=dgp_inst,
                template_counts=template_counts,
                n_outer=n_outer,
                inner_reps=inner_reps,
                b5_budget=b5_budget,
                is_smoke=is_smoke,
            )
            all_scenario_results[name] = sc_res
            if not sc_res["passed"]:
                all_passed = False

        if mode == "smoke":
            # Smoke mode is for kernel correctness testing, not final production certification
            gate_status = (
                GateStatus.SMOKE_TEST_PASS.value
                if all_passed
                else GateStatus.GATE_UNVALIDATED.value
            )
        else:
            gate_status = (
                GateStatus.SCORE_KERNEL_VALIDATED.value
                if all_passed
                else GateStatus.GATE_UNVALIDATED.value
            )

        report = {
            "gate_status": gate_status,
            "mode": mode,
            "b5_budget": b5_budget,
            "n_outer": n_outer,
            "inner_reps": inner_reps,
            "all_scenarios_passed": all_passed,
            "scenarios": all_scenario_results,
            "tolerances": {
                "wilson_size_upper_tol": self.config.wilson_size_upper_tol,
                "wilson_coverage_lower_tol": self.config.wilson_coverage_lower_tol,
                "wilson_power_lower_tol": self.config.wilson_power_lower_tol,
            },
        }

        # Export formal report
        out_path = self.reports_dir / "simulation_gate_report.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        logger.info(f"Simulation Gate Report saved to {out_path}")

        return report
