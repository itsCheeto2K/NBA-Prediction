"""
Unit tests for Missing-Role P0 & Minutes Allocator P1
Specification: NBA_MISSING_ROLE_ALLOCATOR_FIX_SPEC.md
Validates:
- Top2 ranking according to ell_j = (1 - pi_j)*b_j with deterministic tie-breaks (§4.2)
- Delta L_iq calculation with minimum 5 snapshots (§4.3)
- Allocator exact numerical match with §7.2 8-player example
- Overtime budgets OT0 (240), OT1 (265), OT2 (290)
- Infeasibility detection when sum(u) < B
- Roster ordering invariance
- Support screen triggering TEAM_CONTEXT_SUPPORT_UNVALIDATED
"""

import numpy as np
import pytest

from src.features.injury_roles import (
    compute_missing_role_features,
    compute_delta_missing_role_features,
    evaluate_injury_context_support,
)
from src.distribution.minutes_allocator import (
    allocate_team_minutes,
    PlayerAllocationInput,
    AllocationResult,
)


def test_top2_expected_lost_minutes_ranking():
    """
    Validates §4.2:
    b = (32, 30, 20), pi = (0.7, 0.8, 0.85) -> ell = (9.6, 6.0, 3.0)
    L_minutes = 18.6, L_top2 = 15.6.
    Target player excluded from teammate sum.
    """
    roster_profiles = [
        {"player_id": 999, "player_name": "Target Player", "baseline_minutes": 35.0, "volumes": {}},
        {"player_id": 101, "player_name": "Teammate A", "baseline_minutes": 32.0, "volumes": {}},
        {"player_id": 102, "player_name": "Teammate B", "baseline_minutes": 30.0, "volumes": {}},
        {"player_id": 103, "player_name": "Teammate C", "baseline_minutes": 20.0, "volumes": {}},
    ]
    participation_probs = {
        "101": 0.70,   # ell = (1 - 0.70) * 32.0 = 9.6
        "102": 0.80,   # ell = (1 - 0.80) * 30.0 = 6.0
        "103": 0.85,   # ell = (1 - 0.85) * 20.0 = 3.0
    }

    features = compute_missing_role_features(
        target_player_id=999,
        team_roster_profiles=roster_profiles,
        participation_probs=participation_probs,
    )

    # L_minutes = 9.6 + 6.0 + 3.0 = 18.6
    assert features["teammate_missing_minutes"] == pytest.approx(18.6, 0.01)
    # L_top2 = 9.6 + 6.0 = 15.6
    assert features["teammate_top2_lost_minutes"] == pytest.approx(15.6, 0.01)
    assert features["teammate_missing_min_norm"] == pytest.approx(18.6 / 240.0, 1e-4)


def test_top2_deterministic_tie_breaking():
    """Validates deterministic tie-breaking by player_id string when ell_j values are identical."""
    roster_profiles = [
        {"player_id": 999, "baseline_minutes": 30.0, "volumes": {}},
        {"player_id": 201, "baseline_minutes": 20.0, "volumes": {}},  # ell = 10.0
        {"player_id": 202, "baseline_minutes": 20.0, "volumes": {}},  # ell = 10.0
        {"player_id": 203, "baseline_minutes": 20.0, "volumes": {}},  # ell = 10.0
    ]
    participation_probs = {"201": 0.50, "202": 0.50, "203": 0.50}

    features = compute_missing_role_features(
        target_player_id=999,
        team_roster_profiles=roster_profiles,
        participation_probs=participation_probs,
    )
    # L_top2 = 10.0 + 10.0 = 20.0
    assert features["teammate_top2_lost_minutes"] == pytest.approx(20.0, 0.01)


def test_delta_missing_role_features():
    """Validates §4.3: Delta L_iq requires >= 5 historical snapshots."""
    current_feat = {
        "teammate_missing_minutes": 25.0,
        "teammate_missing_pts": 15.0,
    }

    # Case 1: 3 snapshots (< 5) -> returns NaN
    past_3 = [{"teammate_missing_minutes": 10.0, "teammate_missing_pts": 6.0}] * 3
    res_3 = compute_delta_missing_role_features(current_feat, past_3, min_snapshots_required=5)
    assert res_3["delta_history_count"] == 3
    assert res_3["delta_context_ready"] is False
    assert np.isnan(res_3["teammate_missing_minutes_delta"])

    # Case 2: 5 snapshots (avg = 10.0) -> delta = 25.0 - 10.0 = 15.0
    past_5 = [{"teammate_missing_minutes": 10.0, "teammate_missing_pts": 6.0}] * 5
    res_5 = compute_delta_missing_role_features(current_feat, past_5, min_snapshots_required=5)
    assert res_5["delta_history_count"] == 5
    assert res_5["delta_context_ready"] is True
    assert res_5["teammate_missing_minutes_historical_mean"] == pytest.approx(10.0, 0.01)
    assert res_5["teammate_missing_minutes_delta"] == pytest.approx(15.0, 0.01)


def test_allocator_section_7_2_exact_8_player_match():
    """
    Validates §7.2 exact numerical match:
    8 players, m_base = (35, 35, 30, 30, 25, 20, 15, 10), all v_i = 1, upper 48, B = 240.
    Sum baseline = 200, deficit = 40 -> each receives +5.
    Solution: (40, 40, 35, 35, 30, 25, 20, 15).
    """
    baselines = [35.0, 35.0, 30.0, 30.0, 25.0, 20.0, 15.0, 10.0]
    roster = [
        PlayerAllocationInput(player_id=f"p_{idx}", baseline_minutes=m, is_eligible=True, variance_scale=1.0)
        for idx, m in enumerate(baselines)
    ]

    res = allocate_team_minutes(roster, overtime_periods=0)
    assert res.status == "SUCCESS"
    assert res.budget_minutes == 240.0
    assert res.total_allocated == pytest.approx(240.0, 1e-4)

    expected = [40.0, 40.0, 35.0, 35.0, 30.0, 25.0, 20.0, 15.0]
    for idx, exp_val in enumerate(expected):
        pid = f"p_{idx}"
        assert res.allocated_minutes[pid] == pytest.approx(exp_val, 1e-4)


