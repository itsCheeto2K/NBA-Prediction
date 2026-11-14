# Home: lịch sử cầu thủ và đối đầu — chỉ để tham khảo

Ngày: 2026-11-14 · Phiên bản: 1.0

## 1. Mục tiêu và giới hạn bắt buộc

Thêm vào **Home**, không thêm vào FastCheck:

1. Bảng 10 trận gần nhất cầu thủ thực sự ra sân.
2. Bảng 10 trận gần nhất cầu thủ thực sự ra sân gặp đội đối thủ được chọn.
3. So sánh kết quả từng trận với line và cửa Over/Under đang nhập; tô xanh lá nhạt khi đạt cửa đó.

**Hai tính năng này chỉ dùng để user reference. Không đưa dữ liệu tổng hợp từ hai bảng vào công thức đang dùng. Không sửa feature model, shrinkage, dự đoán phút, mean, dispersion, CDF, xác suất, EV, Kelly, trạng thái vận hành hoặc chọn kèo. Không retrain, refit hay thay ModelBundle để triển khai tính năng này.**

Các rolling feature lịch sử đã có trong mô hình tiếp tục hoạt động như cũ. Yêu cầu này không xóa chúng và không tạo thêm bản sao của chúng. Không dùng hit rate của bảng hoặc H2H để nhân/chỉnh xác suất hay EV.

Tình trạng tài liệu: đặc tả triển khai. Chưa chỉnh hoặc kiểm thử repository thực tế trong phiên soạn tài liệu này; agent triển khai phải kiểm tra cấu trúc code trước khi chọn tên file.

## 2. Nguồn và cách lấy dữ liệu

Ưu tiên game logs đã lưu trong database/parquet của dự án. NBA API chỉ phục vụ đồng bộ hoặc backfill thiếu dữ liệu, không gọi lại khi người dùng chỉnh line.

Endpoint phù hợp: `nba_api.stats.endpoints.playergamelogs.PlayerGameLogs`. Tài liệu có các tham số PlayerID, OpposingTeamID, Season, SeasonType, DateFrom, DateTo, LastNGames và các trường MIN, PTS, REB, AST, STL, BLK, FG3M, FGM/FGA, FTM/FTA, GAME_ID, GAME_DATE, TEAM_ID, MATCHUP.

Tham chiếu: https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/playergamelogs.md

Không giả định upstream luôn trả đủ 10 trận hoặc hỗ trợ truy vấn nhiều mùa trong một lần gọi. Nếu cần, lấy từng mùa, gộp, khử trùng lặp và sắp xếp ở backend. Với dữ liệu local, join lịch hai đội theo game_id để lấy opponent_team_id; không dựa riêng vào tên viết tắt hiển thị.

Không truy vấn riêng từng stat; một dòng box score đã chứa các stat cần thiết.

## 3. Quy tắc chọn trận thống nhất

### 3.1. Phạm vi

- Mặc định Regular Season. Cho phép chọn Playoffs riêng nếu nguồn đã có; không âm thầm trộn hai loại.
- Chọn những trận đã hoàn tất, trước giờ bắt đầu trận đang xem. Loại trận mục tiêu và live game.
- Nếu không gắn với trận sắp tới, dùng thời điểm truy vấn làm as_of và ghi rõ phạm vi.
- Lấy 10 **lần ra sân**, không phải 10 trận lịch của đội. DNP/Did Not Dress không được biến thành stat = 0.
- Trận có ra sân nhưng PTS/REB/AST = 0 là kết quả thật, phải giữ.
- Dùng trạng thái participation hoặc thời lượng chính xác từ nguồn để xác nhận ra sân; không loại chỉ vì MIN hiển thị đã làm tròn thành 0.
- Thời lượng hoặc trạng thái tham gia không xác định: không tự suy luận DNP từ stat = 0; báo thiếu dữ liệu.
- Khóa trùng theo player_id + game_id. Game ID luôn là chuỗi.
- Sắp xếp mới nhất trước theo thời điểm trận; dùng game_id làm khóa phụ ổn định.
- Missing stat là null, không phải 0; không đưa vào mẫu số hit rate của stat đó.

### 3.2. Bảng gần nhất

Lọc player_id trên các trận hợp lệ, lấy 10 trận mới nhất. Giữ đội cầu thủ ở thời điểm từng trận, kể cả trước khi chuyển nhượng.

### 3.3. Bảng đối đầu

Lọc player_id và opponent_team_id trước, rồi mới lấy 10 trận mới nhất. Đây là **cầu thủ gặp đội bóng**, không phải matchup với một hậu vệ cụ thể.

Không giới hạn cầu thủ phải thuộc đội hiện tại ở các lần đối đầu cũ. Hiển thị mùa và đội lịch sử để tránh hiểu sai. Các trận xuất hiện ở cả hai bảng vẫn được giữ trong mỗi bảng.

