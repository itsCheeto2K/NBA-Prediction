# NBA Player Props: Phase 3 to Phase 6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hoàn thiện toàn bộ hệ thống dự đoán NBA Player Props từ Giai đoạn 3 đến Giai đoạn 6: Huấn luyện mô hình CatBoost/LightGBM Poisson, xây dựng động cơ phân phối xác suất rời rạc (NB2/Poisson) & hiệu chỉnh CDF (Isotonic Calibration, proper RPS), xử lý các nhóm đặc biệt, và dựng hệ thống API FastAPI kèm giao diện Web Dashboard sang trọng theo chuẩn thiết kế Linear (`awesome-design-md`).

**Architecture:**
- `src/models/baseline.py`: Baseline trung bình trượt và phút $\times$ rate.
- `src/models/trainer.py`: Pipeline huấn luyện LightGBM và CatBoost với Poisson loss (log-link) trên tập B0/B1, lưu model weights vào `models/`.
- `src/distribution/engine.py`: Động cơ phân phối rời rạc (Poisson / Negative Binomial 2), tính $F(k)$, tính $q_{over}, q_{under}, q_{push}$ tại bất kỳ line nào.
- `src/distribution/calibration.py`: Isotonic CDF recalibration (Đường A stats-only qua full-RPS).
- `src/distribution/pricing.py`: Multiplicative de-vig, tính EV tại odds thực tế, tính ngưỡng hòa vốn.
- `src/api/main.py`: FastAPI server cung cấp REST endpoints tra cứu cầu thủ, lịch đấu, dự đoán phân phối và tính EV.
- `web/`: Giao diện Dashboard hiện đại theo chuẩn Linear (`awesome-design-md/design-md/linear.app/DESIGN.md`) hiển thị danh sách cầu thủ, biểu đồ PMF phân phối xác suất, bảng tính Over/Under/Push và phân tích EV.

**Tech Stack:** Python 3.14, `catboost`, `lightgbm`, `scipy`, `sklearn`, `fastapi`, `uvicorn`, `pandas`, `pyarrow`, TailwindCSS / Chart.js.

