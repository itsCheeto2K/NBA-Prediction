import io
import pytest
from unittest.mock import MagicMock, patch
from PIL import Image, ImageDraw
import numpy as np

from src.services.odds_ocr_parser import (
    clean_player_name,
    resolve_player,
    parse_odds_image,
)

SAMPLE_PLAYERS = [
    {"player_id": 201939, "full_name": "Stephen Curry"},
    {"player_id": 2544, "full_name": "LeBron James"},
    {"player_id": 203507, "full_name": "Giannis Antetokounmpo"},
    {"player_id": 1629630, "full_name": "Ja Morant"},
    {"player_id": 1642259, "full_name": "Alex Sarr"},
    {"player_id": 1630559, "full_name": "Austin Reaves"},
]

def test_clean_player_name():
    assert clean_player_name("Stephen Curry (22.5)") == "Stephen Curry"
    assert clean_player_name("DuncanRobinsonToPoints") == "Duncan Robinson"
    assert clean_player_name("Giannis Antetokounmpo Over") == "Giannis Antetokounmpo"
    assert clean_player_name("LeBron James 1.90") == "LeBron James"
    assert clean_player_name("Tài Stephen Curry") == "Stephen Curry"


def test_resolve_player_exact():
    res = resolve_player("Stephen Curry", SAMPLE_PLAYERS)
    assert res is not None
    assert res["player_id"] == 201939
    assert res["matched_name"] == "Stephen Curry"
    assert res["confidence"] == 1.0


def test_resolve_player_alias():
    res = resolve_player("Alexandre Sarr", SAMPLE_PLAYERS)
    assert res is not None
    assert res["player_id"] == 1642259
    assert res["matched_name"] == "Alex Sarr"
    assert res["confidence"] >= 0.95


def test_resolve_player_fuzzy():
    res = resolve_player("Stephn Curry", SAMPLE_PLAYERS)
    assert res is not None
    assert res["player_id"] == 201939
    assert res["matched_name"] == "Stephen Curry"
    assert 0.8 <= res["confidence"] < 1.0


def test_resolve_player_initial_last_name():
    res = resolve_player("A. Reaves", SAMPLE_PLAYERS)
    assert res is not None
    assert res["player_id"] == 1630559
    assert res["matched_name"] == "Austin Reaves"
    assert res["confidence"] >= 0.7


def test_resolve_player_not_found():
    res = resolve_player("Nonexistent Mystery Player", SAMPLE_PLAYERS)
    assert res is None


def test_parse_odds_image_line_not_parsed_as_odds_and_no_blind_duplicate():
    """
    Test Issue 13 fixes:
    1. Line token (e.g. 22.5) must NOT be parsed as odds_over or odds_under.
    2. When only one odds is detected (e.g. 1.91), odds_under must be None (NOT duplicated).
    3. Match confidence score is populated.
    """
    # Create a small dummy image in-memory
    img = Image.new("RGB", (400, 100), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_bytes = buf.getvalue()

    # Simulate RapidOCR output for a row:
    # box format: [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
    # Item 1: Player Name (cx=50, cy=30)
    # Item 2: Line (cx=150, cy=30) "22.5"
    # Item 3: Over odds (cx=250, cy=30) "1.91"
    # Item 4: Under odds (cx=350, cy=30) "1.85"
    simulated_ocr_result = [
        ([ [20, 20], [100, 20], [100, 40], [20, 40] ], "Stephen Curry", 0.98),
        ([ [140, 20], [180, 20], [180, 40], [140, 40] ], "22.5", 0.95),
        ([ [230, 20], [270, 20], [270, 40], [230, 40] ], "1.91", 0.96),
        ([ [330, 20], [370, 20], [370, 40], [330, 40] ], "1.85", 0.94),
    ]

    mock_engine = MagicMock(return_value=(simulated_ocr_result, None))
    with patch("src.services.odds_ocr_parser.get_ocr_engine", return_value=mock_engine):
        results = parse_odds_image(img_bytes, SAMPLE_PLAYERS)

    assert len(results) == 1
    r = results[0]
    assert r["player_id"] == 201939
    assert r["matched_name"] == "Stephen Curry"
    assert r["line"] == 22.5
    # Line must NOT be parsed as odds
    assert r["odds_over"] == 1.91
    assert r["odds_under"] == 1.85
    assert r["confidence"] == 1.0


def test_parse_odds_image_single_odds_does_not_duplicate():
    """Ensure single odds does not duplicate to opposite side."""
    img = Image.new("RGB", (400, 100), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_bytes = buf.getvalue()

    # Only one odds: 1.95 (no second odds)
    simulated_ocr_result = [
        ([ [20, 20], [100, 20], [100, 40], [20, 40] ], "LeBron James", 0.98),
        ([ [140, 20], [180, 20], [180, 40], [140, 40] ], "25.5", 0.95),
        ([ [230, 20], [270, 20], [270, 40], [230, 40] ], "1.95", 0.96),
    ]

    mock_engine = MagicMock(return_value=(simulated_ocr_result, None))
    with patch("src.services.odds_ocr_parser.get_ocr_engine", return_value=mock_engine):
        results = parse_odds_image(img_bytes, SAMPLE_PLAYERS)

    assert len(results) == 1
    r = results[0]
    assert r["player_id"] == 2544
    assert r["line"] == 25.5
    assert r["odds_over"] == 1.95
    assert r["odds_under"] is None  # Must NOT be 1.95!
    assert r["confidence"] == 1.0
