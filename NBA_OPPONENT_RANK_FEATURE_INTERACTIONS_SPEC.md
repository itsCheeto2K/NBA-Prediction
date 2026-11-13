# Opponent Rank & Feature Interactions — đặc tả triển khai NBA player props

Ngày: 13/11/2026 (giờ Việt Nam)  
Phiên bản: opponent_rank_v1 — cấu hình khởi đầu để triển khai và kiểm chứng.  
Phạm vi: team-level opponent stats/ranks và tương tác với feature hiện có cho PTS/REB/AST. Thu thập thêm block context; chưa tự mở market BLK hoặc matchup1-on-1.  
Trạng thái: SPECIFIED; chưa đọc code hiện hành, chạy endpoints trên máy người dùng hoặc xác nhận predictive improvement.

## 1. Mục tiêu và nguyên tắc

Bổ sung bối cảnh đối thủ cho phép bao nhiêu PTS/AST/REB, phòng ngự/rebounding/shot mix và blocks. Cung cấp cả **giá trị thực**, **relative context** và **rank tại cùng cutoff**. Model học cách các yếu tố tương tác, không cộng point/EV bằng tay theo rank.

Hai câu hỏi khác nhau:

- Đội B cho phép đối phương ghi nhiều điểm không? → points allowed của B.
- Đội B tự ghi nhiều điểm không? → points scored của B; có thể liên quan pace/shot volume, nhưng không phải points allowed.

Player i thuộc đội A gặp B: features opponent lấy từ B, nhưng các allowed stats của B phải được dựng từ rows của những đội từng gặp B. Không join nhầm stats tấn công của B thành defensive allowances.

Đây là phần mở rộng kế hoạch opponent/schedule, injury, shrinkage và distribution/selection. Không đổi primary H/S+H, cutoff60 phút hoặc protocol xác nhận. Recipe mới cần version, regenerate features và retrain/recalibrate trước khi release phù hợp.

## 2. Data sources và cách lấy ưu tiên

### 2.1. Ưu tiên dữ liệu local đã có

`LeagueGameLog` cấp đội/box scores → mỗi game có2 team rows. Self-join bằng game_id, khác team_id để có row own/foe. Advanced box scores bổ sung possessions/pace khi có coverage và publication lineage hợp lệ.

Đây là đường ưu tiên cho train/backtest: kiểm soát ngày, window, rank và revision tốt hơn việc lấy bảng season-to-date hiện tại rồi gán ngược quá khứ.

### 2.2. Endpoint dùng đối chiếu/current snapshots

`LeagueDashTeamStats` hỗ trợ MeasureType Base/Opponent/Advanced/Defense, LastNGames, DateFrom/DateTo và PerGame/Per100Possessions theo docs đã đối chiếu trong cuộc trao đổi. Constructor/schema phải kiểm tra trong package cài đặt; các chế độ có thể trả columns khác nhau, không giả expected_data Base chứa mọi OPP_* field.

Base có BLK/BLKA và các rank columns trong tài liệu. Khi dùng Opponent mode, xác minh nghĩa/tên thực của OPP_* và đối chiếu với self-join trước khi đưa vào pipeline. Không coi rank từ provider đã đúng chiều định nghĩa của dự án.

DateTo là filter theo ngày, không chứng minh biết data tại một timestamp cụ thể trong ngày. Nếu cần exact cutoff hoặc xử lý trận cùng ngày/late correction, dùng raw archive/as-of game history. Current aggregate tải hôm nay không tự là archived pregame snapshot.

## 3. Schema, timestamps và invariant

Historical canonical row tối thiểu:

`game_id, team_id, opponent_team_id, season_id, season_type, tipoff_utc, game_end_utc, stat_available_at, pts, ast, oreb, dreb, reb, blk, blka, fga, fgm, fg3a, fg3m, fta, tov, pf, possessions, source_version`.

Target: player_id, current team_id, game_id, opponent_id, prediction_cutoff_utc, feature_recipe_version, prior_bundle_id và schedule_snapshot_id.

