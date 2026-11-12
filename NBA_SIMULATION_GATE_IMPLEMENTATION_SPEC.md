# Simulation Gate: công thức, DGP, inference engine và kế hoạch triển khai

Ngày: 10/11/2026 (giờ Việt Nam)  
Phiên bản: gate_spec_v2 — đề xuất chi tiết hóa/sửa ambiguity của §11.7.6–11.7.8, cần đưa vào manifest trước release B5.  
Trạng thái: SPECIFIED; chưa có codebase đầy đủ, B4 odds/lines hoặc simulation results để xác nhận implementation/pass.  
Phạm vi: xác nhận pooled ΔBrier của H_refit so với S+H_refit. Không là module xác nhận ROI, parlay hay từng bet riêng.

## 1. Đánh giá báo cáo hiện tại

Đúng: gate nằm giữa B4 pilot và B5 prospective; cần empirical size/coverage/power dưới nhiều DGP; RMS chỉ diagnostic; weekly-refit là primary; futility chỉ dừng, không ADOPT.

Cần sửa/làm rõ:

| Nhận định | Sửa |
|---|---|
| Tầng1–4 đã vững chắc | Chưa xác minh code/artifacts/data lineage; gate không chứng nhận các tầng đó chỉ từ mô tả |
| 12 mean configs×48 recipes | Đặc tả selection trước là12 mean configs, tối đa48 composite recipes/stat **tổng**, không576 |
| Ω được gọi ma trận rồi đưa vào công thức T | Ω của estimator Δ là scalar; covariance matrix cần ký hiệu khác |
| Bootstrap ít blocks rất dễ under-cover | Là risk cần mô phỏng; không khẳng định mọi dataset đều under-cover hoặc cùng mức |
| Futility-only triệt tiêu alpha inflation | Nó không thêm efficacy look; không sửa final CI sai hoặc data-dependent recipe changes |
| Unit tests kiểm chứng coverage chính xác | Tests kiểm tra implementation; coverage chỉ được ước lượng dưới DGP, có MC error/model risk |
| Score-level resampling kiểm tra full weekly-refit | Không; phải có adaptive replay/simulation adapter chạy lại thuật toán |
| Đủ synthetic data là mở B5 | Không thay được missing B3/B4 actual odds, snapshots và pilot exposure |

Gate chưa code không chặn stats-only development/shadow logging. Nó chặn **tuyên bố xác nhận theo protocol này**, không tự chứng minh model không có tín hiệu.

## 2. Những gì giữ nguyên và chi tiết mới phải đăng ký

Giữ mặc định main1.8: δ0.001; Δ_alt0.002; final CI95 hai phía; ADOPT khi L>δ; width target chỉ báo cáo; B4 checkpoints140/280; B5 budget200 scheduled game dates; l14; final bootstrap10000; simulator inner1999 và tối thiểu2000 outer/scenario; Wilson size upper≤0.035, coverage lower≥0.93, overall-power lower≥0.80.

Các lựa chọn mới được định nghĩa trong file: daily-vector schema, exact resampling procedure, DGP score generators, VAR fit/stress, oracle-truth interface, statuses, MC precision checks và module contracts. Không âm thầm coi chúng đã được freeze trong main1.8. Nếu đã có freeze/release thực tế, version protocol trước khi dùng dữ liệu xác nhận mới.

Không đổi δ/Δ_alt bằng observed pilot mean, không tune DGP để gate đạt, không tăng budget sau khi xem B5. Một lần gate pass không là distribution-free guarantee cho NBA.

## 3. Input contracts và blockers

### 3.1. Prediction ledger trước khi aggregate

Mỗi row có `(game_id,player_id,stat,cutoff)`, season_id, scheduled UTC game_date, reference book/canonical main market, half-point line, two-side odds, raw market r, p_H, p_SH, y, settled/entered flags, source/activation timestamps, model/feature/recipe hashes.

Population theo main §11.7.1: Regular Season, entered/settled, main half-point PTS/REB/AST, snapshot mới nhất không sau cutoff60 phút và không cũ hơn15 phút so với cutoff. One canonical row/player-game-stat; book đã khóa. Integer lines/Push/void không nhập binary primary score. Không gán Push=Under.

p_H và p_SH phải là predictions prequential của **hai fitted pipelines**, không raw market odds đối chiếu với stats model tùy ý. r_market đã de-vig là input của H, không tự bằng p_H.

### 3.2. Daily vectors

Cho stat s trong ngày d:

`S_ds=Σ_(eligible rows d,s) [(p_H−y)²−(p_SH−y)²]`;

`N_ds=count_(eligible rows d,s)`.

Ngày có trận theo locked schedule nhưng không có eligible props giữ N=0,S=0. Ngày không có Regular Season game không tính vào T. Missing collection không tự là genuine empty day: lưu `data_missing` và coverage audit, không che collector failure bằng0 counts.

Giữ vector sáu chiều `V_d=(S_d,PTS,S_d,REB,S_d,AST,N_d,PTS,N_d,REB,N_d,AST)` cùng calendar date, gap_days, season và provenance. Toàn bộ games/player/stat của ngày dùng chung bootstrap indices. Chỉ được aggregate sau khi ledger audit pass.

