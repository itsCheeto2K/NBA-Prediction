# NBA Player Props: Opponent Context & Schedule Supplement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Triển khai toàn bộ đặc tả từ `NBA_OPPONENT_SCHEDULE_SUPPLEMENT_PLAN.md` (v1.0): xây dựng bộ đặc trưng đối thủ nâng cao (pace, def rating per 100 poss, allowed AST per 100, DREB share), lịch thi đấu hai đội (b2b, rest advantage, 3-in-4, 4-in-6), phân biệt tải thi đấu cá nhân cầu thủ (`player_played_prev_team_game`, `team_b2b_but_player_rested`, `minutes_last7days`), thực hiện nghiên cứu thực nghiệm ablation A0–A3, cập nhật mô hình ML và tích hợp lên Dashboard.

**Architecture:**
- `src/features/schedule_context.py`: Xây dựng module tính toán lịch thi đấu chi tiết cho cả 2 đội (team & opponent) và cầu thủ cá nhân (`3in4`, `4in6`, `rest_advantage_days`, `team_b2b_but_player_rested`, `player_minutes_last7days`).
- `src/features/opponent_context.py`: Xây dựng module tính toán đặc trưng phòng ngự đối thủ per-100 possessions (`opp_pace`, `opp_def_rating_per100`, `opp_allowed_ast_per100`, `opp_dreb_share`, `opp_fg3a_share`).
- `src/features/builder.py`: Cập nhật pipeline feature builder để tích hợp các trường mới với cờ missing/sample count đầy đủ.
- `src/models/ablation.py`: Chạy ablation study A0 (baseline), A1 (opponent), A2 (schedule/workload), A3 (full) trên khối B1, xuất báo cáo `reports/ablation_A0_A3_report.json`.
- `src/api/schemas.py` & `src/api/main.py`: Bổ sung thông tin bối cảnh lịch & đối thủ vào response API.
- `src/api/static/`: Cập nhật giao diện Linear dashboard hiển thị các badges: Rest Advantage, B2B status, 3-in-4 Congestion, Opponent Pace & Defensive Rating.

**Tech Stack:** Python 3.14, `pandas`, `pyarrow`, `lightgbm`, `catboost`, `scipy`, `pytest`, `fastapi`.

