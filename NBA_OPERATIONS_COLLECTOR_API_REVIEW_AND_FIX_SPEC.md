# Rà soát và sửa vận hành: Collectors / Sync / API / Dashboard / Rollback

Ngày: 10/11/2026 (giờ Việt Nam)  
Phiên bản: ops_spec_v2 — đề xuất triển khai cho §5 và §13.  
Bằng chứng: đánh giá từ báo cáo agent do người dùng cung cấp; chưa đọc code mới, dữ liệu Parquet, checkpoints, logs hoặc truy cập server trên máy người dùng. Không xác nhận localhost đang chạy, dữ liệu đầy đủ hay production ổn định.

## 1. Kết luận và thứ tự sửa

Giữ các hướng tốt: IDs dạng chuỗi, chuẩn hóa minutes, phân biệt DNP/null/zero, checkpoint/raw cache, API đọc dữ liệu đã chuẩn bị, distribution object vô hạn và atomic ModelBundle.

Nhưng một status SUCCESS, số rows hoặc trang web chạy được chưa chứng minh vận hành đúng. Cần điền các contracts sau:

| Mức | Vấn đề trong báo cáo | Sửa bắt buộc |
|---|---|---|
| P0 | 0.6 giây/request được gọi an toàn/chống chặn | Không có quota guarantee; global throttle, retry/circuit breaker có giới hạn |
| P0 | Backfill COMPLETED từ tổng số rows | Đối chiếu expected game IDs theo season_type/status, đủ2 phía và player coverage |
| P0 | Sync lúc startup được gọi đồng bộ liên tục | Thêm scheduler/worker có single-owner lease, watermark và forecast deadline |
| P0 | 94 injuries/29 teams được coi live completeness | Audit submission/completeness, timestamps và teams có0 rows vs chưa thu được |
| P0 | ESPN feed thay nguồn official mặc định | Source variant/priority và archive-as-of phải rõ, không backfill bằng current feed |
| P0 | EV/Kelly tự động từ nhập odds | EV có điều kiện/settlement rõ; stake recommendation phải có policy validation riêng |
| P0 | DNP Void mô tả theo0 giây | Dùng verified entry và book rules; minutes rounding0 không chứng minh DNP |
| P0 | ModelBundle loại bỏ hoàn toàn mismatch | Bundle giảm rủi ro; cần schema/hash/adapter/runtime checks và atomic activation thật |
| P1 | Health chỉ tiến trình/cache | Tách liveness/readiness/data freshness/model/data coverage và operational alerts |

File này không tự thay collector cadence, tạo automation hoặc kích hoạt betting. Các lịch/thresholds bên dưới là recipe đề xuất phải được code/config/version.

## 2. Data normalization và lưu raw

### 2.1. IDs và minutes

`game_id` giữ string từ nguồn; validate format theo league/endpoint, không tự pad một integer đã mất provenance rồi coi ID đúng. Không build ID từ số trận giả định.

ISO duration `PT36M22.00S` tương ứng `36+22/60=36.366666...` phút. 36.37 chỉ là display rounding; **không làm tròn2 decimals trước feature/exposure/train**. Giữ raw duration và parsed seconds, support fractional seconds/giờ nếu parser library hỗ trợ, reject malformed string thay vì trả0.

`played`, minutes, DNP reason và stat fields độc lập: played0/DNP khác played1,minutes>0,PTS0; played1 nhưng minutes parse0 do rounding phải unresolved hoặc dùng raw seconds đúng. Không infer DNP từ points0 hoặc min==0 duy nhất.

### 2.2. Raw archive không chỉ cache

Cache dùng giảm request; raw archive dùng replay/audit và phải append/version. Mỗi response lưu endpoint/provider, params, package/schema version, HTTP status, published_at nếu có, fetched_at, content hash và request_id. Canonical cache key gồm season/season_type/game/params, không chỉ endpoint name.

Thư mục `.nba_api_docs/` agent báo đang dùng cần xác minh chứa docs hay response cache. Tách config `docs_cache`, `response_cache`, `raw_archive`; không coi xóa cache docs đồng nghĩa được phép xóa archive/prediction lineage.

