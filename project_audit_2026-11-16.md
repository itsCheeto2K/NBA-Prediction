# Báo cáo rà soát NBA Props Prediction

- Ngày rà soát: 2026-11-16.
- Phạm vi: cấu trúc thư mục, API, UI, collectors, features, models, distribution, simulation gate, scripts, tests và dữ liệu Parquet hiện có.
- Trạng thái: đã tái kiểm sau commit sửa lỗi `d94f2c4`; lượt tái kiểm này chỉ cập nhật báo cáo, không sửa mã nguồn, cấu hình hoặc mô hình.
- Tài liệu này ghi lại kết quả của lượt rà soát, không phải chứng nhận rằng toàn bộ lỗi có thể tồn tại đã được phát hiện.

## 0. Kết quả tái kiểm sau commit d94f2c4

**Kết luận: chưa sửa hết. Trong 36 mục ban đầu, 13 mục đã sửa trong phạm vi kiểm tra, 18 mục sửa một phần và 5 mục chưa sửa. Tổng cộng còn 23 mục cần xử lý hoặc xác minh hoàn tất.** Tên commit nói sửa 30 lỗi không được dùng thay cho bằng chứng kiểm tra từng mục.

Ngày tái kiểm: 2026-11-16. Đối chiếu mã tại commit `d94f2c4` và dữ liệu working tree quan sát trong lượt kiểm tra. Giữ nguyên ID 01–36 để tiện theo dõi. Phần mô tả cũ bên dưới được giữ làm lịch sử; **khối trạng thái tái kiểm ở đầu mỗi mục mới là kết luận hiện tại**.

| ID | Ưu tiên | Trạng thái hiện tại | Nội dung còn lại hoặc kết quả xác nhận |
| --- | --- | --- | --- |
| 01 | P1 | Sửa một phần | HEALTHY/not_listed đúng; inactive và unavailable vẫn thành available, participation 0.99. |
| 02 | P1 | Đã sửa | Questionable thực sự đi vào model với status_code=1, own_is_questionable=1. |
| 03 | P1 | Chưa sửa | Vẫn dùng dòng training cuối: rolling PTS 24.2 thay vì 23.8. |
| 04 | P1 | Chưa sửa | Days-since-last mặc định 2; games_since_return vẫn 0/5. |
| 05 | P1 | Sửa một phần | Builder và features_all đã đúng; feature train theo mùa và model phát hành vẫn chưa cập nhật. |
| 06 | P1 | Đã sửa | Đã tính missing role trước trận từ injury status/rolling minutes, loại bỏ hoàn toàn boxscore leakage. |
| 07 | P1 | Đã sửa | API legacy dùng phân phối đầy đủ, không còn giới hạn xác suất ở 60. |
| 08 | P1 | Sửa một phần | Player lạ trả 404; player có tên nhưng thiếu feature vẫn nhận mean/PMF mặc định và readiness READY. |
| 09 | P1 | Đã sửa | OUT + đồng đội thiếu nhiều vẫn not_issued, không có line probabilities/pricing. |
| 10 | P2 | Sửa một phần | Builder/features_all có tên AST chuẩn; feature train 2023-24/2024-25 vẫn thiếu. |
| 11 | P2 | Sửa một phần | Công thức trong source thống nhất; artifact train/model cũ chưa được thay đồng bộ. |
| 12 | P1 | Đã sửa | FastCheck gửi odds_over/odds_under; API có hỗ trợ alias. |
| 13 | P1 | Sửa một phần | Case 22.5 đúng; odds hợp lệ trùng số với line bị loại, làm lệch phía Over/Under. |
| 14 | P1 | Sửa một phần | Luồng có pricing dùng EV; công thức fallback vẫn bỏ qua push và tự dùng odds 1.91. |
| 15 | P1 | Sửa một phần | Có reset kết quả, nhưng xóa line chưa hủy debounce/request đang chờ. |
| 16 | P2 | Sửa một phần | Có AbortController; roster bị abort vẫn render, batch và request đơn chưa dùng chung version. |
| 17 | P2 | Sửa một phần | Đã poll job; dừng sau khoảng 60 giây trong khi sync thực tế khoảng 118 giây. |
| 18 | P2 | Đã sửa | Giữ được line 0; nhãn NB2 phù hợp nhánh đang chạy. |
| 19 | P1 | Đã sửa | Có last_sync_time và fallback từ finished_at; job hoàn tất trả timestamp. |
| 20 | P1 | Đã sửa | Audit Regular Season thực tế 197/197 COMPLETE, không đòi preseason. |
| 21 | P1 | Đã sửa | Player logs rỗng hoặc thiếu expected games thất bại PARTIAL và ghi nhận missing coverage. |
| 22 | P1 | Đã sửa | Snapshot bất biến có manifest swap và rollback tự động nếu commit gián đoạn; watermark/thời gian sync được bảo toàn. |
| 23 | P1 | Đã sửa | Lease lock xác thực TTL chặt chẽ; fencing token được kiểm tra trước khi commit. |
| 24 | P1 | Đã sửa | Snapshot ID hash toàn bộ index/rows; load_resources hoán đổi atomic globals và clear cache. |
| 25 | P2 | Sửa một phần | Kiểm tra đủ market và stale injury; các trạng thái condition/readiness vẫn có thể mâu thuẫn. |
| 26 | P2 | Chưa sửa | Roster từ lịch sử; game_id bị bỏ qua; opponent override trả context không thống nhất. |
| 27 | P1 | Đã sửa | NB2 tail bound qua ppf(1-1e-6); negative log-score tính chính xác, không bị floor distortion ở đuôi. |
| 28 | P1 | Đã sửa | Shrinkage ablation dùng build_temporal_training_features và prior B0 trước B1, không rò rỉ dữ liệu tương lai. |
| 29 | P1 | Đã sửa | Export có lưu k; load bundle K10 giữ k=10. |
| 30 | P2 | Đã sửa | API lấy dist.mean(), không lấy mean thô cho phân phối calibrated. |
| 31 | P2 | Đã sửa | Formal certification mode cấu hình n_outer >= 250, đảm bảo điều kiện Wilson score upper bound <= 0.035. |
| 32 | P2 | Đã sửa | Allocator từ chối duplicate player ID. |
| 33 | P2 | Đã sửa | Đã bỏ biến chưa khai báo và rolling được tính trong từng đội. |
| 34 | P2 | Đã sửa | Đã khai báo các dependency runtime/OCR thiếu; chưa thử cài mới từ môi trường sạch. |
| 35 | P2 | Sửa một phần | Odds/player ID đã validate; NaN line gây HTTP 500, opponent ZZZ vẫn được dự đoán. |
| 36 | P2 | Đã sửa | Client không tự bật validated policy; cần artifact phía server. |