Nếu chỉ có 6 trận: hiện “6/10 trận có dữ liệu”. Nếu chưa backfill hết phạm vi, thêm “Dữ liệu đối đầu chưa đầy đủ”, không tuyên bố cầu thủ chỉ từng gặp đội này 6 lần. Response phải phân biệt hết lịch sử sẵn có với thiếu coverage/backfill.

Không tự mở backfill toàn sự nghiệp đồng bộ ngay trong request Home. Trả dữ liệu hiện có và trạng thái thiếu; dùng job nền hiện hữu để bổ sung nếu dự án hỗ trợ.

## 4. Nội dung trên Home

Đặt phần “Lịch sử tham khảo” dưới kết quả dự đoán. Hai tab hoặc hai bảng: “10 trận gần nhất” và “Đối đầu [tên đội]”. Không sửa FastCheck.

Các cột mặc định:

| Cột | Nội dung |
|---|---|
| Ngày / mùa | Ngày trận và mùa giải |
| Đội | Đội cầu thủ ở thời điểm trận |
| Đối thủ | Tên đội và sân nhà/sân khách |
| MIN | Phút thi đấu |
| PTS / REB / AST | Chỉ số chính |
| 3PM / STL / BLK / TOV | Chỉ số bổ sung, cuộn ngang trên mobile |
| Kết quả so line | Hit / Miss / Push / Không có dữ liệu |

Có thể thêm FGM/FGA, 3PM/3PA, FTM/FTA trong phần mở rộng nếu dữ liệu local đã có. Không cam kết mọi chỉ số tracking/advanced đều có từ game logs.

Banner luôn nhìn thấy:

> Chỉ để tham khảo. Lịch sử và tỷ lệ hit dưới đây không tham gia công thức dự đoán, xác suất hoặc EV hiện tại.

Chú thích dưới bộ nhập line:

> So sánh kết quả lịch sử với line đang nhập; không phải kết quả cược theo line nhà cái ở từng trận. Tỷ lệ hit lịch sử không phải xác suất dự đoán trận tiếp theo.

## 5. Line, cửa và màu sắc

### 5.1. Quy tắc tương tác

Dùng stat + line + side đang chọn trên Home làm mặc định cho cả hai bảng. Hiển thị rõ ví dụ “PTS · Over 25.5”. Không thay đổi giá trị bộ nhập dự đoán chỉ vì chuyển tab history.

Nếu Home chưa có side, bổ sung selector Over/Under riêng cho history. Selector này chỉ điều khiển phần tham khảo, không âm thầm đổi lựa chọn pricing.

Khi chọn PTS thì chỉ tô ô PTS và badge kết quả; không tô cả hàng khiến người dùng hiểu REB/AST cũng đạt line. Các stat khác vẫn hiện bình thường. V1 dùng một stat/line/side cùng lúc; không so REB hoặc AST với line PTS. Tính năng nhập đồng thời nhiều line, nếu bổ sung sau, phải có line và side riêng cho từng stat.

### 5.2. Hàm so sánh

Với stat x và line L:

| Cửa | Hit | Miss | Push |
|---|---|---|---|
| Over | x > L | x < L | x = L |
| Under | x < L | x > L | x = L |

Các stat đếm là số nguyên; line bán nguyên không có Push. Không làm tròn line để so sánh.

- Hit: nền xanh lá nhạt, chữ tương phản đủ đọc và nhãn “Hit”.
- Miss: nền đỏ nhạt hoặc trung tính với nhãn “Miss”.
- Push: xám với nhãn “Push”.
- Missing: dấu “—”, không màu hit/miss.
- Chưa nhập line hợp lệ: hiển thị stats, chưa tô màu và chưa tính tỷ lệ.

Không chỉ dùng màu để truyền đạt kết quả. Dùng nhãn/badge và hỗ trợ bàn phím. Validate line hữu hạn, không âm, bước 0.5 cho PTS/REB/AST/3PM/STL/BLK/TOV của V1; chặn NaN/Infinity và chuỗi không hợp lệ.

### 5.3. Tổng kết tham khảo

Đặt H = số Hit, M = số Miss, P = số Push của những dòng có stat hợp lệ.

- Hiển thị H Hit · M Miss · P Push, cùng số trận có dữ liệu.
- “Hit / tổng trận”: H / (H + M + P).
- Nếu thêm tỷ lệ loại Push, đặt nhãn riêng “Hit trong các trận không Push”: H / (H + M).
- Mẫu số bằng 0: hiện “—”, không hiện 0% hoặc 100%.
- Không gọi các tỷ lệ này là win probability, confidence, backtest ROI hay accuracy của model.

Ví dụ Over 20, kết quả [21, 20, 19]: 1 Hit, 1 Push, 1 Miss; Hit/tổng = 33.3%; loại Push = 50%.