Chỉ lấy game đã kết thúc trước cutoff, stat version đã available trước cutoff; target game không có trong input window. Dữ liệu backfill không có archive first-seen phải gắn `revised_history_replay`, không bịa stat_available_at quá khứ.

Invariants:

- Đúng2 unique team rows/game; home/away/team IDs khớp schedule, không cross join trùng.
- Count stats finite, không âm; missing khác0. Không fill null BLK/possessions thành0.
- Kiểm tra own BLKA so với foe BLK, own points so với foe points allowed được dựng; data conflict/correction chưa đồng bộ phải quarantine/audit, không tự sửa nguồn.
- REB family đối chiếu OREB+DREB theo source semantics; team rebounds/box-score exceptions giữ riêng.
- Season Regular Season theo policy; không lẫn Playoffs/Preseason/Cup games không thuộc scope.
- Timezone UTC dùng cutoff; league_game_date cho b2b riêng, không lấy ngày Việt Nam để xếp lịch NBA.

## 4. Possessions: denominator phải đúng phía

Trong trận g, t là đội đang dựng opponent profile, u là đội gặp t. P_tg là offensive possessions của t, P_ug là offensive possessions của u.

Default dùng một possessions recipe cố định cho toàn feature version. V1 có thể dùng proxy từ team box scores:

`P_tg = FGA_tg + 0.44 FTA_tg − OREB_tg + TOV_tg`.

Tính cùng công thức cho u; vì vậy TOV là required nếu chọn proxy mode. Đây là approximate offensive possessions, không exact possession count. P≤0 hoặc required counts missing→rate unavailable, không thay denominator bằng1. Tham số0.44 là working approximation, cần đối chiếu với advanced possession source và sensitivity, không coi mọi FT đều có cùng cơ chế possession.

Có thể đăng ký variant dùng possessions từ advanced dataset nếu coverage/semantics đủ; không mix advanced cho đội này với proxy cho đội khác trong cùng rank table mà không version/audit. Không chỉ gọi endpoint `pace_adjust=Y` rồi coi mọi denominator đã đúng.

Allowed PTS/AST của t chia offensive possessions của u. Blocks made của t cũng chia possessions của u, vì xảy ra lúc t phòng ngự. Stats t tự ghi hoặc bị block chia possessions của t.

Riêng REB/OREB/DREB family v1 dùng cùng `Pbar_g=(P_tg+P_ug)/2` làm **common game-possession normalization** để giữ additive rates. DREB_u phát sinh khi t tấn công, OREB_u khi u tấn công; Pbar không phải exact exposure của từng loại rebound. Rebound shares ở §7 mới tách cạnh tranh cơ hội theo phía. Ghi rõ recipe này khi đối chiếu provider per100, không giả mọi NBA aggregate dùng đúng cùng denominator.

## 5. Core metrics: công thức và đúng nghĩa của block

Window W_t,K(c) là K trận trước gần nhất của **đội t**, có pair data hợp lệ và available tại cutoff c; horizon tối đa365 ngày. P0 K10; P1 K20. Không dùng chung một window10 calendar days thay cho10 appearances của đội.

| Metric key | Tử số Y_tg | Exposure E_tg | Ý nghĩa |
|---|---|---|---|
| `pts_allowed` | PTS_u | P_u | Đội t để đối phương ghi điểm |
| `ast_allowed` | AST_u | P_u | Assists được ghi bởi đối phương |
| `oreb_allowed` | OREB_u | Pbar | Offensive rebounds đối phương, normalized theo common game possessions |
| `dreb_allowed` | DREB_u | Pbar | Defensive rebounds đối phương; phụ thuộc shot misses của t, chưa là opportunity rate |
| `reb_allowed` | REB_u | Pbar | Tổng rebound đối phương, common normalization, chưa điều chỉnh cơ hội cụ thể |
| `fg3m_allowed` | 3PM_u | P_u | 3PT makes đối phương |
| `fg3a_allowed` | 3PA_u | P_u | 3PT attempts đối phương, phản ánh volume/shot mix |
| `fta_allowed` | FTA_u | P_u | Free throw attempts đối phương |
| `blocks_made` | BLK_t | P_u | Blocks t thực hiện khi đối phương tấn công |
| `blocks_allowed` | BLKA_t hoặc BLK_u đã reconcile | P_t | Các cú ném của t bị block |
| `missed_fga` | FGA_t−FGM_t | P_t | Missed field goal volume của t, proxy bối cảnh rebound |

