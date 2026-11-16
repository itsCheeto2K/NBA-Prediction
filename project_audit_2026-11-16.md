# Báo cáo rà soát NBA Props Prediction

- Ngày rà soát: 2026-11-16.
- Phạm vi: cấu trúc thư mục, API, UI, collectors, features, models, distribution, simulation gate, scripts, tests và dữ liệu Parquet hiện có.
- Trạng thái: chỉ kiểm tra và đề xuất; chưa sửa mã nguồn, cấu hình hoặc mô hình.
- Tài liệu này ghi lại kết quả của lượt rà soát, không phải chứng nhận rằng toàn bộ lỗi có thể tồn tại đã được phát hiện.

## 1. Phương pháp và giới hạn

Đã kiểm kê các thư mục `src`, `tests`, `scripts`, `data`, `models`, `reports`, `docs`, `.nba_api_docs`, `awesome-design-md`, `.hallmark` và các thư mục cache. Tài liệu, thiết kế tham khảo và cache được phân biệt với mã chạy của ứng dụng.

Đã đọc và đối chiếu các luồng xử lý chính, chạy test phù hợp và dùng các ví dụ nhỏ trong bộ nhớ để tái hiện lỗi. Kiểm tra API bổ sung dùng cache injury và tắt auto-sync trong bộ nhớ để tránh cập nhật dữ liệu.

Kết quả kiểm tra:

- **126 test chạy thành công** qua hai nhóm kiểm tra.
- **6 test bị chặn ở bước tạo thư mục tạm do quyền môi trường**. Đây là lỗi thiết lập test trong môi trường kiểm tra, chưa phải bằng chứng test logic thất bại.
- **3 test khác chưa chạy** trong lượt kiểm tra API bổ sung: async sync, lease lock và OCR dùng ảnh ngoài dự án.
- **91 file Python và 2 file JavaScript** qua kiểm tra cú pháp.
- **24 file JSON** trong `data`, `reports`, `models` đọc được.
- Không phát hiện trùng khóa player/game hoặc team/game trong các Parquet được kiểm tra tại thời điểm rà soát.
- UI được kiểm tra qua mã và luồng API; **chưa kiểm chứng hiển thị thực tế trên trình duyệt/mobile**.
- Không thực hiện tải dữ liệu trực tiếp từ NBA/ESPN để đánh giá tính đúng của dữ liệu bên ngoài.

Các thay đổi dữ liệu và `.hallmark` đã hiện diện trong Git working tree khi bắt đầu kiểm tra; không được coi là thay đổi sửa lỗi của lượt rà soát này.

## 2. Quy ước ưu tiên

| Mức | Ý nghĩa |
| --- | --- |
| P1 | Ưu tiên cao: có thể trả dự đoán sai, làm sai đánh giá mô hình hoặc gây trạng thái dữ liệu không nhất quán. |
| P2 | Cần sửa: ảnh hưởng chức năng, khả năng vận hành, độ tin cậy hoặc khả năng tái tạo. |

Các ví dụ số dưới đây là kết quả tái hiện tại thời điểm kiểm tra hoặc từ dữ liệu tổng hợp có chủ đích. Ví dụ tổng hợp không có nghĩa lỗi đã xảy ra với mọi người dùng thực tế.

## 3. Dự đoán và feature

### 01 — P1: Cầu thủ khỏe bị tính xác suất ra sân 50%

**Vị trí:** [src/features/participation.py](src/features/participation.py), hàm `normalize_injury_status`; [src/api/main.py](src/api/main.py), giá trị mặc định `p_status`.

API dùng `HEALTHY`, nhưng bộ chuẩn hóa chuyển thành `unknown`. Chuỗi chuẩn `not_listed` cũng bị chuyển thành `unknown`.

**Đã tái hiện:**

| Đầu vào | Sau chuẩn hóa | Xác suất participation |
| --- | --- | --- |
| `HEALTHY` | `unknown` | 0.50 |
| `available` | `available` | 0.99 |
| `not_listed` | `unknown` | 0.50 |

**Ảnh hưởng:** sai xác suất void và xác suất settlement vô điều kiện; các trường participation đưa vào model cũng có thể sai.

**Đề xuất:** thống nhất tập trạng thái và bảo đảm chuẩn hóa một trạng thái đã chuẩn hóa không làm đổi nghĩa. Dùng trạng thái phù hợp khi không có tên trong báo cáo injury.