## 6. API nội bộ đề xuất

Tên endpoint có thể điều chỉnh theo repository:

`GET /api/players/{player_id}/history?opponent_team_id=...&target_game_id=...&season_type=Regular%20Season&limit=10`

Backend trả hai tập raw history trong một response, không gọi inference. Với target_game_id, backend tự xác định cutoff và kiểm tra opponent đúng trận; với chọn đối thủ tự do thì đánh dấu reference-only và không sửa đối thủ của prediction.

Các trường response:

```json
{
  "player_id": "...",
  "opponent_team_id": "...",
  "as_of": "...",
  "season_type": "Regular Season",
  "reference_only": true,
  "affects_prediction": false,
  "recent": {"rows": [], "returned_count": 0},
  "vs_opponent": {"rows": [], "returned_count": 0},
  "coverage": {
    "seasons_available": [],
    "history_complete_for_requested_scope": false,
    "backfill_pending": false
  },
  "data_updated_at": "...",
  "warnings": []
}
```

Mỗi row có game_id, game_date, season, season_type, player_team_id/name, opponent_team_id/name, home_away, minutes, participation_status và các stats nullable. Không cần gửi odds hay line để endpoint lấy lịch sử. Frontend tính màu và hit rate từ response đã cache.

Không thêm các trường này vào payload prediction hoặc feature manifest. Lỗi history phải có trạng thái riêng; không làm hỏng kết quả dự đoán đã tải.

## 7. Tích hợp và hiệu năng

1. Kiểm tra nguồn game logs, ID mapping, participation và các thành phần Home hiện có.
2. Tạo read service độc lập, truy vấn player/date và player/opponent/date từ kho dữ liệu local.
3. Tạo endpoint và kiểu response; kiểm tra target cutoff, thiếu coverage và null.
4. Tạo component Home; dùng một pure function so line chung cho hai bảng.
5. Cache theo player, opponent, cutoff, season_type và phiên bản dữ liệu. Đổi line/side không invalidation raw history.
6. Bỏ response cũ khi người dùng chuyển cầu thủ nhanh để tránh hiển thị history nhầm người.
7. Không thêm bootstrap, model fitting, DvP computation hoặc NBA API fan-out vào luồng chỉnh line.

Nếu thiếu dữ liệu, hiển thị trạng thái thực tế; không dùng dữ liệu giả làm fallback production.

## 8. Kiểm chứng và điều kiện hoàn thành

Kiểm tra bằng fixture cố định và một lượt kiểm tra Home:

- Recent đúng 10 lần ra sân trước cutoff, không lẫn target game/live/DNP.
- H2H lọc đối thủ trước khi limit; gộp nhiều mùa và giữ đội lịch sử sau chuyển nhượng.
- Player/game trùng được khử; zero thật giữ nguyên, null không biến thành zero.
- Over/Under tại line nguyên và bán nguyên đúng; Push, missing và mẫu số 0 đúng.
- Đổi line cập nhật cả hai bảng, không gọi NBA upstream và không chạy lại inference.
- Chỉ tô stat đang chọn; có nhãn ngoài màu; mobile xem được các cột.
- Chuyển nhanh cầu thủ không hiển thị response cũ; history lỗi không làm lỗi prediction.
- FastCheck giữ nguyên.
- Với cùng payload prediction và cùng ModelBundle, output trước/sau thay đổi không đổi: mean, PMF/CDF, xác suất, EV, Kelly và operational state. Thực hiện với fixture/cache deterministic, không so hai request dùng dữ liệu live đã đổi.
- Feature manifest và ModelBundle không thay đổi; không có đường đọc history summary từ prediction engine.

Agent bàn giao danh sách file sửa, ảnh Home có dữ liệu thật hoặc fixture được ghi nhãn, kết quả kiểm tra và giới hạn coverage còn lại. Không tuyên bố tính năng này tăng độ chính xác hay lợi nhuận: đây là công cụ hiển thị tham khảo.

## 9. Prompt giao cho agent triển khai

> Triển khai NBA_HOME_PLAYER_HISTORY_REFERENCE_SPEC.md trên codebase hiện tại. Chỉ thêm hai bảng history vào Home, không vào FastCheck. Dùng dữ liệu local trước, không gọi upstream khi chỉnh line. Hỗ trợ 10 lần ra sân gần nhất và 10 lần đối đầu với đội được chọn, có màu theo stat/line/Over-Under và xử lý Push, DNP, thiếu dữ liệu đúng đặc tả. Bắt buộc hiển thị ghi chú reference-only. Không can thiệp công thức hiện tại, feature model, pipeline inference, xác suất, EV, Kelly hay ModelBundle; không retrain. Kiểm tra source thực tế trước khi sửa, hoàn tất các kiểm chứng ở §8 và báo rõ phần nào chưa đủ dữ liệu.