Raw response cũ không ghi đè khi có stat corrections. Canonical tables có version/effective/observed times phù hợp. Historical data tải hôm nay ghi `revised_history_backfill`, không tự tạo first_seen_at trong quá khứ.

## 3. Backfill completeness: đối chiếu IDs, không chỉ counts

Agent báo1.396/1.400 schedule rows trong khi2.460 team logs/mùa. Hai số này không cùng population nếu schedule chứa preseason/play-in/playoffs, postponed placeholders hoặc duplicates. **Chưa đủ thông tin kết luận thiếu hoặc đủ dữ liệu.**

Gọi G_expected là tập canonical game IDs đã completed trong phạm vi đã khóa (mùa, league, Regular Season, as-of audit time), từ schedule được đối chiếu với authoritative game listing:

`G_seen=unique completed game IDs trong team/player datasets`;

`G_missing=G_expected−G_seen`, `G_unexpected=G_seen−G_expected`.

Theo từng game g cần:

- Đúng2 team rows unique `(game_id,team_id)`, IDs trùng hai phía schedule và không cùng một team.
- Player rows unique `(game_id,player_id)`; team_at_game đúng; played/roster/box-score reconciliation có nguồn.
- Totals cho fields áp dụng đối chiếu player sums với team totals, có tolerance/exception log (ví dụ team rebounds không luôn bằng tổng player rebounds). Không bắt mọi box-score quantity có identity cộng đơn giản.
- Critical fields counts/seconds finite và parse pass; optional fields thiếu có coverage flags riêng.
- Lưu season_type/status và exclusions: cancelled/postponed/unplayed, chưa mature, non-Regular-Season; không dựa riêng prefix ID khi nguồn phân loại phức tạp.

2.460 team rows bằng1.230 games chỉ khi unique đúng2 rows/game. Nó chưa chứng minh đủ player stats hoặc tất cả games được lấy đúng scope. 308 team rows hiện tại tương ứng154 games dưới cùng điều kiện, không tự chứng minh3.479 player rows complete.

### 3.1. Khi nào COMPLETED

Theo endpoint/dataset scope, chỉ set complete khi G_missing rỗng, duplicates/conflicts0 chưa giải quyết, schema/critical parses pass và reconciliation đã giải quyết/ghi accepted exceptions. Nếu advanced/injury/roster chưa backfill được, ghi completeness riêng, không để overall COMPLETED che phần thiếu.

Output coverage report cần expected/observed game IDs, missing/extra IDs, per-game team counts, player coverage, optional-field missingness và raw/checkpoint hashes. Checkpoint là tiến trình, không tự là bằng chứng coverage.

## 4. HTTP client: throttle, retry và circuit breaker

Hướng dẫn nba_api khuyên một request mỗi lần, pause khoảng1 giây và cache; đó không phải SLA/quota chính thức [1]. Default đề xuất chuyển NBA stats pacing tối thiểu1 giây giữa starts, configurable theo provider. Không gọi0.6 giây là mức chống chặn được bảo đảm.

- Một global queue/rate limiter cho provider trên máy, không chỉ semaphore trong mỗi FastAPI worker.
- Connect/read timeout cấu hình rõ; v1 connect10s/read30s. Mỗi logical request tối đa3 attempts tổng, không3 retries cộng request đầu nếu report không nói rõ.
- Backoff trước retry2/3:2s và5s, thêm jitter Uniform[0,0.5s], đồng thời respect Retry-After nếu lớn hơn. Không cộng request song song chỉ vì client timeout.
- Retry transient timeout/network/5xx có giới hạn; 429 pause/circuit theo provider. 403/block/schema drift dừng batch để audit, không retry vô hạn.
- Circuit default mở khi3 transient failures liên tiếp hoặc429/403 rõ; cooldown ít nhất10 phút hoặc Retry-After nếu dài hơn. Một probe sau cooldown; thành công mới resume. Thresholds là vận hành đề xuất, không nguồn NBA bảo đảm.
- HTTP200+empty data cần phân biệt no-games hợp lệ/wrong params/schema/parser fail; endpoint object construction có thể gửi request, phải audit không tạo request kép.

