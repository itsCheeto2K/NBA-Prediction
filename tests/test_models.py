import pytest
import numpy as np
import pandas as pd
from src.models.baseline import WeightedAverageBaseline, MinutesRateBaseline, calculate_poisson_deviance

def test_poisson_deviance_calculation():
    # If prediction matches actual exactly, deviance is 0
    y_true = np.array([10.0, 20.0, 30.0])
    y_pred = np.array([10.0, 20.0, 30.0])
    dev = calculate_poisson_deviance(y_true, y_pred)
    assert pytest.approx(dev, 0.001) == 0.0
    
    # Deviance is always non-negative
    y_pred_bad = np.array([15.0, 15.0, 25.0])
    dev_bad = calculate_poisson_deviance(y_true, y_pred_bad)
    assert dev_bad > 0.0

def test_baseline_predictions():
    df = pd.DataFrame([
        {"pts_roll_mean_5": 22.0, "min_roll_mean_5": 30.0, "pts_rate_shrinkage": 0.7, "target_pts": 25.0},
        {"pts_roll_mean_5": 18.0, "min_roll_mean_5": 25.0, "pts_rate_shrinkage": 0.8, "target_pts": 20.0},
    ])
    
    avg_base = WeightedAverageBaseline(stat="pts")
    preds_avg = avg_base.predict(df)
    assert list(preds_avg) == [22.0, 18.0]
    
    min_base = MinutesRateBaseline(stat="pts")
    preds_min = min_base.predict(df)
    # 30 * 0.7 = 21.0, 25 * 0.8 = 20.0
    assert pytest.approx(preds_min[0], 0.01) == 21.0
    assert pytest.approx(preds_min[1], 0.01) == 20.0