### 02 — P1: Trạng thái injury không đi đúng vào model

**Vị trí:** [src/api/main.py](src/api/main.py), mapping `own_status_code`.

Hàm chuẩn hóa trả chữ thường, nhưng bảng mapping dùng chữ hoa.

**Đã tái hiện:** giả lập `Questionable`, model nhận `own_status_code=0`, `own_is_questionable=0`, trong khi participation là 0.54 và condition là `SCENARIO_ONLY`.

**Ảnh hưởng:** thông tin hiển thị cho người dùng và feature thực sự vào model không nhất quán.

**Đề xuất:** dùng một enum/mapping chung cho collector, training, inference và UI.

### 03 — P1: Feature dự đoán chậm một trận

**Vị trí:** [src/api/main.py](src/api/main.py), `load_resources`, thao tác `groupby("player_id").last()`.

Dòng feature mới nhất vẫn chứa rolling đã `shift(1)` dành cho chính trận đó, rồi được dùng dự đoán trận tiếp theo.

**Đã tái hiện:** với Donovan Mitchell, API dùng PTS trung bình 5 trận là **24.2**, trong khi trung bình 5 trận gần nhất đã hoàn thành là **23.8**.

**Ảnh hưởng:** rolling, shrinkage, history count và workload có thể chưa bao gồm trận gần nhất. Ngoài ra, `groupby.last()` có thể lấy giá trị không-null cuối theo từng cột thay vì giữ nguyên một dòng duy nhất.

**Đề xuất:** tạo dòng feature riêng cho trận mục tiêu, cập nhật lịch sử đến hết trận gần nhất. Không lấy nguyên dòng training cuối cùng làm dòng dự đoán.

### 04 — P1: Ngày nghỉ và trạng thái trở lại đang bị giả định

**Vị trí:** [src/api/main.py](src/api/main.py), `days_since_last`, `games_since_return`.

Dataset hiện không có `days_since_last_appearance`, nên API rơi vào mặc định **2 ngày**. `games_since_return` bị gán 0 hoặc 5.

**Ảnh hưởng:** phát hiện nghỉ dài và giai đoạn trở lại có thể sai; workload và condition không phản ánh thời điểm trận mục tiêu.

**Đề xuất:** tính từ lần ra sân thực tế gần nhất tới ngày trận mục tiêu; dùng state machine return episode đã có và cập nhật các feature lịch liên quan cùng lúc.

### 05 — P1: Feature tương tác sai thứ tự pipeline

**Vị trí:** [src/features/builder.py](src/features/builder.py), [src/features/opponent_context.py](src/features/opponent_context.py), [src/features/opponent_interactions.py](src/features/opponent_interactions.py).

Interactions được tính trước rolling, nên dùng các giá trị mặc định thay cho phong độ cầu thủ. Khi inference lại tính bằng rolling thật.

**Đã kiểm tra trên 83.790 dòng:**

| Interaction | Số dòng khác khi tính lại sau rolling |
| --- | ---: |
| `interact_pts_3pa_x_opp_3pm_allowed` | 82.635 |
| `interact_pts_fta_x_opp_fta_allowed` | 82.811 |
| `interact_pts_2pt_x_opp_blocks_made` | 82.646 |
| `interact_ast_rate_x_opp_ast_allowed` | 82.825 |
| `interact_reb_dreb_x_opp_missed_fga` | 82.621 |

**Ảnh hưởng:** cùng một tên feature có cách tính khác nhau giữa training và inference.

**Đề xuất:** tính rolling trước, sau đó tính interactions khi đã có cả rolling và opponent context; rebuild dataset và đánh giá lại model.

### 06 — P1: Training injury có thông tin biết sau trận

**Vị trí:** [src/models/injury_ablation.py](src/models/injury_ablation.py), `enrich_dataset_with_injury_features`.

Hàm lấy tập cầu thủ xuất hiện trong gamelog của chính trận để suy ra thiếu hụt đội hình. Đây là thông tin participation sau trận. Khi chạy thật, API lại dùng injury report và tỷ lệ cố định.

