# Kế hoạch xây dựng hệ thống dự đoán NBA Player Props

Ngày lập: 09/11/2026  
Bản sửa: 1.8 — đăng ký refit-primary, pilot futility-only, hai mốc freeze, gate-gap và T-grid assurance ngày 09/11/2026.  
Trạng thái: Kế hoạch triển khai; chưa huấn luyện hoặc xác nhận hiệu quả mô hình.  
Phạm vi mặc định: dự đoán trước trận, dữ liệu miễn phí, chạy được trên máy cá nhân.

## 1. Mục tiêu và quyết định ban đầu

Xây hệ thống dự đoán phân phối Points (PTS), Rebounds (REB), Assists (AST) của cầu thủ, sau đó tính xác suất Over, Under và Push tại một line cụ thể.

- Dữ liệu chính: NBA.com thông qua thư viện cộng đồng `nba_api`.
- Lịch sử khởi đầu: ba mùa hoàn chỉnh 2023-24, 2024-25, 2025-26 và mùa đang diễn ra 2026-27. Đây là lựa chọn triển khai, không phải mức tối thiểu đã được chứng minh.
- Bắt đầu bằng Regular Season; lưu loại trận để mở rộng Playoffs và Play-In sau.
- Huấn luyện chung toàn bộ cầu thủ, mỗi stat một model. Không tạo model riêng cho từng cầu thủ.
- CatBoost là model khởi đầu; LightGBM là đối chứng bắt buộc trước khi chọn model chính. XGBoost và NGBoost là thí nghiệm tiếp theo.
- Ban đầu hỗ trợ nhập line/odds thủ công. Nguồn props lịch sử là hạng mục riêng.
- Chưa triển khai live prediction, tự động đặt cược hoặc tối ưu parlay.

Đặc tả xác nhận mặc định cập nhật tới bản 1.8 nằm ở §11.7; recipe và các mốc điều hành mới ở §11.7.8 được ưu tiên khi các ghi chú lịch sử mô tả frozen-v1.7; các lựa chọn/ablation khác trong tài liệu là thăm dò nếu §11.7 không chỉ định. Ngưỡng thiết kế là quy ước vận hành chốt trước dữ liệu xác nhận, không phải kết quả thực nghiệm.

Đầu ra phải phân biệt ba mục tiêu: dự đoán stat, xác suất đã hiệu chỉnh, và hiệu quả so với thị trường. Đạt mục tiêu thứ nhất không tự chứng minh hai mục tiêu còn lại.

## 2. Đầu ra của một dự đoán

Mỗi dự đoán gắn với cầu thủ, trận, market, thời điểm chốt thông tin và phiên bản model.

| Trường | Nội dung |
|---|---|
| `prediction_time`, `data_cutoff` | Thời điểm tạo dự đoán và giới hạn thông tin được sử dụng |
| `player_id`, `game_id`, `market` | Định danh cầu thủ, trận và PTS/REB/AST |
| `expected_value`, `median` | Kỳ vọng và trung vị; không mặc định hai giá trị giống nhau |
| `prediction_interval` | Khoảng dự đoán cho kết quả trận, có mức phủ được kiểm chứng |
| `line`, `p_over`, `p_under`, `p_push`, `p_void` | Tách xác suất có điều kiện thi đấu và xác suất settlement vô điều kiện; không trộn hai hệ quy chiếu |
| `participation_condition` | Dự đoán có điều kiện cầu thủ thi đấu hay bao gồm nguy cơ không thi đấu |
| `data_quality_flags` | Ít dữ liệu, vừa trở lại, vai trò thay đổi, thiếu injury snapshot… |
| `scenario` | Kịch bản đội hình hoặc giới hạn phút nếu chưa thể gộp đáng tin cậy |
| `model_version`, `feature_version` | Phiên bản để tái dựng dự đoán |

Không đồng nhất khoảng dự đoán kết quả với khoảng tin cậy của xác suất ước lượng. Không hiển thị nhãn “confidence cao” chỉ vì model đưa xác suất cao.

## 3. Nguồn dữ liệu và endpoint

Các endpoint dưới đây được chọn từ tài liệu `nba_api`. Cần xác nhận constructor và schema của phiên bản cài đặt trước khi viết collector; tài liệu trên `master` có thể khác bản phát hành.

| Mức | Endpoint/nguồn | Thu thập | Công dụng |
|---|---|---|---|
| P0 | `nba_api.stats.static.players`, `teams` | ID và danh mục tham chiếu | Định danh; không dùng đội hiện tại để ghi đè lịch sử |
| P0 | `PlayerGameLogs` | Stat cầu thủ theo trận, phút, FGA/FTA/3PA | Dữ liệu huấn luyện chính; lấy nhiều cầu thủ theo mùa/khoảng ngày |
| P0 | `ScheduleLeagueV2`, `ScoreboardV3` | Lịch, hai đội, giờ bắt đầu, trạng thái | Lịch dự đoán, ngày nghỉ và cập nhật trận |
| P0 | `LeagueGameLog` ở cấp đội | Box score đội theo trận | Đặc trưng đội/đối thủ từ lịch sử |
| P1 | `BoxScoreTraditionalV3` | Chi tiết từng trận, cầu thủ và đội | Đối chiếu, bổ sung dữ liệu và trạng thái ghi nhận trong box score |
| P1 | `BoxScoreAdvancedV3` | Usage, pace, possessions, các tỷ lệ | Bổ sung cơ hội và bối cảnh thi đấu |
| P1 | NBA Injury Report | Trạng thái tham dự, lý do, thời điểm công bố | Thông tin trước trận từ nguồn riêng |
| P2 | `BoxScorePlayerTrackV3` | Touches, passes, rebound chances | Nâng cấp REB/AST và vai trò tấn công |
| P2 | `GameRotation`, `PlayByPlayV3` | Thay người, diễn biến trận | Nghiên cứu rotation và mô phỏng sâu hơn |
| Riêng | Nguồn line/odds | Nhà cái, market, line, giá, timestamp | Kiểm chứng xác suất tại giá thực tế |

Lưu ý nguồn:

- Không cần thu thập toàn bộ endpoint trong mục lục.
- Ưu tiên V3 khi tài liệu ghi nhận V2 đã bị thay thế; không giả định tất cả endpoint V2 đều hỏng.
- `BoxScorePlayerTrackV3` có passes, touches và rebound chances trong schema đã đọc; không giả định có `potentialAssists`.
- Endpoint live `Odds` được tài liệu minh họa bằng thị trường cấp trận như 2way/spread. Chưa xác nhận đây là nguồn player props hoặc kho odds lịch sử.
- Injury snapshot trước trận không thể thay thế bằng danh sách inactive ghi nhận sau trận.
- Phần mềm miễn phí không đồng nghĩa có quyền tái phân phối mọi dữ liệu; kiểm tra điều khoản nguồn trước khi công khai hoặc thương mại hóa.

## 4. Kiến trúc triển khai

| Thành phần | Lựa chọn ban đầu |
|---|---|
| Collector và feature pipeline | Python, `nba_api`, pandas hoặc Polars |
| Raw data | JSON nén theo endpoint, tham số và thời điểm tải |
| Dữ liệu phân tích | Parquet; DuckDB để kiểm tra và dựng tập train |
| Dữ liệu ứng dụng | PostgreSQL |
| Huấn luyện | CatBoost, LightGBM; bổ sung XGBoost/NGBoost khi cần |
| Dịch vụ dự đoán | FastAPI |
| Giao diện khi model đã được kiểm chứng | Next.js |
| Lịch tác vụ | Cron hoặc scheduler đơn giản; chưa cần hệ thống phân tán |
| Theo dõi thử nghiệm | Manifest JSON cùng model/metrics; có thể chuyển sang MLflow sau |

Luồng xử lý: lấy và lưu raw data → chuẩn hóa → kiểm tra chất lượng → tạo features theo cutoff → dự đoán phân phối → tính xác suất tại line → lưu dự đoán → đối chiếu sau trận.

Không gọi NBA.com mỗi lần người dùng mở trang. Giao diện đọc dữ liệu đã được đồng bộ và dự đoán đã lưu.

## 5. Collector lịch sử và cập nhật

### 5.1. Kiểm tra trước khi tải lớn

1. Cố định phiên bản thư viện và ghi commit/tag nếu dùng bản nguồn.
2. Kiểm tra chữ ký constructor, tham số mùa/loại trận và tên dataset của các endpoint P0.
3. Chọn vài trận đã kết thúc; kiểm tra game logs, lịch và một box score V3 có thể ghép đúng.
4. Kiểm tra một mẫu có không thi đấu, overtime và thiếu trường nếu có sẵn.
5. Nếu máy cloud timeout lặp lại, thử collector trên máy cá nhân để phân biệt lỗi truy cập với lỗi code.

### 5.2. Backfill

- Lấy danh mục trận và game logs theo mùa/khoảng ngày; tránh vòng lặp từng cầu thủ × từng mùa khi endpoint hỗ trợ lấy gộp.
- Nếu phản hồi quá lớn hoặc thiếu, chia theo tháng/ngày và đối chiếu danh mục trận để phát hiện thiếu.
- Tải advanced/traditional box scores theo các `game_id` cần bổ sung, có checkpoint để tiếp tục.
- Giữ danh sách lỗi riêng; không coi HTTP 200 hoặc bảng rỗng là thành công mặc định.
- Ghi `endpoint`, tham số, phiên bản package, thời điểm tải và hash raw response.

### 5.3. Cập nhật

- Đồng bộ lịch và các thay đổi hoãn/đổi giờ.
- Sau khi trận kết thúc, lấy kết quả; tải lại một cửa sổ trận gần đây để nhận chỉnh sửa thống kê.
- Lưu injury snapshots và props snapshots trước trận khi có nguồn.
- Chọn cutoff vận hành ban đầu là 60 phút trước giờ bóng lăn; chỉ dữ liệu đã có tại cutoff được tham gia dự đoán đó.
- Nếu cập nhật sát trận, tạo dự đoán mới có timestamp; không ghi đè dự đoán cũ.

### 5.4. Độ ổn định

- Gửi tuần tự, cache kết quả và nghỉ khoảng một giây giữa các request theo hướng dẫn repo; không coi đây là quota bảo đảm.
- Retry có giới hạn và backoff cho lỗi tạm thời. Dừng batch khi bị chặn hoặc schema sai, không retry vô hạn.
- Lưu `game_id` dạng chuỗi để giữ số 0 đầu.
- Chuyển V3 camelCase và các cột uppercase về schema thống nhất.
- Chuẩn hóa phút về số thực; giữ null khi chưa xác định thay vì tự đổi thành 0.

## 6. Schema dữ liệu

| Bảng | Khóa/nội dung chính |
|---|---|
| `players`, `teams` | ID ổn định, thông tin tham chiếu có nguồn/thời điểm |
| `games` | `game_id`, mùa, loại trận, đội, giờ bắt đầu, trạng thái |
| `player_game_stats` | `(game_id, player_id)`, đội ở trận đó, stat thực tế, trạng thái thi đấu |
| `team_game_stats` | `(game_id, team_id)`, stat đội và đối thủ |
| `roster_snapshots` | Đội, cầu thủ, thời điểm quan sát/hiệu lực nếu có |
| `injury_snapshots` | Cầu thủ, trận nếu ghép được, trạng thái, `source_published_at`, `fetched_at` |
| `prop_snapshots` | Cầu thủ, trận, market, book, line, odds hai phía, timestamp |
| `feature_snapshots` | Cầu thủ, trận, cutoff, version và feature values |
| `predictions` | Phân phối/xác suất, line, điều kiện tham dự, model version, flags |
| `settlements` | Kết quả thực tế và win/loss/push/void theo quy tắc market |
| `ingestion_runs` | Tiến trình, số dòng, lỗi, schema version và nguồn raw |

Với dữ liệu lịch sử vừa tải, `fetched_at` không chứng minh thời điểm dữ liệu từng được công bố. Đánh dấu backtest dùng kết quả đã chỉnh sửa nếu không có bản lưu đương thời.

## 7. Chất lượng dữ liệu và chống leakage

- Mỗi cầu thủ/trận có một dòng chuẩn hóa; giữ raw nếu nguồn trùng/mâu thuẫn.
- Đối chiếu tổng stat cầu thủ với đội ở những trường áp dụng; theo dõi sai khác, không tự sửa tùy tiện.
- Phân biệt: không thi đấu, thi đấu 0 điểm, dữ liệu chưa về và lỗi parse.
- Không giới hạn tập lịch sử ở cầu thủ hiện còn active: tránh bỏ những người đã rời giải.
- Không gán đội hiện tại cho trận cũ hoặc dùng roster cuối mùa để suy ngược mọi trận.
- Features chỉ dùng dữ liệu có trước cutoff. Mọi rolling phải dịch một trận trước khi tính.
- Không dùng actual minutes, actual starting status chưa được biết trước trận, usage/pace hoặc tổng kết mùa chứa tương lai của chính trận đích.
- Mã hóa categorical, chọn feature, tuning và calibration chỉ học từ phần train/validation phù hợp.
- Mọi dòng cùng một trận phải thuộc cùng một fold; chia theo ngày/trận thực tế, không chia ngẫu nhiên player-game rows.
- Ghi coverage theo mùa, endpoint và nhóm cầu thủ; không để model âm thầm dùng dữ liệu tracking chỉ có ở một phần mẫu.

Kiểm tra bắt buộc gồm: khóa trùng, schema drift, phút bất thường, thiếu trận, thời điểm feature vượt cutoff, đổi đội và các ca DNP/overtime.

## 8. Feature set

| Nhóm | Feature khởi đầu |
|---|---|
| Phong độ | Mean/std 5, 10, 20 trận; trung bình có trọng số; số trận đủ dữ liệu |
| Minutes | Phút gần đây, biến động, xu hướng, ngày từ trận cuối |
| Cơ hội PTS | FGA, FTA, 3PA, usage lịch sử, hiệu suất ném đã làm trơn |
| Cơ hội REB | OREB/DREB, tỷ lệ rebound, rebound chances khi có |
| Cơ hội AST | AST, passes, touches, tỷ lệ assist khi có |
| Bối cảnh | Nhà/khách, ngày nghỉ, back-to-back, loại trận |
| Đối thủ | Pace và defensive/rebounding context từ các trận đã diễn ra |
| Vai trò | Đội tại thời điểm trận, lịch sử đá chính, thay đổi phút/cơ hội |
| Availability | Injury status tại cutoff, đồng đội quan trọng vắng được xác nhận |
| Nhóm đặc biệt | Rookie, số trận NBA, ngày nghỉ dài, số trận kể từ trở lại |

### 8.1. Shrinkage tỷ lệ theo phút

Với nhóm tương tự g và prior Gamma theo tham số shape–rate:

- `ρ ~ Gamma(α_g, β_g)`; `X_i | ρ, M_i ~ Poisson(M_i ρ)`.
- Posterior mean: `ρ_hat = (α_g + Σ_i X_i) / (β_g + Σ_i M_i)`.
- Prior mean là `α_g/β_g`; `β_g` có đơn vị phút, diễn giải như exposure giả.
- Với trọng số giảm theo thời gian: `ρ_hat_w = (α_g + Σ_i w_i X_i) / (β_g + Σ_i w_i M_i)`.

Bản có trọng số là power-likelihood/generalized Bayes khi w không phải tần suất nguyên; không gọi là posterior chuẩn của các trận độc lập không trọng số. Cố định thang w (ví dụ trận mới nhất w=1), vì nhân mọi w với hằng số sẽ đổi độ mạnh prior tương đối.

Ước lượng nền nhóm và chọn độ mạnh prior chỉ bằng dữ liệu trước cutoff trong train/validation. Không chọn β riêng bằng cách nhìn kết quả trận đích. Với không có lịch sử, công thức quay về prior mean, nhưng vẫn thiếu thông tin về vai trò/phút.

Báo `n_eff_games = (Σw)^2 / Σ(w^2)`, số trận thật và exposure `Σw M`. Nếu không có quan sát, quy ước n_eff=0. Đây là ESS theo trọng số, không phải số quan sát độc lập sau khi tính tương quan thời gian và không thay thế tổng phút.

Gamma–Poisson là baseline hợp lý cho count/exposure; với PTS là tổng điểm có trọng số, công thức shrinkage vẫn có thể thử như xấp xỉ, nhưng không tự tạo posterior bất định đúng theo cơ chế ghi điểm. Với NB hoặc mô hình scoring components, cần prior/likelihood tương thích nếu muốn diễn giải Bayes đầy đủ.

Tránh trung bình các tỷ lệ cực lớn từ những trận ít phút. Không điền feature thiếu của rookie thành 0 như thể đó là phong độ thực tế. Shrinkage giảm phương sai ước lượng; không giải quyết hoàn toàn rookie, đổi vai trò hoặc dữ liệu khác miền.

## 9. Rookie, đổi vai trò và trở lại sau chấn thương

### 9.1. Rookie hoặc ít trận

