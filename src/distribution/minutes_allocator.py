"""
Module: Research Minutes Allocator (§6, §7 of NBA_MISSING_ROLE_ALLOCATOR_FIX_SPEC.md)
Point-allocation candidate for research and scenario diagnostics.
Enforces:
- Exact team duration budget: B = 5*T = 240 + 25*o (where T = 48 + 5*o)
- Eligibility-only upper bounds: u_i = min(T, cap_i) if E_i=1 else 0
- Exact KKT / Bisection solver with budget residual tolerance <= 1e-6 min
- Strict feasibility diagnostics: INFEASIBLE_SCENARIO when sum(u) < B
"""

from typing import Any, Dict, List, Optional, Union
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field


class PlayerAllocationInput(BaseModel):
    player_id: Union[int, str]
    player_name: Optional[str] = None
    baseline_minutes: float = Field(ge=0.0, description="Pregame baseline minutes m_base,i")
    is_eligible: bool = Field(default=True, description="E_i in {0, 1}: available in this scenario")
    variance_scale: float = Field(default=1.0, gt=0.0, description="Scale s_i from training")
    hard_cap: Optional[float] = Field(default=None, description="Official hard cap if verified")
    is_entered: Optional[bool] = Field(default=None, description="A_i in {0, 1} if entered-set is modeled")


class AllocationResult(BaseModel):
    status: str = Field(description="SUCCESS, INFEASIBLE_SCENARIO, or INVALID_ALLOCATOR_INPUT")
    allocated_minutes: Optional[Dict[str, float]] = None
    lambda_optimal: Optional[float] = None
    budget_minutes: float
    total_allocated: Optional[float] = None
    residual: Optional[float] = None
    overtime_periods: int
    player_max_duration: float
    active_bounds: Optional[Dict[str, List[str]]] = None
    diagnostics: Optional[Dict[str, Any]] = None
    recipe_version: str = "minutes_allocator_v1_research"