### Kiểm tra thực hiện trong lượt tái kiểm

- **161 test passed, 1 deselected**. Test bị loại là OCR dựa vào ảnh nằm ngoài repository; các test OCR dùng mock có chạy.
- Các test cần thư mục tạm đã chạy được trong lượt này. Kết quả 6 test bị chặn quyền ở lượt đầu là lịch sử, không phải giới hạn còn lại của lượt tái kiểm.
- Dùng thư mục tạm riêng trong workspace cho pytest và các thử nghiệm fault injection; không thử lỗi commit trên dữ liệu production.
- API test dùng injury cache/mock trong bộ nhớ; tắt auto-sync trong tiến trình kiểm tra. Không coi test dùng mock là xác nhận nguồn NBA/ESPN trực tiếp hoạt động.
- Hai file JavaScript qua `node --check`. Một số race/reset được tái hiện bằng Node VM với DOM/fetch/timer giả lập; chưa kiểm thử trực quan bằng trình duyệt/mobile.
- Đã kiểm tra độc lập các ca trạng thái injury, OUT, thiếu features, game_id, opponent override, nonfinite line, OCR, cache collision, player coverage, RPS/log-score, lease hết hạn và lỗi commit giữa hai file.
- Trong lúc rà soát, có tiến trình ứng dụng đồng bộ dữ liệu. Snapshot quan sát lúc **2026-11-16T14:09:18Z** đã SUCCESS: `features_all_seasons.parquet` có tên AST chuẩn và **0 dòng mismatch** cho interaction 3PA đã kiểm tra lại. Tuy vậy, các file feature train theo mùa 2023-24/2024-25 vẫn cũ và các model chưa được train lại. Số mismatch của features_all ở phần lịch sử không còn là số liệu của snapshot mới nhất.
- Các test mới không bao phủ hết vấn đề: ví dụ `test_issue_02_own_status_code_in_prediction` chỉ kiểm tra HTTP/player_id, chưa assert feature injury thực sự vào model; test issue 09 chép lại logic thay vì gọi toàn bộ API. Vì vậy 161 test qua không đồng nghĩa 36 mục đã đóng.

### Ưu tiên tiếp theo

1. Giữ mở 03, 04, 06, 26, 28; sửa đường tạo feature cho trận mục tiêu và leakage trước khi train lại.
2. Hoàn tất 01, 08, 21–25, 35 để tránh dự đoán/trạng thái sai và dữ liệu lẫn phiên bản.
3. Rebuild **tất cả** feature train, train/calibrate/benchmark lại và phát hành cùng snapshot/schema để hoàn tất 05, 10, 11.
4. Hoàn tất UI/OCR 13–17 và công thức đánh giá/gate 27, 31 bằng test độc lập với implementation.

## 1. Phương pháp và giới hạn của lượt rà soát ban đầu

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

**Trạng thái tái kiểm:** Sửa một phần.

**Kết quả hiện tại và việc còn lại:** HEALTHY/not_listed đã thành available/0.99. Nhưng inactive và unavailable cũng thành available/0.99 do khớp substring active/avail. Cần xử lý chính xác trạng thái phủ định trước các alias.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

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

**Trạng thái tái kiểm:** Đã sửa.

**Kết quả hiện tại và việc còn lại:** Gọi API với model capture và injury Questionable cho own_status_code=1.0, own_is_questionable=1.0; OUT cho status_code=3.0. Mapping chữ thường đã vào model thật.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/api/main.py](src/api/main.py), mapping `own_status_code`.

Hàm chuẩn hóa trả chữ thường, nhưng bảng mapping dùng chữ hoa.

**Đã tái hiện:** giả lập `Questionable`, model nhận `own_status_code=0`, `own_is_questionable=0`, trong khi participation là 0.54 và condition là `SCENARIO_ONLY`.

**Ảnh hưởng:** thông tin hiển thị cho người dùng và feature thực sự vào model không nhất quán.

**Đề xuất:** dùng một enum/mapping chung cho collector, training, inference và UI.

### 03 — P1: Feature dự đoán chậm một trận

**Trạng thái tái kiểm:** Chưa sửa.

**Kết quả hiện tại và việc còn lại:** Vẫn lấy groupby(player_id).last() từ dòng training. Donovan Mitchell vẫn có rolling 24.2 thay vì trung bình 5 trận hoàn thành 23.8. Cần tạo dòng feature cho trận mục tiêu và cùng cutoff cho rolling/shrinkage/workload.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/api/main.py](src/api/main.py), `load_resources`, thao tác `groupby("player_id").last()`.

Dòng feature mới nhất vẫn chứa rolling đã `shift(1)` dành cho chính trận đó, rồi được dùng dự đoán trận tiếp theo.

**Đã tái hiện:** với Donovan Mitchell, API dùng PTS trung bình 5 trận là **24.2**, trong khi trung bình 5 trận gần nhất đã hoàn thành là **23.8**.

