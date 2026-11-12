import pytest
import pandas as pd
from src.collectors.boxscore import (
    parse_iso_duration_to_minutes,
    normalize_boxscore_traditional_v3,
    normalize_boxscore_advanced_v3,
)

def test_parse_iso_duration():
    assert pytest.approx(parse_iso_duration_to_minutes("PT34M25.00S"), 0.01) == 34.417
    assert pytest.approx(parse_iso_duration_to_minutes("PT05M00.00S"), 0.01) == 5.0
    assert pytest.approx(parse_iso_duration_to_minutes("PT48M00.00S"), 0.01) == 48.0
    assert parse_iso_duration_to_minutes("") is None
    assert parse_iso_duration_to_minutes(None) is None
    # Also support standard MM:SS
    assert pytest.approx(parse_iso_duration_to_minutes("34:25"), 0.01) == 34.417

def test_normalize_boxscore_traditional():
    raw_sample = pd.DataFrame([{
        "gameId": 22400061,
        "teamId": 1610612739,
        "teamCity": "Cleveland",
        "teamName": "Cavaliers",
        "teamTricode": "CLE",
        "personId": 1628378,
        "firstName": "Donovan",
        "familyName": "Mitchell",
        "position": "G",
        "comment": "",
        "minutes": "PT34M12.00S",
        "points": 30,
        "reboundsTotal": 4,
        "assists": 5,
        "fieldGoalsAttempted": 20,
        "freeThrowsAttempted": 6,
        "threePointersAttempted": 11,
    }])
    
    clean = normalize_boxscore_traditional_v3(raw_sample)
    assert clean.iloc[0]["game_id"] == "0022400061"
    assert clean.iloc[0]["player_id"] == 1628378
    assert clean.iloc[0]["pts"] == 30
    assert clean.iloc[0]["reb"] == 4
    assert clean.iloc[0]["ast"] == 5
    assert bool(clean.iloc[0]["is_dnp"]) is False
    assert pytest.approx(clean.iloc[0]["min"], 0.01) == 34.2

def test_normalize_boxscore_dnp():
    raw_sample = pd.DataFrame([{
        "gameId": "0022400061",
        "teamId": 1610612739,
        "personId": 9999999,
        "firstName": "Bench",
        "familyName": "Player",
        "position": "",
        "comment": "DNP - Coach's Decision",
        "minutes": "",
        "points": 0,
        "reboundsTotal": 0,
        "assists": 0,
        "fieldGoalsAttempted": 0,
        "freeThrowsAttempted": 0,
        "threePointersAttempted": 0,
    }])
    
    clean = normalize_boxscore_traditional_v3(raw_sample)
    assert bool(clean.iloc[0]["is_dnp"]) is True
    assert clean.iloc[0]["min"] is None