Log attempts/cache_hit/retry_wait/HTTP/parse outcome; duration5.21s có thể chủ yếu là cache/no-change, không là bằng chứng đã tải full season hoặc live freshness.

## 5. Scheduler, worker và sync state machine

Startup hook/lifespan chỉ là lifecycle [2], không thay scheduler. API restart không nên tự chạy backfill dài và không để mỗi worker khởi động cùng collector.

P0 đề xuất: API load last valid bundle/snapshot, enqueue bootstrap sync nếu cần; một worker/scheduler riêng sở hữu provider jobs. Single-owner lease có heartbeat, run_id, expiry và fencing/version token để process mất lease không commit dữ liệu cũ.

`QUEUED → RUNNING → VALIDATING → COMMITTING → SUCCESS/PARTIAL/FAILED`.

Chỉ tăng committed watermark sau write+validation commit. Một endpoint failure không rollback dữ liệu hợp lệ đã commit ở partition khác, nhưng status phải PARTIAL và affected scopes rõ.

### 5.1. Job cadence khởi đầu

| Job | Cadence/default đề xuất | Giới hạn |
|---|---|---|
| Schedule | 6 giờ/lần; mỗi15 phút khi có trận trong12 giờ tới | Kiểm tra hoãn/đổi giờ và cutoff revision |
| Official injury snapshots | 15 phút trong12 giờ trước các trận theo dõi tới cutoff | Cache/hash, giữ team submission state |
| Results incremental | 15 phút khi còn games đã/đang kết thúc chờ ingest | Không gọi website khi người dùng mở dashboard |
| Corrections reconciliation | Daily, replay7 ngày gần nhất | Không ghi đè forecasts cũ; lưu stats revision |
| Prediction | Một job/cầu thủ-game-market/bundle tại cutoff60 phút | Source availability deadline và idempotency |
| Weekly refit | Thứ Hai00:00 UTC =07:00 giờ Việt Nam | Label age≥48h, windows đúng protocol |

Cadence không hứa source update đúng mỗi15 phút hoặc data mature đúng48h. Publication/availability thực tế vẫn kiểm tra. Máy offline bỏ lỡ cutoff không được backdate forecast; chạy lại ghi `late_replay`, không prospective.

### 5.2. Manual sync API

`POST /api/sync/run` enqueue job trả202+job_id; duplicate request có idempotency key trả job hiện có, không chạy hai batch. Không chạy collector dài trên event loop hoặc mỗi request /predict. Nếu lock đang held, trả existing run/status rõ, không reset lease tùy ý.

Khi app chỉ chạy cá nhân, bind127.0.0.1 và kiểm tra Origin/allowed hosts cho mutation endpoints phù hợp. Nếu mở LAN/public, manual sync/model activation là admin operations cần authorization và rate limit; không gọi localhost app là public production deployment đã hardened.

## 6. Watermarks, freshness và status chính xác

`latest_game_date` không phải freshness theo mọi nguồn. Có thể mới nhất ngày9/11 nhưng thiếu nhiều games cùng ngày hoặc injury chưa cập nhật.

Status cần có:

```json
{
  "run_id": "example-only",
  "status": "PARTIAL",
  "started_at": "2026-11-10T00:00:00Z",
  "finished_at": "2026-11-10T00:00:05Z",
  "season": "2026-27",
  "scope": "incremental-results",
  "latest_observed_game_date": "2026-11-09",
  "expected_completed_games": 154,
  "complete_completed_games": 153,
  "missing_game_ids": ["EXAMPLE_MISSING_GAME"],
  "rows_inserted": 20,
  "rows_revised": 3,
  "cache_hits": 4,
  "request_failures": 1,
  "committed_snapshot_id": "example-snapshot"
}
```

Số/IDs trong JSON là schema minh họa, không kết quả audit dữ liệu thật. `complete_completed_games` theo completeness contract, không chỉ có một row/game. expected còn chờ source publication cần classified lag, không hứa complete ngay sau còi kết thúc.

Health endpoints tách:

- `/api/health/live`: process/event loop đáp ứng, không gọi upstream network.
- `/api/health/ready`: bundle loaded/schema pass, usable data snapshot, writable prediction store, worker/lease state và component degradation. Readiness có scope, không đánh một injury feed stale thành app crash.
- Existing `/api/health` có thể wrapper tương thích; status response chứa snapshot/model versions và age, không tiết lộ secrets/raw filesystem.

