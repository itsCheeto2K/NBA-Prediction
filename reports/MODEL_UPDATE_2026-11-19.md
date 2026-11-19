# Cập nhật model và dữ liệu NBA — 2026-11-19

## Thay đổi đã áp dụng trong code

- Cấu hình pipeline bao gồm thêm hai mùa `2021-22` và `2022-23`, giữ thứ tự thời gian và `2026-27` là mùa hiện tại.
- Hai quy trình phát hành model (`rebuild_release.py` và `train_extended_release.py`) nay dùng các mùa `2021-22` đến `2023-24` làm tập train; phần đầu mùa `2024-25` vẫn dành riêng cho chọn cấu hình. Các mùa sau vẫn là holdout.
- Bộ hiệu chỉnh phân phối chọn mẫu đại diện trên toàn bộ khối calibration theo thứ tự thời gian, thay vì chỉ lấy 300 dòng đầu. Việc lấy mẫu nay có seed cố định để lần chạy lại cho cùng kết quả.
- Khi nhiều recipe có RPS gần như ngang nhau, model ưu tiên recipe không làm negative log-score xấu hơn quá 1% so với phương án tốt nhất. Đây là guard chống calibration quá khớp; nếu không có recipe thỏa điều kiện, selector vẫn dùng quy tắc cũ và bật cảnh báo metric conflict.
- Thêm `scripts/backfill_history.py`; script tải hai mùa, kiểm tra schedule/team/player logs và không cho retrain khi audit chưa `COMPLETE`.

## Tình trạng dữ liệu lần chạy này

Đã thử tải schedule, player logs và team logs mùa `2021-22` từ NBA Stats API. Môi trường chặn kết nối socket (`WinError 10013`), vì vậy hai mùa mới chưa được lưu vào parquet và model chưa được huấn luyện/phát hành lại. Không có dữ liệu cũ phù hợp khác trong thư mục data hiện tại. Những file parquet hiện có vẫn chỉ bắt đầu từ `2023-24`.

Sau khi có kết nối mạng, chạy:

```powershell
python scripts/backfill_history.py
python scripts/train_extended_release.py
```

Lệnh backfill ghi parquet, kiểm tra completeness rồi publish snapshot dữ liệu và feature mới; nó không thay model đang chạy. Lệnh train chạy qua gate so sánh RPS, negative log-score và từng mùa holdout trước khi chuyển bundle. Nếu gate không đạt, model đang chạy được giữ nguyên.

## Cơ sở nghiên cứu và giới hạn

Proper scoring rules như Ranked Probability Score và logarithmic score đánh giá các khía cạnh khác nhau của phân phối xác suất; vì thế không nên chọn calibration chỉ theo một metric. Xem [Gneiting & Raftery (2007)](https://sites.stat.washington.edu/raftery/Research/PDF/Gneiting2007jasa.pdf). Nghiên cứu về dự đoán NBA cũng nhấn mạnh phân biệt accuracy với calibration, nhưng kết quả moneyline không thể coi là bằng chứng trực tiếp cho player props: [Walsh & Joshi (2023)](https://arxiv.org/abs/2303.06021).

Không có line/odds lịch sử tại thời điểm dự đoán trong project nên chưa thể suy ra ROI cược hoặc chứng minh thuật toán làm tăng tỷ lệ thắng. Thay đổi calibration này hướng đến độ tin cậy của phân phối; nó không hứa hẹn đảo chiều các kèo Over/Under.