def test_allocator_overtime_budgets():
    """Validates OT0 (240), OT1 (265), OT2 (290) budgets and max durations (§7.2, §13.1)."""
    roster = [
        PlayerAllocationInput(player_id=f"p_{i}", baseline_minutes=25.0, is_eligible=True)
        for i in range(10)
    ]

    # OT 0: T = 48, B = 240
    res_ot0 = allocate_team_minutes(roster, overtime_periods=0)
    assert res_ot0.budget_minutes == 240.0
    assert res_ot0.player_max_duration == 48.0
    assert res_ot0.total_allocated == pytest.approx(240.0, 1e-4)

    # OT 1: T = 53, B = 265
    res_ot1 = allocate_team_minutes(roster, overtime_periods=1)
    assert res_ot1.budget_minutes == 265.0
    assert res_ot1.player_max_duration == 53.0
    assert res_ot1.total_allocated == pytest.approx(265.0, 1e-4)

    # OT 2: T = 58, B = 290
    res_ot2 = allocate_team_minutes(roster, overtime_periods=2)
    assert res_ot2.budget_minutes == 290.0
    assert res_ot2.player_max_duration == 58.0
    assert res_ot2.total_allocated == pytest.approx(290.0, 1e-4)


def test_allocator_infeasible_capacity_deficit():
    """
    Validates §7.1:
    When sum(u) < B, solver returns INFEASIBLE_SCENARIO and does not relax caps.
    """
    # 8 players all capped at 25 minutes -> sum(u) = 200 < 240
    roster = [
        PlayerAllocationInput(player_id=f"p_{i}", baseline_minutes=20.0, is_eligible=True, hard_cap=25.0)
        for i in range(8)
    ]

    res = allocate_team_minutes(roster, overtime_periods=0)
    assert res.status == "INFEASIBLE_SCENARIO"
    assert res.allocated_minutes is None
    assert res.diagnostics["deficit"] == pytest.approx(40.0, 0.01)


def test_allocator_roster_ordering_invariance():
    """Validates that reordering roster items does not alter per-player allocated minutes (§13.1)."""
    roster_a = [
        PlayerAllocationInput(player_id="star_1", baseline_minutes=36.0, is_eligible=True),
        PlayerAllocationInput(player_id="bench_1", baseline_minutes=12.0, is_eligible=True),
        PlayerAllocationInput(player_id="star_2", baseline_minutes=34.0, is_eligible=True),
        PlayerAllocationInput(player_id="bench_2", baseline_minutes=14.0, is_eligible=True),
        PlayerAllocationInput(player_id="starter_3", baseline_minutes=28.0, is_eligible=True),
        PlayerAllocationInput(player_id="starter_4", baseline_minutes=26.0, is_eligible=True),
        PlayerAllocationInput(player_id="starter_5", baseline_minutes=24.0, is_eligible=True),
        PlayerAllocationInput(player_id="bench_3", baseline_minutes=10.0, is_eligible=True),
    ]
    # Reverse order
    roster_b = list(reversed(roster_a))

    res_a = allocate_team_minutes(roster_a, overtime_periods=0)
    res_b = allocate_team_minutes(roster_b, overtime_periods=0)

    for pid in res_a.allocated_minutes:
        assert res_a.allocated_minutes[pid] == pytest.approx(res_b.allocated_minutes[pid], 1e-4)


def test_allocator_ineligible_player_gets_zero():
    """Validates that ineligible players (E_i = 0) strictly receive 0.0 minutes (§6.1)."""
    roster = [
        PlayerAllocationInput(player_id="out_player", baseline_minutes=35.0, is_eligible=False),
        PlayerAllocationInput(player_id="p_1", baseline_minutes=35.0, is_eligible=True),
        PlayerAllocationInput(player_id="p_2", baseline_minutes=35.0, is_eligible=True),
        PlayerAllocationInput(player_id="p_3", baseline_minutes=35.0, is_eligible=True),
        PlayerAllocationInput(player_id="p_4", baseline_minutes=35.0, is_eligible=True),
        PlayerAllocationInput(player_id="p_5", baseline_minutes=35.0, is_eligible=True),
        PlayerAllocationInput(player_id="p_6", baseline_minutes=35.0, is_eligible=True),
        PlayerAllocationInput(player_id="p_7", baseline_minutes=30.0, is_eligible=True),
    ]

    res = allocate_team_minutes(roster, overtime_periods=0)
    assert res.status == "SUCCESS"
    assert res.allocated_minutes["out_player"] == 0.0
    assert res.total_allocated == pytest.approx(240.0, 1e-4)


def test_context_support_screen():
    """Validates §10 support screen: extreme missing minutes triggers TEAM_CONTEXT_SUPPORT_UNVALIDATED."""
    # 50 minutes missing (50 / 240 = 20.8% <= 45%) -> supported
    support_normal = evaluate_injury_context_support(50.0)
    assert support_normal["is_supported"] is True
    assert support_normal["reason_code"] is None

    # 120 minutes missing (120 / 240 = 50.0% > 45%) -> unsupported
    support_extreme = evaluate_injury_context_support(120.0)
    assert support_extreme["is_supported"] is False
    assert support_extreme["reason_code"] == "TEAM_CONTEXT_SUPPORT_UNVALIDATED"