## 7. Injury ingestion: coverage, nguồn và thời điểm

94 injury rows thuộc29 đội không chứng minh thiếu đúng1 đội: đội còn lại có thể không có rows, không chơi, chưa submit hoặc parse thiếu. Cần matrix theo **scheduled game/team/report**: submitted_complete / zero_entries_verified / unsubmitted / fetch_failed / parse_failed / stale.

NBA Official là primary mặc định theo injury spec; official reports cập nhật trong ngày [3]. ESPN có thể supplementary/source variant nhưng cần URL/schema/raw archive/timestamps và mapping rõ. Không lấy current ESPN state thay historical pregame reports, không đổi nguồn giữa train/inference mà không lineage/version.

`not_listed` chỉ khi report đúng trận, team đã submit và parse đầy đủ. Không thấy tên trong một feed lỗi không bằng available. Injury age policy kế thừa6 giờ max tại cutoff; conflict/late report quan trọng→scenario_only theo injury policy, không âm thầm dùng stale report.

Minute limits cần public timestamp và verification riêng, hard/soft classification; source injury row không tự chứa limit. π_participate phải là learned/calibrated entry probability nếu được dùng, không map questionable→50% bằng tay.

## 8. Forecast snapshots, cutoff và manual odds

Một forecast gắn immutable input snapshot, data cutoff, model bundle, conditioning và created_at. Actual created_at sau cutoff là late forecast/replay, không gọi prospective đúngcutoff chỉ vì features đã shift.

Idempotency key tối thiểu `(game_id,player_id,stat,data_cutoff,bundle_id,feature_recipe)` cho base distribution; line/odds pricing snapshot là record riêng trỏ tới distribution đó. Cùng PMF có thể query nhiều lines, không retrain/recompute distribution khi người dùng kéo slider.

Schedule đổi giờ: giữ snapshot/version đã biết, policy hủy/reschedule pending prediction rõ. Forecast mới có ID mới, không overwrite forecast cũ. Display timezone Việt Nam riêng; cutoff timestamp UTC canonical, league game date dùng lịch NBA theo opponent/schedule spec.

Manual line/odds phải có `entered_at`, optional source_quote_time, book, market, line và rule profile. Odds nhập hôm nay không tự thành timestamp trướccutoff, không được đưa vào paired market benchmark hoặc H inputs như same-cutoff nếu không đủ evidence. Có thể tính pricing hypothetical ở quote đó nhưng gắn label đúng.

## 9. Odds, de-vig, EV và Kelly: output policy

### 9.1. Odds conversion và matching

American odds a>0: `d=1+a/100`; a<0: `d=1+100/|a|`. a0 invalid; P0 UI nhận standard American |a|≥100, các định dạng khác phải normalize explicit. Decimal d phải finite và>1.

De-vig multiplicative: `r_O=(1/d_O)/(1/d_O+1/d_U)`, r_U=1−r_O. Hai phía phải cùng line/book/rules và quote window. Nếu không matching, không gọi đó là de-vig của một market. Overround có thể≤0 ở underround/promo; flag audit, không dùng câu “đã loại phế nên biết xác suất thật”.

### 9.2. Conditional/unconditional settlement

Final stat PMF theo A=entered. q_O/q_U/q_P sum1. Chỉ dưới rules DNP void, đã vào sân đều settled, không void khác:

`p_O=π q_O`, `p_U=π q_U`, `p_P=π q_P`, `p_void=1−π`.

DNP xác định bằng verified participation, không raw minutes rounded0. Hoãn/hủy, starter requirements hoặc injury protection cần settlement map riêng. Không gán generic DNP Void cho mọi book. Rule profile không hỗ trợ→unconditional probabilities/EV=null với reason, vẫn có thể xuất conditional PMF có nhãn.

EV per unit stake với push/void hoàn tiền toàn bộ:

`EV=p_win(d−1)−p_loss`.

