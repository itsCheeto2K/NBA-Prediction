# Defense vs Position: đặc tả dữ liệu, công thức, model và UI

Ngày: 13/11/2026 (giờ Việt Nam)  
Phiên bản: dvp_v1 — đề xuất triển khai và kiểm chứng.  
Phạm vi: bổ sung team-level DvP cho PTS/REB/AST; chưa phải matchup1-on-1, chưa mở market3PM/BLK tự động.  
Bằng chứng: dựa trên mô tả agent được cung cấp và tài liệu endpoint đã đối chiếu; chưa đọc implementation DvP mới hoặc xác minh rankings NBA được nêu trong ví dụ.

## 1. Quyết định thiết kế

Giữ team-level defense làm nền. Thêm DvP như **feature/context lịch sử**, tách ba loại quantity:

1. Production của cả nhóm vị trí trên100 team possessions.
2. Production của nhóm trên player-minute, để nhìn rate khác với tổng minutes mà nhóm được dùng.
3. P1: observed/expected residual có điều chỉnh năng lực lịch sử đối thủ đã gặp, vẫn không causal.

Không dùng DvP rank để cộng points/EV bằng tay. Không gọi nhóm Guard gặp rank26 là “kèo thơm Over” khi chưa xét line/odds và final calibrated probability. UI chi tiết hơn không chứng minh model tốt hơn.

Ví dụ Denver/Jokić/Mitchell và các hạng3/26 trong mô tả trước **chưa được xác minh**. Nếu cần minh họa, dùng độiA/B giả định hoặc ghi rõ hypothetical, không giải thích một ranking là do một defender cụ thể khi chưa có bằng chứng.

## 2. Những chỗ cần sửa trong đề xuất ban đầu

| Nội dung | Sửa |
|---|---|
| DvP chuyên sâu hơn nên chính xác hơn | Chỉ là granularity cao hơn; có thể tăng noise và confounding |
| PF vào Wing, C mới là Big | Mapping này khác prior feature spec; v1 giữ mapping chung cũ và version rõ |
| “Cho phép vị trí ghi bao nhiêu” | Chốt denominator và units; total group volume khác rate theo phút |
| τ500 “khử nhiễu” | Làm trơn một phần; không xóa uncertainty/bias hoặc tự đúng cho mọi exposure |
| Rank21 nghĩa dưới trung bình | Rank chỉ thứ tự; không suy so với arithmetic mean hoặc khoảng cách đội |
| Hạng/30 luôn có | Chỉ khi đủ universe30 đội theo season; thiếu coverage phải hiện denominator thực |
| Thêm UI/FastCheck là model đã dùng DvP | Tách display-only, model-enabled và validated states |

Không mặc định thiếu DvP hiện tại là lỗi model. Feature này chỉ được giữ sau comparison ngoài mẫu với team-only baseline.

## 3. Nguồn và data contract

Nguồn chính: player-game logs/BoxScoreTraditionalV3 cho PTS/REB/AST/minutes; team-game pairs và possessions từ opponent-rank recipe; position metadata có source và history. Không cần matchup1-on-1 tracking cho DvP v1.

Fields:

```text
player-game: game_id, player_id, team_id_at_game, played,
             seconds/minutes, pts, reb, ast,
             position_raw, position_source, position_observed_at,
             game_end_utc, stat_available_at, source_version
team-game:   game_id, own_team_id, foe_team_id, season/type,
             possessions_own, possessions_foe, possession_recipe,
             game_end_utc, stat_available_at
target:      player_id, game_id, team_id, opponent_id,
             cutoff_utc, position_mapping_version, feature_recipe
```

PlayerGameLogs/box-score schema không tự chứng minh có đầy đủ vị trí historically correct. Phải audit metadata coverage. Không dùng tên/team hiện tại để sửa lịch sử sau trade, không gán position lấy hôm nay cho tất cả games quá khứ nếu không có provenance. Target position phải biết trước cutoff, không inferred từ actual target lineup/minutes.

Khi group position của game lịch sử được ghi trong một historical box score, nó chỉ dùng làm mô tả của game **đã kết thúc và available trước target cutoff**. Nó không là thông tin pregame của chính game lịch sử đó. V1 ưu tiên position snapshots as-of trước từng game để nhất quán; backfill metadata thiếu phải gắn limitation, không giả known-at-time.