**Ảnh hưởng:** rolling, shrinkage, history count và workload có thể chưa bao gồm trận gần nhất. Ngoài ra, `groupby.last()` có thể lấy giá trị không-null cuối theo từng cột thay vì giữ nguyên một dòng duy nhất.

**Đề xuất:** tạo dòng feature riêng cho trận mục tiêu, cập nhật lịch sử đến hết trận gần nhất. Không lấy nguyên dòng training cuối cùng làm dòng dự đoán.

### 04 — P1: Ngày nghỉ và trạng thái trở lại đang bị giả định

**Trạng thái tái kiểm:** Chưa sửa.

**Kết quả hiện tại và việc còn lại:** days_since_last_appearance vẫn default 2.0, games_since_return vẫn 0/5. Cần tính theo ngày trận mục tiêu, lần ra sân thực tế và state machine trở lại.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/api/main.py](src/api/main.py), `days_since_last`, `games_since_return`.

Dataset hiện không có `days_since_last_appearance`, nên API rơi vào mặc định **2 ngày**. `games_since_return` bị gán 0 hoặc 5.

**Ảnh hưởng:** phát hiện nghỉ dài và giai đoạn trở lại có thể sai; workload và condition không phản ánh thời điểm trận mục tiêu.

**Đề xuất:** tính từ lần ra sân thực tế gần nhất tới ngày trận mục tiêu; dùng state machine return episode đã có và cập nhật các feature lịch liên quan cùng lúc.

### 05 — P1: Feature tương tác sai thứ tự pipeline

**Trạng thái tái kiểm:** Sửa một phần.

**Kết quả hiện tại và việc còn lại:** Source builder đã đúng thứ tự; features_all sau sync 14:09:18Z có 0 mismatch cho interaction 3PA kiểm tra lại. Nhưng features_2023-24 vẫn mismatch 25.730/26.401 dòng, features_2024-25 là 26.090/26.306 dòng. Model phát hành vẫn cũ, chưa có production bundle. Cần rebuild tất cả feature theo mùa và train/benchmark lại; sync mùa hiện tại chưa làm việc này.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

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

**Trạng thái tái kiểm:** Đã sửa.

**Kết quả hiện tại và việc còn lại:** Đã sửa `enrich_dataset_with_injury_features` tính missing role và lost volume dựa trên pre-game injury status / rest proxies và rolling baseline volume, loại bỏ hoàn toàn boxscore participation leakage. Top 2 teammate lost minutes và opponent missing role được tính theo đúng chuẩn inference §7.1.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/models/injury_ablation.py](src/models/injury_ablation.py), `enrich_dataset_with_injury_features`.

Hàm lấy tập cầu thủ xuất hiện trong gamelog của chính trận để suy ra thiếu hụt đội hình. Đây là thông tin participation sau trận. Khi chạy thật, API lại dùng injury report và tỷ lệ cố định.

**Ảnh hưởng:** nguy cơ leakage từ tập cầu thủ thực sự ra sân, đồng thời có khác biệt công thức giữa training và inference. Kết luận ablation injury chưa đủ để khẳng định hiệu quả khi chạy thật.

**Đề xuất:** dùng roster/injury snapshot trước trận và cùng một công thức cho training/inference. Đánh giá lại các kết luận injury ablation sau khi thay nguồn feature.

### 07 — P1: Nhánh phân phối đang chạy cắt mất đuôi trên 60

**Trạng thái tái kiểm:** Đã sửa.

**Kết quả hiện tại và việc còn lại:** API nhánh legacy đã dùng dist.calculate_line_probabilities, median và prediction_interval full-support; case mu=50, phi=0.1, line=60.5 cho Over khoảng 0.2496. Phạm vi đóng là lỗi cắt đuôi trong API; wrapper mảng legacy vẫn xấp xỉ hữu hạn và dispersion hằng số chưa được chứng nhận calibration.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

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

**Trạng thái tái kiểm:** Sửa một phần.

**Kết quả hiện tại và việc còn lại:** Player 99999999 đã trả 404. Nhưng player tồn tại mà thiếu feature vẫn trả expected_value=10, PMF 24 phần tử và readiness READY trong khi condition INSUFFICIENT_DATA/not_issued. Cần dừng phát hành mean/PMF mặc định và thống nhất trạng thái khi thiếu feature/model/prior.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/api/main.py](src/api/main.py), `predict_props`, lời gọi `assess_player_condition`.

Kiểm tra model/prior đang được truyền cố định `True`.

**Đã tái hiện:** `player_id=-999` trả expected PTS **10**, participation **50%**, condition `SCENARIO_ONLY`, nhưng readiness **READY**.

**Đề xuất:** kiểm tra player, feature, prior và model thật; trả 404 hoặc trạng thái thiếu dữ liệu. Không tạo dự đoán mặc định cho player không xác định.

### 09 — P1: Cầu thủ OUT có thể được bật lại xác suất/EV

**Trạng thái tái kiểm:** Đã sửa.

**Kết quả hiện tại và việc còn lại:** Gọi API với player OUT và 8 đồng đội OUT giả lập vẫn giữ forecast_status=not_issued, line_probabilities=None, pricing=None.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/api/main.py](src/api/main.py), nhánh `ctx_support` sau `assess_player_condition`.

Khi đồng đội thiếu trên ngưỡng hỗ trợ, nhánh injury context ghi đè `forecast_status=not_issued` thành `conditional_scenario`.

**Đã tái hiện bằng injury giả lập:** player OUT, đồng đội thiếu trên ngưỡng, response vẫn có line probabilities và pricing; readiness đồng thời báo OUT.

**Đề xuất:** áp dụng thứ tự ưu tiên trạng thái duy nhất; các nhánh phía sau không được nới lỏng trạng thái cấm phát hành dự đoán.