Raw rate per100:

`R_tq,K = 100 Σ_(g∈W) Y_tgq / Σ_(g∈W) E_tgq`.

Không average đơn giản các per-game ratios có exposure khác nhau. P0 weights của team window bằng1; chưa đồng thời mở thêm decay grid. Nếu thay weighted version thì tử/mẫu dùng cùng weights và ghi recipe.

**Blocks made khác blocks allowed:** target player BLK đối đầu đội B thường cần nghiên cứu B bị block/shot volume thế nào, không chỉ B block giỏi ra sao. Với PTS target, B blocks-made là defensive context nhưng không tự suy PTS sẽ giảm theo tỷ lệ tương ứng.

Blocks total không tự là rim protection: có cả zone/assignment khác nhau. Không chia total blocks cho riêng rim attempts rồi gọi là rim block rate. P2 chỉ dùng zone-specific rate khi numerator/denominator cùng zone và nguồn đủ coverage.

## 6. Làm trơn team rates và early-season fallback

Team rank đầu mùa dễ nhiễu. Default shrink raw rates về league rate prior từ permitted training prefix, không mean cuối mùa:

`Rtilde_tq = 100 [ΣY_tgq + τ R0_q/100] / [ΣE_tgq + τ]`.

τ=500 possessions ở v1. R0_q là pooled rate per100 của đúng metric/denominator từ train, tối đa730 ngày, origin trước target/fold, có prior snapshot/version. R0 không fit bằng validation/evaluation outcomes hoặc season-end tables.

Đây là empirical smoothing feature, không posterior uncertainty đúng cho mọi q. Same prior denominator units phải là possessions, không lấy β200 phút của player shrinkage đưa vào τ này.

Personal/team rolling lịch sử vẫn cập nhật as-of; prior parameters theo permitted bundle snapshot. Training priors cần forward snapshots như feature spec, không fit full dataset rồi backfill rows cũ. Không có prior hợp lệ→unavailable, không hard-code một league rate giả.

No games nhưng prior hợp lệ: value=R0, sample_games0, exposure0, prior_weight1. Có data dùng `prior_weight=τ/(τ+ΣE)`. Partial window có sample count; không gắn nhãn đủ10 khi chỉ có3.

Điều kiện tối thiểu prior P0: ≥10000 summed valid possessions và≥20 teams trong permitted training pool cho quantity/family; không đủ thì prior unavailable. Đây là coverage screen vận hành, không theorem sample sufficiency.

REB/OREB/DREB dùng paired-valid subset, cùng exposure/τ/fallback để giữ additive rate identities khi source counts tương thích. FGA/3PA families giữ constraints tương ứng. Không trộn samples khác nhau rồi assert identity sai.

## 7. Các tỷ lệ cơ hội bổ sung: dùng denominator tương ứng

Để tách volume khỏi efficiency, P1 thêm:

- Opponent defensive rebound share: `DREB_t/(DREB_t+OREB_u)` gộp cả window. Cao nghĩa đội t thường giành phần DREB trong nhóm cơ hội được ghi nhận này, có thể liên quan OREB của target.
- Opponent offensive rebound share: `OREB_t/(OREB_t+DREB_u)`; liên quan cạnh tranh DREB của target.
- Assisted field goal share allowed: `AST_u/FGM_u` gộp window; proxy share FGM được kiến tạo, không potential assists hoặc assist probability của target.
- Block rate made: `BLK_t/FGA_u`; block rate allowed: `BLKA_t/FGA_t`. Không gọi hai tỷ lệ này cùng là opponent block rate.
- 3PT accuracy allowed: `3PM_u/3PA_u`; shot-mix allowed: `3PA_u/FGA_u`.