### 3.3. Blockers hiện tại

- Chưa có reference book/source hoặc B3/B4 historical snapshots đúng cutoff→BLOCKED_DATA.
- Chưa có genuine prequential replay theo availability/refit→BLOCKED_REPLAY.
- Chưa đủ140/280 scheduled dates→BLOCKED_PILOT/BLOCKED_SMALL_PILOT như main plan.
- Có code/kernel tests nhưng chưa có B4 thật→IMPLEMENTED_UNVALIDATED, không GATE_PASS.

Data giả được dùng để test phần mềm, không cộng vào exposure pilot thật.

## 4. Estimator, influence và Ω

Trong window W gồm T dates, `C_s=Σ_d N_ds>0`, `μhat_s=Σ_d S_ds/C_s`:

`Δhat_W=(μhat_PTS+μhat_REB+μhat_AST)/3`.

Không lấy mean của daily means, không lấy một tỷ số gộp mọi stats nếu muốn mỗi stat trọng số1/3. Days/stat counts không đều phải được giữ.

Influence diagnostic cho stationary approximation:

`ψ_d=(1/3)Σ_s (S_ds−μ_s N_ds)/nbar_s`, `nbar_s=E[N_ds]`.

`Ω=Σ_(h=−∞)^∞ Cov(ψ_d,ψ_(d+h))` là scalar long-run variance của pooled estimator. Nếu dùng covariance matrix Λ của six-dimensional vector, `Ω=gᵀΛg` với gradient `∂Δ/∂E[S_s]=1/(3E[N_s])`, `∂Δ/∂E[N_s]=−μ_s/(3E[N_s])`.

Đây là approximation/diagnostic, không giả định stationarity qua offseason. Main computation dùng ratio statistic trong từng bootstrap replicate:

`Ω_point=T×Var_boot(Δhat*)`, sample variance ddof1.

Planning uncertainty:1000 outer resamples của B4, mỗi outer1999 inner resamples; tính Ω_b cho mỗi outer rồi `Ω_U=quantile_0.95(Ω_b)`. Ω_U là working upper estimate, **không** cận confidence95 có coverage đã biết. Không cộng thêm cluster design-effect vào variance đã chứa cùng dependence.

`T_req=ceil[(z_0.975+z_0.80)² Ω_U/(0.002−0.001)²]`.

`T_precision=z_0.975² Ω_U/(0.0005)²` chỉ report. T_req là initial planning, không assurance; invalid/zero/unidentifiable Ω không được làm T_req0 để pass.

### 4.1. RMS và Brier identity trước planning

Với p=p_SH, q=p_H, a=p−q và m=E[Y|past,state]: `d=a²+2a(Y−p)`, nên `E[d]=E[a²]+2E[a(m−p)]`.

Theo đúng equal-stat weighting, `rms_pool=sqrt[(1/3)Σ_s mean_i((p_i−q_i)²)]`. Nếu residual orthogonality E[a(Y−p)]=0 trên cùng population/weights thì Δ=rms_pool². δ0.001 tương ứng ideal RMS3.1623 percentage points; alt0.002 tương ứng4.4721 points.

RMS tính được từ forecasts không cần outcomes, nhưng không là upper bound cho trueΔ hoặc automatic futility khi p chưa đúng conditional mean. Report cùng exposure/count mix, không đổiδ hoặc invent effectθ từ RMS. Planning variance dùng paired-score Ω, không dùng σ lợi nhuận0.95 của bảng ROI.

## 5. Season-stratified moving-block bootstrap được chốt

Input phải sorted theo scheduled UTC dates, không duplicate date. Season segments được xác định từ metadata/schedule, không nối hai mùa chỉ vì rows kề nhau.

Với mỗi season segment có T_b dates:

1. Block length l14; valid starts j0..T_b−l, block chứa l **scheduled game dates**, giữ actual gap/calendar metadata.
2. Sample starts uniformly có replacement, concatenate full blocks trong season đó, cắt block cuối để được đúng T_b resampled rows.
3. Không wrap last date về first date; không lấy block cross-season. Season output giữ nguyên T_b; ghép các season outputs theo thứ tự.
4. Tính lại ba sums/count ratios trong replicate. Không giữ count denominators gốc khi bootstrap numerator.

Nếu T_b<l: procedure chính không có valid start→INVALID_BOOTSTRAP_SEGMENT; không tự dùng l nhỏ hơn hoặc loại season. Main1.8 đã yêu cầu fail khi không có valid block start. Phải kiểm tra planned B5 season shape trước release; muốn hỗ trợ short-segment bootstrap cần protocol version riêng.

MBB không wrap có boundary under-sampling; đây là hạn chế được tài liệu arch nêu, không phải bootstrap tốt nhất mặc định [2]. Giữ nó để khớp candidate đã đăng ký, test bằng DGP độc lập; nếu thất bại, nghiên cứu CI/bootstrap khác rồi đăng ký lại, không chọn method bằng B5.