**Ảnh hưởng:** nguy cơ leakage từ tập cầu thủ thực sự ra sân, đồng thời có khác biệt công thức giữa training và inference. Kết luận ablation injury chưa đủ để khẳng định hiệu quả khi chạy thật.

**Đề xuất:** dùng roster/injury snapshot trước trận và cùng một công thức cho training/inference. Đánh giá lại các kết luận injury ablation sau khi thay nguồn feature.

### 07 — P1: Nhánh phân phối đang chạy cắt mất đuôi trên 60

**Vị trí:** [src/distribution/engine.py](src/distribution/engine.py), legacy `compute_pmf`, `compute_cdf`, `calculate_line_probabilities`; [src/api/main.py](src/api/main.py), `DIST_ENGINE`.

Tại thời điểm kiểm tra, `models` không có ModelBundle. API dùng legacy engine với `k_max=60`, chuẩn hóa lại prefix PMF thành tổng 1.

**Đã tái hiện bằng tham số tổng hợp:** `mu=50`, `phi=0.1`, `line=60.5`.

| Cách tính | P(Over) |
| --- | ---: |
| Legacy engine | 0% |
| Phân phối đầy đủ | 24.962% |

**Ảnh hưởng:** xác suất, median và interval có thể sai khi phần đuôi đáng kể. Dispersion của nhánh legacy cũng đang dùng các hằng số theo stat, chưa đi qua quy trình fitted bundle.

**Đề xuất:** dùng trực tiếp `DiscreteDistribution` cho mọi truy vấn xác suất, median và interval; prefix chỉ phục vụ biểu đồ. Fit và kiểm chứng dispersion trước khi phát hành bundle.

### 08 — P1: Player không tồn tại vẫn nhận dự đoán

**Vị trí:** [src/api/main.py](src/api/main.py), `predict_props`, lời gọi `assess_player_condition`.

Kiểm tra model/prior đang được truyền cố định `True`.

**Đã tái hiện:** `player_id=-999` trả expected PTS **10**, participation **50%**, condition `SCENARIO_ONLY`, nhưng readiness **READY**.

**Đề xuất:** kiểm tra player, feature, prior và model thật; trả 404 hoặc trạng thái thiếu dữ liệu. Không tạo dự đoán mặc định cho player không xác định.

### 09 — P1: Cầu thủ OUT có thể được bật lại xác suất/EV

**Vị trí:** [src/api/main.py](src/api/main.py), nhánh `ctx_support` sau `assess_player_condition`.

Khi đồng đội thiếu trên ngưỡng hỗ trợ, nhánh injury context ghi đè `forecast_status=not_issued` thành `conditional_scenario`.

**Đã tái hiện bằng injury giả lập:** player OUT, đồng đội thiếu trên ngưỡng, response vẫn có line probabilities và pricing; readiness đồng thời báo OUT.

**Đề xuất:** áp dụng thứ tự ưu tiên trạng thái duy nhất; các nhánh phía sau không được nới lỏng trạng thái cấm phát hành dự đoán.

### 10 — P2: Tên feature AST không thống nhất

**Vị trí:** [src/features/opponent_context.py](src/features/opponent_context.py), [src/models/trainer.py](src/models/trainer.py), [src/features/matchup_resolver.py](src/features/matchup_resolver.py).

Builder tạo `opp_allowed_ast_per100_prev10`, trainer/live dùng `opp_ast_allowed_per100_prev10`. Cột thứ hai không có trong dataset hiện tại.

**Đề xuất:** chuẩn hóa tên và kiểm tra schema bắt buộc trước train/inference. Không âm thầm loại feature quan trọng khỏi tập train.

### 11 — P2: Hai định nghĩa possessions khác nhau

**Vị trí:** [src/features/opponent_context.py](src/features/opponent_context.py), [src/features/opponent_pairs.py](src/features/opponent_pairs.py).

Opponent context cũ nhân `0.96`; opponent ranks/DvP dùng công thức không nhân hệ số đó. Các chỉ số per-100 vì thế không cùng chuẩn.

**Đề xuất:** chọn một công thức chuẩn, dùng chung và ghi phiên bản feature. Nếu cố ý giữ hai định nghĩa thì đặt tên rõ và không so sánh trực tiếp.

## 4. UI và OCR

### 12 — P1: FastCheck gửi sai trường odds