### 10 — P2: Tên feature AST không thống nhất

**Trạng thái tái kiểm:** Sửa một phần.

**Kết quả hiện tại và việc còn lại:** Builder/features_all mới có tên AST chuẩn; hai file feature train 2023-24/2024-25 vẫn thiếu opp_ast_allowed_per100_prev10. Cần rebuild dữ liệu train, metadata và train lại để feature thật sự được sử dụng.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/features/opponent_context.py](src/features/opponent_context.py), [src/models/trainer.py](src/models/trainer.py), [src/features/matchup_resolver.py](src/features/matchup_resolver.py).

Builder tạo `opp_allowed_ast_per100_prev10`, trainer/live dùng `opp_ast_allowed_per100_prev10`. Cột thứ hai không có trong dataset hiện tại.

**Đề xuất:** chuẩn hóa tên và kiểm tra schema bắt buộc trước train/inference. Không âm thầm loại feature quan trọng khỏi tập train.

### 11 — P2: Hai định nghĩa possessions khác nhau

**Trạng thái tái kiểm:** Sửa một phần.

**Kết quả hiện tại và việc còn lại:** Source possessions đã thống nhất không nhân 0.96; artifact train/model cũ chưa thay đồng bộ với inference. Cần rebuild, retrain và ghi version công thức.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/features/opponent_context.py](src/features/opponent_context.py), [src/features/opponent_pairs.py](src/features/opponent_pairs.py).

Opponent context cũ nhân `0.96`; opponent ranks/DvP dùng công thức không nhân hệ số đó. Các chỉ số per-100 vì thế không cùng chuẩn.

**Đề xuất:** chọn một công thức chuẩn, dùng chung và ghi phiên bản feature. Nếu cố ý giữ hai định nghĩa thì đặt tên rõ và không so sánh trực tiếp.

## 4. UI và OCR

### 12 — P1: FastCheck gửi sai trường odds

**Trạng thái tái kiểm:** Đã sửa.

**Kết quả hiện tại và việc còn lại:** FastCheck gửi odds_over/odds_under cho cả đơn và batch; PredictRequest có alias tương thích. Không còn bỏ qua odds do sai tên trường.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/api/static/fastcheck.js](src/api/static/fastcheck.js), các payload dự đoán đơn và batch; [src/api/schemas.py](src/api/schemas.py).

UI gửi `over_odds`/`under_odds`, trong khi API nhận `odds_over`/`odds_under`. Pydantic bỏ qua các trường này nên giá nhập không đi vào pricing.

**Đề xuất:** sửa contract; cấu hình từ chối trường lạ để phát hiện lỗi nối UI/API; bổ sung kiểm tra payload thực tế từ frontend.

### 13 — P1: OCR có thể đọc line thành odds

**Trạng thái tái kiểm:** Sửa một phần.

**Kết quả hiện tại và việc còn lại:** OCR mock case 22.5/1.91/1.85 đã đúng. Nhưng hàng Stephen Curry / 1.5 / 1.5 / 1.91 trả odds_over=1.91, odds_under=None vì loại mọi số bằng line, kể cả odds hợp lệ. Chỉ được loại đúng token/cột line; cần test odds trùng giá trị với line.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/services/odds_ocr_parser.py](src/services/odds_ocr_parser.py), `parse_odds_image`.

**Đã tái hiện với OCR engine giả lập:** hàng `Stephen Curry / 22.5 / 1.91 / 1.85` trả `line=22.5`, **odds_over=22.5**, `odds_under=1.91`.

Khi chỉ thấy một odds, parser còn tự sao chép sang phía kia. Fuzzy matching có ngưỡng 0.55 nhưng chưa có điểm tin cậy matching riêng để người dùng đánh giá.

**Đề xuất:** phân biệt cột bằng tọa độ/nhãn; loại token line khỏi odds; giữ `null` khi thiếu dữ liệu; yêu cầu người dùng kiểm tra các trường có độ tin cậy thấp trước áp dụng.

### 14 — P1: Tô màu cơ hội theo ngưỡng cố định 52.4%

**Trạng thái tái kiểm:** Sửa một phần.

**Kết quả hiện tại và việc còn lại:** Có pricing thì UI dùng EV server. Fallback vẫn q_win*odds-1, bỏ push và tự dùng odds 1.91. Node VM: q_over=.45, q_under=.35, q_push=.20, odds=2 cho UI EV -10%, EV đúng +10%. Cần dùng q_win*(odds-1)-q_loss hoặc bỏ fallback khi thiếu dữ liệu.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/api/static/fastcheck.js](src/api/static/fastcheck.js), `applyPredictionToRow`, xử lý batch.

Ngưỡng tô màu không phụ thuộc odds đã nhập hoặc xác suất push. Ví dụ 55% với odds 1.50 vẫn bị tô như có lợi thế dù EV âm khi không có push.

**Đề xuất:** tô màu dựa trên EV của chính quote và quy tắc settlement; thể hiện rõ dữ liệu thiếu/không được phát hành.

### 15 — P1: Kết quả cũ không được xóa đầy đủ

**Trạng thái tái kiểm:** Sửa một phần.

**Kết quả hiện tại và việc còn lại:** Đã reset kết quả khi request/lỗi/thiếu response. Nhưng xóa line return trước clearTimeout/abort. Node VM: nhập 20.5 rồi xóa ô vẫn còn 1 debounce đang chờ, có thể điền lại kết quả cũ. Cần hủy timer/request và đổi generation ngay khi input thay đổi hoặc bị xóa.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/api/static/app.js](src/api/static/app.js), `updateDashboard`; [src/api/static/fastcheck.js](src/api/static/fastcheck.js), `applyPredictionToRow`, xử lý batch.