Final CI: percentile2.5/97.5 với quantile method `linear`,10000 replicates, actual procedure seed20261109. Sensitivity l7/28 không cứu kết luận chính nếu l14 invalid. Mọi bootstrap replicate có C_s=0 là invalid; không discard rồi redraw cho tới khi đủ đẹp. B5 original có≥100 eligible pairs/stat; sai điều kiện→CI_INVALID.

MBB bảo toàn covariance giữa scores/counts/stat trong cùng resampled date, nhưng không tự mô phỏng retraining causal feedback. Phân biệt inference bootstrap trên forecasts đã tạo với adaptive DGP ở §10.

## 6. CI decision và futility state machine

Final CI[L,U], δ0.001:

- L>δ và data/inference gate hợp lệ→ADOPT.
- U<δ→DO_NOT_ADOPT.
- Nếu −δ<L và U<δ, thêm practical-equivalence label; U<0 thêm harm label.
- Còn lại→INCONCLUSIVE.
- CI invalid không được map sang no-signal/futility; technical failure riêng.

Width `(U−L)/2` không điều kiện ADOPT. L>δ của CI95 hai phía tương ứng nominal one-sided2.5% khi CI hợp lệ; ngưỡng simulation0.035 là tolerance, không đổi nominal alpha thành3.5%.

Pilot: tại đúng prefixes140/280, đủ≥100 pairs/stat thì tính CI cùng method. U_j<δ→STOP_PILOT_FUTILITY, không ADOPT, không kết luận equivalence. Thiếu counts140→skip statistical look; thiếu280→BLOCKED_DATA. Không thử thêm ngày141/150 vì p-value đẹp hơn.

Với final rejection event A và continuation C đã định trước, `P(A∩C)≤P(A)`. Điều này không bảo đảm một final test vốn under-cover sẽ đúng. Khi pilot được dùng đổi recipe/inference thresholds, bất đẳng thức không hợp thức hóa toàn bộ thay đổi đó.

B4G: sau pilot đóng đến hết ngày UTC chứa release R; không chấm/tune inference gate bằng paired outcomes B4G. B5 bắt đầu scheduled date đầu từ ngày sau R,200 dates, settlement/corrections tối đa7 ngày sau window. Không backdate release hoặc append outcomes cho tới khi ADOPT.

## 7. Wilson bounds và MC denominators

Với k successes trong n independent outer datasets, p_hat=k/n, z=z_0.975:

`den=1+z²/n`;

`center=(p_hat+z²/(2n))/den`;

`half=z sqrt[p_hat(1−p_hat)/n+z²/(4n²)]/den`;

`[W_L,W_U]=[center−half,center+half]`.

n phải>0; no successes không có nghĩa true rate0 chắc chắn. Dùng `method='wilson'` để cross-check với statsmodels [1]. Đây là MC uncertainty của tỷ lệ dưới DGP, không CI cho actual NBA ROI/Δ.

Mỗi DGP/scenario/T report:

- overall ADOPT: denominator **tất cả outer datasets**, kể cả stop-pilot.
- conditional ADOPT: denominator continuation datasets; no continuation→undefined, không0/1 giả.
- unconditional final-CI coverage: tính counterfactual final CI cho mọi outer datasets, kể cả research đã stop; simulation có thể tiếp tục shadow path chỉ để đo diagnostic.
- conditional coverage: chỉ các datasets thật sự continue; report selection effect riêng.
- P(stop140), P(stop280), budget/technical stop, invalid-CI rate, width/bias và calendar savings.

Main coverage gate≥0.93 áp vào unconditional final-CI coverage; conditional coverage vẫn phải report và audit trước release, không được gộp hai denominators. Nếu muốn conditional coverage cũng là pass threshold, đăng ký thành yêu cầu mới trước run, không đổi sau khi nhìn kết quả.

Invalid dataset/CI không được drop để Wilson đẹp hơn: count invalid như non-covered/non-adopted để report, đồng thời gate technical validity fail nếu có unresolved invalid replicates. Không dùng technical failures làm size nhỏ để pass.

Pointwise Wilson95 per cell không là simultaneous95 cho toàn suite. Báo số cells và thêm multiplicity sensitivity dùng z_(1−0.05/(2J)) cho J acceptance proportions đã khóa. Main pass vẫn giữ pointwise rules của1.8; không quảng cáo đó là family-wise MC assurance. Nếu đổi sang simultaneous MC decision thì version gate trước B5.

## 8. DGP score-level: biết truth nhưng không giả là NBA games

Mục đích: kiểm tra inference kernel trên paired-score/count processes. Các S giả có thể vượt bounds của realized Brier differences; **không clip** để làm giống thật rồi vẫn giữ truth cũ. Score surrogate không đủ pass adaptive gate.

Khóa template counts N_ds của một lịch B4/B5 scenario **trước outcomes mô phỏng**. Counts có thể khác theo ngày/stat và bằng0; C_s>0. DGP true estimand tại fixed template là:

`Δ_true=(1/3)Σ_s [Σ_d E(S_ds|template)/C_s]`.

Core effect levels θ_s=θ chung, θ∈{0,0.001,0.002}. Generate:

`S_ds=N_ds θ_s+sqrt(N_ds) e_ds`, và S0 khi N0.