- Model học chung toàn giải, dùng tuổi/vị trí/thể hình khi nguồn đủ tin cậy và vai trò dự kiến.
- Kết hợp nền của nhóm tương tự với lịch sử cá nhân; mức độ dựa vào cá nhân tăng theo dữ liệu, chọn bằng validation.
- Không dựa vào player ID để giải quyết người chưa xuất hiện trong train.
- College/G League/giải nước ngoài là nguồn nâng cấp; cần mô hình chuyển đổi, không nhập thẳng các thống kê như tương đương NBA.
- Báo số trận quan sát, dữ liệu thiếu và khoảng dự đoán; backtest riêng rookie.

### 9.2. Trở lại sau nghỉ dài

- Dùng `days_since_last_game`, số trận/phút kể từ trở lại và giới hạn phút công bố trước cutoff.
- Khoảng nghỉ dài chỉ là proxy; không tự kết luận mọi khoảng nghỉ là chấn thương.
- Không ghi các trận không tham dự thành hiệu suất bằng 0 trong model có điều kiện thi đấu.
- Giữ thông tin năng lực trước nghỉ, nhưng không mặc định số phút/vai trò cũ đã phục hồi.
- Khi giới hạn phút hoặc availability chưa rõ, xuất kịch bản riêng. Chỉ gộp khi trọng số kịch bản có cơ sở và đã được đánh giá.

### 9.3. Đổi đội và vai trò

- Thêm số trận ở đội mới, biến động minutes/usage, thay đổi đồng đội.
- Ưu tiên tín hiệu vai trò hiện tại, giữ lịch sử hiệu suất có làm trơn.
- Không giả định ảnh hưởng của đồng đội vắng có thể cộng tuyến tính: nhiều người vắng đồng thời có thể tạo rotation khác hẳn.

Lớp đánh giá đủ dữ liệu xuất flags và trạng thái `ready`, `scenario_only`, `insufficient_data`. Ngưỡng được đặt bằng validation và phải báo tỷ lệ trường hợp bị loại.

## 10. Chiến lược mô hình

### 10.1. Baseline

So sánh ít nhất với trung bình có trọng số gần đây và baseline phút × hiệu suất lịch sử có làm trơn. Mỗi baseline phải tuân thủ cutoff giống ML.

### 10.2. Đại lượng đích, loss và model trực tiếp

Quy ước thông tin: C_stats là dữ liệu thực sự khả dụng cho pipeline stats tại cutoff (features, prior và các đầu vào được phép dùng); H_market là line/odds và thông tin thị trường cùng cutoff. H_market ở đây là dữ liệu thị trường **quan sát được**, không đồng nhất với toàn bộ thông tin nội bộ mà thị trường đã sử dụng. Khi phân tích lý thuyết, ký hiệu I_mkt cho information set của một forecaster thị trường lý tưởng; không mặc định C_stats là tập con của I_mkt. C_aug=(C_stats,H_market) là tập thông tin của biến thể có thị trường. Trong các phương trình stats dưới đây, C=C_stats trừ khi ghi rõ augmented model. “Có trước cutoff” không đồng nghĩa “đã được đưa vào model”. A là điều kiện thi đấu/đủ điều kiện được định nghĩa rõ. Với mỗi stat, mean model dự đoán `μ(C) = E[X | C, A]`; median và quantile là các đại lượng riêng. Model mean không phải model phân phối đầy đủ.

| Đại lượng | CatBoost | LightGBM | Metric nhất quán với mục tiêu |
|---|---|---|---|
| Kỳ vọng không âm — ứng viên chính | `loss_function='Poisson'` | `objective='poisson'` | Poisson deviance; RMSE trên μ là metric phụ chung |
| Kỳ vọng — đối chứng | `loss_function='RMSE'` | `objective='regression'` | RMSE/MSE; Poisson deviance chỉ khi đầu ra dương |
| Kỳ vọng — thí nghiệm bổ sung | `Tweedie:variance_power=p`, 1<p<2 | `objective='tweedie'`, `tweedie_variance_power=p` | Deviance tại p cố định giữa các ứng viên và RMSE |
| Trung vị nếu cần point model riêng | `MAE` hoặc `Quantile:alpha=0.5` | `regression_l1` hoặc `quantile`, alpha=0.5 | MAE trên trung vị |
| Các quantile | `MultiQuantile`/`Quantile` theo khả năng implementation | `quantile` theo từng alpha | Pinball loss tại cùng các mức alpha |

Chốt Poisson và squared-error là hai cấu hình mean đầu tiên, cùng feature set và ngân sách tuning. Tweedie chỉ mở thêm nếu validation cho thấy cần, để kiểm soát số lần thử. Chọn cấu hình bằng metric chính đã đăng ký; khi các metric đổi thứ hạng phải báo rõ, không chọn metric có lợi sau khi xem kết quả.

Điểm cần phân biệt:

- Squared-error/RMSE vẫn là lựa chọn đúng để học kỳ vọng, không đòi hỏi dữ liệu Gaussian hoặc phương sai hằng. Gaussian chỉ là giả định bổ sung nếu dùng squared loss để suy ra toàn bộ phân phối.
- Poisson loss cho mean có thể dùng như quasi-likelihood trên mục tiêu không âm ngay cả khi dữ liệu overdispersed. Nó không ép dữ liệu thực tế Var=μ và không tự xác nhận Poisson PMF phù hợp.
- Poisson có lý do cấu trúc để thử: output dương, tác động nhân trên mean qua log-link và working variance tỷ lệ với mean. Khi mean model đúng, Var(X|C)≈c·μ và các điều kiện regularity phù hợp, quasi-score Poisson có thể hiệu quả hơn unweighted least squares. Chỉ biết variance “tăng theo mean” chưa đủ: NB2 có V(μ)=μ+φμ², còn Tweedie có V(μ)∝μ^p. Boosting hữu hạn mẫu, regularization và model misspecification cũng làm kết quả khác lý thuyết tiệm cận.
- Với μ=exp(f), cập nhật cộng Δf tương ứng nhân mean với exp(Δf). Đây là đặc điểm log-link, không độc quyền của Poisson; có thể xây mean model với link dương và loss khác. Không huấn luyện squared-error trên log(X+1) rồi mặc định exp(prediction)−1 là E[X|C]: cần xử lý bias do biến đổi.
- Tweedie với 1<p<2 có atom ở 0 và phần dương liên tục (compound Poisson–Gamma), không phải phân phối đếm nguyên của NBA points. Có thể thử làm loss học mean, không lấy density liên tục làm xác suất Push tại số nguyên.
- Log-link cho mean dương. Kiểm tra `predict` trả raw log-score hay mean theo từng thư viện; không exponent hai lần. Model RMSE có thể dự đoán âm: nếu dùng clipping thì đó là bước của pipeline, phải cố định và đánh giá toàn bộ pipeline. Không tính Poisson deviance với μ≤0; nếu dùng epsilon phải ghi rõ chính sách.
- Không cấm báo MAE của mean như metric mô tả, nhưng không dùng nó làm bằng chứng model ước lượng mean tốt hơn. Nếu có phân phối đầy đủ, lấy mean/median từ chính phân phối cuối để chấm đúng đại lượng.

Train riêng PTS, REB, AST trên player-game rows toàn giải. Chọn thuật toán riêng từng stat. Cửa sổ train 1/2/3 mùa, decay và XGBoost đều thuộc ngân sách thử nghiệm được ghi sổ; không mặc định chạy mọi tổ hợp.

### 10.3. Phân phối hỗn hợp theo phút

Đây là ứng viên cạnh tranh với phân phối trực tiếp, không mặc định tốt hơn. Dùng cùng C và A xuyên suốt:

`P(X=k | C,A) = ∫ P(X=k | M=m,C,A) f_M(m | C,A) dm`.

M là số phút liên tục; dùng tổng trên các bin phút làm xấp xỉ, hoặc tích phân Monte Carlo. Không gọi tổng trên phút nguyên là công thức chính xác cho minutes liên tục.

Ứng viên conditional count model:

`X | M=m,C,A ~ NB2(μ=m·ρ(m,C), φ(m,C))`,

với quy ước `Var(X | m,C,A) = μ + φ μ²`, `φ≥0`, Poisson là giới hạn φ=0. Phải ghi quy ước này vì thư viện khác có thể dùng size r=1/φ. NB là giả định ứng viên, không hệ quả của định luật xác suất toàn phần; so PMF trực tiếp và hướng tách 2PM/3PM/FTM khi nghiên cứu sâu PTS.

Hai đẳng thức cần bảo toàn:

- `E[X | C,A] = E_M[ E[X | M,C,A] ]`.
- `Var(X | C,A) = E_M[Var(X | M,C,A)] + Var_M(E[X | M,C,A])`.

Nếu rate cũng ngẫu nhiên/phụ thuộc phút, không thay `E[Mρ | C,A]` bằng `E[M | C,A]E[ρ | C,A]` trừ khi có giả định phù hợp. Không khẳng định phần phương sai do phút “thường chiếm đa số” trước khi đo phân rã trên dữ liệu ngoài mẫu.

Phân phối phút cần biểu diễn được nghỉ sớm, giới hạn phút, rotation thường lệ và overtime. So mô hình một thành phần với mixture/empirical distribution có đuôi trái. Không bắt buộc thêm một component “chấn thương trong trận” nếu không có dữ liệu nhận dạng; nhãn nghỉ sớm có thể gồm foul trouble, blowout, chiến thuật. Ước lượng trọng số bằng dữ liệu train, kiểm chứng ngoài mẫu; không tự gán tỷ lệ. Giữ support phù hợp, không chặn mọi trận ở 48 phút nếu market tính overtime.

Hai cách dùng minutes phải tách biệt:

1. **Generative conditional model:** có thể học `X | actual M,C,A` trong train rồi tích hợp trên phân phối M dự đoán ở inference. Đây là cách phân rã xác suất, không phải tự động leakage. Tuy nhiên actual M và hiệu suất có phản hồi hai chiều; cần kiểm tra fit joint/phân phối marginal, không diễn giải causal “cho thêm phút sẽ được thêm điểm” máy móc.
2. **Plug-in feature model:** nếu đầu vào stat model ở inference là predicted minutes, trong train cũng phải tạo predicted minutes bằng chronological out-of-fold. Không train kiểu này bằng actual minutes rồi thay thế khi vận hành.

Mô phỏng: lấy mẫu M theo phân phối phút; tính conditional μ,φ; lấy X; lặp và dựng PMF/CDF marginal. Đánh giá cả phân phối phút, conditional stat và marginal stat. Tránh double-counting biến động phút bằng cách vừa trộn M vừa dùng dispersion đã fit từ residual marginal chứa toàn bộ biến động đó.

### 10.4. Dispersion, CDF và hiệu chỉnh xác suất

#### 10.4.1. Dispersion và simulation

- Poisson PMF là baseline. PTS là `2·2PM + 3·3PM + FTM`, nên mô hình compound scoring có cơ chế biến động khác đếm sự kiện đơn vị. Không suy ra conditional overdispersion chỉ từ Var/Mean gộp: khác biệt μ giữa cầu thủ/trận cũng làm tăng tỷ lệ này.
- Có thể ước lượng μ và φ đồng thời bằng likelihood trong tập train; không có luật cấm học dispersion trong train. Nếu fit hậu xử lý dispersion từ residual của mean model linh hoạt, ưu tiên chronological out-of-fold để tránh variance quá nhỏ do overfit. Calibration và đánh giá cuối luôn dùng dữ liệu chưa được fit tương ứng.
- Joint likelihood không miễn nhiễm optimism: mean learner quá linh hoạt có thể hấp thụ noise, làm fitted dispersion nhỏ và predictive intervals hẹp. Dùng temporal validation để chọn complexity, regularization, stopping và cấu trúc dispersion; kiểm tra RPS/log score, PIT và coverage ngoài mẫu. Không mặc định mọi joint estimator đều có cùng độ thiên lệch hoặc cùng chiều trong mọi bối cảnh. Không refit dispersion bằng holdout cuối sau khi xem coverage.
- Bắt đầu bằng dispersion có pooling theo stat/nhóm; chỉ cho phụ thuộc C hoặc M khi đủ mẫu và có cải thiện ngoài mẫu. Không tuyên bố mọi nhóm đều cần dispersion model riêng.
- Dùng quy ước NB2 ở §10.3 và regularization để φ không chạy theo noise; ghi rõ variance conditional hay marginal.
- Pearson residual `r_i=(x_i-μ_i)/sqrt(V_i)` từ dự đoán ngoài mẫu dùng cho diagnostics và kiểm tra working variance. Phép tái dựng `x*=μ_new+sqrt(V_new)·r*` không tự tạo count distribution hợp lệ.
- Pipeline xác suất production ưu tiên họ rời rạc tham số hoặc conditional PMF/CDF có support được đặc tả rõ. Không dùng clip/round residual draws tùy ý để tạo PMF, đặc biệt khi tính Push. Nếu nghiên cứu một quy tắc discretization, phải định nghĩa xác suất mỗi bin/tail và chấm như model riêng; clipping/rounding không bị cấm về toán học nhưng chưa phải giải pháp thống kê được kiểm chứng. Không dùng residual thô với σ chung.
- NGBoost là thí nghiệm phân phối; kiểm tra distribution implementation. CatBoost `RMSEWithUncertainty` giả định Gaussian, không mặc định đúng cho counts.

#### 10.4.2. Quantile và CDF hợp lệ

- Kiểm tra crossing tại mọi mẫu; dùng rearrangement hoặc isotonic projection theo mức alpha trước khi dựng CDF. Việc sửa crossing không tự bảo đảm calibration.
- Cố định lưới quantile, nội suy và cách xử lý tails trên validation. Ít quantile không xác định duy nhất PMF, đặc biệt atom tại line nguyên.
- Đảm bảo CDF không giảm, có giới hạn 0/1, support không âm; PMF lấy từ chênh lệch CDF phải không âm và tổng bằng 1, có xử lý tail mass. Không cắt bỏ tail rồi mặc nhiên coi phần còn lại là toàn bộ phân phối.

#### 10.4.3. Hiệu chỉnh toàn CDF

Thử một biến đổi đơn điệu chung trong từng stat/nhóm được định nghĩa trước:

`F_cal(k | C,A) = G(F_raw(k | C,A))`,

với `G:[0,1]→[0,1]` không giảm, G(0)=0, G(1)=1 và thỏa điều kiện liên tục phải cần thiết cho CDF. Lựa chọn đơn giản: isotonic trên lưới thresholds với endpoints ràng buộc. Học G bằng CDF-Brier/RPS trên một calibration block riêng, giới hạn độ phức tạp, cố định trọng số của thresholds và player-games. Một lựa chọn khác là phương pháp recalibration hỗ trợ discrete PIT đúng nghĩa, không áp dụng công thức PIT liên tục một cách máy móc.

**Điều kiện information set và sửa chính sách weights bản 1.3:**

Với một threshold k, đặt Z_k=1{Y≤k}, forecast f_k đo được theo C_stats và trọng số W_k≥0 có kỳ vọng hữu hạn, dương. Nghiệm tối ưu của weighted binary squared loss, khi chưa áp ràng buộc joint-CDF, là:

`f*_k(C_stats)=E[W_k Z_k | C_stats,A]/E[W_k | C_stats,A]`.

Do đó:

`f*_k−P(Y≤k | C_stats,A)=Cov(W_k,Z_k | C_stats,A)/E[W_k | C_stats,A]`.

W_k đo được theo C_stats (và k) là điều kiện đủ để giữ đúng conditional CDF target ở threshold có weight dương; zero conditional covariance cũng đủ, còn measurability không phải điều kiện cần duy nhất. Phải áp điều kiện này cho **trọng số tổng**, gồm selection vào sample, trọng số player-game và threshold normalization, không chỉ kernel của k.

Line L có thể chứa thông tin không có trong C_stats; dù L có trước cutoff và dùng chung cho mọi ứng viên, W_k(L) vẫn có thể đổi mục tiêu khi tối ưu forecasts chỉ dùng C_stats. Bản 1.3 đã nhập nhằng hai information sets khi dùng line-weights để học một G chung cho stats-only CDF. Không giữ chính sách đó làm mặc định.

Ví dụ kiểm tra: C_stats không phân biệt hai nhóm thị trường B=0/1 có xác suất 1/2; P(Z=1|B=0)=0.2, P(Z=1|B=1)=0.8. Dùng W=0.25 khi B=0 và W=1 khi B=1 cho E[Z]=0.5 nhưng E[WZ]/E[W]=0.68. Forecast tối ưu đã đổi dù W không dùng outcome đã quan sát và B có thể xuất hiện trước trận.

**Đường A — calibration và lựa chọn model stats-only:**

