"""Service for extracting NBA player prop lines and odds from sportsbook screenshots via RapidOCR."""
import io
import re
import difflib
import logging
from typing import List, Dict, Any, Optional
import numpy as np
from PIL import Image

logger = logging.getLogger("odds_ocr_parser")

# Global singleton OCR engine to avoid repeated model loading
_OCR_ENGINE = None

def get_ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _OCR_ENGINE = RapidOCR()
            logger.info("RapidOCR engine initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize RapidOCR: {e}")
            raise RuntimeError(f"RapidOCR engine could not be initialized: {e}")
    return _OCR_ENGINE


def clean_player_name(raw_text: str) -> str:
    """Clean OCR text to isolate the player's name."""
    # Remove parenthesized numbers like (22.5), ( 11.5 )
    t = re.sub(r"\(\s*\d+(\.\d+)?\s*\)", "", raw_text)
    # Remove standalone numbers (odds, lines, jersey numbers)
    t = re.sub(r"\b\d+(\.\d+)?\b", " ", t)
    # Split merged TOPoints / TUPoints / ToPoints / OverPoints
    t = re.sub(r"(?i)(to|tu|over|under)(points|point|pts)", " ", t)
    # Split camelCase if preceded by 3+ lowercase letters (e.g. DuncanRobinson -> Duncan Robinson, but keep LeBron/DeMar)
    t = re.sub(r"(?<=[a-z]{3})([A-Z])", r" \1", t)
    # Remove common betting terms: TO, TU, Over, Under, Points, PTS, Tài, Xỉu
    t = re.sub(r"\b(to|tu|points|point|pts|over|under|tài|xỉu|tai|xiu|total)\b", " ", t, flags=re.IGNORECASE)
    # Remove stray punctuation, keeping letters, spaces, hyphens, apostrophes
    t = re.sub(r"[^a-zA-Z\s\'-]", "", t)
    return " ".join(t.split()).strip()


# Common nickname/alias map for NBA players that might differ from official NBA rosters
NAME_ALIASES = {
    "alexandre dam sarr": "Alex Sarr",
    "alexandre sarr": "Alex Sarr",
    "cam thomas": "Cameron Thomas",
    "cam johnson": "Cameron Johnson",
    "herb jones": "Herbert Jones",
    "tim hardaway": "Tim Hardaway Jr.",
    "derrick jones": "Derrick Jones Jr.",
    "kelly oubre": "Kelly Oubre Jr.",
    "larry nance": "Larry Nance Jr.",
    "gary trent": "Gary Trent Jr.",
    "wendell carter": "Wendell Carter Jr.",
    "marvin bagley": "Marvin Bagley III",
    "trey murphy": "Trey Murphy III",
    "marcus morris": "Marcus Morris Sr.",
    "robert williams": "Robert Williams III",
    "kenyon martin": "Kenyon Martin Jr.",
    "jabari smith": "Jabari Smith Jr.",
    "jaime jaquez": "Jaime Jaquez Jr.",
}


def resolve_player(
    raw_name: str, 
    all_players: List[Dict[str, Any]], 
    latest_features_df=None
) -> Optional[Dict[str, Any]]:
    """Match cleaned raw name against official NBA players."""
    norm = raw_name.lower().strip()
    if not norm:
        return None

    # Check alias map
    is_alias = False
    if norm in NAME_ALIASES:
        norm = NAME_ALIASES[norm].lower()
        is_alias = True

    name_to_player = {p["full_name"].lower(): p for p in all_players}
    
    # 1. Exact match
    if norm in name_to_player:
        p = name_to_player[norm]
        team_abbr = None
        if latest_features_df is not None:
            sub = latest_features_df[latest_features_df["player_id"] == p["player_id"]]
            if not sub.empty:
                team_abbr = sub.iloc[0].get("team_abbreviation")
        return {
            "player_id": int(p["player_id"]),
            "matched_name": p["full_name"],
            "team_abbreviation": team_abbr,
            "confidence": 0.98 if is_alias else 1.0,
        }

    # 2. Fuzzy match using difflib
    db_names = [p["full_name"] for p in all_players]
    close = difflib.get_close_matches(norm, [n.lower() for n in db_names], n=1, cutoff=0.55)
    matched_full = None
    if close:
        matched_full = name_to_player[close[0]]["full_name"]
    else:
        close_raw = difflib.get_close_matches(raw_name, db_names, n=1, cutoff=0.55)
        if close_raw:
            matched_full = close_raw[0]

    if matched_full:
        p = name_to_player[matched_full.lower()]
        team_abbr = None
        if latest_features_df is not None:
            sub = latest_features_df[latest_features_df["player_id"] == p["player_id"]]
            if not sub.empty:
                team_abbr = sub.iloc[0].get("team_abbreviation")
        ratio = difflib.SequenceMatcher(None, raw_name.lower(), matched_full.lower()).ratio()
        return {
            "player_id": int(p["player_id"]),
            "matched_name": matched_full,
            "team_abbreviation": team_abbr,
            "confidence": round(float(ratio), 3),
        }

    # 3. Last name + First initial match
    parts = norm.split()
    if len(parts) >= 2:
        last_name = parts[-1]
        first_letter = parts[0][0]
        candidates = [
            p for p in all_players 
            if p["full_name"].lower().endswith(last_name) and p["full_name"].lower().startswith(first_letter)
        ]
        if len(candidates) == 1:
            p = candidates[0]
            team_abbr = None
            if latest_features_df is not None:
                sub = latest_features_df[latest_features_df["player_id"] == p["player_id"]]
                if not sub.empty:
                    team_abbr = sub.iloc[0].get("team_abbreviation")
            ratio = difflib.SequenceMatcher(None, norm, p["full_name"].lower()).ratio()
            return {
                "player_id": int(p["player_id"]),
                "matched_name": p["full_name"],
                "team_abbreviation": team_abbr,
                "confidence": round(max(0.70, float(ratio)), 3),
            }

    return None