Nếu E[e_ds|template]=0 thì Δ_true=θ **chính xác theo DGP**, không chỉ gần bằng observed sample mean. Stress seasonal mean/drift dùng θ_ds với weighted centering sao cho cùng pooled target; lưu formula, không cộng một hằng số vào sums mà bỏ qua counts.

### 8.1. DGP1: season-stratified residual blocks, l_DGP7 và14

Pilot residual vectors theo season: `r_ds=(S_ds−μhat_season,s N_ds)/sqrt(N_ds)` nếu N>0, otherwise0. Không coi r0 ở missing/stat-count0 như observed perfect forecast; track masks và template transport validity.

Resample full3-vector r bằng MBB trong donor season, dùng l_DGP7/14, map tới target template theo season-phase mapping đã khóa. Target counts giữ cố định. Do no-wrap blocks làm boundary positions có donor distribution khác nhau, center **mỗi target position**:

`e_d=r_(J_d)−E_J[r_(J_d)]`.

E_J tính đúng bằng average qua mọi valid starts cho offset của position trong sampled block, không center bằng sample mean của chính simulated future path. Với block cuối bị cắt, offsets tương ứng vẫn giữ như algorithm. Season-phase donor mapping, masks, counts shapes cần audit; không đủ matching→DGP_TRANSPORT_UNVALIDATED.

Nhờ position-centering, E[e_d]=0 dưới donor sampler cố định, trueθ được biết. Không tự gọi đây là valid joint player/market generator, cũng không coi DGP giống bootstrap là bằng chứng duy nhất.

### 8.2. DGP2: vector VAR với calendar-gap và season reset

Fit3-dimensional residual process r trên B4, dùng các within-season pairs gap1 calendar day có đủ observed counts. Center residuals theo fitted season means, ridge fit:

`A0=(Σ r_d r_(d−1)ᵀ)(Σ r_(d−1)r_(d−1)ᵀ+λI)^−1`.

V1 λ=0.1×trace(second matrix without ridge)/3, floor1e-12. Enforce stable working matrix `A=A0 min(1,0.95/||A0||_2)`; không có đủ valid pairs(≥50)→DGP2_UNFIT, không bịa dependence0.

Innovations residuals r_d−Ar_prev; covariance Q=0.9Q_sample+0.1diag(Q_sample)+jitter I, jitter1e-8×max(trace(Q_sample)/3,1e-12). Σ∞ giải discrete Lyapunov `Σ∞=AΣ∞Aᵀ+Q`.

Trong cùng season, gap h calendar days:

`e_d=A^h e_prev+η_d`, `η_d~N(0,Q_h)`, `Q_h=Σ∞−A^hΣ∞(A^h)ᵀ`.

Đầu season sample N(0,Σ∞), không coi offseason là adjacent game-date lag1. Q_h phải PSD trong numerical tolerance; negative eigenvalue lớn→fit invalid, không sửa mọi covariance sai bằng clipping im lặng.

e có zero mean nên score generator phía trên giữ exact θ với fixed counts. Shared innovations/covariance giữ cross-stat dependence ở daily level. Season means/count density và roster/game-level correlation chưa được mô tả đầy đủ; report giới hạn.

### 8.3. DGP3: variance/persistence stress có scale đo được

Dựa vào DGP2, đăng ký persistence multiplier1.0 và1.1, cap spectral norm0.98; refit stationary covariance nhất quán với A_stress/Q. Đăng ký variance targets `max(Ω_base,Ω_U)` và `max(Ω_base,1.5Ω_U)`; không chọn target thấp hơn để gate đẹp.

Với fixed template, đặt weight vector `v_ds=sqrt(N_ds)/(3C_s)`. Khi `S=Nθ+sqrt(N)e`:

`Var(Δhat)=Σ_(d,d') v_dᵀ Cov(e_d,e_d') v_(d')`.

Tính covariance từ VAR/gap/season reset, `Ω_base=T Var(Δhat)`. Nhân toàn residual vector bởi `c=sqrt(Ω_target/Ω_base)` để đạt target scalar. Nếu Ω_base0/không xác định thì scenario invalid. Scaling cả vector giữ correlation structure, không chỉ tăng diagonal một stat rồi gọi đã stress pooledΩ.

Các persistence/variance levels trên là stress assumptions mới, cần pilot uncertainty/transport audit và registry; không ước lượng được từ B4 thì gate chưa validated, không gọi là thực nghiệm NBA đã biết.

## 9. DGP pipeline: true paired gain và weekly-refit feedback

Score-level DGP1–3 không tái tạo feature updates, market changes, fitted H/SH hoặc learned parameters. Full adaptive gate phải có **ít nhất một pipeline-generating adapter hợp lệ**, thêm vào scenarios mandatory, không thay bằng score-shift.

### 9.1. Một cấu trúc generator có thể triển khai

Khóa schedule/roster/availability/line templates và exogenous pregame covariates; mỗi synthetic path có burn-in/training history trước pilot đủ cho recipe. Không copy future outcomes vào template features. Rolling/shrinkage/return features được dựng lại từ outcomes đã available trong synthetic path.

Latent state h_d theo VAR/season model, player/game factors có parameter manifest. Conditional count model ứng viên:

`μ_true,i,s,d=exp(α_s+b_sᵀ x_i,d+loadings_sᵀ h_d)`;

`X_i,s,d ~ NB2(μ_true,i,s,d,φ_true,s)`.

Để tạo dependence trong game giữa players/stats, sample vector Z~N(0,R_game), diagR=1, R PSD; `U=Φ(Z)`, `X=F_NB^−1(U)`. Conditional vào latent state trước draw, từng marginal vẫn NB, cross-player/stat covariance do copula. Model này là sports surrogate, không tự bảo toàn mọi box-score/team constraints; declare phạm vi và stress misspecification.

Generate observable market probability từ restricted pregame covariates/latent-noise process riêng:

`r_market=clip(sigmoid(a_m+b_mᵀ x_market+ε_market),0.05,0.95)`.

Đặt implied quotes `u_O=(1+v)r_market`, `u_U=(1+v)(1−r_market)`, v=0.02 ở core, odds1/u; timestamp trong đúng snapshot window. Quote process không nhìn realized X hoặc future latent innovations. Có thể stress market efficiency/noise, nhưng parameters phải fit/register bằng pilot/development, không tùy chỉnh sau gate failures để “tạo edge”.

Run lại actual feature builders, priors/base model/G/H/SH theo locked weekly-refit, labels available≥48h, windows730 days/84 dates(42G+42stack) đúng main recipe. Training searches12 configs **không chạy lại mỗi tuần**: class/features/hyperparameters đã khóa; chỉ fitted parameters cập nhật. G/rate/phi recipe mới từ specs khác phải được ghi rõ version trước replay.

### 9.2. Truth của adaptive pipeline không phải coefficient của DGP

Với p=p_SH, q=p_H và known true event probability m ở state trước outcome:

`g_i=E[d_i|past,state]=(q_i−m_i)²−(p_i−m_i)²`.

Trong count generator trên, `m_i=P(X>line|state)` từ NB SF nếu copula draws có marginal standard normal và chưa conditioning lên một future draw. Nếu có thêm conditional latent factors ở copula, oracle phải tích hợp đúng, không mặc định NB marginal khi điều kiện đã đổi.

Δ_true,T là expected pooled ratio score gain của **thuật toán refit** trên horizon template, lấy expectation qua paths/refits; không là mean g của một path duy nhất. Dùng independent high-precision oracle simulation, có seeds riêng và oracle CI. Điều này giảm outcome noise ở g nhưng không loại training/path uncertainty.

Effect injection chỉ được điều chỉnh **generator parameters** (signal/market noise/context), chạy lại pipeline và oracle. Không dịch observed d hoặc p_SH sau khi fit để giả Δ_alt. Gain có thể không monotone/không đạt0.002; nếu root/target không khả thi→TARGET_EFFECT_UNATTAINABLE, không giả kết quả.

### 9.3. Numerical truth và boundary audit

Score surrogate có exact truth0/δ/alt. Adaptive truth thường cần oracle estimate: default oracle CI halfwidth≤1e-5 Brier units, dataset/seeds độc lập acceptance suite. Lưu interval[θ_L,θ_U] và sensitivity, không coi estimated mean là truth exact.

Cho null adaptive scenarios, require θ_U≤δ; gần-boundary case target interval trong[δ−2e-5,δ]. Cho alt target interval nằm trong[0.002−1e-5,0.002+1e-5]. Không đạt tolerance/boundary→TRUTH_UNCERTIFIED. Báo gần-boundary, không nói đã mô phỏng chính xácΔ=δ cho adaptive generator. Mandatory score scenarios vẫn kiểm tra exact boundaryδ.

Coverage conservative event khi truth có interval là `L≤θ_L và U≥θ_U`; report riêng với point-truth coverage. Numeric truth uncertainty không được lờ đi để pass. Các tolerances này là chi tiết hóa mới phải version; không là guarantee size đúng cho mọi possible adaptive DGP.

Nếu chưa implement/fit được valid adapter, có thể report `SCORE_KERNEL_VALIDATED` sau score suite, **không** ADAPTIVE_GATE_PASS và không mở B5 theo gate này. Đó là blocker khoa học thật, không được code agent thay bằng VAR trên d cố định.

## 10. Full-study simulation và tránh vòng đệ quy gate

Một outer dataset là **một nghiên cứu hoàn chỉnh**, gồm synthetic/replayed training context, pilot tới280 dates, B4G assumption và future B5 horizon. Không chỉ generate200 final dates rồi bỏ futility/refits.

Cho mỗi path:

1. Dựng training/burn-in và weekly updates theo adapter; tạo pilot predictions as-of.
2. Tính prefix140 CI, có thể futility stop; nếu continue tính280.
3. Nếu continue, rerun Ω_point/Ω_U/planning feasibility của synthetic pilot bằng đúng registered algorithm; T_req>budget→budget stop. Model failures theo cùng production rules.
4. Run future200-date algorithm nếu continue; final CI và decision. Để đo unconditional coverage/bias, generate counterfactual continuation path cho stopped studies nhưng không tính nó là ADOPT thật.
5. Record unconditional/conditional denominators, stop reasons và final labels.

