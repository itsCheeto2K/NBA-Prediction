# Kiểm định FGA dự báo trong công thức Points

Đã thêm `shot_expected_fga` vào bộ feature PTS 105 cột hiện hành và chạy lại đủ 48 cấu hình mean/phân phối/calibration. Các dự báo FGA ở tập train được tạo theo từng khối ngày mở rộng, chỉ fit từ trận đã diễn ra trước khối đó; đầu mùa warmup dùng FGA L5. Các mùa giữ lại được dự báo bằng model FGA fit trên 2023-24. Chỉ cầu thủ đã ra sân được đưa vào tập đánh giá PTS có điều kiện.

| Tập kiểm tra | Số dòng | RPS PTS hiện hành | RPS PTS + FGA dự báo | Log-score cũ | Log-score mới | Độ phủ 90% cũ → mới |
|---|---:|---:|---:|---:|---:|---:|
| Phần cuối 2024-25 | 17.622 | 3,32228 | 3,32199 | 3,20788 | 3,20706 | 89,58% → 89,09% |
| 2025-26 | 26.649 | 3,28716 | 3,29110 | 3,18831 | 3,18945 | 89,86% → 89,43% |
| 2026-27 đến 16/11 | 4.618 | 3,31146 | 3,32392 | 3,17912 | 3,18552 | 90,23% → 89,50% |
| Tổng theo số dòng | 48.889 | 3,30211 | 3,30533 | 3,19450 | 3,19543 | 89,80% → 89,31% |

RPS thấp hơn là tốt hơn. Ứng viên **xấu hơn 0,097% RPS** trên toàn bộ kỳ kiểm tra, trong đó cả hai mùa gần đây đều xấu hơn; log-score cũng xấu hơn. Gate phát hành yêu cầu cải thiện ít nhất 0,5% RPS và đã trả `passed=false`. **Quyết định: giữ model PTS hiện hành, không đưa `shot_expected_fga` vào PMF, Over%, EV.** Model FGA riêng vẫn có thể hiển thị để tham khảo.

File chi tiết: `reports/shot_volume_pts/comparison.json`; sổ 48 cấu hình: `reports/shot_volume_pts/model_selection_ledger_pts.json`. Có thể tái chạy bằng `python scripts/evaluate_shot_volume_pts.py`. Đây là kiểm định xác suất điểm, chưa phải backtest cược vì chưa có odds/line lịch sử theo thời điểm đặt vé.