- Mặc định học G bằng full RPS trên calibration block gồm quần thể player-games mục tiêu có thể tái dựng bằng C_stats, không chỉ những người được mở kèo. Dùng lưới threshold nguyên cố định theo stat, đủ rộng và khóa bằng development data; xử lý tail mass và báo độ nhạy theo độ rộng để xấp xỉ tổng RPS đúng. Không để normalization/support thay đổi theo outcome hoặc theo model đang chấm.
- Các ứng viên được chấm trên cùng sample policy và cùng fixed-grid weights; báo full RPS, discrete log score, discrete PIT, coverage, tails và Push. Lựa chọn/calibration policies chỉ học từ các khối development, không từ holdout.
- Thử nghiệm phụ có thể dùng weights từ một baseline chung đã khóa, là hàm của C_stats. Đăng ký baseline, vùng threshold, normalization và population; không dùng F riêng của từng ứng viên hoặc một reference có thông tin ngoài C_stats.
- Với fixed nonnegative weights, `S_C(F,y)=Σ_k w_k(C_stats)[F(k)−1{y≤k}]²` giữ conditional target trong vùng weight dương. Trọng số bằng 0 không nhận dạng toàn bộ CDF. Không gọi mọi objective cắt vùng là strictly proper cho toàn phân phối.
- Một G chỉ nhận u=F_raw(k) là model hậu xử lý bị giới hạn thông tin. Dù w đo được theo C_stats, nghiệm trong lớp G này vẫn là weighted projection và không tự bảo đảm unweighted marginal calibration trên mọi population/cohort. Phân biệt proper target của full forecast với guarantee của lớp calibrator hạn chế; kiểm tra calibration sau fit. Chọn full-RPS/fixed-grid làm mặc định để giảm nhập nhằng, không quảng cáo nó chữa mọi misspecification.
- Nếu chỉ có dữ liệu của offered players, khai báo rõ calibration target là population đó; không coi trọng số C_stats tự khôi phục population toàn giải hoặc tự giải quyết selection do thị trường. Muốn suy rộng cần dữ liệu và giả định selection phù hợp.

**Đường B — pricing và so model với thị trường:**

- Tại mỗi snapshot, dùng chính L của book để đánh giá CDF tại cùng event như §11.4; line nguyên thêm threshold L−1 để xác định Under/Push. Chuẩn hóa theo player-game và threshold duy nhất để alternate lines/books không tăng giả số quan sát độc lập.
- Có thể báo line-weighted CDF-Brier/RPS quanh vùng main line theo policy đã khóa. Đây là utility/pricing score có thể chọn lọc theo H_market; không gọi nó là proper calibration objective cho P(Y|C_stats) nếu không thỏa conditional-covariance condition.
- So hai stats-only model bằng paired pricing scores trả lời được model nào tốt hơn ở offered events, nhưng trong kế hoạch này **không dùng bảng đó làm tiêu chí chọn G_stats/base stats model**. Chọn stats-only pipeline bằng đường A, khóa rồi mới báo pricing. Nếu sau này tối ưu stats-only model riêng cho pricing, phải đăng ký là target/variant khác và có holdout mới; không đổi model stats mặc định chỉ vì bảng line-score đẹp hơn.
- Không dùng W(L) để học G_stats rồi áp nó lên toàn bộ CDF như thể không có market information. Nếu nghiên cứu cách này, gắn nhãn market-selected calibration, giữ G riêng và không dùng làm default.

**Đường C — biến thể có thị trường:**

- Chỉ khi H_market được cung cấp **thực sự** cho model/calibrator cả train lẫn inference tại cùng cutoff, xây `F_aug(Y | C_stats,H_market,A)` và công bố là model có thị trường. Chỉ tuyên bố đổi tập thông tin trên giấy mà không cấp đầu vào không giải quyết misspecification của một G không biết L.
- W_k(L) đo được theo C_aug nên có thể dùng cho objective conditional tương ứng; vẫn cần cùng support/population policy và validation ngoài mẫu. Không so kết quả augmented với stats-only như thể dùng cùng thông tin.
- Nếu calibrator trả một CDF cho mỗi snapshot, G(u;C_aug) phải không giảm theo u với context giữ cố định; không fit các biến đổi theo threshold tùy ý làm CDF crossing. Bao gồm L trong context không tự làm model calibrated hoặc tail-correct.

**Sensitivity và quyết định đã đăng ký:**

1. Fit G_stats bằng đường A; đây là production default của stats-only system.
2. Nếu dữ liệu cho phép, fit G_line-selected riêng để audit failure mode; không dùng kết quả của thí nghiệm để đổi mục tiêu holdout hồi tố.
3. Đánh giá hai bản trên cùng future block bằng full RPS, discrete PIT, tail/Push calibration và pricing score riêng; dùng paired block intervals. Kiểm tra sai khác giữa offered và toàn bộ target population.
4. Giữ G_stats trừ khi một augmented pipeline hoặc một target pricing riêng đã được đăng ký và xác nhận; không chọn bằng tiêu chí “kéo ít hơn ở đuôi” hoặc PIT một mình.

**Điều kiện chính xác cho xu hướng về 0.5 tại line:**

Với W_k=1{L=k}, nghiệm threshold-specific là `P(Y≤k | C_stats,L=k,A)`. Điều kiện ideal median `P(Y≤L | I_mkt,A)=0.5` suy ra giá trị này bằng 0.5 nếu (C_stats,L) đo được theo I_mkt, bằng tower property. Với sai số median bounded bởi epsilon, sai lệch conditional được chặn tương ứng nếu cùng các điều kiện. Đây là kết quả có điều kiện, mạnh hơn một ví dụ tùy ý nhưng không tự suy ra chỉ từ tên gọi “thị trường hiệu quả”.

Nếu không có nesting, từ `P(Y≤L | I_mkt,A)≈0.5` không suy ra `P(Y≤L | C_stats,L,A)≈0.5`: C_stats có thể có thông tin bổ sung. Counterexample cho các giả định xác suất: hai nhóm C_stats có xác suất bằng nhau; tại một L cố định, CDF thật theo nhóm là 0.2 và 0.8, trong khi market không phân biệt hai nhóm nên CDF market lý tưởng bằng 0.5. Stats-only CDF đúng vẫn là 0.2/0.8 tại line; line-weighted G không bắt buộc kéo về 0.5. Ví dụ này kiểm tra logic nesting, không là bằng chứng tồn tại edge NBA.

Thêm nữa, line thực có thể là alternate line hoặc odds hai phía lệch. Market-calibration không đồng nghĩa mọi line là median: nếu tại line nửa điểm xác suất Under fair là q khác 0.5, target tham chiếu là q; với line nguyên, Push và conditioning decisive còn làm P(Y≤L) khác 0.5 ngay khi hai phía có xác suất decisive cân bằng.

Cách diễn đạt vận hành: **kỳ vọng co về xác suất thị trường tại line khi line gần median, market gần ideal cho information set bao hàm C_stats, và các conditioning rules tương thích; mức độ co cần đo**. Không định nghĩa một hệ số co tỷ lệ tuyến tính với “độ hiệu quả thị trường” khi chưa có định nghĩa và mô hình cho độ hiệu quả đó.

Chẩn đoán G_line-selected bằng reliability plots của raw u và outcome trên line-selected samples, stratify theo market-implied probability, stat, line, cohort; so identity, G_line-selected(u) và G_stats(u). Đánh giá full-CDF ở đường A riêng. Reliability plot có thể kiểm tra biểu hiện co nhưng không tự xác nhận causal mechanism, information-set nesting hoặc market efficiency.

Nếu L có trước cutoff và calibration dùng dữ liệu quá khứ đúng thời gian, đây là **market-information contamination/selection-induced target shift** của pipeline stats-only, không tự động là leakage từ tương lai hay dùng outcome trận đích. Phân biệt với việc dùng closing line sau cutoff, vốn vi phạm thời điểm thông tin.

Sau biến đổi, `p_cal(k)=F_cal(k)-F_cal(k-1)`. Một G dùng chung across thresholds giữ tính nhất quán và làm xác suất Over không tăng khi line tăng; không fit G khác nhau tùy line. G chung không bảo đảm calibration có điều kiện cho mọi cầu thủ/vai trò; phải kiểm tra theo cohort và drift. Tính đơn điệu riêng nó cũng không bảo đảm calibration biên: đó là mục tiêu cần học và kiểm chứng, không là hệ quả tự động của phép biến đổi.

PIT diagnostics cho dữ liệu rời rạc:

- Không kỳ vọng `F(X_observed)` có phân phối Uniform như trường hợp liên tục.
- Randomized PIT: `U=F(X-1)+V·[F(X)-F(X-1)]`, V~Uniform(0,1) độc lập.
- Có thể dùng non-randomized PIT theo Czado, Gneiting & Held (2009): mỗi quan sát đóng góp phân số kỳ vọng vào các bin PIT tương ứng thay vì rút ngẫu nhiên V. Không gọi mid-PIT đơn thuần là phép chẩn đoán có cùng bảo đảm.
- Kiểm tra PIT và marginal calibration trên evaluation block sau calibration; histogram gần đều chưa chứng minh phân phối đúng có điều kiện.

#### 10.4.4. Scoring, khoảng và xác suất

Dùng RPS cho support nguyên có thứ tự và discrete log score cho PMF. Với CDF F và outcome y:

`RPS(F,y)=Σ_{k=0}^∞ [F(k)-1{y≤k}]²`.

Đây cũng là dạng CRPS trên lưới nguyên đơn vị; không nói CRPS sai chỉ vì dữ liệu rời rạc. Khi tính trên support hữu hạn phải ghi chính sách tail; discrete log score là `-log p(y)`, mọi probability floor dùng vì số học phải được công bố.

Với mức γ, có thể xuất tập dự đoán A nhỏ nhất theo số phần tử sao cho `Σ_{k∈A}p_cal(k)≥γ`; tập này có thể không liên tục. Nếu giao diện cần một khoảng, chọn khoảng nguyên liên tục ngắn nhất thỏa cùng điều kiện, nêu tie-break và phân biệt với equal-tail interval.

Bất đẳng thức trên là **khối lượng theo phân phối dự đoán**, không bảo đảm độ phủ thực tế ≥γ khi model sai hoặc drift. Nếu F bằng phân phối thật có điều kiện C,A thì tập được chọn có conditional coverage ít nhất γ; phần vượt mức có thể do các atom rời rạc. Chỉ đạt marginal/PIT calibration không đủ suy ra bảo đảm đó cho mọi tập dự đoán thích nghi hoặc cohort, và tần suất đo được trên một holdout hữu hạn vẫn có sai số lấy mẫu. Đo empirical coverage ngoài mẫu cùng độ rộng/cardinality và độ bất định; không quảng cáo finite-sample coverage guarantee nếu chưa có phương pháp và giả định tương ứng.

Với X nguyên, xác suất có điều kiện A tại line L:

- `q_over = 1-F_cal(floor(L))`.
- `q_under = F_cal(ceil(L)-1)`.
- `q_push = p_cal(L)` nếu L nguyên, ngược lại bằng 0.
- `q_over + q_under + q_push = 1`.

Các q ở đây chưa bao gồm void; chuyển thành xác suất settlement theo §12. Mean/median của phân phối sau calibration có thể đổi so với mean model đầu; phải ghi và chấm phân phối cuối mà người dùng nhận.

### 10.4.5. Ứng viên PTS theo cơ chế ném: volume và accuracy

Đưa vào roadmap P2 như đối chứng cơ chế, chưa thay mặc định mean/distribution model trực tiếp. Dữ liệu game logs hiện có đủ đếm attempts/makes cơ bản, nhưng phải xác nhận các ràng buộc sau chuẩn hóa.

1. Lấy mẫu minutes M và shared context/game factors C.
2. Dự đoán/lấy mẫu FGA và FTA từ conditional count distribution. Gamma–Poisson shrinkage trên rate attempts là baseline; thêm NB/dispersion nếu ngoài mẫu ủng hộ.
3. Để tránh đếm trùng và mẫu bất khả thi, lấy `3PA | FGA` bằng Binomial hoặc Beta-Binomial với 0≤3PA≤FGA; đặt `2PA=FGA−3PA`. Một cách khác là mô hình joint 2PA/3PA rồi cộng thành FGA; không sample FGA và 3PA độc lập mà bỏ qua ràng buộc.
4. Với loại ném j∈{2PT,3PT,FT}, dùng `θ_j ~ Beta(a_j,b_j)`, `made_j | attempts_j,θ_j ~ Binomial(attempts_j,θ_j)`. Phân phối made count sau tích phân θ là Beta-Binomial. Chính xác hơn nên nói “Beta cho xác suất ném, Beta-Binomial cho số lần vào có điều kiện số lần ném”, không gọi Beta-Binomial là phân phối của tỷ lệ liên tục.
5. Với prior Beta và các trận trước cutoff, baseline posterior parameters là `a_post=a_prior+Σ made`, `b_post=b_prior+Σ(attempts−made)`; weights/nhóm prior phải có quy ước và được chọn như §8. Không cộng thêm một lần posterior uncertainty nếu đầu ra đã là posterior predictive Beta-Binomial.
6. Tính `PTS=2·2PM+3·3PM+FTM`; các made counts luôn nguyên, không âm và không vượt attempts. Kiểm tra quan hệ `FGM=2PM+3PM`, `FGA=2PA+3PA`.

Beta-Binomial hỗ trợ variation/uncertainty về accuracy nhưng không tự mô tả đúng mọi shot dependence; phân biệt posterior uncertainty về rate với biến động rate giữa các trận để tránh double-counting. Attempts, accuracy, shot mix và FTA có thể phụ thuộc nhau qua chất lượng cú ném, vai trò và pace; không mặc định độc lập vô điều kiện. So mô hình components với PTS trực tiếp bằng RPS/log score, mean errors, tail/Push calibration và độ phức tạp.

### 10.5. PRA và mở rộng

PRA, 3PM, steals/blocks để sau MVP. Với mô phỏng PRA, lấy **cùng một mẫu phút M** cho PTS, REB, AST của cầu thủ, cùng game/scenario factors khi có, rồi cộng ba mẫu stat trong mỗi lần mô phỏng. Cách này giữ phần tương quan qua phút, nhưng chưa giữ hết conditional covariance do usage, possessions và tương tác stat. Đánh giá joint/tổng ngoài mẫu; chỉ thêm residual copula/shared factors khi có bằng chứng và dữ liệu đủ.

Ứng viên khác: học trực tiếp phân phối `PTS+REB+AST`. Nếu phân phối trực tiếp và các marginal model không đồng nhất, báo riêng và kiểm tra tính nhất quán. Kỳ vọng tổng bằng tổng kỳ vọng, nhưng không cộng ba xác suất Over và không mặc định độc lập có điều kiện chỉ vì dùng chung M.

## 11. Backtest và tiêu chí lựa chọn

### 11.1. Thiết kế thời gian và chia block — cập nhật bản 1.8

Từ bản 1.6 chọn **các khối tách biệt liên tiếp**, không để code agent tự chọn giữa cách đó và nested OOF cho thử nghiệm xác nhận. OOF vẫn có thể dùng trong nghiên cứu development bên trong block được phép, nhưng không thay vai trò các block sau:

| Block | Khoảng dữ liệu và cách xác định | Được học gì? |
|---|---|---|
| B0 | Regular Season 2023-24 | Base stats candidates và baseline |
| B1 | Một phần ba đầu các ngày có trận Regular Season 2024-25 | Chọn base stats features/loss/hyperparameters theo full-RPS/stats metrics; không chọn theo line-pricing score |
| B2 | Một phần ba giữa các ngày có trận Regular Season 2024-25 | Fit G_stats cho base đã khóa; không fit stacker |
| B3 | Một phần ba cuối các ngày có trận Regular Season 2024-25 | Fit H và S+H/stacker; giữ base và G_stats cố định |
| B4 | Tối đa280 scheduled game dates từ đầu Regular Season 2025-26, có checkpoint140 và280 | Prequential pilot của recipe refit đã khóa; futility-only, variance và inference gate; không sửa recipe theo mean |
| B4G | Các dates sau B4 và trước registration release R; không kéo dài B4 | Gate computation/operational gap, không chấm như pilot hoặc holdout |
| B5 | 200 scheduled game dates bắt đầu từ ngày sau release R | Xác nhận duy nhất H_refit/S+H_refit theo recipe §11.7.8; frozen pair thăm dò |

Chia B1/B2/B3 bằng danh sách ngày UTC có trận Regular Season 2024-25 tăng dần: cut1=floor(D/3), cut2=floor(2D/3), không tách một ngày/trận qua hai block. Freeze các ngày biên thực và hash schedule trong manifest trước khi tính model scores. Từ bản 1.7, B4/B5 dùng trục **scheduled Regular-Season game dates**, không trục calendar liên tục. Ngày có trận theo schedule nhưng không có eligible props vẫn giữ counts=0, không được loại sau khi thấy missing/outcomes. Ngày không có trận Regular Season không đếm vào T. Giữ lịch UTC thật và season_id để mô hình dependence nhận biết nghỉ dài/offseason.

Cuối B1, refit base stats đã chọn trên B0+B1 rồi khóa; B2 dự đoán bằng base đó và fit G_stats. Sau B2 khóa G_stats; B3 tạo stats outputs từ base+G đã khóa rồi fit H/S+H. Sau B3 khóa recipe/hyperparameters và lưu bộ weights frozen làm đối chứng. Từ bản 1.8, primary refit bundle cập nhật parameters đúng recipe §11.7.8 trong B4/B5; không đổi recipe do mean Δ. Mỗi feature/training label vẫn tuân thủ thời điểm khả dụng. Không dùng B4 sửa recipe chỉ vì score đẹp; sửa như vậy làm mất pilot nguyên vẹn và phải version/replay/validate lại trước B5.

