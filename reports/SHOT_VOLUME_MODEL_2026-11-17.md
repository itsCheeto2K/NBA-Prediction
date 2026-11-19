# Model 3: Khối lượng ném dự kiến

Đã huấn luyện model Poisson dự báo FGA trước trận, có điều kiện cầu thủ ra sân. Đầu vào gồm lịch sử FGA 5/10/20 trận, lịch sử phút, PTS, FTA, 3PA và lịch thi đấu. Model được train bằng mùa 2023-24; trọng số pha với baseline L5 được chọn trên đầu mùa 2024-25. Hai mùa 2025-26 và 2026-27 chỉ dùng để kiểm tra.

| Giai đoạn | MAE baseline L5 | MAE model | Số dòng |
|---|---:|---:|---:|
| Đầu 2024-25 (chọn cấu hình) | 2.861 | 2.783 | 8,681 |
| 2025-26 (giữ lại) | 2.890 | 2.825 | 26,649 |
| 2026-27 (giữ lại) | 2.994 | 2.953 | 4,618 |

Model đã qua ngưỡng giảm MAE tối thiểu 0,5% trên cả tập chọn cấu hình và từng mùa giữ lại. Artifact nằm tại `data/aux_models/shot_volume/sync_fc94ec9f14`; bản báo cáo số liệu đầy đủ nằm trong `evaluation.json` cùng thư mục. API `POST /api/predict` trả `shot_volume_projection.expected_fga`, và giao diện hiển thị Expected shots dưới Playing Time. Khi dataset sync sang snapshot khác cần train lại bằng `python scripts/train_shot_volume.py`; API chỉ nạp model gắn đúng phiên bản snapshot.

FGA dự báo hiện là đầu ra riêng; model PTS đang chạy chưa có feature FGA dự báo trong schema. Đã chạy thử đủ 48 cấu hình PTS sau khi tạo FGA dự báo cho dữ liệu train theo trình tự thời gian. Kết quả RPS xấu hơn 0,097% trên các mùa giữ lại, nên giữ model PTS hiện hành. Xem [báo cáo đối chiếu](SHOT_VOLUME_PTS_COMPARISON_2026-11-17.md).