**Vị trí:** [src/api/static/fastcheck.js](src/api/static/fastcheck.js), các payload dự đoán đơn và batch; [src/api/schemas.py](src/api/schemas.py).

UI gửi `over_odds`/`under_odds`, trong khi API nhận `odds_over`/`odds_under`. Pydantic bỏ qua các trường này nên giá nhập không đi vào pricing.

**Đề xuất:** sửa contract; cấu hình từ chối trường lạ để phát hiện lỗi nối UI/API; bổ sung kiểm tra payload thực tế từ frontend.

### 13 — P1: OCR có thể đọc line thành odds

**Vị trí:** [src/services/odds_ocr_parser.py](src/services/odds_ocr_parser.py), `parse_odds_image`.

**Đã tái hiện với OCR engine giả lập:** hàng `Stephen Curry / 22.5 / 1.91 / 1.85` trả `line=22.5`, **odds_over=22.5**, `odds_under=1.91`.

Khi chỉ thấy một odds, parser còn tự sao chép sang phía kia. Fuzzy matching có ngưỡng 0.55 nhưng chưa có điểm tin cậy matching riêng để người dùng đánh giá.

**Đề xuất:** phân biệt cột bằng tọa độ/nhãn; loại token line khỏi odds; giữ `null` khi thiếu dữ liệu; yêu cầu người dùng kiểm tra các trường có độ tin cậy thấp trước áp dụng.

### 14 — P1: Tô màu cơ hội theo ngưỡng cố định 52.4%

**Vị trí:** [src/api/static/fastcheck.js](src/api/static/fastcheck.js), `applyPredictionToRow`, xử lý batch.

Ngưỡng tô màu không phụ thuộc odds đã nhập hoặc xác suất push. Ví dụ 55% với odds 1.50 vẫn bị tô như có lợi thế dù EV âm khi không có push.

**Đề xuất:** tô màu dựa trên EV của chính quote và quy tắc settlement; thể hiện rõ dữ liệu thiếu/không được phát hành.

### 15 — P1: Kết quả cũ không được xóa đầy đủ

**Vị trí:** [src/api/static/app.js](src/api/static/app.js), `updateDashboard`; [src/api/static/fastcheck.js](src/api/static/fastcheck.js), `applyPredictionToRow`, xử lý batch.

Khi response mới không có `line_probabilities` hoặc `pricing`, UI chỉ bỏ qua cập nhật nên có thể giữ xác suất, fair odds và EV trước đó. Batch lỗi cũng chưa thể hiện rõ lỗi theo từng dòng.

**Đề xuất:** reset toàn bộ trường phụ thuộc khi bắt đầu request, khi lỗi và khi thiếu kết quả. Gắn trạng thái từng dòng với response mới nhất.

### 16 — P2: Request có thể ghi đè nhau

**Vị trí:** [src/api/static/app.js](src/api/static/app.js), `runPrediction`, `searchPlayers`; [src/api/static/fastcheck.js](src/api/static/fastcheck.js), đổi đội và dự đoán đơn.

Đổi cầu thủ/đội/line nhanh không có request ID hoặc hủy request dự đoán cũ. Response cũ về muộn có thể ghi lên lựa chọn mới. Đây là rủi ro từ luồng bất đồng bộ trong mã; chưa tái hiện bằng trình duyệt trong lượt kiểm tra này.

**Đề xuất:** dùng `AbortController` và kiểm tra request/version trước khi render; hủy debounce cũ khi reset lựa chọn.

### 17 — P2: Nút Sync báo xong quá sớm

**Vị trí:** [src/api/static/app.js](src/api/static/app.js), [src/api/static/fastcheck.js](src/api/static/fastcheck.js), `triggerManualSync`.

UI bật lại nút và chạy dự đoán ngay sau response tạo job, chưa đợi đồng bộ hoàn tất.

**Đề xuất:** poll theo `job_id`; chỉ refresh dự đoán sau trạng thái kết thúc; hiển thị `PARTIAL`/`FAILED`, lỗi và thời điểm dữ liệu mới nhất.

### 18 — P2: Line bằng 0 bị mất và nhãn engine không đúng nhánh chạy

**Vị trí:** [src/api/static/app.js](src/api/static/app.js), `runPrediction`; [src/api/static/index.html](src/api/static/index.html).