Tỷ lệ có denominator0 để missing, không0%. Các numerator phải thỏa đúng constraints của ratio trước fit. Shrinkage share dùng `(successes+κ p0)/(trials+κ)`, κ100 trials ở v1; p0 fit từ train đúng quantity. Trials là shots/rebound opportunities được định nghĩa, không possessions hoặc minutes tráo đơn vị.

Missed FGA không bằng exact rebound chances: còn FT misses, offensive boards, dead-ball và team rebounds. Dùng tên proxy, không mô phỏng total rebound opportunities như đã biết chắc.

## 8. Rank tại cùng cutoff: giá trị lớn không đồng nghĩa thuận lợi

Tại target cutoff c, dựng rate table cho **mọi đội trong season membership** bằng lịch sử hợp lệ của từng đội tới cùng c. Không dùng mỗi đội ở một timestamp khác nhau hoặc rank hôm nay cho target quá khứ.

Rank P0 dựa Rtilde per100, ascending:

`rank_asc_t = rank(Rtilde_t, method='average', ascending=True)`.

`pct_asc_t=(rank_asc_t−1)/(N−1)`, N là số teams có valid smoothed value; N1 thì pct0.5 kèm flag. Missing prior/value→không tham gia rank, rank/pct missing, report rank_coverage_count/N_expected. Partial coverage vẫn là rank trong subset, **không gắn nhãn hạng/30** nếu chỉ có25 teams.

- pts_allowed rank1: ít points allowed nhất trên quantity/window đã định nghĩa.
- blocks_made rank1: ít blocks made nhất; không phải blocker tốt nhất.
- blocks_allowed rank1: ít bị block nhất.
- Nếu UI muốn “block strength rank1=nhiều blocks nhất”, tạo display field `_rank_desc` riêng, không âm thầm đổi meaning model column.

Equal values dùng average rank, không tie-break bằng team_id để tạo strength giả. All equal→mọi pct0.5; `rank_informative=false`. Các teams chỉ có prior được giữ value/rank nếu prior hợp lệ nhưng có flags no_history/prior_weight1; đó không phải evidence họ thực sự mạnh bằng league average.

P0 model chỉ bật rank features khi rank_coverage_count=N_expected, còn giá trị thật có thể dùng theo missing policy. Report rank universe/count/version. Không cố điền missing teams bằng rank30.

## 9. Feature dictionary và relative context

Mỗi metric q/window K tạo:

```text
opp_{q}_per100_raw_prev{K}
opp_{q}_per100_shrunk_prev{K}
opp_{q}_rank_asc_prev{K}
opp_{q}_pct_asc_prev{K}
opp_{q}_log_relative_prev{K}
opp_{q}_sample_games_prev{K}
opp_{q}_exposure_possessions_prev{K}
opp_{q}_prior_weight_prev{K}
```

`log_relative=log(Rtilde/R0)` khi cả hai>0; missing khi không hợp lệ, không dùng epsilon để giấu invalid prior. Positive nghĩa quantity cao hơn baseline league reference, **không tự là tác động thuận lợi cho mọi stat**.

Base context kèm `opponent_id`, `team_id`, `opponent_snapshot_cutoff`, source/possession_recipe/prior versions, rank universe/coverage, sample age/missing flags. Không cần đưa mọi raw/shrunk/rank variants vào train cùng lúc; all có thể persist để audit, feature manifest chọn subset.

P0 values gồm pts/ast/reb/oreb/dreb allowed, blocks made/allowed, fg3a/fg3m/fta allowed và missed_fga. P1 shares/prev20 mở riêng. Nếu hiện chưa có BLK prediction model, vẫn dùng block context làm inputs PTS/REB/AST; không tự thêm output BLK với model PTS hay preset probabilities.

Rank và numeric value tương quan, không là hai nguồn bằng chứng độc lập. Rank không giữ khoảng cách giữa đội; luôn ưu tiên value khi thiếu rank coverage hoặc rank không thêm lợi ích.