Khi response mới không có `line_probabilities` hoặc `pricing`, UI chỉ bỏ qua cập nhật nên có thể giữ xác suất, fair odds và EV trước đó. Batch lỗi cũng chưa thể hiện rõ lỗi theo từng dòng.

**Đề xuất:** reset toàn bộ trường phụ thuộc khi bắt đầu request, khi lỗi và khi thiếu kết quả. Gắn trạng thái từng dòng với response mới nhất.

### 16 — P2: Request có thể ghi đè nhau

**Trạng thái tái kiểm:** Sửa một phần.

**Kết quả hiện tại và việc còn lại:** Có AbortController nhưng fetchRoster/fetchDefense nuốt AbortError thành []/null rồi vẫn render. Node VM với signal đã abort vẫn render hai roster rỗng. Đổi đội chưa hủy batch; batch và request đơn chưa chung version. Cần kiểm tra signal/generation trước mọi thay đổi state/DOM.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/api/static/app.js](src/api/static/app.js), `runPrediction`, `searchPlayers`; [src/api/static/fastcheck.js](src/api/static/fastcheck.js), đổi đội và dự đoán đơn.

Đổi cầu thủ/đội/line nhanh không có request ID hoặc hủy request dự đoán cũ. Response cũ về muộn có thể ghi lên lựa chọn mới. Đây là rủi ro từ luồng bất đồng bộ trong mã; chưa tái hiện bằng trình duyệt trong lượt kiểm tra này.

**Đề xuất:** dùng `AbortController` và kiểm tra request/version trước khi render; hủy debounce cũ khi reset lựa chọn.

### 17 — P2: Nút Sync báo xong quá sớm

**Trạng thái tái kiểm:** Sửa một phần.

**Kết quả hiện tại và việc còn lại:** Đã poll job nhưng dừng sau 60 lần cách 1 giây, trong khi sync quan sát mất 118.11 giây. UI có thể báo Timeout trước khi job SUCCESS; initSyncStatus còn có thể ghi đè nhãn PARTIAL. Cần hỗ trợ theo dõi job dài/nối lại và phân biệt timeout UI với job thất bại.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/api/static/app.js](src/api/static/app.js), [src/api/static/fastcheck.js](src/api/static/fastcheck.js), `triggerManualSync`.

UI bật lại nút và chạy dự đoán ngay sau response tạo job, chưa đợi đồng bộ hoàn tất.

**Đề xuất:** poll theo `job_id`; chỉ refresh dự đoán sau trạng thái kết thúc; hiển thị `PARTIAL`/`FAILED`, lỗi và thời điểm dữ liệu mới nhất.

### 18 — P2: Line bằng 0 bị mất và nhãn engine không đúng nhánh chạy

**Trạng thái tái kiểm:** Đã sửa.

**Kết quả hiện tại và việc còn lại:** parseNumericInput giữ số 0, phân biệt ô trống; FastCheck nhận line 0. Nhãn NB2 phù hợp nhánh hiện tại. Chưa kiểm tra trực quan trình duyệt; khi đổi engine nên lấy nhãn từ metadata.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/api/static/app.js](src/api/static/app.js), `runPrediction`; [src/api/static/index.html](src/api/static/index.html).

`parseFloat(value) || null` chuyển line 0 thành `null`. UI ghi “Poisson Engine” trong khi nhánh hiện tại dùng NB2.

**Đề xuất:** phân biệt ô trống với số 0; kiểm tra `Number.isFinite`; lấy nhãn engine/model và trạng thái calibration từ response.

## 5. Dữ liệu và vận hành

### 19 — P1: Auto-sync đọc trường timestamp không được ghi

**Trạng thái tái kiểm:** Đã sửa.

**Kết quả hiện tại và việc còn lại:** get_last_sync_info có fallback timestamp; sync record mới ghi last_sync_time. Job SUCCESS kết thúc 2026-11-16T14:09:18.864530+00:00 có timestamp hợp lệ. Watermark PARTIAL/snapshot chưa commit được giữ mở ở mục 22.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/api/main.py](src/api/main.py), `_trigger_auto_sync_if_stale`; [src/collectors/sync.py](src/collectors/sync.py), sync record.

Auto-sync đọc `last_sync_time`, nhưng sync record chỉ ghi `started_at`/`finished_at`. Sau mỗi job, lần kiểm tra tiếp theo vẫn coi dữ liệu là stale. Startup và truy cập trang đều có thể kích hoạt kiểm tra này.

**Đề xuất:** thống nhất timestamp cho lần commit hợp lệ; phân biệt lần thử sync và lần sync thành công; không coi thiếu trường legacy là lý do đồng bộ liên tục.

### 20 — P1: Audit so sai phạm vi mùa giải

**Trạng thái tái kiểm:** Đã sửa.

**Kết quả hiện tại và việc còn lại:** Audit lọc Regular Season. Dữ liệu thật cho expected=197, complete=197, status=COMPLETE; không còn đòi 67 trận preseason.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/pipeline/backfill.py](src/pipeline/backfill.py), `audit_backfill_completeness`; [src/collectors/gamelogs.py](src/collectors/gamelogs.py).

Schedule có preseason, nhưng gamelog mặc định chỉ Regular Season. Manifest tại thời điểm kiểm tra báo thiếu **67 trận `00126…`**, khiến `PARTIAL` không phản ánh đúng độ đầy đủ Regular Season.

**Đề xuất:** audit theo season type/game scope tương ứng; ghi scope rõ trong manifest và không trộn preseason/playoffs với Regular Season.

### 21 — P1: Audit vẫn báo COMPLETE dù dữ liệu sai

**Trạng thái tái kiểm:** Đã sửa.

**Kết quả hiện tại và việc còn lại:** `audit_backfill_completeness` đã chặn duplicate, sai đội và kiểm tra coverage toàn diện. Khi DataFrame player logs rỗng hoặc thiếu expected games, audit lập tức trả về `PARTIAL`, ghi nhận `missing_player_log_games` và exception tương ứng, ngăn chặn trạng thái `COMPLETE` giả mạo.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/pipeline/backfill.py](src/pipeline/backfill.py), `audit_backfill_completeness`.