`parseFloat(value) || null` chuyển line 0 thành `null`. UI ghi “Poisson Engine” trong khi nhánh hiện tại dùng NB2.

**Đề xuất:** phân biệt ô trống với số 0; kiểm tra `Number.isFinite`; lấy nhãn engine/model và trạng thái calibration từ response.

## 5. Dữ liệu và vận hành

### 19 — P1: Auto-sync đọc trường timestamp không được ghi

**Vị trí:** [src/api/main.py](src/api/main.py), `_trigger_auto_sync_if_stale`; [src/collectors/sync.py](src/collectors/sync.py), sync record.

Auto-sync đọc `last_sync_time`, nhưng sync record chỉ ghi `started_at`/`finished_at`. Sau mỗi job, lần kiểm tra tiếp theo vẫn coi dữ liệu là stale. Startup và truy cập trang đều có thể kích hoạt kiểm tra này.

**Đề xuất:** thống nhất timestamp cho lần commit hợp lệ; phân biệt lần thử sync và lần sync thành công; không coi thiếu trường legacy là lý do đồng bộ liên tục.

### 20 — P1: Audit so sai phạm vi mùa giải

**Vị trí:** [src/pipeline/backfill.py](src/pipeline/backfill.py), `audit_backfill_completeness`; [src/collectors/gamelogs.py](src/collectors/gamelogs.py).

Schedule có preseason, nhưng gamelog mặc định chỉ Regular Season. Manifest tại thời điểm kiểm tra báo thiếu **67 trận `00126…`**, khiến `PARTIAL` không phản ánh đúng độ đầy đủ Regular Season.

**Đề xuất:** audit theo season type/game scope tương ứng; ghi scope rõ trong manifest và không trộn preseason/playoffs với Regular Season.

### 21 — P1: Audit vẫn báo COMPLETE dù dữ liệu sai

**Vị trí:** [src/pipeline/backfill.py](src/pipeline/backfill.py), `audit_backfill_completeness`.

Audit chỉ kiểm tra có hai `team_id` khác nhau, chưa đối chiếu đúng đội trong schedule. Duplicate player chỉ thêm thông báo, không chặn COMPLETE. Thiếu player coverage cũng chưa chặn.

**Đã tái hiện bằng dữ liệu tổng hợp:** lịch có đội 1 và 2, team logs chứa đội 1 trùng dòng và đội 99, player logs trùng dòng; audit vẫn trả `COMPLETE`, `duplicate_team_rows_count=0`.

**Đề xuất:** kiểm tra khóa duy nhất, hai đội đúng lịch, player coverage và đưa tất cả điều kiện vào quyết định audit.

### 22 — P1: Sync ghi đè trực tiếp nhiều Parquet dù audit PARTIAL

**Vị trí:** [src/collectors/sync.py](src/collectors/sync.py), `sync_season_data`.

Schedule, team logs, player logs và features được ghi tuần tự vào đường dẫn đang dùng. Lỗi giữa chừng có thể để các file thuộc phiên bản khác nhau; audit PARTIAL vẫn đi vào bước ghi đè.

**Đề xuất:** ghi vào staging, validate, rồi chuyển manifest sang snapshot mới; giữ snapshot hợp lệ trước đó. Xác định chính sách rõ cho dữ liệu PARTIAL thay vì âm thầm thay dữ liệu phục vụ dự đoán.

### 23 — P1: Lease lock chưa khóa an toàn giữa nhiều process

**Vị trí:** [src/collectors/sync.py](src/collectors/sync.py), `SyncLeaseLock`.

Kiểm tra rồi ghi file không atomic. `threading.Lock` chỉ bảo vệ một process. Heartbeat không cập nhật xuyên suốt bước rebuild dài, nên lease có thể hết hạn khi worker vẫn hoạt động.

**Đề xuất:** dùng khóa hệ điều hành hoặc transaction lock và heartbeat định kỳ; kiểm tra quyền sở hữu trước commit. Cần kiểm thử cạnh tranh bằng nhiều process.

### 24 — P1: Cache defensive/DvP có thể trả dữ liệu cũ

**Vị trí:** [src/features/dvp_context.py](src/features/dvp_context.py), [src/features/matchup_resolver.py](src/features/matchup_resolver.py), [src/api/main.py](src/api/main.py), `load_resources`.