def allocate_team_minutes(
    roster: List[Union[PlayerAllocationInput, Dict[str, Any]]],
    overtime_periods: int = 0,
    tolerance: float = 1e-6,
    epsilon: float = 1e-6,
    max_iter: int = 200,
) -> AllocationResult:
    """
    Solves the Constrained Quadratic Projection point-allocation problem (§6.1, §7):
    
        min_M  sum_i (M_i - m_base,i)^2 / (s_i^2 + eps)
        s.t.   sum_i M_i = B
               l_i <= M_i <= u_i
               
    where:
        o = overtime_periods >= 0
        T = 48 + 5*o (game duration per position)
        B = 5*T = 240 + 25*o (total team player-minutes)
        u_i = 0 if not is_eligible else min(T, hard_cap if hard_cap is not None else T)
        l_i = 0.0 (by default for eligibility-only)
    """
    if overtime_periods < 0:
        return AllocationResult(
            status="INVALID_ALLOCATOR_INPUT",
            budget_minutes=240.0,
            overtime_periods=overtime_periods,
            player_max_duration=48.0,
            diagnostics={"error": "Overtime periods must be non-negative"},
        )

    T = 48.0 + 5.0 * float(overtime_periods)
    B = 5.0 * T

    if not roster:
        return AllocationResult(
            status="INVALID_ALLOCATOR_INPUT",
            budget_minutes=B,
            overtime_periods=overtime_periods,
            player_max_duration=T,
            diagnostics={"error": "Empty roster provided"},
        )

    pids: List[str] = []
    m_base_list: List[float] = []
    l_bounds: List[float] = []
    u_bounds: List[float] = []
    v_weights: List[float] = []

    for item in roster:
        if isinstance(item, dict):
            inp = PlayerAllocationInput(**item)
        else:
            inp = item

        pid_str = str(inp.player_id)
        pids.append(pid_str)

        m_b = max(0.0, float(inp.baseline_minutes))
        m_base_list.append(m_b)

        # Upper bound u_i
        if not inp.is_eligible:
            u_i = 0.0
            l_i = 0.0
        else:
            if inp.hard_cap is not None and not np.isnan(inp.hard_cap):
                cap_val = max(0.0, float(inp.hard_cap))
                u_i = min(T, cap_val)
            else:
                u_i = T
            l_i = 0.0

        # Non-finite or invalid bounds guard
        if np.isinf(u_i) or np.isnan(u_i) or u_i < l_i:
            return AllocationResult(
                status="INVALID_ALLOCATOR_INPUT",
                budget_minutes=B,
                overtime_periods=overtime_periods,
                player_max_duration=T,
                diagnostics={"error": f"Invalid bounds for player {pid_str}: [{l_i}, {u_i}]"},
            )

        l_bounds.append(l_i)
        u_bounds.append(u_i)

        # v_i = s_i^2 + epsilon
        s_val = float(inp.variance_scale) if inp.variance_scale > 0 else 1.0
        v_i = (s_val ** 2) + epsilon
        v_weights.append(v_i)

    m_base_arr = np.array(m_base_list, dtype=np.float64)
    l_arr = np.array(l_bounds, dtype=np.float64)
    u_arr = np.array(u_bounds, dtype=np.float64)
    v_arr = np.array(v_weights, dtype=np.float64)

    sum_l = float(np.sum(l_arr))
    sum_u = float(np.sum(u_arr))

    # Feasibility Check (§7.1)
    if B < sum_l - 1e-6 or B > sum_u + 1e-6:
        return AllocationResult(
            status="INFEASIBLE_SCENARIO",
            budget_minutes=B,
            overtime_periods=overtime_periods,
            player_max_duration=T,
            diagnostics={
                "sum_lower_capacity": round(sum_l, 4),
                "sum_upper_capacity": round(sum_u, 4),
                "budget_required": round(B, 4),
                "deficit": round(B - sum_u, 4) if B > sum_u else 0.0,
                "excess": round(sum_l - B, 4) if B < sum_l else 0.0,
            },
        )

    # Boundary exact solutions
    if abs(B - sum_l) <= tolerance:
        M_final = l_arr
        lam_star = -1e9
    elif abs(B - sum_u) <= tolerance:
        M_final = u_arr
        lam_star = 1e9
    else:
        # KKT Bisection Solver (§7.2)
        # f(lambda) = sum_i clip(m_base_i + lambda * v_i, l_i, u_i) - B
        def f_val(lam: float) -> float:
            return float(np.sum(np.clip(m_base_arr + lam * v_arr, l_arr, u_arr)) - B)

        f_zero = f_val(0.0)
        if abs(f_zero) <= tolerance:
            lam_star = 0.0
        elif f_zero < 0:
            # Need positive lambda to increase minutes
            l_lam = 0.0
            r_lam = 1.0
            doublings = 0
            while f_val(r_lam) < 0 and doublings < 60:
                r_lam *= 2.0
                doublings += 1

            for _ in range(max_iter):
                mid = (l_lam + r_lam) / 2.0
                val = f_val(mid)
                if abs(val) <= tolerance:
                    l_lam = mid
                    r_lam = mid
                    break
                if val < 0:
                    l_lam = mid
                else:
                    r_lam = mid
            lam_star = (l_lam + r_lam) / 2.0
        else:
            # Need negative lambda to decrease minutes
            r_lam = 0.0
            l_lam = -1.0
            doublings = 0
            while f_val(l_lam) > 0 and doublings < 60:
                l_lam *= 2.0
                doublings += 1

            for _ in range(max_iter):
                mid = (l_lam + r_lam) / 2.0
                val = f_val(mid)
                if abs(val) <= tolerance:
                    l_lam = mid
                    r_lam = mid
                    break
                if val < 0:
                    l_lam = mid
                else:
                    r_lam = mid
            lam_star = (l_lam + r_lam) / 2.0

        M_final = np.clip(m_base_arr + lam_star * v_arr, l_arr, u_arr)

    allocated_dict = {pids[i]: round(float(M_final[i]), 4) for i in range(len(pids))}
    total_alloc = float(np.sum(M_final))
    res = float(total_alloc - B)

    # Detect active bounds
    lower_active = [pids[i] for i in range(len(pids)) if abs(M_final[i] - l_arr[i]) <= 1e-5 and u_arr[i] > l_arr[i]]
    upper_active = [pids[i] for i in range(len(pids)) if abs(M_final[i] - u_arr[i]) <= 1e-5 and u_arr[i] > l_arr[i]]

    return AllocationResult(
        status="SUCCESS",
        allocated_minutes=allocated_dict,
        lambda_optimal=round(float(lam_star), 6),
        budget_minutes=B,
        total_allocated=round(total_alloc, 4),
        residual=round(res, 6),
        overtime_periods=overtime_periods,
        player_max_duration=T,
        active_bounds={"lower": lower_active, "upper": upper_active},
        diagnostics={
            "n_players": len(pids),
            "n_eligible": int(np.sum(u_arr > 0)),
            "tolerance_met": bool(abs(res) <= 1e-4),
        },
    )