## 4. Mapping vị trí thống nhất và unknown bucket

V1 kế thừa feature/shrinkage mapping:

| Raw label chuẩn hóa | Group |
|---|---|
| PG, SG, G | guard |
| SF, F, G-F, F-G | wing |
| PF, C, F-C, C-F | big |
| Missing/khác chưa có rule | unknown |

Đây là approximation, không mô tả role thật hay assignment defender. Không thể dùng guard DvP để khẳng định PG defense và SG defense giống nhau. Giữ raw/hybrid flags, source và mapping_version.

P0 mỗi player-game được gán đúng1 bucket; không cho G-F vào cả Guard và Wing làm double count. Fractional assignment là P2 riêng, weights mỗi player phải sum1 và có temporal provenance.

Nếu muốn PG/SG/SF/PF/C hoặc mapping PF→Wing khác, đăng ký mapping variant và regenerate toàn prior/rank/features. Không cho UI một mapping, model/shrinkage một mapping khác cùng tên group.

Unknown không bị drop: giữ minutes/stat của unknown để đối chiếu và coverage. Target unknown→DvP target feature missing, dùng team-level fallback. Không chọn group có rank thuận lợi nhất cho player hybrid sau khi xem line/outcome.

## 5. Dựng một DvP observation đúng phía

Trong historical game h, t là đội phòng ngự đang được profile, u là đội tấn công gặp t. Với group g:

`Y_tgsh = Σ_(j thuộc u, group_jh=g, played) X_jsh`;

`M_tgh = Σ_(cùng players) minutes_jh`.

Đây là total stat/phút của **mọi cầu thủ nhóm g bên u**, không chỉ starter hoặc người được cho là t kèm chính.

Exposure possessions:

- PTS/AST group production: `E_th=P_uh`, offensive possessions của u.
- REB group production: `E_th=(P_th+P_uh)/2` theo common game-possession normalization của opponent-rank spec, để REB families/group aggregates nhất quán. Nó chưa là exact rebound opportunities.

Trong cùng game/group, E được tính **một lần**, không nhân theo số players trong group. Hai guards cùng chơi tổng80 player-minutes vẫn chỉ đối diện một team-game possession exposure ở quantity group-volume.

DNP không thêm một0-performance appearance vào per-player history; group total có thể0 hợp lệ nếu không có players thuộc group đó thực sự chơi. Nếu roster/position/player rows thiếu thì không suy group total0.

Kiểm tra `Σ_(guard,wing,big,unknown)Y_tgsh=Σ_(played players u)X_jsh` và cùng identity cho player-minutes. Đối chiếu player totals với team totals theo field/source exceptions; team rebounds không luôn là sum mọi player rebound fields nếu bao gồm team rebounds. Không ép sửa source để làm identity đẹp.

## 6. Windows và coverage

Default:10 trận gần nhất của **đội t**, Regular Season, available trước target cutoff, horizon365 ngày. Đây không phải10 trận gần nhất của từng guard hoặc10 ngày lịch. P1 window20 đăng ký round sau.

Giữ team window và metric-valid mask riêng; nếu một game thiếu position/stats, không âm thầm lùi xa hơn để luôn có10 games mà vẫn gọi đúng cùng window team-level. Report `window_team_games`, `valid_dvp_games`, IDs và missing reasons.

P0 quality screens đề xuất theo từng game/quantity:

- Canonical player rows/participation/minutes completeness pass.
- Mapped-to-known-group minutes ≥95% verified player-minutes của đội u.
- Unknown-group stat≤5% tổng player stat của quantity đó. Khi total stat0, không dùng0/0: value0 có thể hợp lệ nếu labels/counts đầy đủ, giữ minutes-mapping coverage check.
- Possessions hợp lệ và paired team rows đầy đủ.

Không đạt thì observation unavailable cho DvP metric, vẫn giữ raw/coverage. Các thresholds95/5 là operational defaults mới, không guarantee không bias. Nếu unknown players không random, filtering vẫn có selection; report coverage theo team/time/group.

