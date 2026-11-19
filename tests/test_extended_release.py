import numpy as np
import pandas as pd
from types import SimpleNamespace

from scripts.train_extended_release import promotion_gate, score


def period(old_rps=2., new_rps=1.98, old_log=3., new_log=3., rows=100):
    return {"rows": rows, "baseline": {"mean_full_rps": old_rps, "mean_neg_log_score": old_log, "coverage_90": .9},
            "candidate": {"mean_full_rps": new_rps, "mean_neg_log_score": new_log, "coverage_90": .9}}


def test_release_requires_meaningful_gain_and_safe_log_loss():
    assert promotion_gate({"season": period()})["passed"]
    assert not promotion_gate({"season": period(new_rps=1.999)})["passed"]
    assert not promotion_gate({"season": period(new_log=3.04)})["passed"]


def test_aggregate_gain_cannot_hide_regression_in_a_small_recent_season():
    result = promotion_gate({"old": period(new_rps=1.8, rows=10000),
                             "recent": period(new_rps=2.03, rows=100)})
    assert result["rps_improvement_pct"] > .5
    assert not result["passed"]


def test_saved_bundle_uppercase_stat_scores_lowercase_dataset_target(tmp_path):
    frame = pd.DataFrame({"target_pts": [5., 10., 20.]})
    bundle = SimpleNamespace(stat="PTS", mean_family="weighted_avg", raw_distribution_family="poisson",
                             fitted_phi=0., _calibrator_obj=None,
                             _mean_predictor=SimpleNamespace(predict=lambda df: df.target_pts.to_numpy()))
    metrics = score(bundle, frame, tmp_path)
    assert all(np.isfinite(value) for value in metrics.values())
    assert metrics["mean_full_rps"] > 0