## 10. Tương tác với minutes, rate và vai trò của cầu thủ

P0 direct model:

`μ_is=exp(f_s(player_history,role,minutes_history,injury,schedule,opponent_values,ranks,interaction_candidates))`.

Không dùng `μ_new=μ_old×rank_multiplier` chưa fit. Cây có thể học interactions nhưng cần sample/support và validation, không bảo đảm chỉ thêm columns là tự học đủ.

V1 giữ P0 raw mean model với pooled dispersion đã fit OOF; không cộngφ bằng tay khi gặp opponent rank cực trị. Muốn contextualφ là candidate riêng theo distribution/special-groups specs. Sau feature đổi, refit mean/φ/G theo temporal lineage; không giữ G cũ mặc định.

Nếu P1 minutes–rate mixture: schedule/own role/availability chủ yếu vào minutes model, defense/shot context vào conditional stat/rate; cùng một covariate có thể vào cả hai nhưng toàn marginal phải fit/evaluate. Không coi tác động hai tầng là independent uplifts rồi nhân thêm lần nữa. Predicted minutes feature phải temporal OOF; actual target minutes không làm input P0.

## 11. Các interaction candidates theo stat

Ưu tiên **giá trị và log-relative** cho explicit products; ranks chỉ context bổ sung. Các products là feature hypotheses, không hiệu ứng nhân quả hoặc tỷ lệ adjustment cố định.

### 11.1. PTS

- Player 3PA share × opp 3PM_allowed log_relative: nghiên cứu shooter volume gặp defense3PT; cần cả3PA allowed/accuracy để tách volume và conversion.
- Player FTA rate × opp FTA_allowed log_relative: free-throw context.
- Player interior profile × opp blocks_made log_relative: chỉ khi có interior shot share thật. Chưa có thì dùng `player_two_pa_share × opp_blocks_made_log_relative` với tên **2PT proxy**, không gọi mọi2PT là rim attempt.
- Player FGA/FTA rates, minutes history và own-team pace cùng opp points_allowed/defensive context; không points_allowed rank30→+x điểm.

### 11.2. AST

- Player AST rate hoặc passes/touches khi có × opp AST_allowed log_relative.
- Player playmaking role × opp assisted-FG share allowed.
- Teammate shooting/missing-role context cùng opponent defense; cơ hội chuyền và conversion đều có thể thay đổi. Defender tốt không bắt buộc AST giảm; player có thể chuyền nhiều hơn.

### 11.3. REB

- Player DREB rate × opp missed_FGA log_relative: volume miss của đội đối phương là proxy cơ hội DREB.
- Player OREB rate × `(opp_DREB_share−league_DREB_share_prior)`.
- Player DREB rate × `(opp_OREB_share−league_OREB_share_prior)`.
- Own-team rebound competition/injury context và expected minutes cùng opponent volume. Tổng rebounds allowed không phân biệt OREB/DREB hoặc đội nào miss, nên không chỉ dùng một rankREB duy nhất để gán favorable.

### 11.4. BLK chỉ khi mở market riêng sau này

Nghiên cứu player block rate × opp blocks_allowed rate/shot volume, có thể thêm rim attempts nếu tracking đủ. Rare events cần distribution/support/calibration riêng; không suy hiệu quả từ PTS model hoặc từ opp blocks_made.

## 12. Bảng interactions với các modules hiện có