Model-enabled DvP yêu cầu ít nhất5 valid games trong10-game window và prior hợp lệ. Dưới floor, có thể lưu prior-backed descriptive value nhưng `dvp_supported=false`; target model sử dụng missing+flags hoặc team-only fallback đúng recipe đã train.

## 7. Công thức thô: hai estimands khác nhau

Trên W_t(c), q_shares không áp dụng ở đây, s∈{PTS,REB,AST}:

### 7.1. Group production trên100 possessions

`V_tgs = 100 Σ_h Y_tgsh / Σ_h E_th`.

Mỗi valid game đóng1 lần E, kể cả group có minutes0 nếu biết thực sự không có group players tham dự. Quantity này phản ánh cả năng lực/efficiency và số phút/usage của nhóm đã gặp.

### 7.2. Group rate theo phút

`R_tgs = Σ_h Y_tgsh / Σ_h M_tgh`.

Nếu M0 và Y0: không có rate information, không kết luận defense khóa group100%. Nếu M0 mà Y>0: data invalid. Rate/minute cũng lẫn opponent quality, shot mix và role; chia phút không tự causal-adjust đầy đủ.

### 7.3. Exposure profile

`minutes_per_game_g=ΣM/valid_games`;

`minutes_per100poss_g=100 ΣM/ΣE`;

`minutes_share_g=ΣM/Σ_(all groups incl unknown)M`.

Khi dùng cùng valid subset, V=R×minutes_per100poss. Giữ exposure features để không nhầm đội cho Guards ghi nhiều vì opponents dùng nhiều Guards với “đội thủ Guard kém”.

## 8. Priors và shrinkage đúng đơn vị

Priors được fit trên permitted past training prefix, không current/final-season table. Snapshot/OOF/weekly bundle policy theo feature spec. League prior theo group **và stat**, không dùng team-total prior trực tiếp cho mỗi group.

`V0_gs=100 Σ_(train valid observations)Y_tgsh / Σ_(train valid observations)E_th`;

`R0_gs=ΣY_tgsh/ΣM_tgh`.

P0 prior coverage:≥20 teams,≥30 valid team-games và≥10000 possessions cho V0; R0 cần thêm≥1000 group-player-minutes. Không đủ→prior unavailable/fallback team-level, không bịa rate nhóm. Defaults cần audit đầu mùa và phụ thuộc archive coverage.

Group volume smoothing:

`Vtilde_tgs=100 [ΣY+τ_poss V0_gs/100]/[ΣE+τ_poss]`, τ_poss=500 possessions.

Group minute-rate smoothing:

`Rtilde_tgs=[ΣY+β_min R0_gs]/[ΣM+β_min]`, β_min=500 **player-minutes**.

Hai số cùng500 là hai concentrations có units khác; không dùng exposure field chung để tráo. Đây là defaults đề xuất, không “Bayes tự khử mọi nhiễu” hoặc strength đã tối ưu. PTS compound scoring/weighted mixtures không mặc định có Gamma–Poisson sampling posterior chính xác.

No group minutes→Rtilde=R0 với prior_weight1, support false; no observations→Vtilde=V0 khi prior hợp lệ. Priors không là evidence đội đó đã thực sự phòng ngự group ngang league.

Không claim sum shrunk V các nhóm bằng shrunk team-total nếu valid subsets/priors/denominators khác. Chỉ assert identity khi cố tình dùng common subset, exposures/τ và priors cộng nhất quán, unknown bucket được giữ.

## 9. Rank, percentile và so với team-level

Tại cùng cutoff c, dựng profiles mọi teams trong season universe, cùng mapping/window/denominator/prior recipe. Xếp **riêng từng group,stat,estimand**:

`rank_volume_asc=average_rank(Vtilde_tgs, ascending=True)`;

`rank_minrate_asc=average_rank(Rtilde_tgs, ascending=True)`.

Rank1 nghĩa lượng stat/rate thấp nhất, không phải chắc chắn defense tốt nhất sau quality adjustment. Average ties; percentile `(rank−1)/(N_valid−1)`, N1→0.5 flagged. Rank trong subset phải hiện N_valid/N_expected, không tự gắn `/30`.

Display rank chính P0 dùng volume-per100, luôn label rõ; per-minute rank là tab/field riêng. Không mix một team rankvolume với một DvP rankminrate rồi gọi chênh hạng là matchup advantage.