Đây là model-implied EV tại quote/rules, không empirical expected profit đã xác nhận. Gọi nó “model EV”, không “lợi nhuận chắc chắn”. Scenario_only hoặc insufficient_data không tự phát EV/recommendation theo state policy; không cho client bypass chỉ bằng field `force=true`.

### 9.3. Kelly không tự là production staking policy

Cho một bet độc lập được xét riêng, return win b=d−1, loss−1, refund0 và probabilities được coi là biết:

`g(f)=p_win log(1+bf)+p_loss log(1−f)`.

Nếu p_win+p_loss>0, unconstrained optimum:

`f*=[b p_win−p_loss]/[b(p_win+p_loss)] = (d r−1)/(d−1)`, r=p_win/(p_win+p_loss).

Không dùng p_win unconditional trực tiếp trong công thức binary khôngrefund `[(d p−1)/(d−1)]`. Nếu p_win+p_loss0 thì g không phụ thuộc f dưới mô hìnhrefund, operational stake0/null, không chia0. f*<0 nghĩa không có positive-stake optimum ở phía này; f=1 chỉ là mathematical boundary, không recommendation bankroll.

Kelly giả định probability/return model đúng cho bài toán log-growth [4]; uncertainty/model error, many correlated bets, parlay và portfolio exposure không tự được xử lý bởi formula một bet. Fractional Kelly tùy ý không chứng minh risk đã calibrated.

Default đề xuất: **ẩn stake recommendation**, `kelly_recommendation=null`, reason `STAKING_POLICY_UNVALIDATED`; có thể hiển thị công thức trong chế độ diagnostics với nhãn mathematical-only nếu người dùng chủ động xem. Muốn bật stake suggestions cần đăng ký policy/limits/exposure/validation riêng. Simulation Gate xác nhận ΔBrier không tự xác nhận ROI hoặc optimal staking.

API tách `forecast_validated`, `market_edge_validated`, `staking_policy_validated`; READY không có nghĩa cả3=true. Không cần chặn mọi stats forecast chỉ vì nghiên cứu market gate chưa hoàn thành.

## 10. API contract và frontend correctness

`/api/players` fuzzy search chỉ tìm candidate names; `/api/predict` nhận player_id+game_id+stat canonical, không silently chọn người có tên gần nhất. Xác minh team/membership tại game/cutoff và market được hỗ trợ.

Pydantic/request validation: finite line/odds, supported market/rules, canonical timestamps, bounded request size và no NaN/Infinity trong JSON. Invalid payload→422 với reason. Chưa có valid bundle/data→503 hoặc domain forecast_status rõ, không HTTP200 với probabilities0 giả.

`/api/predict` đọc committed snapshot/bundle, không gọi NBA/ESPN trong request path. Response có forecast_id, created_at/cutoff, distribution conditioning, source/model/snapshot versions, operational state/reasons, raw mean vs final mean labels, final median/interval policy, prefix+tail và pricing_quote_id.

PMF chart có thể chỉ render prefix70 nhưng phải display tail mass, không normalize prefix bars thành1. CDF/Over/Push ở line>70 vẫn query distribution object. Hiển thị interval90% equal-tail như mô tả là đúng policy, nhưng không claim empirical coverage90% nếu chưa có report.

Frontend null/unknown không render thành0 hoặc READY. OperationalState khác component health và khác model-validation state. Thiếu scenario model/weights thì context diagnostics thôi, không probability/EV giả dưới banner cảnh báo.

## 11. Atomic ModelBundle và rollback đúng nghĩa

Bundle packaging là đúng hướng nhưng **không loại bỏ hoàn toàn mismatch**. Manifest có thể ghi sai feature order, G đúnghash nhưng fit cho mean khác, thiếu prior/minutes adapter hoặc runtime đổi preprocessing.

Mandatory manifest:

- mean model, feature schema/order/dtypes/missing policy và preprocessing code/schema compatibility.
- prior bundle/feature recipe, fitted dispersion/parameterization, learned minutes/participation dependencies nếu dùng.
- G artifact đúng **21 knot pairs** (u_j,c_j), interpolation/mix/regularization settings, hard endpoints và tail/numerical policy; không chỉ21 output values thiếu input knots.
- train/φ/G split hashes, code/package versions, validation report, supported population/rule profiles, bundle_id/hash/activation.