| Module/feature | Cách kết hợp | Điều không làm |
|---|---|---|
| Minutes/form | Cho model cùng nhìn minutes history và opponent per100 values | Không ép minutes×opponent rank như forecast chính xác |
| Shrunk player rate | Kết hợp prior-backed rate/exposure/prior_weight với opponent context | Không sửa α/β dựa kết quả target hoặc rank cuối mùa |
| Own role/shot mix | Registered products theo §11, giữ sample/missing flags | Không suy position label xác định shot profile |
| Team/opponent pace | Tách scoring/volume per100 khỏi pace, cả hai là inputs | Không cộng pace uplift rồi cộng per-game allowed uplift cùng nguồn bằng tay |
| Own/opp rest,b2b,3in4 | Context và tối đa một interaction với defense được mở ở P1 | Không b2b→giảm defense x% cố định |
| Opponent absences | Opp missing-role vectors L/ΔL cùng historical rank | Không defender out→tự hạ5 rank hoặc tăng5%EV |
| Teammate absences | Cơ hội/phút của target cùng opponent opportunities | Không phân stat người vắng cho người còn lại theo rank |
| Rookie/return/transfer | Priors/support flags và scenario policy, giữ opponent values bình thường | Không dùng favorable opponent để override thiếu data/limit phút |
| Market inputs | H/augmented branch riêng, same snapshot rules | Không line-weight fit G_stats hoặc pricing chọn stats-only feature set |
| EV/selection | Tính từ final calibrated probabilities tại quote/rules | Không cộng điểm rank thành edge hay đảm bảo bet thắng |

Các interactions có thể trùng thông tin với raw inputs; thử hữu hạn, regularize và ablation. Không tạo hàng trăm rank×playerID×injury products rồi chọn cái đẹp nhất.

## 13. Pace và injury: tránh đếm lại cùng bối cảnh

### 13.1. Pace

Lấy pace từ nguồn advanced đã chuẩn hóa hoặc proxy48 phút có recipe riêng. Nếu dùng possessions proxy: `pace48_g=48×(P_tg+P_ug)/(2T_g)`, T_g=48+5o_g của **game quá khứ**. Đây là proxy nhịp độ, không exact NBA pace. Không dùng overtime trận đích hoặc assume overtime game cũ không có.

`pace_pair_proxy=(own_pace_prev10+opp_pace_prev10)/2` có thể dùng làm feature, không phải forecast possessions chính xác. Opp points_allowed pergame đã chứa pace; per100 giúp tách bớt. Persist cả pergame để UI nếu cần, tránh default đưa nhiều duplicates chưa ablation.

### 13.2. Opponent injury mới so với lịch sử

Rank từ10 games có thể phản ánh đội hình khác lineup sắp tới. Thêm opp missing-role L_now, Lbar, ΔL và sample age như injury spec. Model học sự khác biệt; không sửa rank trực tiếp thành một bảng strength giả cho lineup mới.

Một người đã vắng lâu có thể đã được phản ánh trong opponent rolling defense; L/ΔL giúp mô tả context, không bảo đảm thống kê tách causal effects. Thiếu defender-quality metrics thì missing minutes không tự đo quality rim/perimeter mất đi.

Khi questionable/return context ngoài support, scenario_only theo policy; không thấy đối thủ rank30 rồi tự chuyển READY. Nếu có validated scenario joint, condition weights đúng khi target vào sân; không chỉ average rank của hai scenarios rồi coi là full mixture.

## 14. Rank chính xác theo thời gian và batch inference

Với mỗi unique target cutoff c:

1. Resolve schedule/team membership/opponent snapshot tại c.
2. Load canonical pair histories có data available trước c, excluded targetgame.
3. Với mọi teams trong season universe, build windows/rates/shrinkage tại **c chung**.
4. Build rank/percentile trên same metric/window/recipe, average ties, coverage mask.
5. Join row của opponent vào target player-game; join player features as-of c.
6. Build selected interactions, apply quality/support policy; persist snapshot/hash.

Có thể cache theo `(cutoff_bucket,input_snapshot_id,prior_bundle_id,recipe)` chỉ khi bucket được chứng minh không nhập events sau target cutoff. Default exact cutoff timestamps trước tối ưu; không round cutoff lên phút/giờ rồi lấy data tương lai. Source sửa stats tạo snapshot mới, không overwrite feature/prediction cũ.

Daily precomputed ranks có thể dùng nếu freeze trước earliest target cutoff và bỏ data phát sinh sau snapshot. Nó sẽ cũ hơn intraday ranks; ghi age. Không gọi intraday accurate chỉ vì column có tên rank_today.