B4 **thay vai trò holdout cuối của 2025-26 trong bản ≤1.5**. Bản 1.8 định trước tối đa280 scheduled game dates với hai checkpoint chỉ-dừng, có thể cần nhiều hơn một mùa; đây là sàn planning vận hành 20×14, không là định lý “20 blocks thì bootstrap đúng”. Nếu chưa tới checkpoint140, status là BLOCKED_PILOT; nếu tiếp tục sau140 nhưng chưa đủ280 cho gate đầy đủ, status là BLOCKED_SMALL_PILOT, không tự giả lập thêm data như observations thực. Không báo B4 là kết quả xác nhận nữa. B5 chỉ gồm dự đoán thực có timestamp sau freeze; không gọi các trận 2026-27 đã diễn ra trước freeze là prospective holdout.

Nếu thiếu historical odds đúng cutoff cho B3/B4, nhánh xác nhận market bị `BLOCKED_DATA`, không tự chuyển sang closing odds hoặc tự ghép mùa khác. Stats-only MVP vẫn triển khai được. Việc cần bổ sung nguồn dữ liệu không được giải quyết bằng code agent tự chọn lại split. Chỉ mở B5 sau feasibility gate ở §11.7; không tạo automation hay bắt đầu thu thập theo lịch chỉ từ tài liệu kế hoạch.

Giữ registry toàn bộ trials development, kể cả failures, thay đổi thủ công và ensemble weights. Các cấu hình thăm dò không được thăng thành cặp xác nhận sau khi đã thấy B5. Nếu thay protocol sau khi xem B5, giữ bản cũ và dùng dữ liệu mới; không sửa nhãn exploratory thành confirmatory.

### 11.2. Metrics, phụ thuộc và kiểm định theo cặp

| Phần | Metrics và quy ước |
|---|---|
| Kỳ vọng | Poisson deviance với μ>0 và RMSE trên mean; cùng mục tiêu/samples khi so |
| Trung vị/quantile | MAE trên median, pinball tại cùng alpha |
| Phân phối rời rạc stats-only | Full RPS/fixed-grid weights theo C_stats, discrete log score và PIT; tách riêng line-selected pricing score |
| Tập/khoảng dự đoán | Empirical coverage, cardinality/width, theo mức γ và cohort |
| Over/Under | Brier/log loss trên xác suất có cùng conditioning; không coi Push là Under |
| Vận hành | Coverage cầu thủ, độ trễ, thiếu dữ liệu, collector/schema failures |
| Thị trường | Paired ΔBrier/Δlog loss trên cùng sự kiện, EV/ROI settlement, số lựa chọn và drawdown |

Nguồn phụ thuộc gồm alternate lines cùng người/trận; PTS/REB/AST cùng người; cầu thủ trong cùng trận do pace/blowout; và tương quan giữa các ngày do phong độ/đội hình.

- So hai model bằng `d_i = score_A(i)-score_B(i)` trên cùng observations, rồi tính khoảng của mean(d) bằng paired block bootstrap. Không suy luận khác biệt bằng cách nhìn hai confidence intervals riêng có chồng nhau không.
- Giữ toàn bộ cầu thủ, markets và lines cùng trận trong một cluster. Để giữ cả phụ thuộc thời gian, ưu tiên moving/stationary bootstrap theo **khối nhiều ngày liên tiếp**, chứa toàn bộ trận của ngày. Cluster theo trận đơn lẻ không giữ tự tương quan xuyên trận.
- Chọn block length bằng chính sách trước evaluation và báo sensitivity; không mặc định một block length loại bỏ mọi phụ thuộc hoặc bảo đảm đúng khi drift mạnh.
- Báo riêng rookie, nghỉ dài, đổi đội, bench/starter, mức line và giai đoạn mùa. Ghi cả coverage của model, không chỉ kết quả trên nhóm được giữ lại.

### 11.3. Quy tắc chấp nhận và lượng bằng chứng

- Stats-only candidates so với baseline trong development; quyết định xác nhận thêm stats ngoài market dùng đúng estimand/margin/CI ở §11.7. Không bác bỏ H0 không được diễn giải là không có thông tin.
- So model cùng cutoff, tập đánh giá, conditioning và ngân sách tuning. Chọn trước metric chính, không đặt accuracy tùy ý.
- Ensemble weights chỉ học từ development data; đánh giá đầy đủ pipeline cuối.
- Không kết luận có lợi nhuận nếu thiếu line/odds khả dụng đúng thời điểm, quy tắc settlement hoặc số quan sát hiệu dụng.

Ước lượng sơ bộ để lập ngân sách kiểm chứng, với stake bằng nhau, lợi nhuận R mỗi lượt và độ lệch chuẩn giả định σ=0.95:

- Muốn sai số khoảng 2 standard errors bằng ROI δ: `n≈(2σ/δ)²`. δ=2% cho n≈9.025; δ=5% cho n≈1.444 quan sát **độc lập**.
- Đây là phép tính precision/signal-to-noise, **không phải** thiết kế kiểm định có power 80%.
- Với kiểm định mean ROI hai phía α=5%, power 80%, xấp xỉ Normal: `n≈[(z_0.975+z_0.80)σ/δ]²`, tương ứng n≈17.709,03 và 2.833,45, làm tròn lên **17.710** và **2.834**. Nếu σ gần 1 thay vì 0.95, số cần lớn hơn; odds đúng 2.00 và win/loss gần 50/50 cho σ gần 1.
- Nếu giả thuyết xác nhận được đăng ký **một phía** H0: ROI≤0, H1: ROI>0, dùng z_0.95 thay z_0.975. Với cùng α=5%, power=80%, σ=0.95: n≈13.949,4 cho δ=2% và n≈2.231,9 cho δ=5%, làm tròn lên **13.950** và **2.232** quan sát độc lập. Giảm khoảng 21,2% so với hai phía. Không chọn số phía sau khi xem dấu của ROI; một phía không cho phép phát biểu đối xứng về cả lợi/lỗ.

| Thiết kế, power=80%, σ=0.95; n làm tròn lên | ROI 2% | ROI 5% |
|---|---:|---:|
| Hai phía, α=0.05, một giả thuyết | 17.710 | 2.834 |
| Một phía, α=0.05, một giả thuyết | 13.950 | 2.232 |
| Hai phía, α=0.05/3, Bonferroni ba giả thuyết | 23.621 | 3.780 |
| Một phía, α=0.05/3, Bonferroni ba giả thuyết | 19.898 | 3.184 |

**Multiplicity của bảng ROI minh họa:** bảng mô tả các thiết kế có thể dùng nếu một nghiên cứu ROI riêng đăng ký một giả thuyết gộp hoặc ba giả thuyết PTS/REB/AST với family-wise α=5%. **Trong protocol xác nhận bản 1.6, chỉ ΔBrier gộp H/S+H ở §11.7 là primary; ROI và ba subgroup estimates chưa là giả thuyết xác nhận.** Bảng Bonferroni chia α cho 3; không cần độc lập giữa ba tests để có Bonferroni control nếu từng p-value hợp lệ. Holm là lựa chọn step-down không kém Bonferroni về rejection power với cùng family/p-values hợp lệ. Bảng giữ Bonferroni vì alpha_test=alpha/m cố định cho phép minh họa closed-form planning; không phải vì Bonferroni tốt hơn. Nếu nghiên cứu tương lai xác nhận nhiều hypotheses, mặc định dùng Holm với block-valid p-values và mô phỏng power theo joint distribution; không lấy bảng Bonferroni làm exact power của Holm. Đăng ký family gồm mọi confirmatory tests, kể cả β/selected-edge tests nếu chúng cũng được dùng để tuyên bố thành công; không dùng α/3 khi thực tế family lớn hơn.

Các con số Bonferroni là marginal power 80% cho từng test tại alpha đã chia, không bảo đảm xác suất phát hiện **cả ba** bằng 80%. So với cùng thiết kế một giả thuyết, n tăng khoảng 33,4% cho hai phía và 42,6% cho một phía; không gộp cả hai thành “tăng 33%”. Một giả thuyết gộp có thể che khác biệt giữa markets, nên vẫn báo subgroup estimates mà không tự biến chúng thành ba tuyên bố xác nhận độc lập.

**Variance theo odds:** nếu chỉ win/loss, R=d·I_win−1 và `Var(R)=d² p(1−p)`. Tại giá công bằng p=1/d, `Var(R)=d−1`. Vì vậy d=3,p=1/3 cho σ=sqrt(2)≈1.414 và n tỷ lệ theo σ² lớn khoảng 2.216 lần so với giả định σ=0.95, nếu giữ nguyên các giả định khác. Với push/void hoàn tiền, `Var(R)=p_win(d−1)²+p_loss−EV²`; với nhiều mức odds, thêm sự khác biệt giữa conditional means theo law of total variance. Ước lượng variance từ phân bố giá, stakes và settlement của policy thực tế trong development; mô phỏng power dưới các effect-size scenarios đã định trước. Không dùng σ=0.95 cho mọi price hoặc tối ưu σ sau khi xem holdout.

Đây là xấp xỉ Normal với variance giả định gần cố định dưới null/alternative; không phải số mẫu bảo đảm cho NBA betting. Khi variance hai giả thuyết khác đáng kể, dùng thiết kế/mô phỏng có σ0 và σ1 thay vì một σ chung.

- Tương quan, stake khác nhau, void/push, số lượng chiến lược đã thử và nonstationarity làm công thức đơn giản này không còn trực tiếp áp dụng. Cần mô phỏng power theo quy trình lựa chọn thực và các khối ngày/trận, không thay raw bet count vào công thức độc lập.
- Với stationary return sequence có tự hiệp phương sai γ_h, xấp xỉ `Var(mean R)≈[γ_0+2Σ_{h≥1}γ_h]/n`; ESS cho mean return có thể định nghĩa `n_eff≈n·γ_0/[γ_0+2Σγ_h]`. Khi phụ thuộc dương làm long-run variance tăng, n_eff giảm. Đây là ESS theo metric, khác ESS theo trọng số ở §8; không có một n_eff chung cho mọi ROI, score difference và portfolio.
- Không khẳng định n_eff “nhỏ hơn rất nhiều” hoặc luôn nhỏ hơn n chỉ từ việc có dependence. Dấu và độ lớn covariance cần được ước lượng; tương quan âm/hedging có thể giảm variance. Ước lượng paired score difference cũng có dependence khác raw returns. Báo design effect/long-run variance, sensitivity theo block length và power mô phỏng.

Không coi “một mùa” là đơn vị đủ bằng chứng. Một mùa có thể không đủ để xác nhận ROI nhỏ; cũng không thể khẳng định mọi một-mùa holdout đều không đủ nếu chưa biết effect size, variance và effective sample size. Phân biệt bằng chứng model cải thiện scoring rule với bằng chứng một chiến lược có ROI dương.

#### 11.3.1. Nguồn gốc số power và mã tái lập

**Tất cả n trong bảng là phép tính giải tích xấp xỉ Normal do kế hoạch tự tính, không lấy từ một bảng thực nghiệm hoặc mô phỏng NBA.** Nguồn 21 giải thích alpha/power/effect size; nguồn 30 giải thích multiple-testing corrections. Không nguồn nào cung cấp các số NBA này.

Assumptions của bảng:

- Stake 1, mean return effect delta=0.02 hoặc 0.05; sigma=0.95 được giả định gần như nhau dưới null/alternative.
- Các return observations của **từng test** độc lập theo lượt/trận/ngày trong phép tính; không có cluster/time dependence được mô phỏng trong bảng này.
- Bonferroni điều chỉnh ba hypotheses nhưng không giả định tương quan PTS/REB/AST bằng 0 để kiểm soát FWER. Không tính joint power cả ba; các tests có thể phụ thuộc. Nếu gộp ba markets vào một mean portfolio test, variance phải có covariance giữa markets, không dùng lại sigma=0.95 máy móc.
- Cỡ mẫu cuối được ceil từ số thực; không chọn alpha/sides/sigma/effect sau khi xem holdout.

Mã Python dùng standard library, có thể chép chạy trực tiếp:

```python
from math import ceil, sqrt
from statistics import NormalDist

N = NormalDist()
alpha_family = 0.05
power = 0.80
sigma = 0.95
for hypotheses in (1, 3):
    alpha_test = alpha_family / hypotheses
    for sides in (2, 1):
        z_alpha = N.inv_cdf(1 - alpha_test / sides)
        for delta in (0.02, 0.05):
            n_real = ((z_alpha + N.inv_cdf(power)) * sigma / delta) ** 2
            print(hypotheses, sides, delta, ceil(n_real))

# No push/void: fair decimal odds d give variance d-1.
d = 3.0
print("sigma at fair d=3:", sqrt(d - 1))
print("sample-size multiplier vs sigma=.95:", (d - 1) / sigma**2)
```

Expected counts (hypotheses, sides, ROI 2%, ROI 5%): `(1,2,17710,2834)`, `(1,1,13950,2232)`, `(3,2,23621,3780)`, `(3,1,19898,3184)`.

**Phụ thuộc thực tế chưa có tham số được ước lượng:** không gán rho cho NBA hoặc tuyên bố đã có empirical power. Khi có development returns/score differences, ước lượng long-run covariance theo §11.2–11.3 và mô phỏng/resample cả vectors PTS/REB/AST trong các block nhiều ngày, giữ player-game/market grouping và locked policy. Đăng ký null/alternative, cơ chế effect injection và số simulations, báo Monte Carlo error, empirical size và marginal/joint power nếu cần.

Sensitivity đại số có thể dùng independent equal-size clusters m và common within-cluster return correlation rho: `design_effect=1+(m−1)rho`, `n_raw≈n_independent×design_effect`. Đây là stress assumption, không là ước lượng NBA; không mô tả serial dependence giữa clusters. Không cộng design effect này với long-run covariance theo cách đếm trùng cùng nguồn phụ thuộc. Correlation của raw stat không bằng correlation của bet returns hoặc paired score differences.

### 11.4. Benchmark thị trường và chọn mẫu


**Vai trò đã khóa của bảng chấm tại line:** đây là đánh giá hiệu quả pricing/ra quyết định tại offered events. Nó không phải bài kiểm tra thuần về calibration của G_stats, cũng không là phép đo thuần của khoảng cách thông tin. Chênh lệch scores gồm thông tin, approximation/estimation error, calibration của cả hai phía, cách de-vig, selection và sampling uncertainty. Không dùng bảng này chọn G_stats trong pipeline mặc định.

Nếu hai forecasters đều ideal cho các tập thông tin lồng nhau và score proper tương ứng với event/weights đã biết ở tập lớn, forecaster có nhiều thông tin hơn không kém về **expected score**. Kết luận không tự áp dụng cho các model học hữu hạn mẫu hoặc giá thị trường thực chưa phải true conditional probability. Thua pricing không chứng minh G_stats sai; thắng cũng không tự chứng minh có leakage. Phải kiểm tra timestamps, selection và uncertainty theo quy trình chung, không mặc định thắng thị trường là bất thường.

Để nghiên cứu **thông tin bổ sung ngoài thị trường**, benchmark chính là market-only pipeline dùng H_market và augmented pipeline dùng (C_stats,H_market) ở cùng cutoff, sample, lines, calibration budget và temporal split. Giữ raw de-vig odds làm baseline thương mại. Việc cấp H_market không cô lập hoàn toàn “chỉ còn thông tin stats”: model misspecification, learning error và recalibration vẫn tồn tại; báo contribution bằng ablation ngoài mẫu, không diễn giải thành pure information gain đã biết.

- Báo metric dự báo stats trên toàn tập mục tiêu và báo metric thị trường trên **đúng tập cầu thủ/market được mở line**, khả dụng ở cutoff. Không ngoại suy kết quả của nhóm này sang mọi player-game.
- Benchmark pricing chính là xác suất thị trường bỏ vig từ odds **cùng cutoff, book, line, settlement rules**. Việc đánh giá trên line thị trường có thể chứa thông tin ngoài C_stats; không dùng score này để tuyên bố proper full-CDF calibration cho stats-only model. G_stats vẫn fit theo đường A ở §10.4.3. So model với thị trường trên cùng sự kiện và conditioning, báo paired Δlog loss/ΔBrier cùng block confidence intervals.
- Cách triển khai ở mỗi offered snapshot: lấy line L của chính nhà cái; tính `q_model,O=1−F_model(floor(L))` và q_push từ CDF/PMF tại **cùng cutoff**. Với line nửa điểm, so trực tiếp với xác suất de-vig hai phía. Với line nguyên, dùng `r_model,O=q_model,O/(1−q_model,push)` khi mẫu số>0 để so với r_market trên các kết quả decisive, hoặc dùng phân phối settlement đầy đủ khi baseline có đủ xác suất Push/void.
- Tính cùng outcome và cùng weighting cho từng cặp model/market rồi mới lấy score difference. CDF giúp đánh giá model tại line thị trường bất kỳ, nhưng không khôi phục được giá thị trường ở cutoff bị thiếu và không biến dữ liệu closing thành snapshot sớm. Khi có alternate lines, không tăng giả tạo cỡ mẫu độc lập bằng cách đếm mỗi line như một trận mới.
- Closing odds/line là benchmark tham khảo mạnh về thông tin cuối, nhưng có thể chứa tin sau cutoff. Không dùng làm feature hoặc baseline “cùng thông tin” của model dự đoán sớm.
- Nếu closing line khác line lúc dự đoán, hai phía đang dự đoán hai sự kiện khác nhau: không so trực tiếp Brier/log loss tại hai thresholds rồi diễn giải là hơn/kém. Chỉ so ở line chung có odds/distribution hợp lệ; báo CLV theo quy tắc đã định nghĩa như phân tích riêng, không xem CLV là lợi nhuận bảo đảm.
- Với line nguyên, de-vig hai phía cho xác suất có điều kiện không Push/void. Muốn chấm xác suất vô điều kiện tại threshold phải có mô hình p_push/p_void hoặc dùng subset decisive đã khai báo. Không tự suy ra p_push chỉ từ một cặp odds hai phía.
- Tính ROI bằng odds thực sự có sẵn cho lựa chọn ở cutoff, không gán closing price hồi tố; ghi cả nguồn và coverage.