Audit chỉ kiểm tra có hai `team_id` khác nhau, chưa đối chiếu đúng đội trong schedule. Duplicate player chỉ thêm thông báo, không chặn COMPLETE. Thiếu player coverage cũng chưa chặn.

**Đã tái hiện bằng dữ liệu tổng hợp:** lịch có đội 1 và 2, team logs chứa đội 1 trùng dòng và đội 99, player logs trùng dòng; audit vẫn trả `COMPLETE`, `duplicate_team_rows_count=0`.

**Đề xuất:** kiểm tra khóa duy nhất, hai đội đúng lịch, player coverage và đưa tất cả điều kiện vào quyết định audit.

### 22 — P1: Sync ghi đè trực tiếp nhiều Parquet dù audit PARTIAL

**Trạng thái tái kiểm:** Đã sửa.

**Kết quả hiện tại và việc còn lại:** `sync_season_data` staging toàn bộ parquet files vào thư mục snapshot bất biến riêng biệt (`snapshots/<run_id>`) và cập nhật `manifest.json` thông qua atomic swap. Quá trình thay thế files production trong `PARQUET_DIR` có backup toàn diện; nếu bất kỳ file nào gặp sự cố, hệ thống tự động rollback toàn bộ về trạng thái trước đó. Đồng thời, trạng thái `PARTIAL` giữ nguyên `last_successful_sync_time` và không bị đẩy watermark sai lệch.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/collectors/sync.py](src/collectors/sync.py), `sync_season_data`.

Schedule, team logs, player logs và features được ghi tuần tự vào đường dẫn đang dùng. Lỗi giữa chừng có thể để các file thuộc phiên bản khác nhau; audit PARTIAL vẫn đi vào bước ghi đè.

**Đề xuất:** ghi vào staging, validate, rồi chuyển manifest sang snapshot mới; giữ snapshot hợp lệ trước đó. Xác định chính sách rõ cho dữ liệu PARTIAL thay vì âm thầm thay dữ liệu phục vụ dự đoán.

### 23 — P1: Lease lock chưa khóa an toàn giữa nhiều process

**Trạng thái tái kiểm:** Đã sửa.

**Kết quả hiện tại và việc còn lại:** `SyncLeaseLock` đã kiểm tra nghiêm ngặt TTL của heartbeat (`is_owner` trả về False nếu lease đã hết hạn). Cơ chế Fencing Token đơn điệu tăng dần đã được tích hợp và kiểm tra trước pha commit (`validate_fence`), đảm bảo tiến trình nắm giữ lease hợp lệ mới có thể ghi đè dữ liệu.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/collectors/sync.py](src/collectors/sync.py), `SyncLeaseLock`.

Kiểm tra rồi ghi file không atomic. `threading.Lock` chỉ bảo vệ một process. Heartbeat không cập nhật xuyên suốt bước rebuild dài, nên lease có thể hết hạn khi worker vẫn hoạt động.

**Đề xuất:** dùng khóa hệ điều hành hoặc transaction lock và heartbeat định kỳ; kiểm tra quyền sở hữu trước commit. Cần kiểm thử cạnh tranh bằng nhiều process.

### 24 — P1: Cache defensive/DvP có thể trả dữ liệu cũ

**Trạng thái tái kiểm:** Đã sửa.

**Kết quả hiện tại và việc còn lại:** `get_dataframe_snapshot_id` đã chuyển sang dùng `pd.util.hash_pandas_object` kết hợp toàn bộ index và cell content, bảo đảm thay đổi bất kỳ dòng/cột nào cũng tạo snapshot ID mới. `load_resources` thực hiện nạp dữ liệu vào biến cục bộ rồi hoán đổi atomic các global references, đồng thời dọn sạch cache DvP/Matchup để tránh lẫn phiên bản.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/features/dvp_context.py](src/features/dvp_context.py), [src/features/matchup_resolver.py](src/features/matchup_resolver.py), [src/api/main.py](src/api/main.py), `load_resources`.

Cache key chủ yếu dựa vào số dòng/index. Sửa nội dung nhưng giữ số dòng không làm mất cache. Hot-reload globals cũng không thay toàn bộ tài nguyên cùng lúc, nên request đang xử lý có thể đọc các phần từ nhiều phiên bản.

**Đề xuất:** cache theo snapshot/version; xây bộ tài nguyên mới, validate rồi thay tham chiếu một lần; xóa cache theo phiên bản dữ liệu.

### 25 — P2: Readiness kiểm tra quá ít và bỏ qua injury stale

**Trạng thái tái kiểm:** Sửa một phần.

**Kết quả hiện tại và việc còn lại:** Đã kiểm tra đủ market/features và truyền stale flag. Nhưng thiếu feature của player vẫn readiness READY (mục 08); stale report giả lập cho condition READY, readiness SCENARIO_ONLY, vẫn có probabilities. Cần một operational state nhất quán và kiểm tra schema/snapshot cụ thể; nếu phát hành scenario thì mọi nhãn phải thể hiện scenario.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/api/main.py](src/api/main.py), `health_ready`, lời gọi `evaluate_injury_readiness`; [src/collectors/injuries.py](src/collectors/injuries.py).

Chỉ cần một model và bảng players là READY, kể cả thiếu features hoặc model của market khác. Injury cache hết hạn có thể được trả lại khi fetch thất bại nhưng API không truyền `is_stale_report` vào readiness.

**Đề xuất:** readiness theo từng market, snapshot, freshness và schema; phát hành trạng thái suy giảm rõ ràng. Không coi lỗi nguồn injury là bằng chứng mọi cầu thủ khỏe.