Model features ưu tiên values, log-relative và support; rank bổ sung optional. Define:

`dvp_volume_rel=log(Vtilde_tgs/V0_gs)`;

`dvp_minrate_rel=log(Rtilde_tgs/R0_gs)`.

Chỉ khi values/prior>0; invalid/degenerate prior→unavailable, không epsilon để che data problem. Với zero-count quantity prior có thể cần parent model hợp lệ; v1 không tự bịa positive count.

Một interaction context bổ sung khi cùng denominator/valid semantics:

`dvp_vs_team_rel=dvp_volume_rel−log(team_allowed_rate/team_allowed_prior)`.

Đây là difference of relative contexts, không causal group-specific defensive effect. Team-level và DvP correlated; không coi chúng hai likelihood độc lập rồi nhân strengths.

## 10. P1: giảm confounding do những cầu thủ đã gặp

Raw DvP có thể cao vì10 games gần nhất gặp nhiều elite Guards. P1 thử observed/expected proxy, chưa mặc định cần train model mới.

Với player j ở historical game h, lấy rate estimate rhohat_jsh đã biết **trước game h**, không fit bằng game h/future; baseline này không dùng identity/rank/defensive context của đội t đang được đo để tránh tự hấp thụ effect cần nghiên cứu.

`B_tgsh=Σ_(j nhóm g đội u) M_actual,jh × rhohat_jsh`.

Actual minutes là exposure của **trận quá khứ đã hoàn thành**, không actual minutes target. B là expected-count proxy có điều chỉnh player baseline và exposure, chưa true conditional mean và không causal. Nếu thiếu baseline/history thì coverage thiếu; không thay actualY làm expectedY.

Aggregate Y=ΣY_tgsh, B=ΣB_tgsh, shrink ratio:

`OE_tgs=(Y+κ_count)/(B+κ_count)`, κ_count=50 expected-stat units, prior ratio1.

OE>1 nghĩa group ghi nhiều hơn baseline proxy ở các games đã xét; OE<1 ít hơn. Keep B/Y/games/player baseline quality. κ_count units khác500 possessions/minutes. M0/B0 không có informative observation; model-quality failures không được che bằngκ.

P1 fit expected baseline bằng chronological OOF/forward priors. Controls minutes/quality chưa sửa mọi bias từ scheme, assignments, pace errors, injuries và lịch chọn opponents. Compare P1 với raw DvP ngoài mẫu, không đổi nhãn thành “defender strength đã loại hết nhiễu”.

## 11. Ghép vào target và interactions theo stat

Player target i gặp t, group g_i theo metadata as-of: join `t,g_i,cutoff,mapping_version`. Không join primary defender theo position. Unknown group→DvP missing, giữ team-level.

P0 direct mean:

`μ_is=exp(f_s(player_form,shrunk_rates,minutes_history,role,team_context,injury,schedule,DvP_values,exposure_flags))`.

Các candidates có thể thử có giới hạn:

| Target stat | Interactions |
|---|---|
| PTS | Player FGA/FTA rates, shot mix và minutes cùng DvP PTS volume/minrate; shot-profile×team3PT/rim context nếu dữ liệu đủ |
| REB | Player OREB/DREB role và minutes cùng DvP REB, opponent miss volume, DREB/OREB shares; không tổngREB rank duy nhất thay toàn cơ chế |
| AST | Player AST/passing/cầm bóng role cùng DvP AST, teammate scoring/missing-role và minutes context |

V1 cho cây học từ raw contextual features trước, tối đa2 explicit interaction products/stat ở vòng sau. Không áp group rank thành upliftμ hoặc cộngEV. Cầu thủ cùng Guard vẫn có thể là scorer hoặc playmaker; DvP group không thay role/shot profile.

Giữ availability và rest/b2b của hai đội làm context. Historical DvP có thể đã phản ánh người vắng lâu; thêm L/ΔL như injury spec, không tự sửa rank giảm5 bậc khi center out. Favorable rank không override missing injury/source/support.

Nếu thêm DvP vào conditional dispersion thì là candidate riêng có fit/validation; không tăngφ bằng tay vì group sample nhỏ. Refit downstream mean/φ/G theo schema mới; không append columns inference vào bundle cũ.