### 11.5. Selected-edge validation và forecast encompassing

Một model cải thiện full-sample score chưa tự chứng minh hiệu quả trên tập được chọn vì edge cao. Với policy đã khóa, trung bình return trên dữ liệu mới có thể ước lượng kỳ vọng của policy cho chính quần thể đánh giá dưới giả định sampling/denominator phù hợp; không tự bảo đảm không chệch cho một quần thể tương lai khác khi drift, optional stopping hoặc missing outcomes có chọn lọc. Nếu estimated edge chứa noise, chọn các chênh lệch cực đại có thể làm observed edge lạc quan. Tuy nhiên không có định luật mọi selected edge đều bị phóng đại: nếu p_model là xác suất có điều kiện đúng trên toàn thông tin dùng để chọn, selection theo forecast không tự phá calibration.

Không so trực tiếp ROI với `p_model−p_market`: một bên là lợi nhuận/stake, bên kia là chênh lệch xác suất. Đánh giá predicted EV tại odds thực so với realized return. Giữ lại cả Brier/log loss trên đúng selected subset, predicted-versus-realized EV theo edge bins, số cược, turnover/coverage và block confidence intervals. Policy chọn phía Over/Under, edge threshold, odds range, tối đa lựa chọn mỗi game và stakes phải được tune trong development rồi khóa; tránh báo lại các threshold đẹp nhất trên holdout.

**Encompassing/logit blend là phép thử bổ sung**, không thay backtest strategy. Dùng các r_model, r_market cùng event/snapshot và conditioning decisive; với line nguyên loại Push/void khỏi binary outcome và báo tỷ lệ còn lại. Không tạo y=0 từ Push. Với line nửa điểm và điều kiện settled phù hợp, y=1{Over}.

`z_i = logit(r_model,i) − logit(r_market,i)`.

Mô hình offset chính để chẩn đoán:

`logit P(y_i=1 | r_model,i,r_market,i, decisive) = logit(r_market,i) + a + β z_i`.

- Phiên bản không intercept đặt a=0; báo như constrained sensitivity. Ở chính phiên bản này, β=1 đã tái tạo r_model đúng về đại số. Với bản có intercept, cần thêm a=0 để có cùng đẳng thức. Bản có intercept cho phép dịch chuyển mức nền, tránh ép β hấp thụ toàn bộ market-level bias.
- Ước lượng bằng likelihood/regularization trên chronological out-of-fold forecasts hoặc calibration/development block; dùng paired multi-day block bootstrap để ước lượng bất định và refit a,β trong mỗi block replicate. Nếu muốn bao gồm uncertainty từ model selection/training, phải refit toàn bộ quy trình thích hợp trong outer resampling hoặc báo rõ CI chỉ điều kiện trên forecasts đã tạo.
- β=0 nghĩa là không cần **linear logit-difference term trong đặc tả này**, không chứng minh model không chứa bất kỳ nonlinear/interacting information nào ngoài thị trường. Không bác bỏ β=0 cũng không chứng minh β=0; có thể thiếu power hoặc collinearity.
- β=1,a=0 tái tạo r_model về mặt đại số; không chứng minh model là “xác suất thật” hay nên tin hoàn toàn. 0<β<1 tạo logit shrinkage về thị trường; đây là ứng viên blend cần kiểm chứng ngoài mẫu, không hệ số co chân lý mặc định. β có thể <0 hoặc >1 nếu diagnostic fit không ràng buộc.
- Sensitivity để tách market recalibration và incremental signal: `logit P(y=1)=a+b·logit(r_market)+βz`. β ở hai đặc tả không có diễn giải y hệt; kiểm tra separation, collinearity và độ ổn định, không chọn specification theo kết quả holdout có lợi.
- Fit blend trong development, khóa rồi đánh giá trên block tương lai chưa dùng. Nếu dùng β cho production ranking, thử constraint 0≤β≤1 được chọn trước và validate EV/selection. Kiểm định parameter ở boundary cần phương pháp phù hợp; không dùng Wald/Normal CI máy móc sau khi constrain.
- Một β khác 0 không bảo đảm vượt vig hoặc sinh ROI dương. Cần backtest đầy đủ odds, settlement và policy; β có thể phải phân cấp theo stat nếu dữ liệu đủ, còn mọi lựa chọn thêm đều vào trial registry/multiplicity plan.

Cách so với thị trường tại line khác nhau giữa các ngày đã được giải quyết bằng cách chấm CDF tại **line thực của từng snapshot** trong §11.4; không so hai thresholds khác nhau trên cùng trận như cùng một event.

### 11.6. Ablation để tách market inputs và market-selected calibration

Từ bản 1.6, **chỉ H so với S+H ở §11.7 là cặp xác nhận**. Các cặp khác trong năm nhánh, β tests, subgroup tests, log-loss/ROI claims đều thăm dò. Kết quả của chúng không override quyết định primary.

Không coi dùng market ở hai vị trí là tự động double-counting. Fit một conditional model có predictors tương quan không tương đương nhân hai likelihood độc lập. Rủi ro nằm ở việc trộn/nhân các đầu ra như nguồn bằng chứng độc lập, hoặc áp một correction đã chọn lọc theo market mà không validate trong joint pipeline.

Production mặc định: base stats → G_stats của đường A; nếu dùng market thì đưa đầu ra stats này và H_market vào augmented pipeline đã fit trong development. G_line-selected là nhánh audit, không tự xếp chồng vào production.

| Nhánh | Postprocessing stats | Inputs thị trường ở inference | Mục đích |
|---|---|---|---|
| S | G_stats, C_stats-weights | Không | Chọn/kiểm tra full-CDF stats-only |
| H | Market-only model/calibrator | Có | Baseline có cùng H_market quan sát được |
| S+H | G_stats + augmented learner | Có | Kiểm tra giá trị bổ sung của stats |
| SL | G_line-selected, market-selected training | Không trực tiếp | Audit target shift; không gọi market-free training |
| SL+H | G_line-selected + augmented learner | Có | Audit stacking/correlation/miscalibration; không default |

Trong protocol mặc định, dùng đúng B0/B1 → base, B2 → G_stats/G_line-selected, B3 → stacker H/S+H, B4 → variance pilot, B5 → xác nhận theo §11.1. Base/G tạo outputs cho B3 mà không được fit outcomes B3. Không có tùy chọn “OOF hoặc block” cho code agent ở cấp split xác nhận. Các nhánh exploratory dùng cùng block boundaries, không nhận outcomes B5 để fit. Báo lineage của model/G, cutoff, feature availability, weight policy và label provenance.

So S với SL trên full RPS/PIT/tails trong cùng population. So H, S+H và SL+H trên same-event pricing scores cùng timestamps, selected-policy EV và calibration. Báo cả deterioration, không chỉ improvements; thêm configurations vào trial registry và multiplicity plan. Không dùng một bảng riêng để suy ra cơ chế double-counting chắc chắn, nhưng đây là kiểm tra trực tiếp rủi ro của thiết kế.

### 11.7. Protocol quyết định xác nhận H so với S+H — cập nhật bản 1.8

#### 11.7.1. Cặp, population và estimand chính

Chỉ một cặp **H_refit/S+H_refit** và một primary metric. Trong §11.7, H/S+H từ bản1.8 chỉ cặp refit trừ khi ghi frozen; functional form và penalty dưới đây giữ nguyên, parameters cập nhật theo §11.7.8:

- H: per-stat logistic recalibration của market-only, `logit p_H=a_s+b_s logit(r_market)`.
- S+H: cùng baseline terms, thêm stats signal `logit p_SH=a'_s+b'_s logit(r_market)+β_s[logit(r_stats)−logit(r_market)]`.
- B3 dùng tạo initial/frozen reference; mỗi bundle primary được fit trên B_stack(t) đúng recipe §11.7.8. Probability clipping epsilon=1e-6 chỉ để logit số học, chuẩn hóa predictor bằng mean/std của training stack block tương ứng (std=0 thì dùng 1), dùng mean binary log loss + (0.01/2)Σ slope², không phạt intercept. Không chọn lambda sau khi xem B4/B5; dữ liệu-derived coefficients/scaling được refit nhưng lambda và class model cố định. Nếu không hội tụ với tolerance 1e-8/maxiter=5000, fail kỹ thuật; không tự đổi class model. Đây là test của signal qua đặc tả logit đã khóa, không test mọi kiểu thông tin phi tuyến có thể có của stats.
- Initial G_stats học trên B2 theo stats-only objective; G trong mỗi primary bundle refit học trên B_G(t) riêng theo cùng objective và mapping class đã khóa. Không thêm line-selected G vào cặp chính.
- Population chính: settled, đã vào sân, Regular Season player-game PTS/REB/AST, main line **nửa điểm**, snapshot ≤cutoff 60 phút và không cũ hơn 15 phút so với cutoff. Line nguyên/Push/void báo riêng exploratory; không tự đưa vào binary primary score. Báo cả missing/void/excluded counts để minh bạch selection.
- Một dòng mỗi `(game_id,player_id,stat)` theo reference book đã cấu hình trong ingestion manifest và khóa trước B4; nếu chưa có reference book/data source thì `BLOCKED_DATA`, code agent không tự chọn book theo kết quả. Lấy snapshot mới nhất trong cửa sổ hợp lệ. Nếu provider có nhiều market được đánh dấu main, chọn canonical market_id nhỏ nhất theo thứ tự chuỗi, không chọn theo odds gần 2 nhất sau khi xem outcome. Không có main flag thì không tự thay bằng alternate line.
- Với y_i=1{stat vượt line}, `d_i=(p_H,i−y_i)²−(p_SH,i−y_i)²`; d>0 là S+H tốt hơn. Không chia d cho Brier của H, không chuyển thành phần trăm tương đối.
- Estimand gộp: `Δ=(mean(d_PTS)+mean(d_REB)+mean(d_AST))/3`. Trong từng stat mỗi eligible player-game có trọng số bằng nhau, mỗi stat có trọng số 1/3. Bootstrap phải tính lại ba tỷ số/tổng-count trong từng replicate, không coi mọi dòng là IID.
- Log loss, raw de-vig market, ROI, β, từng market riêng và các cặp S/SL/SL+H là secondary/exploratory; không chọn metric/cặp thắng nhất để tuyên bố xác nhận.

#### 11.7.2. Margin, CI và nhãn quyết định

**Giá trị mặc định chốt trước B4/B5:** practical margin `δ=0.001` Brier units tuyệt đối, CI 95% hai phía, precision reporting target `h_target=0.0005` cho nửa độ rộng CI. **Từ bản 1.7 không dùng h_target làm điều kiện ADOPT.** Ví dụ mean Brier từ 0.200 xuống 0.199 có Δ=0.001. Margin này là quy ước chi phí/độ phức tạp nghiên cứu, không phải threshold kinh tế suy ra từ odds, không bảo đảm ROI và không được gán là chuẩn khoa học đã công nhận. Muốn đổi cần protocol version mới trước kết quả dùng để quyết định; không tune margin từ observed Δ.

Chốt CI candidate: paired **moving-block bootstrap** 10.000 replicates, block dài **14 scheduled Regular-Season game dates**, giữ mọi player/game/stat/line cùng ngày; seed 20261109, percentile 2.5%/97.5%. Không wrap hoặc tạo block liền mạch qua offseason: block starts chỉ hợp lệ trong cùng season; mô phỏng/gate phải dùng cùng season-stratified procedure và shape tương lai. Không có block start hợp lệ thì fail kỹ thuật. Scheduled game dates không eligible observations giữ sum/count=0. Block 7 và 28 là sensitivity; bản 28 khi quá ít blocks không được coi là một kiểm chứng đáng tin độc lập hoặc dùng để chọn CI đẹp hơn. B5 có ít nhất 100 eligible pairs mỗi stat, và không replicate nào có stat count=0; nếu vi phạm, CI không đạt điều kiện, không tự bỏ replicates lỗi. Bootstrap coverage là xấp xỉ dưới giả định dependence/stationarity đủ phù hợp, không finite-sample guarantee; report block sensitivity nếu kết luận thay đổi.

Gọi CI=[L,U], h=(U−L)/2. Decision rule tại thời điểm duy nhất kết thúc B5, sau khi inference gate đã đạt:

| Điều kiện | Quyết định vận hành | Được kết luận |
|---|---|---|
| L>δ, đủ điều kiện dữ liệu/CI và inference gate đạt | ADOPT **recipe S+H_refit-v1.8** | Cải thiện vượt margin cho thuật toán cập nhật/population/specification này; không xác nhận mọi lịch refit khác |
| U<δ | DO_NOT_ADOPT; dừng nhánh xác nhận | Loại trừ cải thiện ≥δ ở mức CI đã dùng; không đồng nghĩa tín hiệu bằng 0 |
| L>−δ và U<δ | Nhãn bổ sung PRACTICAL_EQUIVALENCE | Cả CI nằm trong vùng ±δ; có thể có effect nhỏ khác 0 |
| U<0 | Nhãn bổ sung HARM | Có bằng chứng S+H làm score xấu hơn; vẫn thuộc DO_NOT_ADOPT |
| Các trường hợp còn lại | INCONCLUSIVE; giữ H_refit | CI chưa đủ phân biệt với margin; không tuyên bố không bổ sung thông tin |

Báo h và việc đạt h_target như precision diagnostic, không đổi ADOPT thành INCONCLUSIVE khi L>δ. Một L>δ dựa trên CI hợp lệ đã đủ cho quyết định superiority; coverage/size không được cứu bằng một width gate tùy tiện. Các nhãn equivalence/harm có thể cùng là mô tả bổ sung, không là nhiều tests chọn sau dữ liệu. Equivalence theo CI95 này bảo thủ hơn TOST ở alpha=5% dùng CI90; không gọi nó là TOST-IID đã chạy. Đây là một bộ quyết định dựa trên cùng CI của cùng một Δ. Primary superiority statement H0: Δ≤δ đối H1: Δ>δ dùng lower endpoint CI95, tương ứng one-sided nominal 2.5% khi CI có coverage đúng; không gọi là one-sided alpha5%.

“Không bổ sung gì” không được dùng như nhãn kết quả. Dùng “không đạt cải thiện tối thiểu đáng giữ trong đặc tả này”, “tương đương thực tiễn trong ±δ”, hoặc “chưa đủ dữ liệu” theo bảng.

#### 11.7.3. Gate bắt buộc, exposure và dừng

