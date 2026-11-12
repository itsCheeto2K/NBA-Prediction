# NBA Player Props: Phase 1 Completion & Phase 2 (Feature Engineering & Anti-Leakage) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hoàn thành backfill dữ liệu cho mùa 2023-24 và 2025-26, sau đó xây dựng Feature Engineering Engine tuân thủ nghiêm ngặt nguyên tắc chống rò rỉ (anti-leakage lag 1 trận, temporal rolling, Gamma-Poisson rate shrinkage, context sân nhà/khách, B2B, opponent defense/pace context và data quality flags).

**Architecture:** 
- `src/pipeline/backfill.py`: Mở rộng backfill cho toàn bộ các mùa yêu cầu với lưu vết checkpoints.
- `src/features/rolling.py`: Tính toán rolling stats (mean, std 5/10/20 trận, decay weighted mean) với `shift(1)` bắt buộc để loại trừ trận hiện tại.
- `src/features/context.py`: Tính toán lịch thi đấu, ngày nghỉ (`rest_days`), cờ `is_b2b`, sân nhà/khách (`is_home`), và đặc trưng đội đối thủ từ lịch sử quá khứ.
- `src/features/shrinkage.py`: Mô hình Gamma-Poisson rate shrinkage theo phút với thời gian suy giảm (decay weights), tính $n_{eff}$ và exposure.
- `src/features/builder.py`: Pipeline gộp toàn bộ features theo từng `(player_id, game_id)` trước cutoff thời gian, sinh data quality flags (`is_rookie`, `days_since_last_game`, `insufficient_data`).
- `tests/test_features_*.py`: Kiểm thử chống leakage (đảm bảo stat trận đích không bao giờ lọt vào feature), kiểm thử shrinkage và context.

**Tech Stack:** Python 3.14, `pandas`, `duckdb`, `pyarrow`, `pytest`.