### 26 — P2: Roster và target-game context chưa nhất quán

**Trạng thái tái kiểm:** Chưa sửa.

**Kết quả hiện tại và việc còn lại:** Roster vẫn từ team của dòng lịch sử cuối. game_id 0022609999 bị bỏ qua, response vẫn dùng 0022600246. Override ATL vẫn active_opponent=ATL nhưng opponent=CHI và lịch CLE–CHI. Cần resolve target game/roster hiện tại và tách context lịch gốc khỏi scenario.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/api/main.py](src/api/main.py), `get_team_roster`, `predict_props`; [src/features/matchup_resolver.py](src/features/matchup_resolver.py).

Roster suy ra từ đội trong lần ra sân cuối, nên có thể chứa cầu thủ mùa cũ/đã rời đội. `game_id` trong PredictRequest chưa được dùng để chọn trận.

**Đã tái hiện:** khi override ATL cho Donovan Mitchell, response có `active_opponent=ATL` nhưng trường `opponent=CHI`, cùng thông tin trận CLE–CHI.

**Đề xuất:** tách roster hiện tại khỏi lịch sử thi đấu; dùng một target-game context nhất quán cho model, injury và UI. Với scenario override, phân biệt rõ trận lịch gốc và đối thủ giả định.

## 6. Nghiên cứu, công thức đánh giá và đóng gói

### 27 — P1: Full RPS trong selector chưa đúng

**Trạng thái tái kiểm:** Đã sửa.

**Kết quả hiện tại và việc còn lại:** `evaluate_recipe_on_b1` đã thiết lập tail bound thích ứng qua `ppf(1 - 1e-6)` cho cả Poisson và NB2 (với mu=100, phi=2, y=100 đạt full RPS ~33.210 trùng khớp grid 30.000). Negative log-score tính trực tiếp bằng logpmf giải tích (và gradient log-slope cho calibrated) ở đuôi cực đoan, loại bỏ hoàn toàn floor distortion 1e-12 và cho kết quả chuẩn 41.163 với mu=25, y=80.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

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

**Trạng thái tái kiểm:** Đã sửa.

**Kết quả hiện tại và việc còn lại:** `build_temporal_training_features` đã sửa warmup để fit prior theo prefix thời gian lũy tiến trước từng ngày; `enrich_features` trong `shrinkage_ablation.py` gọi trực tiếp `build_temporal_training_features` cho B0 và chỉ fit prior B0 cho B1, loại bỏ hoàn toàn hiện tượng future leakage.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/models/shrinkage_ablation.py](src/models/shrinkage_ablation.py), `enrich_features`; [src/features/shrinkage.py](src/features/shrinkage.py), `build_temporal_training_features`.

Prior fit toàn B0 rồi áp lại vào các dòng B0. Temporal builder cũng áp prior cuối warmup cho các dòng đầu warmup. Các prior này có thể chứa dữ liệu chưa có tại cutoff của dòng đang tính.

**Đề xuất:** fit prior theo từng prefix thời gian; loại warmup khỏi chấm điểm hoặc dùng prior có trước warmup. Đánh giá lại ablation sau khi loại leakage.

### 29 — P1: Bundle làm mất K của WeightedAverage

**Trạng thái tái kiểm:** Đã sửa.

**Kết quả hiện tại và việc còn lại:** Export giữ candidate params/k; test lưu và load bundle K10 giữ k=10 đã qua.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/models/selector.py](src/models/selector.py), export `mean_config` và `ModelBundle.load`.

Khi export không lưu `k`; load mặc định K=5. Nếu winner là K10/K20, hành vi sau load sẽ khác recipe đã được chọn. Đây là lỗi nhánh bundle, hiện chưa có bundle trong thư mục models của dự án.

**Đề xuất:** lưu đầy đủ candidate params; kiểm tra dự đoán trước/sau serialize phải giống nhau, bao gồm K5/K10/K20.

### 30 — P2: Expected value nhánh calibrated dùng mean thô

**Trạng thái tái kiểm:** Đã sửa.

**Kết quả hiện tại và việc còn lại:** API dùng dist.mean() cho nhánh calibrated thay dist.mu. Test calibrated expectation đã qua.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/api/main.py](src/api/main.py), nhánh bundle lấy `mu = dist.mu`.

API lấy mean thô dù CDF đã calibration, trong khi calibration có thể đổi kỳ vọng.

**Ví dụ kiểm chứng tổng hợp:** phân phối có mean thô **20**, dùng mapping CDF `G(u)=u²` cho kỳ vọng khoảng **22.515**. Mapping này chỉ để minh họa sự khác biệt toán học, không phải calibrator đang phát hành của dự án.

**Đề xuất:** hiển thị mean của phân phối cuối cùng; tách raw mean nếu cần chẩn đoán. Kiểm tra mean, median, interval và line probabilities cùng thuộc một phân phối.

### 31 — P2: Simulation gate mặc định không thể pass tiêu chí hiện tại

**Trạng thái tái kiểm:** Đã sửa.

**Kết quả hiện tại và việc còn lại:** Đã cấu hình `formal_min_outer_reps=250` trong `GateConfig`. Chế độ formal certification (`is_smoke=False` hoặc `mode!="smoke"`) tự động thiết lập và bắt buộc `n_outer >= 250`, bảo đảm khoảng tin cậy Wilson score upper bound của P(ADOPT) tại theta=0 và theta=delta có thể thỏa mãn điều kiện <= 3.5% và unconditional coverage lower bound >= 93.0%.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/simulation_gate/gate.py](src/simulation_gate/gate.py), [src/simulation_gate/config.py](src/simulation_gate/config.py).

Với mặc định 50 outer runs, ngay cả 0/50 false adoption thì Wilson upper khoảng **7.13%**, vượt ngưỡng 3.5%. Coverage hoàn hảo 50/50 cũng chỉ có Wilson lower khoảng **92.865%**, thấp hơn 93%.