Activation: download/build vào staging→verify all hashes/schema and smoke predictions→load toàn bundle in memory→atomic pointer swap. Request đang chạy giữ reference bundle cũ tới khi xong; không trộn mean mới/G cũ trong cùng request. Failure staging giữ last valid active bundle.

Data snapshots commit riêng bằng immutable files+manifest, atomic pointer update. Prediction pin cụ thể `(bundle_id,data_snapshot_id)`; model/data pointer không phải một transaction chung trừ khi có explicit compatible-pair registry. Data schema incompatible→ready false cho pair, không tự chọn adapter không có trong manifest.

Rollback: activate **nguyên compatible bundle** và compatible feature adapter/prior, verify lại với snapshot hiện tại; nếu schema không compatible thì dùng compatible data/feature snapshot hoặc stop affected forecasts. Không tự rollback DB/history bằng xóa data mới. Không sửa predictions cũ thành outputs rollback model.

Weekly refit bundle chỉ activate sau job checks; nếu2 scheduled refit failures liên tiếp thì dừng primary forecasts theo main1.8, không dùng bundle cũ mãi mà vẫn gọi đúng adaptive protocol. Không tự rollback vì thấy vài bets thua hoặc primary score xấu trong B5; quality-driven recipe changes thuộc protocol version mới.

## 12. Monitoring, reconciliation và incident rules

### 12.1. Metrics và ngưỡng vận hành ban đầu

| Signal | Action v1 |
|---|---|
| Critical schema/hash/nonfinite probability/mass accounting fail | Quarantine partition/bundle; stop affected forecast immediately |
| Injury report age>6h tại cutoff hoặc missing submission | scenario_only đúngpolicy, không tựavailable |
| Missing completed games quá3h từ known game_end mà source expected available | DATA_LAG alert, retry theo worker policy; không sửa watermark giả |
| Forecast cutoff missed | Log late/missing; không backdate hoặc đếm prospective coverage |
| Job lease heartbeat mất>2 phút với lease TTL5 phút | Alert; takeover sau expiry bằng fencing, không2 writers |
| Refits fail2 tuần liên tiếp | Halt primary theo protocol; report missing status |
| Calibration/cohort drift diagnostic | Alert/report; không auto tune/rollback dựa B5 paired scores |

Các thresholds3h/2min/5min là operational defaults đề xuất, không source SLA. Nếu thiếu game_end metadata, dùng explicit delayed-data state; không tự giả end=tipoff. Source revisions có thể xuất hiện muộn hơn; late-data alert khác coverage fail vĩnh viễn.

Monitor requests/retries/cache hit, expected-vs-observed IDs, parse failures, last commit/source age, forecast latency/coverage, state distribution, tail/mass errors và bundle age. Liveness200 không được che dữ liệu PARTIAL.

### 12.2. Daily reconciliation

Đối chiếu immutable forecasts với settlement bằng book rules/version; lưu actual stat revision_used và settlement timestamp. Stat corrections tạo evaluation revision, giữ version cũ để audit. Tracking lợi nhuận phải có mọi selected/not-selected decisions theo locked policy, stakes/odds/void/push, không chỉ các bets thắng.

Logs có request/run/forecast/bundle/snapshot IDs để nối chuỗi. Không ghi tokens/auth headers vào logs. Alert dashboard cần người vận hành thấy degraded scopes, không chỉ server terminal.

### 12.3. Backup và recovery

Default checkpoint policy: commit tiến trình sau mỗi batch/partition đã validate; daily backup manifests, predictions, settlement/ingestion logs, active/previous bundles và raw archive index. Có thể tái tải public box scores nhưng **không bảo đảm tái tạo được injury/odds snapshots đã trôi qua**, nên archive này ưu tiên durability.

Chạy restore drill trên bản sao: load previous bundle+feature adapter, recover committed snapshots, verify hashes/prediction ledger và resume checkpoint không duplicate. Khả năng rollback chưa được kiểm chứng nếu chưa thử restore.

## 13. Tests và evidence agent phải cung cấp