1. **Algorithm freeze F_A:** sau B3, trước khi tính primary outcomes B4, khóa recipe refit §11.7.8, hyperparameters, book/population, margin, futility checkpoints, CI/gate và hashes. Weights được cập nhật đúng recipe, không được chọn theo kết quả B4. Pilot vẫn không là holdout xác nhận.
2. **Exposure và chỉ-dừng:** B4 checkpoint đúng140 và280 scheduled game dates. Với checkpoint j có ≥100 eligible pairs mỗi stat, tính CI95 cùng paired moving-block method/seed theo prefix đó. Nếu U_j<δ thì STOP_PILOT_FUTILITY, không mở B5, không ADOPT và không tuyên bố tương đương/absence of signal. Nếu prefix140 chưa đủ counts thì skip statistical look, tiếp tục tới280; nếu280 vẫn thiếu thì BLOCKED_DATA. Chỉ chạy gate đầy đủ khi đã tiếp tục tới280. T là game-date exposure, không calendar days và không phải số blocks độc lập. Không chuyển Ω từ một mùa có trận dày sang 200 calendar days có offseason bằng phép chia đơn giản.
3. **RMS diagnostic:** tính rms_s=sqrt(mean[(p_SH−p_H)²]) theo stat và rms_pool=sqrt(mean_s rms_s²), không cần outcomes; dùng đúng offered population/weights. So rms_pool² với δ=0.001 và Δ_alt=0.002, tương ứng RMS khoảng 3.162% và 4.472% dưới ideal nested assumptions ở §11.7.7; không bình phương δ hoặc Δ_alt lần nữa. Nếu RMS chỉ 1%, báo IDEAL_SIGNAL_SCALE_BELOW_MARGIN; không tự coi đó là cận trên thật hoặc test futility khi chưa có conditional calibration. Không đổi δ sau khi thấy RMS; có thể đăng ký protocol khác trước B5 với câu hỏi thực tiễn khác.
4. **Variance uncertainty:** tính Ω_point bằng paired moving-block pilot procedure trên daily vectors của ba stats, giữ count-ratio statistic. Ước lượng phân bố Ω qua outer block resampling trong B4 (1.000 outer replicates, trong mỗi replicate 1.999 inner replicates; seeds/hash ghi manifest). Lấy percentile95 Ω_U như **working upper planning estimate**, không quảng cáo là cận tin cậy95% có coverage đã chứng minh với ít blocks. Báo cả Ω_point, Ω_U, độ bất định và sensitivity theo season/block. Nếu unstable/không nhận dạng được dependence thì STOP_INFERENCE_FEASIBILITY, không dùng Ω_point như chắc chắn.
5. **Size/coverage/power simulation bắt buộc:** trước B5 phải chạy suite §11.7.6 với Ω uncertainty, đúng T/schedule/sample shapes, pilot looks140/280 và **toàn bộ quy trình refit + futility + final decision**. Báo power unconditional của toàn quy trình và conditional-on-continuation riêng. Chỉ mô phỏng variance của estimator hoặc chỉ kiểm tra L>δ bằng Normal-known-SE chưa đủ. Thiếu suite hoặc gate không đạt thì status GATE_UNVALIDATED, không có tuyên bố confirmatory.
6. **Planning budget:** dùng Ω_U trong công thức superiority-over-δ để tính initial T_req; h_target chỉ tạo bảng precision phụ, không là cửa ADOPT hoặc budget gate. Budget B5 là đúng 200 scheduled game dates. Nếu T_req>200 hoặc suite không đạt power assurance toàn quy trình với T=200 thì STOP_FEASIBILITY cho thiết kế này; báo thêm T_min_grid theo §11.7.8, không kết luận signal không tồn tại. Muốn tăng budget phải tạo protocol mới trước B5, không tăng sau khi xem paired scores.
7. **Registration release R:** sau gate đạt, ký manifest/recipe/simulation report và ghi timestamp R riêng với F_A. B5 đếm200 scheduled game dates từ ngày UTC tiếp theo sau R, có thể qua mùa. Các dates giữa B4 và R là B4G theo §11.7.8, không nhập lại làm pilot hay B5. Dự đoán từng trận vẫn tạo đúng cutoff thực và trước outcome; dates sẽ resolve theo schedule thật, hoãn/hủy không tự tăng thông tin. Lưu planned/actual schedule và gap lengths. Không đếm ngày nghỉ/offseason thành thêm sample; không dừng sớm vì p-value hoặc h. Theo dõi data integrity được phép, nhưng không xem paired primary score để quyết định kéo dài.
8. **Một lần kết thúc:** sau date thứ200, chờ settlement/stat corrections tối đa7 ngày rồi đánh giá. Báo lịch thực, drift và coverage; thiếu điều kiện CI/transportability đã khóa thì INCONCLUSIVE/GATE_INVALIDATED, không ADOPT. Không append data cho tới khi vượt margin. ADOPT/DO_NOT_ADOPT/INCONCLUSIVE đều kết thúc protocol này.

#### 11.7.4. Power cho paired score difference và nguồn gốc số

Bảng ROI ở §11.3.1 không trả lời câu hỏi này. Planning giả định cho một d_i IID với SD σ_d và Δ_alt=0.002 (cải thiện đáng phát hiện gấp đôi margin):

`n_power≈[(z_0.975+z_0.80)σ_d/(Δ_alt−δ)]²`,

`n_precision≈(z_0.975 σ_d/h_target)²`.

Bản 1.6 lấy max hai yêu cầu nhưng không tính joint ADOPT power khi SE/width ngẫu nhiên. Bản 1.7 dùng n_power cho initial superiority planning, n_precision chỉ báo precision sensitivity. Chỉ là sensitivity cho mean paired score difference IID đồng nhất, chưa là power của pooled three-stat ratio estimator với clustered data. Không đặt Δ_alt=δ rồi dùng công thức superiority-over-δ để đòi power80%; ở boundary không có khoảng cách effect để phát hiện.

Ví dụ giả định (không ước lượng từ NBA):

| σ_d | n_power xấp xỉ | n_precision cho expected Normal h=0.0005 | max minh họa cũ, không ADOPT assurance |
|---:|---:|---:|---:|
| 0.02 | 3.140 | 6.147 | 6.147 |
| 0.05 | 19.623 | 38.415 | 38.415 |
| 0.10 | 78.489 | 153.659 | 153.659 |

**Planning thực dùng scheduled game dates, không calendar days/raw bet count:** trên B4 moving-block resample toàn bộ daily vectors `(sum_d_s,count_s)` của ba stats rồi tính Δ mỗi replicate. Đặt `Ω_hat=T_pilot×Var_boot(Δ_hat)`. Dưới giả định phân phối/count mix và dependence đủ ổn định, `Var(Δ_hat_T)≈Ω_hat/T`. Initial T_req=ceil((z_0.975+z_0.80)² Ω_U/(0.002−0.001)²). Công thức cho upper-CI loại trừ lợi ích ≥δ khi true Δ=0 có cùng gap0.001 nhưng là đánh giá phụ, không tự gộp thành power của toàn bộ nhãn quyết định. Báo `z_0.975² Ω_U/(0.0005)²` như precision sensitivity riêng. Gate cuối dựa trên mô phỏng toàn rule, không xem Normal formula như assurance.

Cỡ mẫu trên là xấp xỉ; fixed-T percentile CI có width ngẫu nhiên nên n_precision không bảo đảm width pass80%. Bản 1.7 bỏ width khỏi ADOPT, không coi các cỡ mẫu đó là joint-rule power. Chưa có B4/odds nên **chưa có Ω_hat, T_req thực hay kết luận một mùa đủ/thiếu**. Không dùng mean Δ của pilot để chọn Δ_alt hoặc margin. Nếu raw forecast universe, team roles, stat coverage hoặc odds distribution thay đổi, rescaling theo T có thể sai; báo drift/sensitivity thay vì claim power chính xác.

Mã Python standard library tái lập các số sensitivity paired-score; biến `omega_upper_per_game_date` chỉ được truyền từ pilot thực, không hardcode thành variance NBA:

```python
from math import ceil
from statistics import NormalDist

N = NormalDist()
z = N.inv_cdf(0.975)
z_power = N.inv_cdf(0.80)
margin, alternative, halfwidth = 0.001, 0.002, 0.0005
for sd_d in (0.02, 0.05, 0.10):
    n_power = ceil(((z + z_power) * sd_d / (alternative - margin)) ** 2)
    n_precision = ceil((z * sd_d / halfwidth) ** 2)
    print(sd_d, n_power, n_precision, max(n_power, n_precision))

def planned_game_dates(omega_upper_per_game_date):
    if omega_upper_per_game_date <= 0:
        raise ValueError("Pilot upper planning variance must be positive and validated")
    power_dates = ((z + z_power) ** 2 * omega_upper_per_game_date
                   / (alternative - margin) ** 2)
    return ceil(power_dates)  # initial planning only; mandatory simulation gate follows
```

Mã initial planning không phải mô phỏng dependence và chưa đủ để gate đạt. Việc bootstrap pilot cần dữ liệu thật và implementation ratio-statistic đúng ba markets, không thay bằng SD returns. Bắt buộc kiểm tra scenario-specific power/size/coverage theo §11.7.6; kết quả đó chưa tồn tại trong kế hoạch. Tài liệu không được báo gate đã đạt.

#### 11.7.5. Design-effect examples và Holm

Ví dụ equal-size independent clusters, chỉ dùng để minh họa:

| m | rho | 1+(m−1)rho | Raw observations tương ứng n_ind=10.000 |
|---:|---:|---:|---:|
| 3 | 0 | 1.0 | 10.000 |
| 3 | 0.1 | 1.2 | 12.000 |
| 3 | 0.3 | 1.6 | 16.000 |
| 10 | 0.1 | 1.9 | 19.000 |

Không mặc định m=3 vì có ba stat: clusters thực chứa nhiều cầu thủ, markets và games; correlation của d_i có thể khác raw stat/return. Không dùng bảng này thay Ω_hat hoặc cộng thêm vào variance bootstrap đã chứa dependence đó.

Protocol chính có một Δ gộp nên không cần Bonferroni/Holm cho kết luận chính. Chỉ báo subgroup/exploratory estimates, không tuyên bố significance của từng subgroup như confirmatory. Nếu sau này đăng ký family nhiều cặp/metrics, chọn Holm cho kiểm định xác nhận vì không kém Bonferroni với cùng valid p-values; power phải tính theo joint structure và hypothesis alternatives. Bonferroni tables cũ chỉ là planning illustration dễ tái lập, không biện minh lựa chọn kém power cho protocol mới.

#### 11.7.6. Mandatory finite-sample inference validation

Không gọi “size/coverage thật của NBA” là đã biết sau khi resample một pilot. Suite chỉ đo empirical size/coverage/power **dưới các DGP/scenarios được đặc tả**, có model risk. Khoảng12–14 nominal blocks có thể khiến percentile CI under-cover; overlapping block starts không tạo thêm tương đương từng ấy observations độc lập. Tăng số bootstrap replicates giảm Monte Carlo noise, không chữa thiếu dữ liệu.

Trước B5, triển khai và lưu suite sau, không tự chọn method theo outcome B5:

- Gốc là toàn bộ daily vectors/counts và score differences B4, giữ cross-stat/cross-player/game grouping. DGP1: season-stratified moving-block residual simulation tại l=7/14; DGP2: vector autoregressive/shared-factor model fit trong B4, giữ cross-stat covariance và gap/season effects; DGP3: dependence/variance stress với Ω tới Ω_U và stronger residual persistence trong vùng đã đăng ký từ pilot uncertainty. Không dùng một DGP identical với bootstrap đang kiểm tra làm bằng chứng duy nhất.
- DGP cho score-level inference có thể center từng stat rồi shift để pooled true Δ bằng 0, δ=0.001 và Δ_alt=0.002, giữ count weights. Phải tính mean thật của pooled ratio statistic dưới DGP/count-shape, không giả định cộng hằng số vào daily sums tự đạt target. Nếu generate actual binary outcomes thì cần model joint; không dùng score shifts để tuyên bố đã mô phỏng valid NBA games/calibration.
- Mỗi scenario: tối thiểu2.000 outer datasets với B5 shape T=200 scheduled game dates; mỗi dataset chạy đúng CI procedure và ADOPT/futility/equivalence rule, inner bootstrap1.999 replicates. Chạy sensitivity tăng inner lên10.000 trên subset500 datasets cố định trước; nếu classification/quantiles chưa ổn định theo Monte Carlo error thì tăng precision trước freeze, không chọn bằng kết quả có lợi. Tính Wilson95 MC intervals cho mọi tỷ lệ; lưu RNG seeds, code/version và DGP parameters.
- Báo P(ADOPT overall) qua cả pilot futility và final test ở true Δ=0 và δ; coverage của final CI dưới DGP nếu luôn được tính và coverage conditional trên nghiên cứu tiếp tục là hai đại lượng riêng; power overall tại0.002, P(ADOPT|continue), probability stop-pilot/DO_NOT_ADOPT/equivalence/harm và h distribution. Không thay overall power bằng một cửa phụ hoặc chỉ conditional power.
- Gate tolerance đã chốt: ở mọi registered core/stress scenario, Wilson upper95 của P(ADOPT overall) tại 0 và δ ≤0.035; Wilson lower95 của coverage ≥0.93; Wilson lower95 của P(ADOPT overall) tại0.002 ≥0.80; conditional power báo riêng. Đây là **simulation-acceptance tolerances**, không chứng nhận true size2.5% hoặc coverage95%; báo cả sai khác với nominal. Nếu muốn claim stricter nominal error rate, cần protocol/gate chặt hơn và đủ simulation precision.
- Nếu không fit được DGP/Ω uncertainty đáng tin cậy từ B4, hoặc kết quả nhạy đáng kể theo dependence/season shape thì GATE_UNVALIDATED/STOP_INFERENCE_FEASIBILITY. Không được vượt gate chỉ vì “một scenario đạt”. Nếu thay l/CI method/DGP suite theo B4, đó là protocol development: version và khóa lại rồi chạy validation suite độc lập với seeds/datasets mới trước B5; không sửa silently.

Một percentile95 CI được chấp nhận bởi gate vẫn là approximate inference có điều kiện theo assumptions; cùng data pilot không thể xác lập error rate distribution-free cho một quá trình NBA không biết và có drift. Cận Ω_U cũng là working bound cần stress, không thành chắc chắn nhờ được lấy percentile95.

**Tái lập phác thảo width-gate, không phải NBA:** mô phỏng Normal estimator độc lập với SE estimate proportional sqrt(χ²_df/df), 200.000 draws, seed20261109, true Δ=0.002. Tại SE0=0.0005/z0.975, old joint rule cho ADOPT≈0.553(df10),≈0.526(df27), trong khi chỉ L>δ≈0.967/0.971. SE0×0.85 cho old ADOPT≈0.817/0.909; mức “15% buffer đạt82–84%” không phổ quát theo df/model của SE. Bản 1.7 không dùng kết quả phác thảo này như actual bootstrap coverage.

#### 11.7.7. RMS feasibility, Brier identity và phạm vi frozen pipeline

Gọi p=p_SH, q=p_H, a=p−q và m=E[Y|p,q,context]. Với d=(q−Y)²−(p−Y)²:

`d=a²+2a(Y−p)`;

`E[d]=E[a²]+2E[a(m−p)]`.

Nếu p là conditional mean thật đối với information set chứa cả q (hoặc đủ điều kiện E[a(Y−p)]=0), có `Δ=E[(p−q)²]` chính xác trên cùng weights/population. Separate marginal calibration của p và q hoặc chỉ nói mô hình “nested” về covariates không tự bảo đảm residual orthogonality đó trong model học hữu hạn mẫu.

Vì vậy δ=0.001 tương ứng ideal RMS sqrt(δ)=0.0316228, khoảng3.16 percentage points; Δ_alt=0.002 tương ứng4.47 points. RMS1point cho ideal gain0.0001. Khi p chưa đúng conditional mean, residual term có thể dương hoặc âm; **RMS² không là cận trên chung cho Δ thật**, nên RMS chỉ là cheap outcome-free feasibility diagnostic. Không đổi margin để vừa với mức signal nhìn thấy sau pilot; thay câu hỏi cần protocol khác trước xác nhận.

Ngay dưới ideal p=m, `Var(d)=E[4a²p(1−p)]+Var(a²)`. σ_d xấp xỉ RMS chỉ trong vùng p≈0.5 và Var(a²) nhỏ; không là đồng nhất thức cho mọi odds/cohort. Estimator Δ gộp còn cần count weights và covariance giữa stat/ngày.

**Phạm vi nhãn kết quả:** bản1.7 xác nhận frozen pipeline; bản1.8 thay primary trước B5 bằng **weekly-refit algorithm** đã đăng ký dưới đây. Frozen-v1.7 pair được lưu làm thăm dò, không đồng chính và không dùng để cứu kết quả primary. Mọi nhãn ADOPT/DO_NOT_ADOPT/INCONCLUSIVE phải ghi recipe version, lịch cập nhật và dates. Không có kết quả xác nhận frozen nào được giữ rồi đổi tên thành adaptive.

Drift có thể ảnh hưởng cả H và S+H; không mặc định hướng bất lợi cho stats. Adaptive protocol vẫn cần kiểm tra season/time effects và dependence của score process do sử dụng outcomes quá khứ để refit.

#### 11.7.8. Các quyết định điều hành khóa bản1.8

**A. Chọn production-refit làm primary ngay, không để sau B5**

Đăng ký duy nhất cặp H_refit/S+H_refit. Không có hai co-primary hypotheses, vì vậy không thêm Holm cho frozen/adaptive. Frozen pair, từng stat, beta tests và các ablations tiếp tục exploratory. Đây là thay đổi trước khi có primary NBA model results; nếu thực tế người triển khai đã xem kết quả của candidate rồi mới chọn recipe thì phải ghi là development và dùng dữ liệu xác nhận mới.

Recipe chung cho B4 prequential replay và B5 production:

1. **Lịch:** mỗi thứ Hai00:00 UTC. Mốc t là data cutoff của refit job; chỉ dùng labels của trận đã kết thúc ít nhất48 giờ trước t và đã có trong ingestion archive tại t. Không dùng “final corrected stats tải sau” như thể đã có đúng t mà không khai báo revision limitation. B4 là historical replay, không gọi là forecast prospective có timestamp đương thời. Thiếu historical line/label availability thì BLOCKED_REPLAY, không tự bịa snapshots.
2. **Cửa sổ:** lấy84 scheduled game dates có resolved/available labels gần nhất trước t; 42 dates đầu là B_G(t), 42 dates sau là B_stack(t), tách cả ngày/trận. Base training dùng các eligible player-games trong730 calendar days trước ngày đầu B_G(t), với lower bound ngày bắt đầu dữ liệu2023-24; không dùng labels của B_G hoặc B_stack để fit base parameters. Thuật toán/class/features/hyperparameters do B1 khóa, không tune lại theo week.
3. **Thứ tự:** fit base trên base window → dự đoán B_G bằng base đó và features as-of từng trận → fit G_stats trên B_G bằng full-RPS/fixed-grid objective → dự đoán B_stack bằng base+G đã fit → fit H và S+H/stacker trên B_stack theo functional form/L2 đã khóa. H và S+H dùng cùng stack dates, book và sample policy. Không dùng labels B_stack để fit G; không dùng outcomes tương lai của tuần dự báo. G/mapping class giữ nguyên, parameters có thể đổi.
4. **Triển khai:** kích hoạt bundle chỉ sau khi job hoàn thành và schema/numerical checks pass; trước đó dùng bundle hợp lệ trước. Forecast lưu actual activation time/model hash. Không lấy score của data mới để quyết định bundle nào tốt hơn. Nếu job không có labels mới thì giữ bundle trước; nếu hai lần cập nhật theo lịch liên tiếp thất bại thì dừng phát forecast primary, báo missing/technical status, không tự đổi algorithm. Áp cùng failure rule cho replay và production.
5. **B4G và B5:** outcomes đã available trong B4 hoặc B4G có thể đi vào cửa sổ training theo recipe, giống production. Outcomes B5 sau khi qua48h cũng có thể đi vào refit của **các trận tương lai**; đây là đánh giá prequential của algorithm đã khóa, không là leakage. Tuyệt đối không sửa forecast cũ, tune hyperparameters hoặc dùng aggregate primary score B5 để đổi recipe.
6. **Tái lập:** lưu update calendar, windows, archive IDs, seeds, fitted transforms, bundle hash, refit failures và prediction cutoff. Việc recipe đóng băng không đồng nghĩa weights đóng băng. Bộ frozen sau B3 chỉ tạo nhánh comparator có nhãn riêng.