def parse_odds_image(
    image_bytes: bytes, 
    all_players: List[Dict[str, Any]], 
    latest_features_df=None
) -> List[Dict[str, Any]]:
    """Parse a screenshot image and extract all player prop lines and odds."""
    engine = get_ocr_engine()
    
    # Load image using PIL then convert to numpy uint8
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img_np = np.array(image)

    ocr_result, _ = engine(img_np)
    if not ocr_result:
        return []

    # Extract items with centers
    items = []
    for box, text, score in ocr_result:
        text = text.strip()
        if not text:
            continue
        cx = (box[0][0] + box[1][0]) / 2
        cy = (box[0][1] + box[2][1]) / 2
        items.append({
            "cx": cx,
            "cy": cy,
            "text": text,
            "box": box,
            "score": float(score) if isinstance(score, (int, float, str)) else 0.8
        })

    # Cluster into rows based on vertical proximity (cy difference < 18 pixels)
    items.sort(key=lambda x: x["cy"])
    rows = []
    for it in items:
        matched_row = None
        for r in rows:
            if abs(r["cy"] - it["cy"]) < 18:
                matched_row = r
                break
        if matched_row:
            matched_row["items"].append(it)
            matched_row["cy"] = sum(x["cy"] for x in matched_row["items"]) / len(matched_row["items"])
        else:
            rows.append({"cy": it["cy"], "items": [it]})

    parsed_results = []
    seen_player_ids = set()

    for r in rows:
        r["items"].sort(key=lambda x: x["cx"])
        texts = [it["text"] for it in r["items"]]

        # Find line number (e.g. 22.5, 11.5)
        line_val = None
        line_item_idx = None
        for idx, t in enumerate(texts):
            m = re.search(r"\(?\b(\d{1,2}\.5)\b\)?", t)
            if not m:
                m = re.search(r"\(?\b(\d{1,2}(\.\d)?)\b\)?", t)
            if m:
                try:
                    val = float(m.group(1))
                    if 0.5 <= val <= 65.5:  # Valid NBA prop line range
                        line_val = val
                        line_item_idx = idx
                        break
                except ValueError:
                    pass

        # Find odds decimal numbers (e.g. 1.67, 1.93, 1.769, 2.05)
        # Ensure the token identified as the line value is never parsed as odds!
        floats = []
        for idx, it in enumerate(r["items"]):
            if line_item_idx is not None and idx == line_item_idx:
                continue
            # Strict decimal number check
            m = re.match(r"^\d+\.\d+$", it["text"])
            if m:
                try:
                    num = float(it["text"])
                    # If token matches the line value, skip it
                    if line_val is not None and abs(num - line_val) < 1e-4:
                        continue
                    if 1.01 <= num <= 25.0:  # Valid odds range
                        floats.append(num)
                except ValueError:
                    pass

        # Do not blindly duplicate odds to opposite side when only one is found
        odds_over = floats[0] if len(floats) >= 1 else None
        odds_under = floats[1] if len(floats) >= 2 else None

        # Extract player name from the first text column
        raw_name = clean_player_name(texts[0])
        if not raw_name or len(raw_name) < 3:
            # Fallback to second column if first was stray
            if len(texts) > 2:
                raw_name = clean_player_name(texts[2])

        if not raw_name:
            continue

        resolved = resolve_player(raw_name, all_players, latest_features_df)
        p_id = resolved["player_id"] if resolved else None
        matched_name = resolved["matched_name"] if resolved else raw_name
        team_abbr = resolved.get("team_abbreviation") if resolved else None
        confidence = resolved.get("confidence", 0.0) if resolved else 0.0

        # Avoid duplicate rows for the same player in one screenshot
        if p_id and p_id in seen_player_ids:
            continue
        if p_id:
            seen_player_ids.add(p_id)

        parsed_results.append({
            "player_id": p_id,
            "matched_name": matched_name,
            "raw_name": raw_name,
            "line": line_val,
            "odds_over": odds_over,
            "odds_under": odds_under,
            "team_abbreviation": team_abbr,
            "confidence": confidence,
        })

    return parsed_results
