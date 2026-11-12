# NBA Player Props: Phase 0 (Feasibility) & Phase 1 (Data Ingestion) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Xây dựng nền tảng thu thập và chuẩn hóa dữ liệu NBA (`nba_api`), bao gồm hệ thống cache raw JSON có mã băm SHA256, rate-limiting chống ban IP, kiểm tra khả thi các endpoint P0/P1, chuẩn hóa dữ liệu và pipeline backfill có checkpoint.

**Architecture:** Thiết kế module hóa hướng dữ liệu (data-driven): `src/config` quản lý hằng số và endpoint parameters; `src/client` bọc `nba_api` với rate-limiting, retry và raw disk caching; `src/collectors` thu thập từng endpoint P0/P1; `src/storage` lưu raw JSON và Parquet; `tests/` kiểm thử đơn vị và kiểm thử tích hợp chống rò rỉ (leakage).

**Tech Stack:** Python 3.14 (hoặc venv Python 3.10+), `nba_api`, `pandas`, `pydantic`, `pyarrow`, `duckdb`, `pytest`.

**Spec:** [NBA_PLAYER_PROPS_PLAN.md](file:///D:/Project/NBA_props_prediction/NBA_PLAYER_PROPS_PLAN.md) (§3, §5, §6, §7, §14, §15)

## Global Constraints

- `game_id` luôn là chuỗi 10 ký tự có số `00` ở đầu (ví dụ: `"0022400061"`), không dùng `int`.
- Tham số `season` luôn truyền tường minh (ví dụ: `"2024-25"`), không dùng default tự suy diễn.
- Tuân thủ rate limit: tối thiểu 1.0 giây nghỉ giữa các request stats.nba.com, `timeout=60`, có retry & backoff.
- Mọi response thô (raw) phải được lưu cache kèm metadata: endpoint name, parameters, fetched_at, và sha256_hash.
- Ưu tiên endpoint V3 (`BoxScoreTraditionalV3`, `BoxScoreAdvancedV3`), không sử dụng endpoint V2 đã bị loại bỏ.
- Phân biệt rõ rệt giữa: không thi đấu (DNP/Inactive), thi đấu 0 stat, dữ liệu chưa về (null), và lỗi parse. Phút thi đấu chuẩn hóa về số thực (float).

## Review Focus

1. `stats.nba.com` trả về timeout hoặc throttling: Client phải xử lý backoff hợp lý và không retry vô hạn.
2. `game_id` mất số 0 đầu: Bắt buộc ép kiểu chuỗi `str` từ tầng schema/validator.
3. Box score V3 chứa camelCase và cấu trúc lồng nhau: Bộ parser phải trích xuất đúng `player_stats` / `team_stats` sang schema phẳng chuẩn.
4. Cầu thủ DNP / Inactive ghi nhận trong box score: Không tự ý điền 0 mà phải đánh dấu trạng thái `did_not_play` hoặc `is_active=False`.
5. Checkpoint ngắt quãng giữa chừng khi backfill: Collector có thể tiếp tục từ mốc bị gián đoạn mà không bị trùng lặp dữ liệu.

---

### Task 1: Thiết lập môi trường, cấu hình và dependencies

**Files:**
- Create: `requirements.txt`
- Create: `src/__init__.py`
- Create: `src/config.py`
- Create: `tests/__init__.py`
- Create: `tests/test_config.py`

**Steps:**
- [x] Tạo file `requirements.txt` với `nba_api>=1.6.0`, `pandas>=2.0.0`, `pydantic>=2.0.0`, `pyarrow`, `duckdb`, `pytest`.
- [x] Cài đặt dependencies vào môi trường Python hiện hành.
- [x] Viết test `tests/test_config.py` kiểm tra các tham số mặc định: seasons (`2023-24` đến `2026-27`), data paths, request timeout, request delay.
- [x] Viết code `src/config.py` định nghĩa các Settings (dùng Pydantic Settings hoặc dataclass) và enum mùa giải/loại trận.
- [x] Chạy `pytest tests/test_config.py` đảm bảo pass.

---

### Task 2: Xây dựng Ingestion Client & Raw Response Cache

**Files:**
- Create: `src/client.py`
- Create: `tests/test_client.py`

**Steps:**
- [x] Viết test `tests/test_client.py` kiểm tra:
  - Cache key generation từ endpoint name và params.
  - Lưu và đọc raw JSON cache kèm metadata (`fetched_at`, `sha256_hash`).
  - Rate limiting logic (đo khoảng cách thời gian giữa các lời gọi).
- [x] Viết code `src/client.py`:
  - `NBAClient` class bọc việc gọi endpoint với `get_request=False`, kiểm tra cache trước khi gửi.
  - Lưu file raw JSON vào thư mục `data/raw/{endpoint}/{hash_or_key}.json`.
  - Cơ chế retry khi gặp `ReadTimeout` hoặc lỗi mạng tạm thời (tối đa 3 lần với exponential backoff).
- [x] Chạy `pytest tests/test_client.py` đảm bảo pass.

---

### Task 3: Thu thập dữ liệu P0 (Static Reference, Schedule, GameLogs)

**Files:**
- Create: `src/collectors/static.py`
- Create: `src/collectors/schedule.py`
- Create: `src/collectors/gamelogs.py`
- Create: `tests/test_p0_collectors.py`

**Steps:**
- [x] Viết test `tests/test_p0_collectors.py`:
  - Kiểm tra tra cứu static `players` và `teams` không cần request mạng.
  - Kiểm tra định dạng schedule trả về có đúng `game_id` (chuỗi 10 ký tự), ngày giờ thi đấu.
  - Kiểm tra `PlayerGameLogs` trích xuất được các cột PTS, REB, AST, MIN.
- [x] Triển khai `src/collectors/static.py`: Tra cứu offline, xuất bảng chuẩn `players` và `teams`.
- [x] Triển khai `src/collectors/schedule.py`: Gọi `ScheduleLeagueV2`, chuẩn hóa lịch thi đấu.
- [x] Triển khai `src/collectors/gamelogs.py`: Gọi `PlayerGameLogs` và `LeagueGameLog` cấp đội cho một mùa giải.
- [x] Chạy test `tests/test_p0_collectors.py`.

---

### Task 4: Thu thập dữ liệu P1 & Xác nhận Feasibility BoxScore V3 (Phase 0 Milestone)

**Files:**
- Create: `src/collectors/boxscore.py`
- Create: `tests/test_boxscore_v3.py`
- Create: `scripts/verify_phase0_feasibility.py`

**Steps:**
- [x] Viết test `tests/test_boxscore_v3.py` kiểm tra parser trích xuất `BoxScoreTraditionalV3` và `BoxScoreAdvancedV3` từ mẫu response JSON.
- [x] Triển khai `src/collectors/boxscore.py`:
  - Lấy `BoxScoreTraditionalV3` và `BoxScoreAdvancedV3` theo `game_id`.
  - Chuẩn hóa cột: chuyển đổi camelCase thành snake_case, chuẩn hóa phút `MIN` sang float (ví dụ `"34:25"` -> `34.417`).
  - Nhận diện trạng thái DNP / Did Not Dress / Inactive.
- [x] Viết script `scripts/verify_phase0_feasibility.py`:
  - Chọn 1-2 trận đấu thực tế đã kết thúc (ví dụ mùa 2024-25 hoặc 2025-26).
  - Tải GameLog, Schedule, Traditional BoxScore V3 và Advanced BoxScore V3.
  - Khớp đối chiếu (reconcile) chỉ số cầu thủ giữa GameLog và BoxScore V3.
  - Ghi log báo cáo nghiệm thu Phase 0 vào `reports/phase0_feasibility_report.json`.
- [x] Chạy script và xác nhận Phase 0 hoàn thành.

---

### Task 5: Pipeline Backfill & Quản lý Checkpoints (Phase 1)

**Files:**
- Create: `src/storage/manifest.py`
- Create: `src/pipeline/backfill.py`
- Create: `tests/test_backfill.py`

**Steps:**
- [x] Viết test `tests/test_backfill.py` kiểm tra việc lưu vết tiến trình (checkpoint), ghi nhận số dòng, trạng thái từng batch, và khả năng resume khi có lỗi.
- [x] Triển khai `src/storage/manifest.py`: Quản lý `ingestion_runs` và checkpoint state (lưu file JSON/SQLite/DuckDB).
- [x] Triển khai `src/pipeline/backfill.py`:
  - Hỗ trợ backfill theo mùa (`2023-24`, `2024-25`, `2025-26`).
  - Chia nhỏ batch theo tháng/khoảng ngày để tránh quá tải.
  - Tích hợp rate limit và checkpoint tự động.
- [x] Chạy test `tests/test_backfill.py`.