- [ ] ISO fractional seconds giữ precision, display rounding không vào model; DNP/played0-point/rounded0 phân biệt.
- [ ] Backfill missing-game/duplicate/wrong-season_type/one-team-row bị phát hiện dù total row counts đẹp.
- [ ] Retry budgets và circuit breaker không loop vô hạn; concurrent startup/manual sync chỉ1 owner commit.
- [ ] API restart không block bởi full backfill; sync async202/jobid, idempotency đúng.
- [ ] Partial job không báo SUCCESS; watermark chỉadvance sau commitvalidation.
- [ ] Injury zero-entries verified khác unsubmitted/fetchfailed; source conflict/stale giữ đúng operational state.
- [ ] Late forecast/quote không backdate; manual odds không trở thành historical market snapshot.
- [ ] American/decimal/de-vig matching, O/U/Push/void và Kelly refund formulas khớp fixtures.
- [ ] EV/Kelly guards enforce ở backend, không chỉẩn frontend.
- [ ] PMF prefix+tail, interval/evaluation conditioning và probabilities từ cùng finaldistribution.
- [ ] Bundle mean/G/schema mismatch stagingfail; in-flight request không đọc nửa bundle; rollback restoredrill pass.
- [ ] Missingdata/modelnotready trả explicitreason/null, không zeros giả và không READY mặcđịnh.

Evidence thực cần code refs, actual scope/coverage report, last runs/errors, request traces, active manifests/hash checks, snapshot freshness và restore test logs. Không từ dòng “hoạt động ổn định” suy ra tất cả evidence đó đã tồn tại.

## 14. Migration theo thứ tự

1. Audit current code/logs/Parquet/checkpoints và verify các counts agent báo, không backfill lại toàn bộ khi chưa biết thiếu gì.
2. Chuẩn hóa raw/versioned snapshots và completeness reports; tách per-source watermarks.
3. Thêm single-owner worker/scheduler, bounded client policy và sync job API; giữ API serve last valid compatible snapshots.
4. Audit injury sources/coverage/timestamps, forecast cutoff/idempotency và operational state guards.
5. Tách model EV diagnostics khỏi staking recommendation; sửa settlement/odds input provenance.
6. Verify bundle loading/activation/rollback+adapters bằng tests/restoredrill; deploy bundleversion mới atomic.
7. Bổ sung health/monitoring/reconciliation; ghi SPECIFIED/IMPLEMENTED/VALIDATED/RELEASED riêng.

Deliverables: code diff/config, coverage manifest, job/retry tests, API contract, forecast/quote ledger, activation/rollback logs và vận hành runbook. Không đổi forecast/statistical recipe đang xác nhận mà thiếu version/revalidation theo main plan.

## 15. Nguồn và giới hạn

1. [nba_api — AI agents guide](https://github.com/swar/nba_api/blob/master/docs/ai_agents.md): constructor/schema/IDs, pacing tuần tự khoảng1s và caching; không bảo đảm quota hoặc endpoint availability.
2. [FastAPI — Lifespan Events](https://fastapi.tiangolo.com/advanced/events/): lifecycle loading/cleanup; không tự là scheduler hoặc exactly-once job execution.
3. [NBA Official Injury Report](https://official.nba.com/nba-injury-report-2026-27-season/): nghĩa vụ báo cáo/cập nhật theo thời gian; không xác minh ESPN feed hoặc coverage archive của ứng dụng.
4. [Kelly (1956), A New Interpretation of Information Rate — Bell Labs](https://www.nokia.com/bell-labs/publications-and-media/publications/a-new-interpretation-of-information-rate/): cơ sở log-growth criterion; công thức win/loss/refund trong file được suy từ objective đã ghi, không benchmark NBA.
5. [Kế hoạch chính](https://chatgpt.com/library?file_id=libfile_277ca19137e08191b2dd587c50debe54&account_id=61294741-651c-40c7-b521-b699e7d014b8).

Các cadences, alert thresholds và API contracts mới là design defaults đề xuất, chưa xác nhận tối ưu hoặc đang triển khai. Số rows, live injury counts và status SUCCESS trong báo cáo chưa được đối chiếu với dữ liệu thực. File không tự chạy collector, truy cập server của người dùng, đặt cược hay bật Kelly recommendation.