## 15. Schema/module contracts và migration

Tables/views:

```text
team_game_pairs          # own/foe rows + possessions/version/availability
opponent_metric_priors   # quantity,units,origin,pool coverage,prior hash
team_context_snapshots  # team,cutoff,window,metric values,samples,quality
team_rank_snapshots     # metric/window/cutoff,rank universe/ranks,ties
player_opponent_features # target IDs,context IDs,selected interactions
```

API đề xuất cho code:

```python
build_team_game_pairs(team_games, schedule, recipe)
fit_opponent_priors(permitted_train_prefix, origin, recipe)
build_team_context_asof(pairs, teams, cutoff, prior_bundle, recipe)
rank_team_context(context_table, expected_team_ids, recipe)
build_player_opponent_features(targets, player_history, context, recipe)
validate_opponent_feature_snapshot(features, lineage)
```

Output giữ row_id/target order, không mutate input. Stats-required thiếu→explicit schema/feature unavailable, không return input như thành công. Source/units/ascending/denominator đều có trong dictionary/schema, tránh `opp_rank` không biết rank gì.

Migration: giữ old baseline artifacts, thêm namespaced columns, regenerate temporal features/priors/ranks, invalidate feature caches và train/recalibrate new bundle trong development. Không append new columns vào inference của model cũ rồi kỳ vọng nó đã học tương tác. Bundle kiểm tra feature names/order/versions, prior/G/distribution match trước atomic activation.

## 16. Ablation và giới hạn trial

Giữ mean algorithm/hyperparameters hiện được chọn cố định trong thí nghiệm feature đầu tiên; fit lại parameters/φ/G theo cùng temporal recipe. Không đồng thời mở12mean configs×48recipes×mọi interaction rồi gọi là chỉ thêm1 feature.

| Trial namespace | Inputs |
|---|---|
| OPPR_R0 | Current valid pipeline/feature manifest, gồm các opponent features cũ đã có |
| OPPR_R1 | R0 + granular per100 values/samples/priors, không ranks mới |
| OPPR_R2 | R1 + selected ascending ranks/percentiles |
| OPPR_R3 | R2 + tối đa3 explicit interaction candidates/stat đã đăng ký |

P0 chỉ K10; P1 K20/shares mở round riêng. R3 interactions chọn từ §11 trước run; nếu shares chưa có thì chỉ chọn products dùng quantities P0 đã kiểm tra, không điền shares0 để đủ3.

Mỗi stat tối đa4 feature recipes/round, same learner/tuning budget, same canonical samples. Baseline R0 không được dùng leaked history để “so đúng code cũ”. Existing duplicates trong R0 phải nhận diện; R1 không thêm cột alias rồi gán improvement cho new information.

Primary development full RPS, secondary discrete log score, mean/median errors, PIT/interval coverage; same tail/numerical policy. Paired block CIs theo ngày/trận, cohort counts và performance qua thời gian. Rank-only win đẹp trên một nhóm nhỏ chưa đủ giữ feature.

Chọn theo indifference/complexity rule của stats-only selection spec trong development; nếu R2/R3 không cải thiện ổn định thì giữ values-only hoặc R0. Không tăng confidence/EV chỉ vì feature importance cao. Report null/deterioration và all trials.

B1 đã từng dùng chọn model/features là reused development, không untouched holdout. Không chọn bằng B2 fit-score hoặc B4/B5 paired primary scores. Muốn confirmatory claim riêng cho opponent rank cần hypothesis/data mới; file này không thêm primary tests.

## 17. Tests và ví dụ số bắt buộc

### 17.1. Ví dụ smoothing

Giả định points allowed count1120, offensive possessions của các đối thủ đã gặp1000; R0=110/100poss, τ500:

`R_raw=112`, `R_shrunk=100×(1120+500×1.10)/(1000+500)=111.3333333333`.

Không lấy mean112 và110 rồi chia2 nếu exposures không tương ứng. Prior_weight=1/3. Đây là dữ liệu giả, không league baseline đã ước lượng.