84/42/42,730days,48h và weekly cadence là quyết định thiết kế trước xác nhận, chưa được chứng minh tối ưu. Nếu muốn thay, phải version trước dữ liệu xác nhận của recipe mới. Chi phí refit và độ trễ được báo cùng quality; không coi một recipe khác là đã được xác nhận tự động.

**B. Pilot futility-only ở140/280, không có pilot ADOPT**

- Cổng dùng Δscore của **cùng recipe refit primary**, không dùng frozen Δ để dừng nhánh adaptive.
- Chỉ hai prefix đã định trước. U_j<δ → STOP_PILOT_FUTILITY; còn lại tiếp tục. Nếu technical/CI invalid, không được gán futility. Gate coverage đầy đủ vẫn chưa đạt tại look140 nên CI pilot là công cụ dừng chi phí, không là tuyên bố equivalence95% đã xác nhận.
- Với final rejection event A đã định trước và continuation event C, `P(A∩C)≤P(A)`: thêm một cửa chỉ-dừng không tự thêm một cơ hội ADOPT. Không cần alpha-spending cho pilot efficacy vì không có pilot efficacy test. Nhưng điều này không sửa một final test vốn có coverage sai hoặc thay rejection region theo data; không được quảng cáo nominal type-I bảo đảm chỉ nhờ futility-only.
- Futility có thể làm giảm power và làm conditional effect estimates của các nghiên cứu tiếp tục bị selection. Suite phải mô phỏng cả checkpoints, gate và final step; báo P(stop140), P(stop280), P(ADOPT overall), P(ADOPT|continue), calendar/sample savings và estimator bias sau selection.
- Nếu checkpoint lịch sử đã trôi qua khi recipe được đăng ký, có thể tính đúng prefix để quyết định có tiếp tục nghiên cứu từ hiện tại không; không tuyên bố đã dừng prospective tại thời điểm quá khứ. Không chọn prefix sau khi nhìn kết quả toàn B4.
- Sau futility, recipe mới vẫn có thể nghiên cứu trong development nhưng không gọi là “tiếp tục cùng protocol”. Không dùng một mean pilot xấu để đổi margin/line policy rồi giữ nguyên nhãn xác nhận.

**C. Hai mốc freeze và block B4G**

| Mốc/block | Ý nghĩa |
|---|---|
| F_A: algorithm freeze | Timestamp thực sau khi xử lý B3, trước tính primary pilot outcomes; khóa recipe/refit schedule/hyperparameters/estimand/margins/futility/test budget, không backdate về ngày trận cuối B3 |
| B4 | Prefix140 hoặc tối đa280 game dates cho pilot theo recipe; kết thúc ở checkpoint đã chỉ định |
| B4G | Mọi dates sau kết thúc B4 đến hết ngày UTC chứa registration release R; dùng để chạy gate và cập nhật training nếu recipe yêu cầu, không dùng để chấm/tune inference gate hoặc thêm vào B4/B5 |
| R: registration release | Sau gate đạt, manifest và validation report được ký/hash; không là ngày khóa model weights |
| B5 | Bắt đầu scheduled game date đầu tiên từ00:00 UTC ngày sau R, forecast thật; đúng200 game dates, không backdate về ngay sau B4 |

Nếu gate mất thời gian qua nhiều ngày, B4G dài thêm nhưng không phát sinh outcome-based optional extension. Gate chỉ dùng B4 đã đóng; nhìn/tune bằng paired scores B4G sẽ biến nó thành development và cần đăng ký release/test mới. Forecasts shadow có thể được lưu trong B4G, nhưng không được hồi tố tính là confirmatory B5.

**D. Suite báo T tối thiểu đạt gate trên lưới, không mặc định n cho đúng80% sẽ đạt assurance**

Lưới discovery đã đăng ký: T∈{100,140,180,200,240,280,320,400,480,560} scheduled game dates. Ở mỗi T chạy full workflow dưới cùng scenario families, gồm pilot futility140/280 và refit feedback; báo cả conditional và unconditional power. Áp ngưỡng Wilson của §11.7.6 lên **P(ADOPT overall)** cho assurance chính. Unconditional power≤P(continue); nếu futility khiến P(continue)<0.80 thì không có T nào sửa được điều đó mà giữ nguyên rule. Phải báo thiết kế pilot/rule không khả thi, không chỉ xin thêm B5 data.

- T_min_grid là T nhỏ nhất trong lưới **được quan sát đạt** discovery gate, không phải nghiệm liên tục hoặc bảo đảm global minimum. Không giả định gate kết quả monotone theo T khi Monte Carlo noise/DGP season mix thay đổi.
- Sau chọn candidate T_min_grid, chạy lại suite với seeds/outer datasets mới độc lập và tất cả core/stress scenarios đã khóa. Chỉ khi validation độc lập đạt mới gọi T_min_validated; báo discovery-vs-validation failures. Không chỉ lấy smallest lucky T qua nhiều MC runs.
- Budget mặc định B5 vẫn200. Nếu200 không đạt, báo T_min_validated hoặc “không có T đạt trong lưới”; không tự mở B5 dài hơn. Thay budget trước B5 cần protocol version/manifest mới; sau khi đã xem B5 không được kéo dài theo CI.
- Simulation phải phân biệt surrogate score-vector DGP với model refit feedback. Để claim operating characteristics của **adaptive algorithm**, phải có tối thiểu một valid player-game/feature/outcome simulation hoặc prequential replay scenario có thực thi lại weekly refits theo availability. Nếu chỉ resample d_i cố định, báo conditional-on-score-process result; chưa đủ pass adaptive gate. Không dùng score shifts tùy ý như thể đã mô phỏng đủ causal model/line generation.

Normal planning tại80% chỉ là initial point estimate. Wilson lower≥0.80 là assurance criterion mạnh hơn việc true rate bằng0.80; thường cần true power cao hơn hoặc nhiều MC precision. Không cài một safety factor duy nhất như15% cho mọi DGP. Gate/search/independent validation mới quyết định.

**E. Hệ quả lịch và phạm vi kết luận**

Nếu không dừng pilot, thiết kế cần280 pilot+200 confirmatory scheduled game dates **cộng B4G và thời gian xử lý**, với phần pilot đã có trong lịch sử chỉ sử dụng được nếu đủ snapshot/archive. Đây là nghiên cứu nhiều mùa, không hứa ra kết quả sau200 calendar days hoặc vài tuần. Phải báo thời gian từ B3 tới B5; frozen comparator có thể già nhiều năm nhưng primary parameters đã cập nhật theo recipe.

Nguồn lịch chính thức2026-27 ghi mùa thường bắt đầu20/10/2026 và kết thúc11/04/2027 theo lịch Mỹ. Những mốc này không đủ tính ngày thứ280/thứ480 **UTC có trận**; cần đếm từ đầy đủ schedule, xử lý games vượt nửa đêm UTC, NBA Cup và hoãn/hủy. Các mốc “tháng2/2027” hoặc “đầu2028” được xem là ước lượng chưa xác nhận, không in thành deadline chắc chắn.

Collector phải xuất timeline manifest gồm game-date count đã resolve, forecast pilot end, gate-duration assumption, B5 start và projected B5 end khi schedule mùa tiếp theo đã có; khi chưa có lịch, hiển thị interval/unknown thay vì bịa dates. Không lấy xác nhận dài hạn này làm điều kiện chặn stats-only MVP, thu thập snapshots hoặc shadow forecasting; chúng có thể tiến hành riêng với nhãn chưa có bằng chứng lợi thế thị trường. Tài liệu không tự tạo tác vụ theo lịch hoặc triển khai production.

## 12. Quy tắc market, Push, void và hòa vốn

### 12.1. Hệ quy chiếu xác suất

Giữ riêng `q_over/q_under/q_push` theo phân phối stat có điều kiện A tại §10.4. Với mô hình đơn giản trong đó A là thi đấu và mọi DNP đều void, không có lý do void khác, gọi `v=P(DNP | C)`:

- `p_over=(1-v)q_over`, `p_under=(1-v)q_under`, `p_push=(1-v)q_push`, `p_void=v`.
- `p_over+p_under+p_push+p_void=1`.

Trong thực tế void có thể do hoãn/hủy trận, cầu thủ không đáp ứng điều kiện market hoặc quy tắc bảo vệ chấn thương; không đồng nhất p_void với p_DNP cho mọi nhà cái. Cần phân hoạch settlement mutually exclusive theo đúng rules; một số rules cần thêm thông tin diễn biến, không chỉ tổng stat. Trận đã vào sân rồi rời sớm không tự động void.

Không mặc định p_push nhỏ hoặc bằng một tỷ lệ cố định. Tính trực tiếp từ PMF tại line nguyên, báo theo stat và mức line. Lưu quy tắc overtime, điều kiện tham dự và settlement theo book.

### 12.2. EV và ngưỡng hòa vốn

Với stake 1, odds thập phân d, push và void hoàn tiền toàn bộ, gọi p_win/p_loss là xác suất settlement vô điều kiện:

`EV = p_win(d−1) − p_loss`.

Khi `p_win+p_loss>0`:

`EV≥0 ⇔ p_win/(p_win+p_loss) ≥ 1/d`.

Nếu p_win+p_loss=0, tất cả hoàn tiền nên EV=0, không định nghĩa tỷ số trên. Đặt `r=p_win/(p_win+p_loss)` thì `EV=(p_win+p_loss)(d r−1)`. Tăng khối lượng push/void **trong khi giữ r và d cố định** chỉ giảm độ lớn, không đổi dấu EV; nếu tái phân bổ win/loss làm r đổi thì không có kết luận đó.

### 12.3. Bỏ vig

MVP dùng multiplicative normalization để có quy ước tái dựng được. Với odds hai phía cùng book, timestamp, line và quy tắc:

`u_O=1/d_O`, `u_U=1/d_U`, `r_market,O=u_O/(u_O+u_U)`, `r_market,U=1-r_market,O`.

Đây là giả định phân bổ vig, không phải xác suất “thật” đã biết. Với line nguyên, các r là xác suất có điều kiện kết quả decisive, không chứa xác suất Push/void.

Phân tích sensitivity có thể dùng power method: tìm a>0 sao cho `u_O^a+u_U^a=1`, lấy `r_j=u_j^a`; ghi cách xử lý dữ liệu bất thường/không hợp lệ. Shin chỉ là ứng viên với giả định riêng, không mặc định ưu việt hoặc luôn cho kết quả khác; trong thiết lập hai cửa chuẩn, một số phương pháp có thể tương đương. Không ghép hai giá từ books khác nhau rồi gọi là overround của một book.

Nếu chưa đủ cơ sở, hiển thị xác suất và giới hạn dữ liệu thay vì gợi ý một lựa chọn bắt buộc.

## 13. Vận hành, giám sát và giao diện MVP

Giao diện gồm danh sách trận, cầu thủ, PTS/REB/AST, line nhập tay, kỳ vọng/khoảng dự đoán, Over/Under/Push, cutoff và flags. Cho xem kịch bản giới hạn phút khi có.

API dự kiến: danh sách trận, chi tiết cầu thủ/trận, dự đoán theo market và line, kết quả đánh giá. Ưu tiên truy vấn dự đoán đã lưu; nếu tính cho line mới, dùng cùng phân phối model đã tạo.

Sau mỗi ngày có trận:

1. Kiểm tra collector và completeness.
2. Đối chiếu dự đoán đã đóng với kết quả.
3. Theo dõi sai số phút/stat, calibration, drift của vai trò và tỷ lệ `insufficient_data`.
4. Giữ phiên bản model trước để rollback.

Trong primary B4/B5, parameters refit mỗi thứ Hai theo recipe §11.7.8; chỉ frozen comparator không refit. Cập nhật features theo ngày/trước cutoff, không đổi recipe theo primary scores. Production được xác nhận chỉ là recipe đó, không phải mọi lịch retrain. Thay đổi tần suất dựa trên đánh giá; không mặc định huấn luyện lại liên tục sẽ tốt hơn. Không ghi đè forecast cũ bằng kết quả của model mới.

## 14. Roadmap và điều kiện hoàn thành

| Giai đoạn | Công việc | Điều kiện hoàn thành |
|---|---|---|
| 0. Khả thi | Kiểm tra P0 và mẫu box score | Ghép đúng mẫu trận, schema/khả năng truy cập xác nhận |
| 1. Dữ liệu | Backfill, DB, raw cache, checkpoints | Có coverage report, chạy lại không trùng, tiếp tục được sau lỗi |
| 2. Features | Cutoff, rolling, roster/team history, flags | Kiểm tra leakage và các ca biên đạt yêu cầu |
| 3. Dự đoán stat | Baseline, CatBoost, LightGBM | Có walk-forward report và model lựa chọn cho từng stat |
| 4. Xác suất | Phân phối, calibration, nhập line | Over/Under/Push nhất quán và được đánh giá ngoài mẫu |
| 5. Nhóm đặc biệt | Rookie, nghỉ dài, đổi vai trò | Báo cáo riêng, flags và scenario fallback hoạt động |
| 6. Vận hành | API, giao diện, snapshots, dự đoán thật | Forecast có timestamp, giám sát và đối chiếu sau trận |
| 7. Nâng cấp | Tracking, NGBoost/XGBoost, PRA/3PM | Chỉ giữ thay đổi có lợi ích ngoài mẫu |

Không ấn định thời gian tải dữ liệu trước khi thử endpoint và độ ổn định kết nối.

## 15. Checklist bàn giao cho code agent

- [ ] Cố định dependencies và có cấu hình seasons/cutoff/endpoints.
- [ ] Collector P0, raw cache, checkpoint, retry có giới hạn, coverage report.
- [ ] Schema DB và chuẩn hóa stat/minutes/IDs.
- [ ] Phân biệt DNP, zero, null, lỗi và trận chưa kết thúc.
- [ ] Feature pipeline dùng chung cho train và inference, hỗ trợ as-of cutoff.
- [ ] Tests cho leakage, đổi đội, rookie, nghỉ dài, overtime và duplicate.
- [ ] Baselines, CatBoost và LightGBM được so sánh công bằng.
- [ ] Phân biệt generative conditional minutes và plug-in OOF; có kiểm tra total variance và double-counting dispersion.
- [ ] Loss/estimand/metrics được chốt; quantile crossing, tails, Push và mean sau calibration được kiểm tra.
- [ ] CDF recalibration theo thời gian, PIT rời rạc và empirical coverage được đánh giá riêng.
- [ ] PTS components (P2) có ràng buộc 3PA≤FGA, made≤attempts, Beta/Beta-Binomial đúng đại lượng và không double-count variance.
- [ ] Holdout được khóa, toàn bộ trials được ghi; paired multi-day block bootstrap, cohort và power assumptions được báo.
- [ ] Benchmark thị trường cùng cutoff/line; closing benchmark riêng; de-vig và conditioning được ghi rõ.
- [ ] Alpha, power, số phía, family tests và multiplicity policy được đăng ký trước; variance theo price và ESS/design effect được ước lượng.
- [ ] Selected-edge policy và logit blend được fit/tune trong development rồi khóa; CI theo block không nhầm thành proof of profitability.
- [ ] Tách C_stats/H_market/C_aug; G_stats học bằng fixed-grid/full-RPS weights và population theo C_stats.
- [ ] Pricing line-weights chỉ dùng đúng target riêng; không lén fit G_stats bằng market-selected sample/weights.
- [ ] Sensitivity G_stats/G_line-selected và augmented model được báo riêng, có validation tails/Push và sample-selection scope.
- [ ] Bảng pricing không chọn G_stats; so market-only H với S+H bằng same-event scores và locked policy.
- [ ] Ablation S/H/S+H/SL/SL+H có lineage và temporal OOF, không giả định predictors tương quan là bằng chứng độc lập.
- [ ] Power ROI minh họa tái lập bằng code §11.3.1; paired-score planning dùng §11.7.4 và Ω pilot thực.
- [ ] Khóa weekly-refit H/S+H primary, pooled ΔBrier, δ=0.001, CI95; frozen pair thăm dò, h_target chỉ báo cáo.
- [ ] B0–B3 khóa recipe/initial references; primary rolling base→42date G→42date stacker mỗi tuần; B4 looks140/280, B4G và B5 tách rõ.
- [ ] Ω_U working planning bound và mandatory size/coverage/full-rule power suite đạt trước B5; không claim distribution-free coverage.
- [ ] RMS diagnostic có residual-term caveat; frozen/adaptive labels không được tráo; refit feedback được đưa vào gate.
- [ ] F_A và R có timestamps riêng; không backdate B5 qua B4G; T-grid search có independent validation và không tự tăng budget.
- [ ] Pilot futility-only không ADOPT; overall assurance gồm xác suất dừng pilot, không chỉ conditional-on-continuation power.
- [ ] STOP_FEASIBILITY/BLOCKED_DATA/INCONCLUSIVE không được báo thành không có signal; không optional extension theo score.
- [ ] Lưu model, feature schema, dataset manifest, seed và metrics.
- [ ] API nhập line, flags, scenario và snapshot history.
- [ ] Injury/props sources được ghi rõ coverage và timestamp; phần thiếu được công khai.
- [ ] Có daily reconciliation, monitoring và rollback.