Cache key chủ yếu dựa vào số dòng/index. Sửa nội dung nhưng giữ số dòng không làm mất cache. Hot-reload globals cũng không thay toàn bộ tài nguyên cùng lúc, nên request đang xử lý có thể đọc các phần từ nhiều phiên bản.

**Đề xuất:** cache theo snapshot/version; xây bộ tài nguyên mới, validate rồi thay tham chiếu một lần; xóa cache theo phiên bản dữ liệu.

### 25 — P2: Readiness kiểm tra quá ít và bỏ qua injury stale

**Vị trí:** [src/api/main.py](src/api/main.py), `health_ready`, lời gọi `evaluate_injury_readiness`; [src/collectors/injuries.py](src/collectors/injuries.py).

Chỉ cần một model và bảng players là READY, kể cả thiếu features hoặc model của market khác. Injury cache hết hạn có thể được trả lại khi fetch thất bại nhưng API không truyền `is_stale_report` vào readiness.

**Đề xuất:** readiness theo từng market, snapshot, freshness và schema; phát hành trạng thái suy giảm rõ ràng. Không coi lỗi nguồn injury là bằng chứng mọi cầu thủ khỏe.

### 26 — P2: Roster và target-game context chưa nhất quán

**Vị trí:** [src/api/main.py](src/api/main.py), `get_team_roster`, `predict_props`; [src/features/matchup_resolver.py](src/features/matchup_resolver.py).

Roster suy ra từ đội trong lần ra sân cuối, nên có thể chứa cầu thủ mùa cũ/đã rời đội. `game_id` trong PredictRequest chưa được dùng để chọn trận.

**Đã tái hiện:** khi override ATL cho Donovan Mitchell, response có `active_opponent=ATL` nhưng trường `opponent=CHI`, cùng thông tin trận CLE–CHI.

**Đề xuất:** tách roster hiện tại khỏi lịch sử thi đấu; dùng một target-game context nhất quán cho model, injury và UI. Với scenario override, phân biệt rõ trận lịch gốc và đối thủ giả định.

## 6. Nghiên cứu, công thức đánh giá và đóng gói

### 27 — P1: Full RPS trong selector chưa đúng

**Vị trí:** [src/models/selector.py](src/models/selector.py), `evaluate_recipe_on_b1`.

Grid cố định; công thức phần dư lệch một đơn vị với outcome vượt grid; log-score clip outcome về 70; nhánh calibrated ép CDF cuối thành 1.

**Đã tái hiện bằng Poisson:**

| Mean | Outcome | RPS selector | RPS full-support |
| ---: | ---: | ---: | ---: |
| 100 | 100 | 30.00000 | 2.33383 |
| 25 | 80 | 53.18613 | 52.18613 |

**Ảnh hưởng:** có thể chọn sai recipe, sai log-score và interval coverage khi tail đáng kể.

**Đề xuất:** dùng cùng scoring full-support/adaptive grid cho mọi recipe; không clip outcome hoặc ép prefix CDF thành 1.

### 28 — P1: Shrinkage ablation dùng prior chứa tương lai của các dòng training

**Vị trí:** [src/models/shrinkage_ablation.py](src/models/shrinkage_ablation.py), `enrich_features`; [src/features/shrinkage.py](src/features/shrinkage.py), `build_temporal_training_features`.

Prior fit toàn B0 rồi áp lại vào các dòng B0. Temporal builder cũng áp prior cuối warmup cho các dòng đầu warmup. Các prior này có thể chứa dữ liệu chưa có tại cutoff của dòng đang tính.

**Đề xuất:** fit prior theo từng prefix thời gian; loại warmup khỏi chấm điểm hoặc dùng prior có trước warmup. Đánh giá lại ablation sau khi loại leakage.

### 29 — P1: Bundle làm mất K của WeightedAverage

**Vị trí:** [src/models/selector.py](src/models/selector.py), export `mean_config` và `ModelBundle.load`.

Khi export không lưu `k`; load mặc định K=5. Nếu winner là K10/K20, hành vi sau load sẽ khác recipe đã được chọn. Đây là lỗi nhánh bundle, hiện chưa có bundle trong thư mục models của dự án.

**Đề xuất:** lưu đầy đủ candidate params; kiểm tra dự đoán trước/sau serialize phải giống nhau, bao gồm K5/K10/K20.

