# Vai trò khi đội hình thay đổi

Đã thêm `Role & Availability` dưới Playing Time và trường `role_context` trong `POST /api/predict`.

## Phần đã hoạt động

- Danh sách đồng đội Reported Out; Questionable, Doubtful và Day-to-day được tách thành nhóm chưa chắc chắn.
- Profile từng người từ tối đa 10 trận đã chơi cho đội hiện tại, trước ngày cần dự đoán: MIN, FGA, FTA, 3PA, PTS, AST.
- Tổng role bị thiếu do các cầu thủ Reported Out và tỷ trọng FGA so với trung bình 10 trận gần nhất của đội. Lượt ném được lấy trực tiếp từ lịch sử từng người; không quy đổi phút thành FGA bằng hệ số cố định.
- Bảng With/Without theo từng đồng đội, gồm N, MIN, FGA, PTS và chênh lệch quan sát. Tối đa 60 trận của cầu thủ cho cùng đội trong hai năm gần nhất. Mức đủ mẫu tối thiểu là 5 trận mỗi nhóm.
- Nếu nhiều người cùng Out, chỉ tính chênh lệch cho tổ hợp khi có mẫu vắng đồng thời; không cộng các hiệu ứng riêng lẻ.

With/Without là so sánh quan sát, không phải tác động nhân quả hoặc số điểm được bảo đảm tăng thêm. Không coi dữ liệu gamelog bị thiếu là DNP. Chỉ nhận trạng thái vắng từ bằng chứng DNP rõ ràng; người có 0 phút nhưng không có xác nhận DNP vẫn là Unknown.

## Dữ liệu thiếu được xử lý thế nào

Report cũ, roster chưa xác minh, tên không map duy nhất hoặc chưa có profile sẽ trả Unknown/thiếu dữ liệu; không thay bằng 0 hay một mức tăng cơ hội giả định. Không dùng tên khớp một phần để tự ghép cầu thủ. Các chỉ số lỗi/không hữu hạn không được trả ra JSON như NaN/Infinity.

Hiện kho ban đầu có 25 bản ghi tham dự được xác nhận, gồm 2 DNP. Các snapshot pregame mới đã bắt đầu được lưu; chưa có đủ snapshot cho các dòng train/validation lịch sử. Vì vậy **chưa huấn luyện hoặc thay model Points bằng nhóm role**. Các model đang dùng được giữ nguyên.

Ví dụ kiểm tra API: Donovan Mitchell có ba đồng đội Reported Out, với tổng profile khoảng 70,5 MIN và 21,7 FGA. Đây là role của các cầu thủ vắng, không phải phần được cộng hết cho Mitchell. Điểm kỳ vọng của model hiện tại vẫn là 23,14.

## Thu thập và huấn luyện về sau

- Khi ứng dụng chạy và có request dự đoán cho trận sắp tới, lưu snapshot pregame có giờ tipoff thật, report còn mới và roster map đầy đủ. Thay line/odds trên cùng nguồn dữ liệu không tạo thêm bản trùng.
- Sau Sync thành công, collector tùy chọn bổ sung tối đa 5 box score chưa có bằng chứng tham dự; lỗi phần này không làm hỏng Sync chính. API nạp evidence mới bằng một lần đổi resource tham chiếu.
- Có 18 feature role khai báo cho pipeline; dữ liệu lịch sử chỉ được tạo từ snapshot thật trước tipoff. Các snapshot sau tipoff hoặc có profile chứa kết quả trận tương lai bị loại.
- Pipeline minutes/Points chỉ chọn role feature khi có tối thiểu số mẫu và mức biến thiên cần thiết. Dự đoán phút hỗ trợ schema riêng trong model manifest; model phút cũ vẫn dùng đúng 18 đầu vào cũ.
- Khi kiểm chứng, phải chọn mốc forecast nhất quán và tách thời gian train/calibration/test. Dùng snapshot cuối trước tipoff không chứng minh hiệu suất của vé đặt từ buổi sáng. Các cửa sổ train cũ cũng cần được đánh giá lại khi thu đủ dữ liệu mới.

Có thể bổ sung lịch sử participation bằng endpoint NBA công khai:

```powershell
python scripts/collect_role_evidence.py --max-games 30 --lookback-days 90
```

Script dừng ngay khi nguồn không truy cập được. Chỉ kiểm tra dữ liệu trong máy:

```powershell
python scripts/collect_role_evidence.py --cache-only
```

## Kiểm tra

- 251 test Python đạt; 45 test JavaScript đạt.
- Kiểm tra chống dùng kết quả trận hiện tại/tương lai; phân biệt Out và trạng thái chưa chắc chắn; không suy vắng mặt từ row bị thiếu; không cộng chồng hiệu ứng; giữ lần capture đầu khi thay line/odds.
- API thật trên localhost trả `role_context`. Kiểm tra thêm bằng TestClient với Donovan Mitchell và Payton Pritchard; không tăng Points bằng hệ số thủ công.
- [Kết quả API](role_context_api_smoke_2026-11-17.json), [kiểm kê bằng chứng](role_evidence_2026-11-17.json).

Không có kết luận tăng tỷ lệ thắng hoặc ROI từ việc thêm module này.

## Tự động backfill lịch sử

Đã thêm collector resume toàn bộ catalog trận đã kết thúc (hiện 3.895 trận, từ 2023-10-24 đến 2026-11-16). Mỗi trận được ghi riêng vào `data/role_evidence/participation/<game_id>.json`; archive hỏng/rỗng hoặc sai game sẽ không được coi là hoàn tất. Tiến độ nằm ở `data/role_evidence/collection_progress.json` và trạng thái job ở `data/role_evidence/backfill_status.json`.

Ứng dụng tự khởi động job nền sau startup, theo batch nhỏ, có lease riêng, checkpoint sau từng trận và retry 10 phút khi API bị lỗi/rate limit. Job không giữ sync lock chính và không chặn endpoint dự đoán. Có thể tắt bằng `ROLE_BACKFILL_AUTOSTART=0`; API điều khiển là `GET /api/role-evidence/status`, `POST /api/role-evidence/backfill`, `POST /api/role-evidence/backfill/stop`.

CLI resume ngoài sandbox:

```powershell
python scripts/collect_role_evidence.py --all-history --max-games 30 --until-complete
```

Trong môi trường kiểm tra hiện tại, request NBA bị Windows chặn (`WinError 10013`), vì vậy một batch đã chuyển đúng sang `UNAVAILABLE` và hẹn retry 600 giây; chưa tải giả dữ liệu nào. Cache-only xác nhận catalog 3.895 trận, 0 archive participation hợp lệ mới, và 25 record cũ vẫn được giữ nguyên.

Các record participation được backfill sau này chỉ là bằng chứng tham dự/DNP quan sát được tại thời điểm thu thập. Chúng không tái tạo được injury report pregame trong quá khứ; không được dùng để gắn nhãn vắng mặt trước trận hoặc tự động publish lại model nếu thiếu snapshot pregame theo thời gian.
