"""
Package: simulation_gate
Implements Section 11.7.6–11.7.8 of NBA_PLAYER_PROPS_PLAN.md & NBA_SIMULATION_GATE_IMPLEMENTATION_SPEC.md.
Provides finite-sample inference validation, moving-block bootstrap, Wilson bounds,
DGP score generators, futility checks, and simulation gate evaluation.
"""

from src.simulation_gate.config import GateConfig, GateStatus
from src.simulation_gate.kernels import (
    pooled_delta,
    season_mbb_indices,
    percentile_ci,
    wilson,
    final_decision,
)
from src.simulation_gate.variance import (
    calculate_omega_point,
    calculate_omega_uncertainty,
    calculate_t_req,
    calculate_pooled_rms,
)
from src.simulation_gate.decision import (
    evaluate_pilot_futility,
    evaluate_final_decision,
)
from src.simulation_gate.dgp_score import DGP1ResidualMBB, DGP2VectorVAR, DGP3VarianceStress
from src.simulation_gate.monte_carlo import MonteCarloStudyRunner
from src.simulation_gate.gate import SimulationGate

__all__ = [
    "GateConfig",
    "GateStatus",
    "pooled_delta",
    "season_mbb_indices",
    "percentile_ci",
    "wilson",
    "final_decision",
    "calculate_omega_point",
    "calculate_omega_uncertainty",
    "calculate_t_req",
    "calculate_pooled_rms",
    "evaluate_pilot_futility",
    "evaluate_final_decision",
    "DGP1ResidualMBB",
    "DGP2VectorVAR",
    "DGP3VarianceStress",
    "MonteCarloStudyRunner",
    "SimulationGate",
]