Score-level suite dùng score generators thay actual learner, nên chỉ conditional-on-score-process claims. Adaptive suite cần actual refit replay.

**Không đệ quy gọi toàn validation suite bên trong mỗi outer study.** MC suite là bước design approval ở ngoài. Bên trong replicate phải giữ các stochastic pilot/refit/futility/Ω-planning rules; external acceptance of this same simulation suite không được tự gọi vô hạn. Báo operating characteristics **conditional vào registered inference design và DGP fitted từ pilot**, không claim đã tích phân mọi research decision/data-dependent DGP selection.

Nếu muốn đo cả việc nhà nghiên cứu đổi CI/DGP/recipe theo pilot, cần outer research-process simulation riêng; không coi pass hiện tại tự bao phủ tất cả adaptation. Không được bỏ Ω-planning step trong overall power mà không đổi nhãn thành conditional diagnostic.

Computation nested1000×1999 Ω trong mỗi outer rất đắt. Có thể optimize/cache deterministic block sums/indices và vectorize, nhưng không thay estimator bằng shortcut chưa kiểm tra. Run rẻ hơn chỉ là smoke/conditional mode, không tự pass gate hoàn chỉnh.

## 11. Acceptance rules, MC precision và T-grid

### 11.1. Gate theo mỗi registered scenario

Tối thiểu2000 independent outer datasets/scenario. Cho θ0 vàδ(score exact), Wilson95 upper của P(ADOPT overall)≤0.035. Cho θ_alt, Wilson95 lower của overall power≥0.80. Unconditional final-CI coverage Wilson95 lower≥0.93. Adaptive null/alt có oracle conditions ở §9 và report approximation labels.

Pass cần **mọi mandatory scenario** đạt, no unresolved technical/data/truth invalidity và adaptive adapter validated. Không average qua DGP để che một stress case fail. Conditional power không thay overall power; nếu P(continue)<0.80 thì tăng T không thể cứu overall power80% với cùng pilot rule.

Wilson95 chỉ mô tả Monte Carlo uncertainty conditional DGP/config. Không dùng chữ “coverage chính xác” hoặc “true type-I NBA đã biết”. Counts/schedule/market/refit drift ngoài scenarios vẫn là model risk.

### 11.2. Inner1999 so với final10000

Simulation inner1999 là approximation của actual procedure10000. Trên subset500 outer datasets được chỉ định bằng indices trước run, recompute10000 với RNG stream prefix coupling. Report label disagreement, CI endpoint changes và MC intervals.

Operational precision screen mới: Wilson95 upper của disagreement rate≤0.01 và percentile95 absolute CI-endpoint differences≤1e-4. Không đạt thì rerun acceptance suite với10000 inner trên toàn scenarios; không chọn phiên bản cho tỷ lệ pass cao hơn. Đây là numerical screen đề xuất, cần manifest, không guarantee1999 là đủ cho mọi DGP.

Actual procedure seed20261109 được giữ cố định khi replay mỗi dataset; outer DGP seeds độc lập. Không dùng Python hash() để tạo seed do hash randomization. Dùng SHA256 semantic IDs/SeedSequence có version; actual CI seed cố định khác discovery/validation streams. Cùng dataset so1999/10000 dùng prefix của cùng index stream.

### 11.3. T-grid và independent validation

T∈{100,140,180,200,240,280,320,400,480,560}. T là số dates của **future window**, pilot vẫn140/280 không đổi. Season/calendar/count shape của mỗi T khóa từ schedule/template assumptions, không tùy chọn seasons có scores tốt.

Discovery tìm T_min_grid nhỏ nhất quan sát đạt mọi checks. Sau đó independent validation với outer datasets/seeds mới cho candidate T_min_grid và budget200; nếu cùng T thì chỉ một validation run. Không giả kết quả monotone theo T, không reuse discovery lucky runs để báo validated.

Budget B5 mặc định vẫn200. T200 không đạt→STOP_FEASIBILITY cho recipe/budget, dù grid có T lớn đạt. Muốn tăng T phải đăng ký protocol mới trước B5, không extend theo paired outcomes. Nếu không có T đạt hoặc continuation ceiling thấp, báo rõ.

## 12. Reference kernels có thể chép thành code

Đoạn dưới chỉ là **numerical core**, không DGP/refit suite hoàn chỉnh và không đủ để pass gate. Daily dates/season ordering, IDs/provenance phải validate ở caller.