### 17.2. Ví dụ rank ties

Ba đội illustrative có values110,110,120 → average rank1.5,1.5,3; percentile0.25,0.25,1. Đây là rank trong3 đội, không `/30`. All values bằng nhau→pct0.5 cho mọi đội.

### 17.3. Checklist correctness

- [ ] Self-join đúng own/foe; pts_allowed lấy foePTS, blocks_made/allowed không tráo.
- [ ] Sửa/add target outcome hoặc future games không làm đổi target rank/features.
- [ ] Whole-season current stats không dùng cho past cutoffs; late correction có version.
- [ ] Per100 ratio-of-sums, đúng offensive possession side; không0/negative denominator fallback ngầm.
- [ ] Missing BLK/possessions khác0; paired family identity và BLKA/foeBLK conflicts được audit.
- [ ] No-history prior/sample flags đúng; prior không chứa evaluation hoặc future rows của đội khác.
- [ ] Tất cả rank rows cùng cutoff/universe/window/units, average ties và coverage-aware.
- [ ] Ascending nghĩa đúng metric; UI descending field không đổi model meaning.
- [ ] Ranks thiếu coverage không tự rank30; no-history/allprior không giả strong evidence.
- [ ] Missing shot share/return/lineup không biến thành0 product; interactions có units và provenance.
- [ ] Blocks context không tự phát outputBLK; no manual rank uplift/φ bump/EV addition.
- [ ] Train/inference feature schema giống nhau; model/G retrained khi recipe đổi.
- [ ] Feature ablations same samples và no market line leakage vào G_stats/selection.

## 18. Bàn giao và điều kiện hoàn thành

1. Data/schema audit: constructor/response/source coverage và canonical pair reconciliation.
2. Feature builder/rank snapshots/priors, đầy đủ dictionary/units/flags và temporal tests.
3. K10 values-only baseline, rank ablation và selected interactions trong development, có prediction ledger/metrics/cohort uncertainty.
4. Model bundle mới với feature/prior/φ/G hashes và activation checks; không sửa forecast cũ.
5. UI có thể hiển thị rate/rank/window/sample/age; kèm đúng nghĩa rank, không “đối thủ hạng30 nên chắc Over”.

Không cần additional learning algorithm chỉ để có rank. Phần mới chủ yếu là data/feature pipeline; giá trị dự báo phải được đo, chưa thể hứa tăng accuracy bao nhiêu phần trăm.

## 19. Nguồn và quan hệ với kế hoạch cũ

- [nba_api — LeagueDashTeamStats](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/leaguedashteamstats.md): modes, date/window/unit parameters, Base stats/ranks; đã đối chiếu docs trong lượt trao đổi, chưa xác minh response live trên máy người dùng.
- [nba_api — LeagueGameLog](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/leaguegamelog.md): nguồn team-game logs đã chọn trong kế hoạch; kiểm tra schema của package thực.
- [Kế hoạch opponent/schedule](https://chatgpt.com/library?file_id=libfile_c8d4b0ef6e288191b5c5a1816c43e6ab&account_id=61294741-651c-40c7-b521-b699e7d014b8).
- [Feature/shrinkage spec](https://chatgpt.com/library?file_id=libfile_faeeb3a721e4819184d13c2f80ebd92b&account_id=61294741-651c-40c7-b521-b699e7d014b8).
- [Injury supplement](https://chatgpt.com/library?file_id=libfile_6e2eaeb7594c81918a09184a24c76129&account_id=61294741-651c-40c7-b521-b699e7d014b8).
- [Stats-only model selection](https://chatgpt.com/library?file_id=libfile_8d0f5bec4c30819184dfecd96e12dd63&account_id=61294741-651c-40c7-b521-b699e7d014b8).

Windows, τ/κ, coverage floors và interaction candidates là operational design đề xuất, chưa chứng minh tối ưu. API/schema availability không chứng minh rank có predictive value. Không có model/code hiện hành được chỉnh trong lượt này; file là đặc tả để agent triển khai và trả bằng chứng.