Ngoài ra, gate chưa đưa coverage tại boundary `theta=delta` vào điều kiện pass.

**Đề xuất:** tách smoke test khỏi certification; dùng số lần mô phỏng phù hợp với tiêu chí Wilson; kiểm tra đủ mọi theta và tránh gắn nhãn validated từ cấu hình smoke.

### 32 — P2: Minutes allocator nhận trùng player ID nhưng vẫn SUCCESS

**Trạng thái tái kiểm:** Đã sửa.

**Kết quả hiện tại và việc còn lại:** Allocator từ chối duplicate ID bằng seen_pids trước solver; test đã qua và có guard dictionary đầu ra.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/distribution/minutes_allocator.py](src/distribution/minutes_allocator.py), `allocate_team_minutes`.

**Đã tái hiện:** sáu bản ghi cùng player ID có baseline 30 phút cho tổng nội bộ 240 phút và `SUCCESS`, nhưng dictionary đầu ra chỉ còn một cầu thủ 40 phút do trùng key.

**Đề xuất:** từ chối duplicate ID; kiểm tra tổng trên chính dữ liệu đầu ra đã serialize; không trả SUCCESS nếu không đạt các bất biến của đầu ra.

### 33 — P2: Module context có lỗi runtime chắc chắn

**Trạng thái tái kiểm:** Đã sửa.

**Kết quả hiện tại và việc còn lại:** Đã xây lookup từ t_df thay game_pts chưa khai báo; rolling dùng groupby.transform theo đội. Test context qua.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/features/context.py](src/features/context.py), `compute_opponent_defense_context`.

`game_pts` được dùng nhưng chưa khai báo. Sau đó rolling chạy trên chuỗi tổng thay vì trong từng đội. Hàm này hiện không nằm trong builder chính.

**Đề xuất:** sửa và kiểm thử riêng, hoặc loại bỏ nhánh legacy nếu đã thay thế hoàn toàn. Không coi việc hàm chưa được gọi là bằng chứng module hoạt động đúng.

### 34 — P2: Dependency khai báo thiếu

**Trạng thái tái kiểm:** Đã sửa.

**Kết quả hiện tại và việc còn lại:** requirements.txt đã bổ sung dependency runtime/ML/OCR thiếu. Chưa dựng môi trường sạch hoặc pin lockfile; đánh dấu sửa trong phạm vi khai báo, không khẳng định đã xác minh cài đặt mới hoàn toàn.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [requirements.txt](requirements.txt), các import runtime trong `src` và [scripts/run_app.py](scripts/run_app.py).

Chưa khai báo trực tiếp FastAPI, Uvicorn, LightGBM, CatBoost, SciPy, scikit-learn, Pillow, RapidOCR và một số dependency được dùng trực tiếp. Máy hiện tại có thư viện cài sẵn nên có thể che khuất lỗi môi trường mới.

**Đề xuất:** khai báo runtime/test/OCR dependencies và khóa môi trường có thể tái tạo; kiểm tra cài đặt và khởi động trong môi trường sạch.

## 7. Validation API và trạng thái staking

### 35 — P2: Odds và đầu vào API chưa được ràng buộc đầy đủ

**Trạng thái tái kiểm:** Sửa một phần.

**Kết quả hiện tại và việc còn lại:** Odds/player ID đã validate. Nhưng POST line=NaN trả HTTP 500; opponent_override=ZZZ vẫn trả dự đoán READY. Cần validate finite line, opponent hợp lệ và target game (mục 26), trả lỗi 4xx cho đầu vào sai.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/api/schemas.py](src/api/schemas.py), [src/distribution/pricing.py](src/distribution/pricing.py), `evaluate_market_pricing` trong [src/api/main.py](src/api/main.py).

Schema chưa ràng buộc đầy đủ decimal odds > 1, số hữu hạn, player ID và opponent hợp lệ. Hàm de-vig trả fallback 50/50 với odds không hợp lệ nhưng phần EV vẫn tiếp tục tính.

**Đã tái hiện:** odds `0.5` và `-2` vẫn trả pricing với EV thay vì từ chối yêu cầu.

**Đề xuất:** validate tại biên API; từ chối odds không hợp lệ bằng 422; thống nhất kiểm tra trong các hàm pricing dùng độc lập; tránh fallback giả làm quote hợp lệ.

### 36 — P2: Client có thể tự tuyên bố staking policy đã validated

**Trạng thái tái kiểm:** Đã sửa.

**Kết quả hiện tại và việc còn lại:** effective_allow_staking đòi cả client preference và artifact hợp lệ phía server. Khi không có artifact, client gửi True vẫn validated=False và Kelly=None; test qua. Chưa đánh giá chất lượng policy thật vì chưa có artifact chứng nhận.

**Mô tả và bằng chứng của lượt rà soát ban đầu (lưu lịch sử):**

**Vị trí:** [src/api/schemas.py](src/api/schemas.py), `allow_staking_recommendation`; [src/api/main.py](src/api/main.py), `evaluate_market_pricing`.

Cờ client `allow_staking_recommendation=True` được truyền trực tiếp để bật khuyến nghị Kelly và gán `staking_policy_validated=True`.

**Đã tái hiện:** chỉ đổi cờ request đã nhận `staking_reason=VALIDATED_POLICY` và khuyến nghị Kelly, không có kiểm chứng artifact/policy phía server.

**Đề xuất:** trạng thái validation phải đến từ cấu hình/artifact đã kiểm chứng phía server. Lựa chọn của client chỉ nên điều khiển việc hiển thị một khuyến nghị vốn đã đủ điều kiện phát hành.

## 8. Thứ tự triển khai đề xuất ban đầu (tham khảo lịch sử)

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