```python
from statistics import NormalDist
import numpy as np

def pooled_delta(sums, counts):
    sums = np.asarray(sums, dtype=float)
    counts = np.asarray(counts, dtype=float)
    if sums.shape != counts.shape or sums.ndim != 2 or sums.shape[1] != 3:
        raise ValueError('Expected equal (T,3) arrays')
    if not np.isfinite(sums).all() or not np.isfinite(counts).all():
        raise ValueError('Nonfinite values')
    if (counts < 0).any() or not np.equal(counts, np.floor(counts)).all():
        raise ValueError('Counts must be nonnegative integers')
    if ((counts == 0) & (sums != 0)).any():
        raise ValueError('Zero count requires zero sum')
    den = counts.sum(axis=0)
    if (den <= 0).any():
        raise ValueError('Every stat needs observations')
    return float(np.mean(sums.sum(axis=0) / den))

def season_mbb_indices(seasons, block_length, rng):
    seasons = np.asarray(seasons)
    n = len(seasons)
    if n == 0 or not isinstance(block_length, int) or block_length < 1:
        raise ValueError('Invalid bootstrap arguments')
    cuts = np.r_[0, np.flatnonzero(seasons[1:] != seasons[:-1]) + 1, n]
    labels = [seasons[a] for a in cuts[:-1]]
    if len(set(labels)) != len(labels):
        raise ValueError('Each season must be one contiguous segment')
    out = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        size = int(b - a)
        if size < block_length:
            raise ValueError('INVALID_BOOTSTRAP_SEGMENT')
        starts = rng.integers(0, size - block_length + 1,
                              size=(size + block_length - 1) // block_length)
        idx = np.concatenate([a + j + np.arange(block_length) for j in starts])
        out.extend(idx[:size])
    return np.asarray(out, dtype=int)

def percentile_ci(sums, counts, seasons, reps=10000, block_length=14,
                  seed=20261109):
    sums = np.asarray(sums, dtype=float)
    counts = np.asarray(counts, dtype=float)
    pooled_delta(sums, counts)
    if len(seasons) != len(sums) or reps < 2:
        raise ValueError('Invalid lengths/replications')
    rng = np.random.default_rng(seed)
    estimates = np.empty(reps)
    for b in range(reps):
        idx = season_mbb_indices(seasons, block_length, rng)
        estimates[b] = pooled_delta(sums[idx], counts[idx])
    bounds = np.quantile(estimates, [0.025, 0.975], method='linear')
    return tuple(map(float, bounds)), estimates

def wilson(k, n, alpha=0.05):
    if not (0 < alpha < 1) or n <= 0 or not (0 <= k <= n):
        raise ValueError('Invalid binomial summary')
    if int(k) != k or int(n) != n:
        raise ValueError('Expected integer counts')
    z = NormalDist().inv_cdf(1 - alpha / 2)
    phat = k / n
    den = 1 + z*z/n
    center = (phat + z*z/(2*n)) / den
    half = z * np.sqrt(phat*(1-phat)/n + z*z/(4*n*n)) / den
    return max(0., center-half), min(1., center+half)

def final_decision(lower, upper, margin=0.001):
    if not np.isfinite([lower, upper, margin]).all() or lower > upper:
        raise ValueError('CI_INVALID')
    if margin <= 0:
        raise ValueError('Margin must be positive')
    if lower > margin:
        return 'ADOPT'
    if upper < margin:
        return 'DO_NOT_ADOPT'
    return 'INCONCLUSIVE'
```

Production wrapper phải kiểm tra ≥100 pairs/stat, data/gate status, convergence và guards; không gọi final_decision đơn lẻ để tự ADOPT khi gate chưa pass. Numeric core không kiểm tra score realizability để còn hỗ trợ surrogate DGP; real-ledger validator phải kiểm tra S∈[−N,N] trong tolerance và Brier rows thực.

Kernels trong file đã được extract/chạy trên fixtures nhỏ: pooled ratio, season boundaries, constant-score bootstrap, strict decision boundaries và Wilson đối chiếu nghiệm phương trình score bằng SciPy. Chưa chạy full2000-outer suite, chưa kiểm chứng empirical coverage NBA; statsmodels cross-check là test yêu cầu cho implementation đầy đủ, chưa chạy ở môi trường soạn tài liệu.

## 13. Module layout và state machine triển khai

```text
simulation_gate/
  config.py              # immutable recipe/scenario registry
  ledger.py              # population, snapshots, availability audit
  daily_vectors.py       # canonical scheduled-date aggregation
  bootstrap.py           # season MBB + ratio CI
  variance.py            # scalar Omega, nested working Omega_U, planning
  decision.py            # futility/final labels, no alpha-look creep
  dgp_score.py           # DGP1/2/3 exact score-surrogate truths
  dgp_pipeline.py        # valid count/market/refit adapter + oracle truth
  study_runner.py        # complete study/pilot/refit/planning/final
  monte_carlo.py         # independent outer paths, Wilson, precision audit
  gate.py                # all-scenarios decision and release guards
  report.py              # manifest/tables/artifact provenance
```

Statuses:

`SPECIFIED → IMPLEMENTED_UNVALIDATED → DATA_READY → PILOT_COMPLETE → SUITE_RUNNING → SCORE_KERNEL_VALIDATED → ADAPTIVE_GATE_PASS → REGISTRATION_RELEASED`.

Các nhánh dừng có reasons: BLOCKED_DATA/REPLAY/SMALL_PILOT, STOP_PILOT_FUTILITY, TRUTH_UNCERTIFIED, DGP_UNFIT, GATE_UNVALIDATED, STOP_INFERENCE_FEASIBILITY, STOP_FEASIBILITY. SCORE_KERNEL_VALIDATED không tự nhảy release nếu chưa có adaptive adapter hoặc dữ liệu thật.