## 12. UI và FastCheck: descriptive trước, model-enabled sau

UI đề xuất hiển thị:

```text
Opponent: Team B | cutoff: ... | window: last 10 team games
Team PTS allowed: ... /100 poss | rank asc .../N
DvP vs Guard — GROUP VOLUME: ... /100 team poss | rank asc .../N
DvP vs Guard — PLAYER-MINUTE RATE: ... /minute | rank asc .../N
Valid games: .../10 | group minutes: ... | mapping coverage: ...%
Prior weight volume/rate: .../... | data age: ...
Feature mode: display-only / model-enabled / validated-scope
```

Đừng gọi model-enabled là validated nếu chỉ đã thêm field. Chưa có valid rank universe/support→rank unavailable/prior-backed rõ; không display #30 thuận lợi giả. No group metadata→unknown, không tự chọn guard/center theo tên.

FastCheck có thể thêm context columns nhưng **chưa sort score/recommendation theo DvP rank**. Nếu muốn ranking policy dùng DvP, nó phải được phát triển/khóa/đánh giá ngoài mẫu riêng cùng selection policy; không line-color đỏ/xanh thành lời hứa Over/Under.

Không dùng causal captions “Jokić khóa Center” hoặc “Guard này kèo thơm” từ raw rank. Ví dụ NBA thật phải có source/cutoff/window và computed artifact, không lấy giả định minh họa làm số liệu.

## 13. Schema và API contracts

Tables/views:

```text
player_position_history      # raw/group/source/validity/mapping
dvp_game_observations        # defense team,foe,group,stat,Y,M,E,quality
dvp_prior_snapshots          # group/stat/estimand/origin/exposure/coverage
dvp_context_snapshots        # cutoff/window/values/ranks/universe/support
player_dvp_features          # target group/context IDs/selected features
```

Code boundaries:

```python
resolve_position_group(player_id, at_time, mapping_version)
build_dvp_game_observations(player_rows, team_pairs, position_history, recipe)
fit_dvp_priors(permitted_train_prefix, origin, recipe)
build_dvp_context_asof(observations, cutoff, prior_bundle, recipe)
rank_dvp_context(context, expected_team_ids, recipe)
join_target_dvp_features(targets, contexts, recipe)
```

Preserve row_id/order; no mutate input. Required schema/ID conflict→error/quarantine; optional DvP unavailable→missing+reason, team-only fallback theo recipe đã train. Store feature/prior/mapping/possession/source hashes.

Current-season position updates tạo metadata version mới; không overwrite historical resolved position trong saved forecasts. Same cutoff rank cache chỉ reuse khi input snapshots/priors/mapping đều match.

## 14. Ablation, evaluation và trial budget

Giữ cùng mean family/hyperparameters, fit lại parameters/φ/G bằng cùng temporal recipe; không mở mọi algorithm search đồng thời.

| Trial | Inputs |
|---|---|
| DVP_D0 | Existing team-level valid baseline |
| DVP_D1 | D0 + group-volume values/exposure/support |
| DVP_D2 | D1 + group-minute-rate/context-relative values |
| DVP_D3 | D2 + selected ranks, không manual multipliers |

P1 OE-adjustment và explicit products mở round riêng, không ép đủ mọi feature vào lần đầu. Budget tối đa4 feature recipes/stat ở P0, all trials logged, same canonical samples và tuning budget. Tách missing/unknown coverage khỏi forecast failure, không chọn sample dễ hơn cho DvP.

Primary development full RPS; log score, mean/median error, PIT, interval coverage/tails và cohorts secondary. Paired multi-day block CI theo plan; reused B1 không trở thành untouched holdout. Nếu không cải thiện ổn định, giữ team-level hoặc values-only; UI có thể giữ descriptive data với label rõ.

Report rookies, unknown/hybrid positions, current-stint changes, elite vs low-minute roles, multiple absences và early-season small sample. Không chỉ toàn-league mean rồi khẳng định mọi group tốt hơn. Feature importance không chứng minh predictive improvement hoặc causal mechanism.

B2 fitG, B4/B5 không dùng chọn lại DvP features/mapping. Changed recipe có version/revalidation, không thêm primary hypotheses hoặc đổi market margin hồi tố.

