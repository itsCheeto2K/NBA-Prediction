# Model 4: Bối cảnh trận đấu

Đã thêm dự báo trước trận cho tổng điểm và nhịp trận (ước lượng số possessions). Mỗi đầu vào chỉ dùng tối đa 10 trận đã diễn ra trước ngày cần dự báo; xét cả điểm ghi, điểm nhận, nhịp và sân nhà/khách. Endpoint `POST /api/predict` trả `game_context_projection` khi có matchup xác định và đủ ít nhất 5 trận lịch sử cho mỗi đội. Giao diện hiển thị ô Game Context dưới Playing Time. Bản giao diện/API hiện tại không trả điểm dự kiến riêng của hai đội.

## Chọn phương pháp

Thử LightGBM dự báo tổng điểm và pace trên 1.230 trận mùa 2023-24. Tập chọn đầu 2024-25: MAE tổng điểm 15,673, cao hơn baseline L10 15,379; MAE pace 4,107 so với 4,002. Các mùa giữ lại cũng không cải thiện tổng điểm: 2024-25 (14,671 so với 14,610), 2025-26 (15,648 so với 15,353), 2026-27 (15,276 so với 14,924). Vì vậy giao diện dùng baseline L10 và model học máy không được phát hành. [Số liệu đầy đủ](../data/aux_models/game_context/sync_d67ab1009a/evaluation.json).

## Kiểm tra ảnh hưởng đến Points

Đã thử thêm `context_total`, `context_pace`, `context_team_points` vào 105 feature PTS hiện hành, huấn luyện lại đủ 48 cấu hình và chấm điểm trên các trận sau ngày chọn cấu hình 19/12/2024.

| Tập kiểm tra | Trận cầu thủ | RPS PTS cũ | RPS PTS + context |
|---|---:|---:|---:|
| Cuối 2024-25 | 17.622 | 3,322279 | 3,323747 |
| 2025-26 | 26.649 | 3,287161 | 3,287066 |
| 2026-27 | 4.618 | 3,311465 | 3,311062 |
| Tổng theo số dòng | 48.889 | 3,302115 | 3,302554 |

Tổng RPS xấu hơn 0,0133%; gate yêu cầu cải thiện ít nhất 0,5% nên không đổi model PTS, PMF, Over/Under hoặc EV. Log-score tổng cải thiện 3,19450 → 3,19064 nhưng không đủ để bù cho RPS. [Kết quả đầy đủ](game_context_pts/comparison.json).

Kiểm tra: 2 test chống dùng kết quả hiện tại/tương lai và lỗi nhãn sân nhà/khách đạt; API thực tế trả tổng 235,7 và pace 102,6 cho ví dụ CLE–MEM. Đây là ước lượng bối cảnh, không phải khuyến nghị cược. Dữ liệu hiện chưa có line và odds lịch sử tại đúng thời điểm đặt vé để kiểm định ROI.