### 30 — P2: Expected value nhánh calibrated dùng mean thô

**Vị trí:** [src/api/main.py](src/api/main.py), nhánh bundle lấy `mu = dist.mu`.

API lấy mean thô dù CDF đã calibration, trong khi calibration có thể đổi kỳ vọng.

**Ví dụ kiểm chứng tổng hợp:** phân phối có mean thô **20**, dùng mapping CDF `G(u)=u²` cho kỳ vọng khoảng **22.515**. Mapping này chỉ để minh họa sự khác biệt toán học, không phải calibrator đang phát hành của dự án.

**Đề xuất:** hiển thị mean của phân phối cuối cùng; tách raw mean nếu cần chẩn đoán. Kiểm tra mean, median, interval và line probabilities cùng thuộc một phân phối.

### 31 — P2: Simulation gate mặc định không thể pass tiêu chí hiện tại

**Vị trí:** [src/simulation_gate/gate.py](src/simulation_gate/gate.py), [src/simulation_gate/config.py](src/simulation_gate/config.py).

Với mặc định 50 outer runs, ngay cả 0/50 false adoption thì Wilson upper khoảng **7.13%**, vượt ngưỡng 3.5%. Coverage hoàn hảo 50/50 cũng chỉ có Wilson lower khoảng **92.865%**, thấp hơn 93%.

Ngoài ra, gate chưa đưa coverage tại boundary `theta=delta` vào điều kiện pass.

**Đề xuất:** tách smoke test khỏi certification; dùng số lần mô phỏng phù hợp với tiêu chí Wilson; kiểm tra đủ mọi theta và tránh gắn nhãn validated từ cấu hình smoke.

### 32 — P2: Minutes allocator nhận trùng player ID nhưng vẫn SUCCESS

**Vị trí:** [src/distribution/minutes_allocator.py](src/distribution/minutes_allocator.py), `allocate_team_minutes`.

**Đã tái hiện:** sáu bản ghi cùng player ID có baseline 30 phút cho tổng nội bộ 240 phút và `SUCCESS`, nhưng dictionary đầu ra chỉ còn một cầu thủ 40 phút do trùng key.

**Đề xuất:** từ chối duplicate ID; kiểm tra tổng trên chính dữ liệu đầu ra đã serialize; không trả SUCCESS nếu không đạt các bất biến của đầu ra.

### 33 — P2: Module context có lỗi runtime chắc chắn

**Vị trí:** [src/features/context.py](src/features/context.py), `compute_opponent_defense_context`.

`game_pts` được dùng nhưng chưa khai báo. Sau đó rolling chạy trên chuỗi tổng thay vì trong từng đội. Hàm này hiện không nằm trong builder chính.

**Đề xuất:** sửa và kiểm thử riêng, hoặc loại bỏ nhánh legacy nếu đã thay thế hoàn toàn. Không coi việc hàm chưa được gọi là bằng chứng module hoạt động đúng.

### 34 — P2: Dependency khai báo thiếu

**Vị trí:** [requirements.txt](requirements.txt), các import runtime trong `src` và [scripts/run_app.py](scripts/run_app.py).

Chưa khai báo trực tiếp FastAPI, Uvicorn, LightGBM, CatBoost, SciPy, scikit-learn, Pillow, RapidOCR và một số dependency được dùng trực tiếp. Máy hiện tại có thư viện cài sẵn nên có thể che khuất lỗi môi trường mới.

**Đề xuất:** khai báo runtime/test/OCR dependencies và khóa môi trường có thể tái tạo; kiểm tra cài đặt và khởi động trong môi trường sạch.

## 7. Validation API và trạng thái staking

### 35 — P2: Odds và đầu vào API chưa được ràng buộc đầy đủ

**Vị trí:** [src/api/schemas.py](src/api/schemas.py), [src/distribution/pricing.py](src/distribution/pricing.py), `evaluate_market_pricing` trong [src/api/main.py](src/api/main.py).

Schema chưa ràng buộc đầy đủ decimal odds > 1, số hữu hạn, player ID và opponent hợp lệ. Hàm de-vig trả fallback 50/50 với odds không hợp lệ nhưng phần EV vẫn tiếp tục tính.

**Đã tái hiện:** odds `0.5` và `-2` vẫn trả pricing với EV thay vì từ chối yêu cầu.

