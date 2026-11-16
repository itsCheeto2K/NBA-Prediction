"""
Module: Simulation Gate Configuration & Status Constants (§2, §11, §13 of Review Spec)
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List


class GateStatus(str, Enum):
    """Lifecycle statuses for Simulation Gate (§13)."""
    SPECIFIED = "SPECIFIED"
    IMPLEMENTED_UNVALIDATED = "IMPLEMENTED_UNVALIDATED"
    DATA_READY = "DATA_READY"
    PILOT_COMPLETE = "PILOT_COMPLETE"
    SUITE_RUNNING = "SUITE_RUNNING"
    SMOKE_TEST_PASS = "SMOKE_TEST_PASS"
    SCORE_KERNEL_VALIDATED = "SCORE_KERNEL_VALIDATED"
    ADAPTIVE_GATE_PASS = "ADAPTIVE_GATE_PASS"
    REGISTRATION_RELEASED = "REGISTRATION_RELEASED"

    # Blocker and failure statuses
    BLOCKED_DATA = "BLOCKED_DATA"
    BLOCKED_REPLAY = "BLOCKED_REPLAY"
    BLOCKED_PILOT = "BLOCKED_PILOT"
    BLOCKED_SMALL_PILOT = "BLOCKED_SMALL_PILOT"
    STOP_PILOT_FUTILITY = "STOP_PILOT_FUTILITY"
    TRUTH_UNCERTIFIED = "TRUTH_UNCERTIFIED"
    DGP_UNFIT = "DGP_UNFIT"
    GATE_UNVALIDATED = "GATE_UNVALIDATED"
    STOP_INFERENCE_FEASIBILITY = "STOP_INFERENCE_FEASIBILITY"
    STOP_FEASIBILITY = "STOP_FEASIBILITY"


@dataclass(frozen=True)
class GateConfig:
    """Immutable Simulation Gate parameters (§2, §11.1)."""
    delta_margin: float = 0.001       # delta = 0.001 (10 bps Brier gain)
    delta_alt: float = 0.002          # Delta_alt = 0.002 (20 bps Brier gain)
    block_length_default: int = 14   # l = 14 scheduled game dates
    final_bootstrap_reps: int = 10000 # Actual procedure bootstrap replications
    simulator_inner_reps: int = 1999  # Simulator inner bootstrap replications
    simulator_outer_reps: int = 2000  # Simulator outer synthetic study datasets
    smoke_inner_reps: int = 200       # Smoke testing inner replicates
    smoke_outer_reps: int = 20        # Smoke testing outer datasets
    formal_min_outer_reps: int = 250  # Formal certification minimum outer replications (Wilson <= 0.035, Issue 31)

    # Gate acceptance tolerances (Wilson 95% intervals) (§11.1)
    wilson_size_upper_tol: float = 0.035      # Upper 95% bound of P(ADOPT) at delta <= 0.035
    wilson_coverage_lower_tol: float = 0.93   # Lower 95% bound of coverage >= 0.93
    wilson_power_lower_tol: float = 0.80      # Lower 95% bound of overall power at Delta_alt >= 0.80

    # Smoke testing tolerances (evaluates empirical point rates on small runs without Wilson interval inflation)
    smoke_size_upper_tol: float = 0.10        # Empirical P(ADOPT) <= 0.10
    smoke_coverage_lower_tol: float = 0.85    # Empirical coverage >= 0.85
    smoke_power_lower_tol: float = 0.60       # Empirical power >= 0.60

    # Operational checkpoints and grid
    pilot_checkpoints: List[int] = field(default_factory=lambda: [140, 280])
    b5_default_budget: int = 200     # T = 200 scheduled game dates
    t_search_grid: List[int] = field(
        default_factory=lambda: [100, 140, 180, 200, 240, 280, 320, 400, 480, 560]
    )
    min_pairs_per_stat: int = 100     # Minimum eligible pairs per stat for valid look

    # Canonical random seeds
    procedure_seed: int = 20261109
    simulation_seed: int = 20261110
