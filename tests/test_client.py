import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from src.client import NBAClient

def test_cache_key_generation():
    client = NBAClient()
    key1 = client._generate_cache_key("playergamelogs", {"season": "2024-25", "season_type_all_star": "Regular Season"})
    key2 = client._generate_cache_key("playergamelogs", {"season_type_all_star": "Regular Season", "season": "2024-25"})
    assert key1 == key2, "Cache key must be deterministic regardless of parameter order"

def test_save_and_load_cache(tmp_path):
    client = NBAClient(cache_dir=tmp_path)
    endpoint = "test_endpoint"
    params = {"game_id": "0022400061"}
    raw_content = '{"resultSets": [{"name": "test", "rowSet": [[1, 2]]}]}'
    
    # Save cache
    cache_path = client.save_raw_cache(endpoint, params, raw_content)
    assert cache_path.exists()
    
    # Verify cached payload structure
    with open(cache_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["endpoint"] == endpoint
    assert data["params"] == params
    assert "fetched_at" in data
    assert "sha256_hash" in data
    assert data["raw_response"] == raw_content
    
    # Load cache
    loaded = client.load_raw_cache(endpoint, params)
    assert loaded == raw_content

def test_rate_limiter_delay(monkeypatch):
    client = NBAClient(request_delay=0.1)
    mock_sleep = MagicMock()
    monkeypatch.setattr("time.sleep", mock_sleep)
    
    client._apply_rate_limit()
    client._apply_rate_limit()
    
    assert mock_sleep.called