**Đề xuất:** validate tại biên API; từ chối odds không hợp lệ bằng 422; thống nhất kiểm tra trong các hàm pricing dùng độc lập; tránh fallback giả làm quote hợp lệ.

### 36 — P2: Client có thể tự tuyên bố staking policy đã validated

**Vị trí:** [src/api/schemas.py](src/api/schemas.py), `allow_staking_recommendation`; [src/api/main.py](src/api/main.py), `evaluate_market_pricing`.

Cờ client `allow_staking_recommendation=True` được truyền trực tiếp để bật khuyến nghị Kelly và gán `staking_policy_validated=True`.

**Đã tái hiện:** chỉ đổi cờ request đã nhận `staking_reason=VALIDATED_POLICY` và khuyến nghị Kelly, không có kiểm chứng artifact/policy phía server.

**Đề xuất:** trạng thái validation phải đến từ cấu hình/artifact đã kiểm chứng phía server. Lựa chọn của client chỉ nên điều khiển việc hiển thị một khuyến nghị vốn đã đủ điều kiện phát hành.

## 8. Thứ tự triển khai sửa đề xuất

1. **Sửa điều kiện phát hành và injury:** lỗi 01, 02, 08, 09, 25, 35, 36. Thống nhất trạng thái trước khi tiếp tục dựa vào output.
2. **Sửa feature cho trận mục tiêu:** lỗi 03–06, 10, 11, 26. Dùng chung công thức và cutoff giữa training/inference.
3. **Sửa phân phối và metric:** lỗi 07, 27–30. Tách giới hạn biểu đồ khỏi miền hỗ trợ toán học.
4. **Sửa snapshot, audit và sync:** lỗi 19–24. Bảo đảm dữ liệu nhất quán và không đồng bộ lặp ngoài ý muốn.
5. **Sửa UI/OCR:** lỗi 12–18. Ưu tiên contract odds, xóa trạng thái cũ và kiểm tra dữ liệu OCR.
6. **Hoàn thiện module nghiên cứu và môi trường:** lỗi 31–34.
7. **Rebuild features, train và benchmark lại**, chỉ phát hành artifact sau khi các bước trên đã được xác minh.

## 9. Các kiểm tra nên bổ sung sau khi sửa

- Kiểm tra chuẩn hóa trạng thái theo bảng, bao gồm tính ổn định khi chuẩn hóa hai lần.
- So sánh feature trận mục tiêu với phép tính trực tiếp từ các trận đã hoàn thành.
- Kiểm tra tính nhất quán của công thức feature ở training và inference.
- Thay đổi dữ liệu tương lai và xác nhận feature của quá khứ không đổi.
- So sánh Over/Under/Push, quantile và RPS với phân phối full-support ở cả phần trung tâm và phần đuôi.
- Kiểm tra player không tồn tại, OUT, dữ liệu thiếu/stale và odds không hợp lệ.
- Kiểm tra UI khi response thiếu xác suất, response lỗi và response cũ về muộn.
- Kiểm tra OCR theo nhiều bố cục, line nguyên/nửa, thiếu một phía odds và tên tương tự nhau.
- Kiểm tra audit với sai đội, thiếu player logs và dòng trùng.
- Kiểm tra sync cạnh tranh nhiều process, hết lease và lỗi giữa các bước ghi snapshot.
- Kiểm tra dự đoán bundle trước/sau lưu và tải lại giống nhau.
- Kiểm tra cài dependency và khởi động từ môi trường sạch.
- Kiểm tra trực tiếp UI desktop/mobile, bàn phím và khả năng truy cập khi có trình duyệt phù hợp.

## 10. Lưu ý về báo cáo cũ

Không dùng số lượng lỗi trong [code_review_report.md](code_review_report.md) cũ làm kết luận cho lần rà soát này. Một số lỗi ghi ở đó đã được sửa trong mã hiện tại. Báo cáo này dựa trên mã và dữ liệu quan sát trong lượt kiểm tra ngày 2026-11-16.

Các báo cáo ablation hiện tại cần được kiểm chứng lại sau khi sửa leakage, thứ tự feature và scoring. Việc các test hiện có chạy thành công chưa chứng minh các công thức hoặc luồng UI/API đã đúng trong những trường hợp được tái hiện ở trên.