**Spec:** [NBA_PLAYER_PROPS_PLAN.md](file:///D:/Project/NBA_props_prediction/NBA_PLAYER_PROPS_PLAN.md) (§7, §8, §8.1, §9, §15)

## Global Constraints

- **Tuyệt đối chống rò rỉ (Strict Anti-leakage)**: Mọi rolling features của trận $t$ chỉ được tính từ tập các trận $1, \dots, t-1$ của cầu thủ. Tuyệt đối không chứa minutes hoặc stat của trận $t$.
- **Temporal Integrity**: Dữ liệu đối thủ (opponent pace, defensive rating) cũng phải là rolling stats chỉ từ các trận quá khứ của đối thủ trước ngày trận đấu diễn ra.
- **Data Quality Flags**: Gắn nhãn rõ ràng: `insufficient_data` (số trận quá khứ < 5), `is_rookie`, `is_returning_rest` (nghỉ > 14 ngày).
- **Phân tách số thực**: Phút thi đấu luôn là `float`, không dùng integer làm tròn bừa bãi.
- **Output Parquet**: Tập feature sau khi build lưu vào `data/parquet/features_{season}.parquet`.

## Review Focus

1. **Rò rỉ tương lai (Future Leakage)**: Rolling mean có vô tình tính cả trận hiện tại không? Test phải bắt buộc kiểm tra `feature(t)` không đổi khi thay đổi điểm số của trận $t$.
2. **Cầu thủ đổi đội giữa mùa**: Lịch sử phong độ cá nhân vẫn giữ, nhưng đối thủ và vai trò đội mới được cập nhật chính xác.
3. **Cầu thủ DNP / Inactive**: Các trận không thi đấu không được tính là 0 phút / 0 điểm trong rate model có điều kiện thi đấu.
4. **Exposure trong Shrinkage**: Khi không có dữ liệu (n_eff = 0), shrinkage rate phải quay về prior mean một cách ổn định, không chia cho 0.
5. **Backfill Resilience**: Khi tải mạng gặp timeout hoặc gián đoạn, checkpoint phải ghi nhận chính xác và tiếp tục tự động.

---

### Task 1: Chạy Backfill hoàn tất các mùa 2023-24 và 2025-26

**Files:**
- Modify: `src/pipeline/backfill.py`
- Output: `data/parquet/schedule_2023-24.parquet`, `data/parquet/player_gamelogs_2023-24.parquet`, `data/parquet/team_gamelogs_2023-24.parquet`
- Output: `data/parquet/schedule_2025-26.parquet`, `data/parquet/player_gamelogs_2025-26.parquet`, `data/parquet/team_gamelogs_2025-26.parquet`

**Steps:**
- [x] Chạy pipeline backfill cho mùa `2023-24` và `2025-26`.
- [x] Kiểm tra tính toàn vẹn của parquet files (số dòng, số cột, không rỗng).
- [x] Xác nhận `checkpoints.json` cập nhật đầy đủ trạng thái `COMPLETED`.

---

### Task 2: Xây dựng Module Rolling Features với cơ chế chống rò rỉ (Lag-1)

**Files:**
- Create: `src/features/rolling.py`
- Create: `tests/test_features_rolling.py`

**Steps:**
- [x] Viết test `tests/test_features_rolling.py`:
  - Test kiểm tra `shift(1)`: giá trị feature tại trận $k$ chỉ phụ thuộc trận $1 \dots k-1$.
  - Test rolling windows (5, 10, 20 trận) cho PTS, REB, AST, MIN, FGA, FTA, 3PA.
  - Test trọng số suy giảm thời gian (exponential decay weights).
- [x] Triển khai `src/features/rolling.py`:
  - Hàm `compute_player_rolling_features(df, windows=[5, 10, 20], decay_halflife=10)`.
  - Tính mean, std, trend, và số trận quan sát được (`n_games_history`).
- [x] Chạy test `tests/test_features_rolling.py` đảm bảo pass.

---

### Task 3: Xây dựng Module Context (Sân nhà/khách, B2B, Ngày nghỉ & Đối thủ)

**Files:**
- Create: `src/features/context.py`
- Create: `tests/test_features_context.py`

**Steps:**
- [x] Viết test `tests/test_features_context.py`:
  - Tính `rest_days` từ khoảng cách giữa ngày trận hiện tại và trận trước.
  - Nhận diện `is_b2b` (rest_days == 1).
  - Trích xuất `is_home` từ MATCHUP (`vs.` = Home, `@` = Away).
  - Tính rolling defensive context của đối thủ (pace, pts allowed, reb allowed, ast allowed) từ các trận quá khứ của đối thủ.
- [x] Triển khai `src/features/context.py`.
- [x] Chạy test `tests/test_features_context.py` đảm bảo pass.

---

### Task 4: Xây dựng Module Gamma-Poisson Rate Shrinkage

**Files:**
- Create: `src/features/shrinkage.py`
- Create: `tests/test_features_shrinkage.py`

**Steps:**
- [x] Viết test `tests/test_features_shrinkage.py`:
  - Kiểm tra công thức $\hat{\rho} = (\alpha + \sum w X) / (\beta + \sum w M)$ theo đúng §8.1.
  - Kiểm tra tính $n_{eff} = (\sum w)^2 / \sum w^2$ và exposure giả $\sum w M$.
  - Khi không có dữ liệu lịch sử ($M=0$), trả về prior mean $\alpha / \beta$ và $n_{eff}=0$.
- [x] Triển khai `src/features/shrinkage.py`.
- [x] Chạy test `tests/test_features_shrinkage.py` đảm bảo pass.

---

### Task 5: Pipeline Tích hợp Feature Builder & Data Quality Flags

**Files:**
- Create: `src/features/builder.py`
- Create: `tests/test_feature_builder.py`
- Create: `scripts/build_features.py`

**Steps:**
- [x] Viết test `tests/test_feature_builder.py`:
  - Gộp rolling stats, context, opponent stats và shrinkage rate thành 1 DataFrame hoàn chỉnh.
  - Kiểm tra sinh các cờ: `insufficient_data`, `is_rookie`, `days_since_last_game`, `is_returning_rest`.
  - Kiểm định chống rò rỉ: giá trị stat của trận hiện tại không tồn tại trong tập feature vector.
- [x] Triển khai `src/features/builder.py`.
- [x] Viết script `scripts/build_features.py` để sinh tập feature cho mùa 2023-24, 2024-25, 2025-26.
- [x] Chạy script và xuất file Parquet `data/parquet/features_2024-25.parquet`.
