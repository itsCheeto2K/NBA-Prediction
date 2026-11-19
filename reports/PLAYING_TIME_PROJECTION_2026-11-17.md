# Dự đoán phút thi đấu và starter

Release: `playing_time_7348952c50e5`

## Phút thi đấu

Dự đoán trung bình phút và khoảng dự đoán mục tiêu 80%, với điều kiện cầu thủ có vào sân. Bao gồm hiệp phụ; không ép phút tối đa về 48. Không suy diễn chỉ định giới hạn phút từ số phút thấp.

Phương pháp trung bình được chọn: `lgbm`. Train: mùa 2023-24; chọn cấu hình: đầu 2024-25 đến 19/12/2024; calibration khoảng dự đoán: phần còn lại 2024-25; kiểm tra sau đó: 2025-26 và 2026-27.

| Tập kiểm tra | MAE rolling L5 | MAE dự đoán | Độ phủ khoảng 80% | Độ rộng khoảng (phút) |
|---|---:|---:|---:|---:|
| 2025-26 | 5.144 | 5.017 | 82.1% | 16.45 |
| 2026-27 | 5.542 | 5.235 | 80.5% | 16.63 |

## Starter — chỉ là dự đoán

Dữ liệu gamelog hiện không có nhãn starter lịch sử đủ để huấn luyện classifier hoặc kiểm chứng xác suất. Không gán starter từ phút đã chơi để tạo nhãn thật. API dự đoán vai trò từ thứ hạng phút dự kiến trong roster hiện tại, bỏ cầu thủ Out khi injury report còn mới. Hai vị trí thứ 5/6 cách nhau dưới 2 phút được ghi Uncertain. Nếu roster thiếu/cũ hoặc thiếu lịch sử rotation thì ghi Unknown. Không trả phần trăm starter, không gọi đây là verified lineup. Cầu thủ dự bị chơi nhiều phút có thể bị dự đoán nhầm starter.

## Thử nghiệm đưa vào model Points

Bốn feature: phút dự kiến, phân vị thấp/cao và độ rộng khoảng chưa calibration. Các dòng train dùng dự đoán mở rộng theo thời gian, chỉ fit từ những ngày trước ngày cần dự đoán. Ngày warmup dùng baseline lagged. Calibration học từ mùa sau không được dùng ngược làm feature. Model PTS cũ có 105 feature; ứng viên thêm 4 feature phút, không ép sử dụng lại 112 stats vừa không cải thiện.

PTS RPS cũ: **3.30211**; ứng viên: **3.29898**; cải thiện: **0.09%**. Kết quả: **Giữ model PTS cũ**.

Đã chạy đủ 48 cấu hình PTS. REB/AST giữ model hiện hành. Không nhân trực tiếp điểm dự đoán theo phút và không thay công thức EV/settlement. Quyết định phát hành dùng tập kiểm tra; cần dữ liệu tương lai để xác nhận. Chưa có odds lịch sử để kết luận tăng tỷ lệ thắng cược hay ROI.

Chi tiết: `data/releases/playing_time_7348952c50e5/reports/playing_time_report.json`.

## Kiểm tra thực thi

- Toàn bộ Python: 234 kiểm tra đạt; kiểm tra riêng Playing Time sau thay đổi cuối: 10 đạt.
- JavaScript: 41 kiểm tra đạt.
- API thực tế đã kiểm tra Donovan Mitchell và Payton Pritchard; trả dự đoán phút, khoảng và starter.
- Không dùng model hoặc trạng thái cầu thủ từ tương lai cho dự đoán phút của trận lịch sử.