**Spec:** [NBA_PLAYER_PROPS_PLAN.md](file:///D:/Project/NBA_props_prediction/NBA_PLAYER_PROPS_PLAN.md) (§2, §10, §11, §12, §13, §14, §15)

## Global Constraints

- **Mục tiêu mô hình**: Poisson loss với log-link $\mu = \exp(f(x))$, bảo đảm dự đoán kỳ vọng không âm $\mu > 0$.
- **Tập chia theo thời gian**: B0 (2023-24) làm train, B1 (1/3 đầu 2024-25) làm validation.
- **Phân phối rời rạc hợp lệ**: $\sum_{k=0}^{K} p(k) = 1$, $p(k) \ge 0$, CDF đơn điệu không giảm.
- **Xác suất Over / Under / Push**:
  - $q_{over} = 1 - F(\lfloor L \rfloor)$
  - $q_{under} = F(\lceil L \rceil - 1)$
  - $q_{push} = p(L)$ khi $L$ nguyên, ngược lại $= 0$.
- **Giao diện**: Tuân thủ bảng màu Linear `#010102` (canvas), `#0f1011` (surface), `#5e6ad2` (lavender primary accent), viền hairline `#23252a`.

---

### Task 1: Xây dựng Baselines & Huấn luyện Mô hình ML (CatBoost & LightGBM Poisson) - Phase 3

**Files:**
- Create: `src/models/baseline.py`
- Create: `src/models/trainer.py`
- Create: `tests/test_models.py`
- Output: `models/lgbm_pts.txt`, `models/lgbm_reb.txt`, `models/lgbm_ast.txt`
- Output: `models/catboost_pts.cbm`, `models/catboost_reb.cbm`, `models/catboost_ast.cbm`
- Output: `reports/phase3_models_benchmark.json`

**Steps:**
- [x] Viết test `tests/test_models.py`:
  - Test baseline predictions (weighted average, rate * minutes).
  - Test Poisson deviance metric calculation.
  - Test LightGBM / CatBoost model inference outputting strictly positive expected values.
- [x] Triển khai `src/models/baseline.py`: Baseline models.
- [x] Triển khai `src/models/trainer.py`:
  - Chuẩn bị ma trận đặc trưng từ `features_all_seasons.parquet`.
  - Chia tập B0 (train) và B1 (validation).
  - Huấn luyện cho 3 chỉ số: PTS, REB, AST.
  - Đánh giá RMSE, MAE, Poisson deviance so sánh giữa Baseline, LightGBM và CatBoost.
  - Lưu model artifacts vào `models/`.
- [x] Chạy huấn luyện và sinh báo cáo `reports/phase3_models_benchmark.json`.
- [x] Chạy `pytest tests/test_models.py` đảm bảo pass.

---

### Task 2: Động cơ Phân phối Xác suất Rời rạc & Hiệu chỉnh CDF (Phase 4)

**Files:**
- Create: `src/distribution/engine.py`
- Create: `src/distribution/calibration.py`
- Create: `src/distribution/pricing.py`
- Create: `tests/test_distribution.py`

**Steps:**
- [x] Viết test `tests/test_distribution.py`:
  - Test tính PMF và CDF từ Negative Binomial (NB2) và Poisson.
  - Test tính $q_{over}, q_{under}, q_{push}$ tại line nửa điểm (24.5) và line nguyên (25.0).
  - Test tổng xác suất $\sum p = 1.0$.
  - Test Isotonic calibration bảo đảm tính đơn điệu của CDF.
  - Test de-vig và EV calculation.
- [x] Triển khai `src/distribution/engine.py`:
  - Lớp `DiscreteDistributionEngine`: nhận $\mu$ và dispersion $\phi$, sinh PMF từ $k=0$ đến 70.
  - Tính CDF, quantile, prediction intervals (90%), median.
  - Hàm `calculate_line_probabilities(cdf_fn, line)`.
- [x] Triển khai `src/distribution/calibration.py`:
  - `IsotonicCDFCalibrator`: fit trên tập B2, áp dụng biến đổi đơn điệu $G(u)$.
- [x] Triển khai `src/distribution/pricing.py`:
  - Bỏ vig (multiplicative normalization).
  - Tính EV và ROI hòa vốn theo §12.2.
- [x] Chạy test `tests/test_distribution.py` đảm bảo pass.

---

### Task 3: Xử lý Nhóm Đặc biệt & Operational Flags (Phase 5)

**Files:**
- Create: `src/distribution/special_groups.py`
- Create: `tests/test_special_groups.py`

**Steps:**
- [x] Viết test `tests/test_special_groups.py`:
  - Xử lý tân binh (Rookie): mở rộng khoảng dự đoán, tăng độ phân tán dispersion $\phi$.
  - Cầu thủ nghỉ dài (> 14 ngày): scenario fallback, cảnh báo giới hạn phút thi đấu.
  - Trạng thái `ready`, `scenario_only`, `insufficient_data`.
- [x] Triển khai `src/distribution/special_groups.py`.
- [x] Chạy test `tests/test_special_groups.py` đảm bảo pass.

---

### Task 4: Xây dựng Backend API (FastAPI) & Verification (Phase 6 Backend)

**Files:**
- Create: `src/api/main.py`
- Create: `src/api/schemas.py`
- Create: `tests/test_api.py`

**Steps:**
- [x] Viết test `tests/test_api.py`:
  - Test endpoint `GET /api/health`.
  - Test endpoint `GET /api/players` và `GET /api/teams`.
  - Test endpoint `POST /api/predict`: trả về $\mu$, median, interval, xác suất Over/Under/Push, PMF và EV.
- [x] Triển khai `src/api/schemas.py`: Pydantic request/response models.
- [x] Triển khai `src/api/main.py`: Khởi tạo FastAPI app, load models và pipeline, cung cấp endpoints.
- [x] Chạy test `tests/test_api.py` đảm bảo pass.

---

### Task 5: Xây dựng Web UI Dashboard theo chuẩn Linear (Phase 6 Frontend)

**Files:**
- Create: `src/api/static/index.html`
- Create: `src/api/static/app.js`
- Create: `src/api/static/styles.css`
- Create: `scripts/run_app.py`

**Steps:**
- [x] Xây dựng giao diện web ứng dụng chuẩn thiết kế Linear từ `awesome-design-md/design-md/linear.app/DESIGN.md`:
  - Dark canvas (`#010102`), thẻ surface (`#0f1011`), viền hairline (`#23252a`), accent lavender (`#5e6ad2`).
  - Thanh tìm kiếm và chọn cầu thủ (Donovan Mitchell, Jayson Tatum, LeBron James, Nikola Jokic...).
  - Chọn stat (Points, Rebounds, Assists) và nhập line / odds tùy ý.
  - Thẻ hiển thị Kỳ vọng $\mu$, Median, Khoảng tin cậy 90% (Prediction Interval).
  - Đồng hồ hiển thị xác suất Over, Under, Push và Giá trị kỳ vọng EV.
  - Biểu đồ phân phối xác suất PMF trực quan tương tác (Chart.js styled dark mode).
  - Badge cảnh báo chất lượng dữ liệu (Data Quality Flags: Ready, Insufficient Data, Extended Rest).
- [x] Viết script `scripts/run_app.py` để khởi chạy server một chạm.
- [x] Kiểm thử tích hợp toàn bộ luồng hoạt động từ trình duyệt/API.