## 16. Nguồn tham khảo

Các nguồn dưới đây đã được tham khảo trong cuộc trao đổi. Master docs có thể đổi; khi triển khai lưu phiên bản cụ thể và kiểm tra trên package thực tế.

1. [nba_api — mục lục](https://github.com/swar/nba_api/blob/master/docs/table_of_contents.md)
2. [Endpoint guide](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoint_guide.md)
3. [Hướng dẫn sử dụng và lỗi thường gặp](https://github.com/swar/nba_api/blob/master/docs/ai_agents.md)
4. [Known upstream issues](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/known_upstream_issues.md)
5. [PlayerGameLogs](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/playergamelogs.md)
6. [ScheduleLeagueV2](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/scheduleleaguev2.md)
7. [BoxScoreAdvancedV3](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/boxscoreadvancedv3.md)
8. [BoxScorePlayerTrackV3](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/boxscoreplayertrackv3.md)
9. [Live Odds schema](https://github.com/swar/nba_api/blob/master/docs/nba_api/live/endpoints/odds.md)
10. [NBA Injury Report 2026-27](https://official.nba.com/nba-injury-report-2026-27-season/)
11. [CatBoost regression objectives](https://catboost.ai/docs/en/concepts/loss-functions-regression)
12. [LightGBM parameters](https://lightgbm.readthedocs.io/en/stable/Parameters.html)
13. [XGBoost parameters](https://xgboost.readthedocs.io/en/stable/parameter.html)
14. [NGBoost — ICML 2020](https://proceedings.mlr.press/v119/duan20a.html)
15. [TimeSeriesSplit — scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)
16. [scikit-learn: Metrics and scoring — quantifying the quality of predictions](https://scikit-learn.org/stable/modules/model_evaluation.html)
17. [scikit-learn: TweedieRegressor](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.TweedieRegressor.html)
18. [Czado, Gneiting & Held (2009): Predictive Model Assessment for Count Data, Biometrics 65(4), 1254–1261](https://doi.org/10.1111/j.1541-0420.2009.01191.x)
19. [Kuleshov, Fenner & Ermon (2018): Accurate Uncertainties for Deep Learning Using Calibrated Regression, ICML](https://proceedings.mlr.press/v80/kuleshov18a.html)
20. [Song, Diethe, Kull & Flach (2019): Distribution calibration for regression, ICML](https://proceedings.mlr.press/v97/song19a.html)
21. [statsmodels: NormalIndPower.solve_power](https://www.statsmodels.org/stable/generated/statsmodels.stats.power.NormalIndPower.solve_power.html)
22. [SciPy: scipy.stats.bootstrap](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html)
23. [arch: Time-series Bootstraps](https://arch.readthedocs.io/en/latest/bootstrap/timeseries-bootstraps.html)
24. [scikit-learn: Nested versus non-nested cross-validation](https://scikit-learn.org/stable/auto_examples/model_selection/plot_nested_cross_validation_iris.html)
25. [statsmodels: Generalized Linear Models](https://www.statsmodels.org/stable/glm.html)
26. [SciPy: scipy.stats.betabinom](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.betabinom.html)
27. [Wedderburn, R. W. M. (1974): Quasi-likelihood functions, generalized linear models, and the Gauss–Newton method, Biometrika 61(3), 439–447](https://doi.org/10.1093/biomet/61.3.439)
28. [Gneiting & Ranjan (2011): Comparing Density Forecasts Using Threshold- and Quantile-Weighted Scoring Rules, Journal of Business & Economic Statistics 29(3), 411–422](https://doi.org/10.1198/jbes.2010.08110)
29. [scoringrules: Weighted scoring rules](https://scoringrules.readthedocs.io/en/latest/weighted_scores.html)
30. [statsmodels: statsmodels.stats.multitest.multipletests](https://www.statsmodels.org/stable/generated/statsmodels.stats.multitest.multipletests.html)
31. [Gneiting & Raftery (2007): Strictly Proper Scoring Rules, Prediction, and Estimation, JASA 102, 359–378 — bản tác giả](https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jasa.pdf)
32. [statsmodels: statsmodels.stats.weightstats.ttost_paired](https://www.statsmodels.org/stable/generated/statsmodels.stats.weightstats.ttost_paired.html)
33. [arch: Long-run Covariance Estimation](https://arch.readthedocs.io/en/latest/covariance/covariance.html)
34. [Shalizi (2018): Simulation for Inference I — The Bootstrap, CMU course notes](https://www.stat.cmu.edu/~cshalizi/dst/18/lectures/18/lecture-18.html)
35. [Ciolino, Kaizer & Bonner (2023): Guidance on interim analysis methods in clinical trials, Journal of Clinical and Translational Science 7:e124](https://doi.org/10.1017/cts.2023.552)
36. [NBA Communications (13/08/2026): NBA announces schedule for 2026-27 regular season](https://pr.nba.com/2026-27-nba-regular-season-schedule)

Nguồn35 giải thích nguyên tắc futility/interim trong bối cảnh clinical trials; không được dùng để xác nhận coverage của bootstrap time-series NBA. Nguồn36 chỉ hỗ trợ lịch mùa đã công bố; không xác nhận ngày kết thúc B4/B5 hay lịch2027-28 chưa được đếm trong kế hoạch.

### 16.1. Rà nguồn và giới hạn diễn giải — bổ sung bản 1.4

Rà lại metadata/nội dung truy xuất được của nguồn 16–26 và thay nguồn 27. Bản 1.2 có nguồn cao nhất là 27; các nguồn 28–30 được thêm trong bản 1.3. Việc rà này không có nghĩa đã đọc toàn văn mọi bài sau paywall hoặc xác nhận hiệu quả của mô hình trên NBA.

| Nguồn | Nội dung phù hợp và giới hạn sử dụng |
|---|---|
| 16 | Consistent scoring cho mean/median/quantile; không chứng minh Poisson thắng RMSE trên NBA |
| 17 | Tweedie power/support/link; tài liệu GLM, không benchmark boosting |
| 18 | Metadata và abstract xác nhận count forecast diagnostics, nonrandomized PIT và proper scores; không bảo đảm coverage cho model hiện tại |
| 19 | Regression recalibration; không áp dụng guarantee liên tục một cách tự động cho dữ liệu rời rạc và thời gian drift |
| 20 | Phân biệt distribution/quantile calibration; không là bằng chứng một G bất kỳ đã calibration có điều kiện |
| 21 | Alpha/power/effect size và one-sample option ratio=0; các bảng n trong file là phép tính Normal approximation tự tính, không số liệu NBA từ tài liệu |
| 22 | Paired resampling dùng cùng indices; riêng tài liệu này không hỗ trợ coi IID bootstrap là hợp lệ với phụ thuộc thời gian |
| 23 | Stationary/circular/moving-block bootstrap; không tự xác định optimal block length cho NBA |
| 24 | Selection bias và nested evaluation; ví dụ Iris không phải temporal CV, phải dùng split thời gian theo §11 |
| 25 | GLM link/variance functions và family definitions; không phải so sánh hiệu quả CatBoost/LightGBM |
| 26 | Beta-Binomial count PMF/CDF; không phải phân phối liên tục của tỷ lệ ném |
| 27 mới | Wedderburn (1974), nguồn gốc quasi-likelihood mean–variance; đối chiếu metadata/abstract từ publisher/JSTOR, không tuyên bố đã đọc full text qua DOI nếu bị chặn |
| 28–29 | Threshold-weighted scoring với các assumptions về weights; không tự chứng minh market-derived weights proper đối với forecaster có ít thông tin hơn. Nguồn 29 đã mở lại: phần threshold-weighting trình bày tổng/tích phân các binary proper scores với weight function không âm. Điều kiện information-set trong §10.4.3 được suy ra trực tiếp từ weighted squared loss, không gán thành kết quả NBA của trang này |
| 30 | Đã mở lại tài liệu multipletests: alpha là FWER, danh sách có bonferroni one-step và holm step-down. Trang này không tính các bảng power NBA và không chứng minh tính hợp lệ của mọi block-resampled p-value |

Nguồn 27 cũ trỏ tới Guan, Jalilian & Waagepetersen (2015), *Quasi-likelihood for Spatial Point Processes* (PMC4450110). Bài đó có trình bày quasi-score tổng quát nhưng lĩnh vực chính là spatial point processes; cách gắn nhãn rộng để làm nguồn trực tiếp cho đoạn GLM/Poisson là không phù hợp. Đã bỏ khỏi danh sách tham khảo chính và thay bằng Wedderburn (1974), không dùng nguồn cũ như bằng chứng NBA hoặc boosting.

Các đặc tả logistic encompassing, trọng số quanh line và chính sách lựa chọn cược trong file là đề xuất thiết kế cần validation, không được gán thành kết quả đã chứng minh của một bài trong danh sách.

Các lựa chọn cửa sổ train, cutoff, model và lịch retrain trong kế hoạch là giả thuyết thiết kế cần kiểm chứng trên dữ liệu NBA, không phải kết quả benchmark đã đạt được.


## 17. Kết quả phản biện bản 1.1

| Đề xuất | Quyết định được đưa vào kế hoạch |
|---|---|
| 1. Loss/estimand | Bổ sung loss cụ thể và scoring đúng đích; giữ RMSE làm mean baseline, Tweedie không coi là integer PMF |
| 2. Mixture minutes | Chấp nhận total probability/variance; dùng tích phân hoặc binning, NB là ứng viên; không khẳng định variance minutes chiếm đa số |
| 3. Dispersion | Bổ sung OOF residual fitting, contextual pooling, Pearson và quantile crossing; không cấm joint train likelihood |
| 4. CDF calibration | Bổ sung G có constraints, discrete PIT/RPS; sửa nhầm model mass thành empirical coverage guarantee |
| 5. Shrinkage | Bổ sung Gamma–Poisson, decay, ESS/exposure; nêu giới hạn với PTS, role change và rookie |
| 6. EV/Push/void | Bổ sung hòa vốn conditional decisive và de-vig cụ thể; void phụ thuộc rules, không chỉ DNP |
| 7. Uncertainty/power | Bổ sung paired multi-day block bootstrap; tách phép tính ~2SE khỏi alpha/power, số mẫu chỉ minh họa |
| 8. Market benchmark | Bổ sung offered-market selection và paired scoring; same-cutoff là chính, closing riêng khi khác thông tin/line |
| 9. Multiple selection | Bổ sung trial registry, ngân sách và xác nhận holdout một lần sau khóa pipeline |
| 10. PRA | Bổ sung shared minutes draws; vẫn kiểm tra conditional covariance còn lại hoặc model tổng trực tiếp |


### 17.1. Chốt tranh luận tiếp theo — bản 1.2

- Thừa nhận Poisson có động cơ cấu trúc; hiệu quả thống kê cần variance function/mean specification phù hợp, không chỉ variance tăng.
- Joint dispersion được kiểm tra và lựa chọn bằng temporal validation; residual clip/round không là production PMF mặc định.
- Bổ sung PTS theo volume + shot mix + accuracy, Beta trên xác suất và Beta-Binomial trên made counts.
- Bổ sung cả thiết kế power một/hai phía, quy tắc đăng ký trước và ESS theo metric.
- Chấm model CDF tại chính line nhà cái cùng snapshot; xử lý conditioning của Push/void.
- Làm rõ monotone G không tự bảo đảm calibration biên; calibration biên không đủ cho mọi tập dự đoán thích nghi.


### 17.2. Chốt phản biện — bản 1.3

- Thay nguồn 27 bằng đúng bài Wedderburn (1974); ghi tên thật, phạm vi nguồn và giới hạn truy xuất trong §16.1.
- Bổ sung multiplicity family, bảng Bonferroni, marginal-vs-joint power và variance theo odds.
- Bổ sung selected-edge evaluation cùng encompassing/logit blend, có intercept/sensitivity và holdout riêng; diễn giải β có điều kiện theo specification.
- Bổ sung threshold weights cụ thể, dùng cùng policy khi calibration/evaluation; không dùng F riêng từng model để chọn vùng được chấm.
- Giữ full-distribution scores làm mục tiêu phụ để phát hiện tail/Push errors; không khẳng định thresholds cực trị luôn lấn át.


### 17.3. Chốt phản biện — bản 1.4

- Chấp nhận lỗi information-set trong chính sách line-weights của bản 1.3; thay default bằng full-RPS/fixed-grid calibration cho stats-only model.
- Thêm công thức weighted optimum/conditional covariance và ví dụ 0.5→0.68 để kiểm tra target shift.
- Tách đường A (stats-only calibration/selection), B (pricing tại line) và C (model có thị trường), kể cả sample-selection weights.
- G_line-selected chỉ là sensitivity; không suy từ line gần median thành mọi G đều bị kéo về 0.5 hoặc gọi mọi market-selected training là future leakage.
- Làm rõ lại β=1 của mô hình không intercept đã tái tạo r_model; bản có intercept cần a=0.
- Nguồn 29 và 30 được kiểm tra lại qua tài liệu trực tiếp; không yêu cầu người dùng xác nhận nguồn và không gán kết quả riêng của kế hoạch cho chúng.


### 17.4. Chốt phản biện — bản 1.5

- Bảng line/pricing không là tiêu chí chọn hoặc kiểm chứng riêng G_stats; kết quả không đo thuần information gap.
- Co về 0.5 tại ideal median cần nesting information sets và conditioning phù hợp; market efficiency riêng trên I_mkt chưa đủ khi C_stats có signal bổ sung.
- Market-selected calibration + H inputs không tự động là double-counting; thêm ablation và OOF stacking để kiểm tra.
- Power counts là analytic Normal approximation với assumptions nêu rõ và mã tái lập; chưa có mô phỏng correlation/power thực nghiệm NBA.


### 17.5. Chốt phản biện — bản 1.6

- Thừa nhận bản 1.5 thiếu ngưỡng quyết định, cặp xác nhận và split G/stacker cụ thể; §11.7 là protocol ưu tiên mới.
- Chốt primary pooled ΔBrier H/S+H, margin/precision/CI, một horizon xác nhận và nhãn terminal không nhầm absence-of-evidence với equivalence.
- B4 năm 2025-26 trở thành variance pilot; B5 tương lai riêng là xác nhận, không tái sử dụng pilot như holdout.
- Bảng paired-score power khác bảng ROI và có code chạy được; chưa biết đủ sample nếu chưa có Ω pilot.
- Thêm design-effect examples và giải thích Bonferroni minh họa vs Holm khi family xác nhận có nhiều tests.
- Margin và calendar/block choices là lựa chọn vận hành đã khóa để có thể phản biện/triển khai, không là ngưỡng tối ưu đã kiểm chứng.


### 17.6. Chốt phản biện — bản 1.7

- Xác nhận width-gate làm joint ADOPT power khác superiority power; bỏ width khỏi ADOPT, giữ diagnostic.
- Đổi exposure từ calendar days sang scheduled Regular-Season game dates; không tạo sample từ offseason, không bootstrap blocks xuyên gap như không tồn tại.
- Pilot mở rộng cố định280 game dates; Ω_U là working bound và size/coverage/full-rule power suite là mandatory pre-test gate, chưa có kết quả NBA.
- Giới hạn nhãn kết quả cho frozen algorithm; refit production cần protocol riêng, không suy chiều drift khi chưa đo.
- Bổ sung RMS feasibility và Brier identity đúng điều kiện; RMS² không là universal upper bound, σ_d không luôn bằng RMS.


### 17.7. Chốt phản biện — bản1.8

- Ghi rõ chi phí nhiều mùa; không xác nhận mốc tháng2/2027/đầu2028 nếu chưa đếm đầy đủ schedule UTC.
- Primary đổi trước B5 thành weekly-refit H/S+H; frozen thăm dò, không co-primary. Recipe, windows, availability và failure rules đăng ký ngay.
- Pilot140/280 thêm U<δ futility-only; không adopt, không suy absence-of-signal, và tính power toàn flow gồm dừng.
- Tách algorithm freeze F_A và registration release R; block B4G không được hồi tố thành pilot hoặc confirmatory data.
- Suite tìm T_min trên lưới và validation độc lập; báo minimum không đạt nếu pilot continuation đã giới hạn overall power.
