# Huấn luyện lại với các nhóm stats mở rộng

- Release: `extended_f736eb44b4a9`
- Recipe: `extended_boxscore_v1`
- Dữ liệu: 136,151 lượt thi đấu; mới nhất 2026-11-18 00:00:00.
- Đầu vào: 217 feature, gồm 112 feature mới.
- Train: các mùa 2021-22, 2022-23, 2023-24 (78,327 dòng).
- Chọn cấu hình: đầu mùa 2024-25 đến 2024-12-19 00:00:00 (8,681 dòng).
- Kiểm tra sau huấn luyện: phần còn lại của 2024-25, 2025-26 và 2026-27 hiện có.

## Các nhóm đã bổ sung

PTS/REB/AST/MIN; FGM/FGA, 2PM/2PA, 3PM/3PA, FTM/FTA; FG%, 2P%, 3P%, FT%, TS%, eFG%; DREB/OREB; STL/BLK; TOV/PF; AST/TO; +/−; tần suất double-double/triple-double.

Mỗi chỉ số có L5/L10/L20 và từ đầu mùa. Chỉ dùng các trận trước trận cần dự đoán. Tỷ lệ ném tính từ tổng made/attempts trên cùng mẫu; không làm tròn đầu vào model. Rank, màu UI và số liệu tổng kết tương lai không được đưa vào công thức.

Chưa có dữ liệu nguồn cho USG%, ORtg, DRtg, PER; không tự tạo số thay thế.

## Kết quả đối chiếu bản đang chạy

RPS và negative log-score càng thấp càng tốt. Độ phủ 90% là chỉ số chẩn đoán, không phải tỷ lệ thắng cược.

| Market | RPS cũ | RPS mới | Cải thiện RPS | Log-score cũ | Log-score mới | Bản được dùng |
|---|---:|---:|---:|---:|---:|---|
| PTS | 3.30319 | 3.26765 | 1.08% | 3.1941 | 3.1118 | Mới |
| REB | 1.32809 | 1.31723 | 0.82% | 2.1888 | 2.1793 | Mới |
| AST | 0.91537 | 0.90555 | 1.07% | 1.7819 | 1.7715 | Mới |

Điều kiện thay bản cũ: RPS tổng cải thiện ít nhất 0,5%; log-score tổng không xấu hơn quá 1%; RPS mỗi mùa không xấu hơn quá 1%. Đã chạy đủ 48 cấu hình/market, tổng 144 cấu hình.

217 feature là bộ đầu vào của các model ứng viên đã huấn luyện. Các market giữ bản cũ vẫn dùng trọng số và schema cũ; các feature mới chưa tác động đến dự đoán của những market này.

## Giới hạn

Giữ nguyên mốc train/chọn cấu hình của release cũ để so sánh. Các mùa sau chỉ dùng để kiểm tra, không được đưa ngược vào train hoặc calibration. Quyết định phát hành có sử dụng tập kiểm tra, nên kết quả sau lựa chọn vẫn cần xác nhận trên các trận tương lai.

Chưa có odds/line nhà cái theo thời điểm lịch sử nên chưa thể kết luận ROI hoặc cải thiện hiệu suất cược. DNP/void, push và công thức settlement/EV vẫn giữ nguyên.

Chi tiết từng mùa, từng cấu hình và đường dẫn model nằm trong `data/releases/extended_f736eb44b4a9/reports/extended_training_report.json`.
