# NBA Player Props Prediction

Ứng dụng dự đoán phân phối điểm số cầu thủ NBA cho các market PTS, REB và AST. Backend dùng FastAPI; giao diện web được phục vụ trực tiếp từ ứng dụng.

## Tính năng

- Xác suất Over / Under / Push từ phân phối xác suất điểm rời rạc.
- EV dựa trên line và decimal odds do người dùng nhập.
- Lịch sử trận đấu, matchup, roster, injury context và thông tin lịch thi đấu.
- FastCheck cho nhiều cầu thủ cùng lúc và nhập odds bằng OCR.
- Đồng bộ game logs và xây dựng feature dataset theo mùa.

Xác suất là ước lượng của model; chúng không đảm bảo kết quả trận đấu hay lợi nhuận cược. Project hiện không lưu historical bookmaker odds theo thời điểm dự đoán, nên báo cáo backtest không chứng minh ROI cược thực tế.

## Chạy local

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts/run_app.py
```

Mở giao diện tại [http://localhost:8000](http://localhost:8000), FastCheck tại [http://localhost:8000/fastcheck](http://localhost:8000/fastcheck), và API docs tại [http://localhost:8000/docs](http://localhost:8000/docs).

Để chạy bộ test Python, cài thêm `requirements-dev.txt`, rồi chạy `python -m pytest`.

## Dữ liệu và model

- `data/parquet/` chứa bộ parquet seed được dùng cho chạy local và khởi tạo ứng dụng.
- Raw API cache, sync snapshots, role evidence và release artifacts được sinh trong quá trình chạy; chúng không thuộc source code và được loại khỏi Git.
- Model baseline trong `models/` được version cùng source. Model release mới và snapshot dữ liệu cần được lưu/backup riêng khi triển khai.
- NBA Stats API được dùng để lấy schedule và game logs; ESPN được dùng cho injury feed. API bên ngoài có thể giới hạn request hoặc thay đổi dữ liệu.

Backfill hai mùa 2021–22 và 2022–23, sau đó dựng snapshot feature:

```powershell
python scripts/backfill_history.py
```

Huấn luyện và chọn release qua gate RPS/log-score:

```powershell
python scripts/train_extended_release.py
```

Release mới chỉ được dùng nếu qua gate; nếu không, model hiện hành được giữ lại. Xem các báo cáo tóm tắt trong `reports/`.

## Cấu hình môi trường

Các giá trị mẫu nằm trong `.env.example`. Biến quan trọng:

| Biến | Mục đích |
|---|---|
| `NBA_DATA_DIR` | Root dữ liệu; đặt vào persistent disk khi host |
| `NBA_RAW_DIR` | Tùy chọn: override thư mục raw cache |
| `NBA_PARQUET_DIR` | Tùy chọn: override thư mục parquet |
| `NBA_REPORTS_DIR` | Tùy chọn: thư mục báo cáo |
| `NBA_SEASONS` | Danh sách mùa, phân cách bằng dấu phẩy và xếp theo thời gian |
| `NBA_ACTIVE_SEASON` | Mùa dùng cho sync, roster và schedule hiện tại |
| `SYNC_CRON_SECRET` | Bearer secret cho scheduled sync endpoint |

Cron service gọi `POST /api/internal/cron/sync` với header `Authorization: Bearer <SYNC_CRON_SECRET>`. Hãy lưu secret trong cấu hình môi trường của host; không ghi secret thật vào GitHub hoặc frontend. Endpoint trả `503` nếu secret chưa được cấu hình.

## Cấu trúc project

```text
src/api/          FastAPI routes, schemas và frontend tĩnh
src/collectors/   NBA/ESPN clients, schedule, logs và sync
src/features/     Feature engineering theo thời điểm trước trận
src/models/       Model training, selection và bundles
src/distribution/ PMF/CDF, calibration, pricing và settlement
src/storage/      Snapshot dataset và manifest
scripts/          Chạy app, backfill, huấn luyện và nghiên cứu
tests/            Python và JavaScript regression tests
docs/             Kế hoạch và tài liệu kỹ thuật
reports/          Báo cáo nghiên cứu, audit và model
```

## Tài liệu

- [Kế hoạch model và feature](NBA_PLAYER_PROPS_PLAN.md)
- [Chiến lược NBA props](NBA_PROPS_BETTING_STRATEGY_PLAYBOOK.md)
- [Tài liệu API collector và sync](NBA_OPERATIONS_COLLECTOR_API_REVIEW_AND_FIX_SPEC.md)
- Các specification chi tiết khác nằm ở thư mục gốc và trong `docs/`.