**Spec:** [NBA_OPPONENT_SCHEDULE_SUPPLEMENT_PLAN.md](file:///D:/Project/NBA_props_prediction/NBA_OPPONENT_SCHEDULE_SUPPLEMENT_PLAN.md) (§5, §6, §10, §11, §12)

## Global Constraints

- **Chống rò rỉ tuyệt đối**: Mọi đặc trưng đối thủ và lịch thi đấu chỉ được tính từ các trận đã kết thúc trước thời điểm trận đấu (lag-1).
- **Phân tách Đội vs Cầu thủ**: Phải phân biệt rõ ràng giữa lịch đội (`team_b2b`) và sự tham gia thực tế của cầu thủ (`team_b2b_but_player_rested`, `player_played_previous_team_game`).
- **Mẫu số chuẩn**: Defensive ratings và per-100 stats phải tính trên đúng số possessions, mẫu số 0 phải xử lý trả về null/missing kèm fallback prior hợp lệ, không chia bừa.
- **Không thay đổi mốc thời gian**: Giữ nguyên phân chia khối B0 (train 2023-24) và B1 (validation 2024-25).

---

### Task 1: Module Lịch Thi Đấu & Tải Thi Đấu Cầu Thủ Chi Tiết (P0/P1)

**Files:**
- Create: `src/features/schedule_context.py`
- Create: `tests/test_supplement_schedule.py`

**Steps:**
- [ ] Viết test `tests/test_supplement_schedule.py`:
  - Test `team_b2b`, `opp_b2b`, `rest_advantage_days`.
  - Test congestion: `team_3in4`, `team_4in6`.
  - Test phân biệt cầu thủ: `player_played_previous_team_game`, `team_b2b_but_player_rested`.
  - Test workload: `player_minutes_sum_prev3`, `player_minutes_last7days`.
- [ ] Triển khai `src/features/schedule_context.py`.
- [ ] Chạy `pytest tests/test_supplement_schedule.py` đảm bảo pass.

---

### Task 2: Module Phòng Ngự & Tương Tác Nhịp Độ Đối Thủ Cấp Đội (P0)

**Files:**
- Create: `src/features/opponent_context.py`
- Create: `tests/test_supplement_opponent.py`

**Steps:**
- [ ] Viết test `tests/test_supplement_opponent.py`:
  - Test tính possessions từ FGA, FTA, OREB, TOV: $\text{Poss} = 0.96 \times (\text{FGA} + 0.44 \times \text{FTA} - \text{OREB} + \text{TOV})$.
  - Test `opp_pace_prev10`, `opp_def_rating_prev10` (pts allowed per 100 poss).
  - Test `opp_allowed_ast_per100_prev10`, `opp_dreb_share_prev10`.
  - Test zero denominator fallback & missing flags.
- [ ] Triển khai `src/features/opponent_context.py`.
- [ ] Chạy `pytest tests/test_supplement_opponent.py` đảm bảo pass.

---

### Task 3: Tích hợp Feature Builder & Re-generate Datasets

**Files:**
- Modify: `src/features/builder.py`
- Create: `tests/test_supplement_builder.py`
- Modify: `scripts/build_features.py`

**Steps:**
- [ ] Viết test `tests/test_supplement_builder.py` kiểm tra các cột mới xuất hiện trong output DataFrame.
- [ ] Cập nhật `src/features/builder.py` gọi `schedule_context` và `opponent_context`.
- [ ] Chạy `python scripts/build_features.py` để cập nhật lại các file parquet `features_all_seasons.parquet` và theo mùa.
- [ ] Chạy kiểm thử pytest đảm bảo pass.

---

### Task 4: Chạy Thí Nghiệm Thực Nghiệm Ablation A0–A3

**Files:**
- Create: `src/models/ablation.py`
- Output: `reports/ablation_A0_A3_report.json`
- Create: `tests/test_ablation.py`

**Steps:**
- [ ] Viết test `tests/test_ablation.py` kiểm tra pipeline định nghĩa đúng 4 cấu hình A0, A1, A2, A3.
- [ ] Triển khai `src/models/ablation.py`:
  - Huấn luyện LightGBM và CatBoost trên B0 và chấm điểm trên B1 cho cả 4 cấu hình.
  - Đo Poisson Deviance, RMSE, MAE cho từng stat (PTS, REB, AST).
  - Đánh giá trên các nhóm bối cảnh: team_b2b, opp_b2b, player_rested, sân khách.
  - Lưu kết quả vào `reports/ablation_A0_A3_report.json`.
- [ ] Chạy script ablation và cập nhật lại mô hình tốt nhất vào `models/`.

---

### Task 5: Cập Nhật API & Web Dashboard Hiển Thị Bối Cảnh Lịch & Đối Thủ

**Files:**
- Modify: `src/api/schemas.py`
- Modify: `src/api/main.py`
- Modify: `src/api/static/index.html`
- Modify: `src/api/static/app.js`

**Steps:**
- [ ] Bổ sung trường `schedule_context` và `opponent_context` vào `PredictResponse` trong `src/api/schemas.py`.
- [ ] Cập nhật `src/api/main.py` trích xuất thông tin rest advantage, congestion, opponent pace & rating khi dự đoán.
- [ ] Cập nhật Web Dashboard (`index.html`, `app.js`):
  - Hiển thị badge: `Rest Advantage (+2d)`, `3 in 4 Nights`, `B2B (Rested Prev)`, `Fast Pace Matchup`.
  - Hiển thị bảng so sánh đối thủ: Opponent Def Rating, Pace, Allowed AST.
- [ ] Chạy toàn bộ test suite và xác nhận Web server phản hồi thông tin mới.