Không tạo scheduled automation, đặt cược hoặc mở B5 chỉ từ việc có file spec. Release là artifact/manifest thực có timestamps, không label trong unit test.

## 14. Tests, compute budget và report

Correctness tests:

- [ ] Pooled ratio khác unweighted mean ngày khi counts khác; zero-day vẫn giữ.
- [ ] Bootstrap tất cả stats dùng chung indices; không cross-season/wrap; short segment fail.
- [ ] C_s0 replicate không bị discard/redraw; original counts floor100/stat được enforce.
- [ ] Wilson k0/kn/n2000 khớp statsmodels; invalid denominator/float counts fail.
- [ ] ExactlyL=δ hoặcU=δ không ADOPT/DO_NOT_ADOPT bằng strict inequalities.
- [ ] Futility chỉ140/280, không efficacy stop; correct overall/conditional denominators.
- [ ] Ω là scalar; nested Ω_U reproducible và no design-effect double count.
- [ ] DGP1 position-centering có exact sampler expectation0; không center từng future realization vềθ làm mất variance mean.
- [ ] VAR gap/season/covariance PSD, stress scalarΩ đúng; zero-count handling có audit.
- [ ] Oracle trueΔ thuộc target/tolerance được xác minh bằng independent runs; không shift d của adaptive path.
- [ ] Full adapter thực chạy weekly refits/48h availability, rolling updates từ synthetic past; frozen comparator không được tráo primary.
- [ ] Independent discovery/validation seeds, chunk resume không tạo duplicate outer paths; bootstrap seed policy khớp actual procedure.
- [ ] Gate all-scenarios, numerical precision, invalid-data/truth guards; toy smoke không được pass release.

Smoke mode:10–50 outer,199–499 inner để kiểm tra correctness/runtime; luôn `NOT_FOR_GATE`. Full mode giữ budgets đã đăng ký. Chunk outer paths theo semantic IDs, checkpoint sau mỗi chunk, output summaries deterministic; không chọn ngừng MC khi Wilson vừa pass nếu chưa có sequential MC design đã đăng ký.

Tối thiểu phải pilot profiling một scenario đầy đủ trước khi hứa runtime. Caching/parallel workers chỉ thay cách tính, không bỏ refit/Ω steps. Nếu budget máy cá nhân không đủ, báo COMPUTE_BLOCKED hoặc conditional diagnostic, không giảm replications rồi giữ tên gate assurance.

Report gồm: raw ledger/schedule hashes, B4/B4G/B5 shapes, recipe/refit/archive versions, fitted DGP parameters, oracle truth intervals, seeds/MC sample counts, size/coverage/power Wilson tables, unconditional/conditional labels, invalid counts, Ω uncertainty, T_req/T_min_grid/T_min_validated, runtime và scope limitations.

## 15. Bàn giao và thứ tự thực hiện

1. Code numerical kernels, test synthetic fixtures và Wilson/bootstrap/decision correctness; không cần odds thật để làm bước này.
2. Build ledger/snapshot ingestion và paired H/SH prequential replay. Nếu thiếu historical odds giữ BLOCKED_DATA, bắt đầu lưu dữ liệu tương lai theo tác vụ được triển khai riêng.
3. Tạo daily vectors B4, futility/checkpoints, Ω planning và timeline manifest.
4. Implement DGP1/2/3 với exact surrogate truth; validate inference kernel, ghi giới hạn conditional-on-score-process.
5. Implement adaptive generator/replay adapter và oracle, chạy full workflow; chưa có thì không mở release gate.
6. Discovery suite/T-grid rồi independent validation; all checks pass mới tạo registration R cho future B5.

Đề nghị agent trả code references/test logs/artifact paths theo từng bước, không chỉ nói “đã viết xong gate”. Ba bet thắng, paper ROI hoặc unit tests pass không thay các đầu vào/validation nói trên.

## 16. Nguồn và phạm vi hỗ trợ

1. [statsmodels — proportion_confint](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.proportion_confint.html): Wilson binomial intervals; không xác nhận full NBA gate hoặc simultaneous guarantees.
2. [arch — Time-series Bootstraps](https://arch.readthedocs.io/en/latest/bootstrap/timeseries-bootstraps.html): moving/stationary/circular variants và boundary limitation của no-wrap MBB; không chọn optimal block length cho ứng dụng này.
3. [Kế hoạch chính NBA_PLAYER_PROPS_PLAN.md](https://chatgpt.com/library?file_id=libfile_277ca19137e08191b2dd587c50debe54&account_id=61294741-651c-40c7-b521-b699e7d014b8).
4. [Stats-only selection fix spec](https://chatgpt.com/library?file_id=libfile_8d0f5bec4c30819184dfecd96e12dd63&account_id=61294741-651c-40c7-b521-b699e7d014b8).

DGP formulas/defaults, oracle tolerances và numerical precision screens là thiết kế đề xuất trong tài liệu, không số thực nghiệm lấy từ nguồn. Gate kiểm tra procedure dưới scenarios/assumptions đã đăng ký; không biết trước true NBA DGP hoặc chứng minh lợi nhuận. Chưa có market B4 dữ liệu thật nên chưa có Ω_U/T_req thực và chưa có gate pass.