## 15. Ví dụ giả và tests bắt buộc

### 15.1. Volume khác minute-rate

Trong10 games giả, Guards gặp độiA ghi600 PTS trong800 player-minutes và1000 team possessions. Với độiB, Guards ghi500 PTS trong500 player-minutes, cũng1000 possessions:

- A volume60 PTS/100 team possessions; rate0.75 PTS/player-minute.
- B volume50 PTS/100 team possessions; rate1.00 PTS/player-minute.

Raw group volume nói A cho Guards ghi nhiều hơn; rate theo phút nói B cao hơn. Không chọn metric nào để tuyên bố defense yếu hơn mà không định nghĩa mục tiêu/kiểm tra context.

Với V0_guard55, τ_poss500: A Vtilde=(600+275)/1500×100=58.3333333333; B Vtilde=(500+275)/1500×100=51.6666666667. Priors0.8 PTS/minute, β_min500: A Rtilde=(600+400)/1300≈0.7692307692; B Rtilde=(500+400)/1000=0.9. Shrinkage không xóa khác biệt estimands.

### 15.2. Correctness checklist

- [ ] Hai guards không làm denominator team possessions bị nhân2; group minutes cộng cả hai đúng.
- [ ] Guard/Wing/Big/Unknown partitions cộng về player totals; không double-count hybrid.
- [ ] Missing group/metadata khác0 performance; no-minutes/Y>0 invalid.
- [ ] Historical position source/time và target position as-of đúng; no current-metadata backfill giả.
- [ ] Team last10 window và metric-valid counts rõ; thiếu rows không lùi window không ghi nhận.
- [ ] Possessions/minutes concentrations đúng units; no league-total prior cho mỗi group.
- [ ] Rank volume và minrate riêng, average ties, đúng universe/cutoff và support flags.
- [ ] No target/future data vào prior/rank; mutation future rows không đổi target features.
- [ ] Actual minutes chỉ dùng historical observation/adjustment, không target input pregame.
- [ ] OE nuisance rate pregame/OOF, không dùng trueY làm expected hoặc absorb target-opponent features không khai báo.
- [ ] Feature/φ/G retrain đúng blocks; UI-only feature không tự được model dùng.
- [ ] FastCheck không cộng rank vàoEV/recommendation khi policy chưa validated.
- [ ] Ví dụ §15.1 khớp; reports có coverage/exclusions/failed trials và no-improvement results.

## 16. Bàn giao, thứ tự làm và nguồn

Thứ tự: audit positions/player-team pair coverage → observation tables/priors/quality tests → UI descriptive và target joins → ablation D0–D3 → model-enabled bundle nếu đạt → P1 opponent-quality adjustment. Không cần làm direct defender assignment mới có DvP, và DvP không chứng minh assignment.

Deliverables: code diff/config mapping, feature dictionary, prior/rank snapshots, tests, position/coverage audit và development comparison report. Chưa có real dataset thì chỉ đánh dấu module correctness, không predictive gain.

Nguồn schema:

- [nba_api — PlayerGameLogs](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/playergamelogs.md).
- [nba_api — BoxScoreTraditionalV3](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoints/boxscoretraditionalv3.md).
- [Opponent rank & interactions spec](https://chatgpt.com/library?file_id=libfile_f57476f67784819182375985229f4e36&account_id=61294741-651c-40c7-b521-b699e7d014b8).
- [Feature/shrinkage spec](https://chatgpt.com/library?file_id=libfile_faeeb3a721e4819184d13c2f80ebd92b&account_id=61294741-651c-40c7-b521-b699e7d014b8).
- [Stats-only selection spec](https://chatgpt.com/library?file_id=libfile_8d0f5bec4c30819184dfecd96e12dd63&account_id=61294741-651c-40c7-b521-b699e7d014b8).

API docs xác định khả năng dữ liệu, không chứng minh feature accuracy. Mapping, windows, τ/β/κ và quality/support floors là operational defaults đề xuất, chưa optimal/empirically verified. Không hứa tăng accuracy hoặc win rate từ việc thêm DvP; chưa có code/bundle production nào được chỉnh trong lượt lập file.
