# 📘 CẨM NANG CHIẾN THUẬT & KINH NGHIỆM ĐẶT CƯỢC NBA PROPS
> **Dành cho Người chơi Sắc bén (Sharp Bettor Playbook)**  
> *Được biên soạn dựa trên Mô hình Máy học Poisson/NegBinomial, Hệ thống Phân tích Matchup DvP và Kinh nghiệm Thực chiến NBA.*

---

## MỤC LỤC
1. [Phần I: Quy Trình Phễu 4 Bước Chọn Kèo Trên Web](#phần-i-quy-trình-phễu-4-bước-chọn-kèo-trên-web)
2. [Phần II: Chiến Thuật Tối Ưu Vé Xiên 3 Chân (3-Leg Parlays)](#phần-ii-chiến-thuật-tối-ưu-vé-xiên-3-chân-3-leg-parlays)
3. [Phần III: Nghệ Thuật Chọn Kèo Khi Nhà Cái Chỉ Mở Points (Only-Points)](#phần-iii-nghệ-thuật-chọn-kèo-khi-nhà-cái-chỉ-mở-points-only-points)
4. [Phần IV: Các Kinh Nghiệm Thực Chiến Đắt Giá (Chưa Được Nhắc Tới)](#phần-iv-các-kinh-nghiệm-thực-chiến-đắt-giá-chưa-được-nhắc-tới)
5. [Phần V: Quản Lý Vốn & Kỷ Luật Tâm Lý (Bankroll & Mindset)](#phần-v-quản-lý-vốn--kỷ-luật-tâm-lý-bankroll--mindset)
6. [Checklist 60 Giây Trước Khi Đặt Cược](#checklist-60-giây-trước-khi-đặt-cược)

---

## PHẦN I: QUY TRÌNH PHỄU 4 BƯỚC CHỌN KÈO TRÊN WEB

Để duy trì tỷ lệ thắng (Win Rate) trên 55% dài hạn với odd chuẩn -110 (1.91), bạn phải áp dụng quy trình lọc phễu từ thô đến tinh.

```
       [Toàn Bộ Danh Sách Kèo Hôm Nay]
                      │
                      ▼
    [BƯỚC 1: FastCheck - Lọc Thô Toán Học]
    • Win Probability ≥ 56.0% | Edge ≥ +5.0%
    • Kelly Stake đề xuất > 0
                      │
                      ▼
    [BƯỚC 2: Oracle Home - Soi Chi Tiết Phân Phối]
    • EV (μ) và Median đồng thuận vượt Line ≥ 1.5 - 2.0 điểm
    • Khoảng tin cậy 90% [L90, U90] không quá bấp bênh
                      │
                      ▼
    [BƯỚC 3: Ma Trận Đối Thủ & Khắc Tinh DvP]
    • Khai thác "Double Green": Def Rtg kém + DvP vị trí Rank 20-30
    • Né "Bẫy Xỉu Ngầm": Def Rtg kém nhưng DvP vị trí Rank 1-8
                      │
                      ▼
    [BƯỚC 4: Thẩm Định Lịch Sử & Báo Cáo ESPN]
    • Bảng 10 trận gần nhất: Tối thiểu 7/10 dải ngang màu Xanh
    • H2H 5 trận gần nhất: Giữ vững hiệu suất nổ Over
    • ESPN Live Injury: Không có bão hạn chế số phút (Minutes Restriction)
                      │
                      ▼
        [CHỐT KÈO VỚI TỶ LỆ THẮNG CAO NHẤT]
```

### Chi tiết các bước:
1. **Bước 1 (FastCheck `/fastcheck.html`)**: Sử dụng OCR hoặc nhập nhanh odds. Bỏ qua toàn bộ các kèo có Edge $< +4\%$ hoặc xác suất thắng $< 54\%$. Điểm hòa vốn lý thuyết là $52.38\%$, do đó phải có biên an toàn (safety buffer) tối thiểu $3 - 5\%$.
2. **Bước 2 (Oracle Home `/`)**: Nhập cầu thủ và đường line. 
   - *Nguyên tắc sống còn:* **EV và Median phải cùng vượt Line**. Nếu $\mu = 26.5 > \text{Line } 24.5$ nhưng $\text{Median} = 22.0$, nghĩa là cầu thủ có 1-2 trận "lên đồng" kéo điểm trung bình ảo $\rightarrow$ BỎ KÈO.
3. **Bước 3 (DvP Matrix)**: Kiểm tra đối thủ phòng ngự vị trí đó như thế nào (Guard, Wing, Big). Ví dụ: Đội A phòng ngự vòng ngoài rất rát nhưng trong rổ để hở $\rightarrow$ Over Center Points, né Over Guard Points.
4. **Bước 4 (Visual Tables)**: Kéo xuống bảng tham khảo. Nếu thấy dải màu xanh chiếm trên 70% và đối đầu lịch sử áp đảo $\rightarrow$ Tự tin vào lệnh.

---

## PHẦN II: CHIẾN THUẬT TỐI ƯU VÉ XIÊN 3 CHÂN (3-LEG PARLAYS)

### 1. Kịch bản 1: 3 Leg CÙNG 1 Trận (Same Game Parlay - SGP)
*Bản chất: Đặt cược vào Kịch Bản Trận Đấu (Game Script).*
* **Công thức Đôi Công Đua Điểm (High-Pace Shootout):**
  * Áp dụng khi: Tổng điểm trận (Total O/U) $\ge 230$, Kèo chấp (Spread) $\le 4.5$ điểm.
  * Leg 1: Ngôi sao số 1 Đội A $\rightarrow$ **OVER Points**.
  * Leg 2: Ngôi sao số 1 Đội B $\rightarrow$ **OVER Points** (Kịch bản rượt đuổi, đánh đến tận giây cuối cùng).
  * Leg 3: Hậu vệ dẫn bóng Đội A **OVER Assists** HOẶC Cầu thủ phụ đánh ở vị trí đối thủ thủ DvP tệ nhất **OVER Points**.
* ⛔ **Cấm kỵ (Cannibalization - Tương quan nghịch):**
  * KHÔNG BAO GIỜ chọn 2 cầu thủ cùng đội cùng OVER Rebounds.
  * KHÔNG chọn 2 cầu thủ dự bị cùng đội cùng OVER Points (họ chia sẻ phút của nhau).

### 2. Kịch bản 2: 2 Leg CÙNG Trận + 1 Leg KHÁC Trận (Hybrid Parlay)
*Bản chất: 1 Cặp tương quan mạnh (The Stack) + 1 Cột mỏ neo an toàn (The Anchor).*
* **Trận 1 (Cặp Stack):** Chọn cặp PG Over Assists + Center Over Points (hoặc Cầu thủ Over Points + Over 3PM).
* **Trận 2 (Chân Anchor):** Đây phải là **kèo độc lập có Edge cao nhất hôm đó**:
  * Cầu thủ có đồng đội ngôi sao nghỉ chấn thương (được xác nhận trên ESPN).
  * Phút thi đấu $\ge 34$ phút.
  * 10 trận gần nhất đạt $\ge 80\%$ dải xanh.
* *Ưu điểm:* Nếu Trận 1 bất ngờ rác trận sớm (blowout), bạn chỉ mất 2 chân trận đó, không bị sụp đổ toàn diện tâm lý.

### 3. Kịch bản 3: 3 Leg KHÁC Trận (Cross-Game Independent)
*Bản chất: Tối đa hóa giá trị toán học thuần túy (Pure EV).*
* Vì là 3 biến cố độc lập ($P_{\text{vé}} = P_1 \times P_2 \times P_3$), tuyệt đối không đánh theo cảm tính.
* **Quy tắc phân bổ:**
  * Chọn ở 3 trận đấu khác nhau có kèo chấp điểm nhỏ (Spread $\le 6.5$ điểm) để tránh kịch bản blowout ngồi ngoài hiệp 4.
  * Trộn loại chỉ số nếu nhà cái cho phép: **1 Points + 1 Rebounds + 1 Assists** (Rebounds và Assists ít biến động theo cảm giác ném hơn Points).

---

## PHẦN III: NGHỆ THUẬT CHỌN KÈO KHI NHÀ CÁI CHỈ MỞ POINTS (ONLY-POINTS)

Khi chỉ được đánh thị trường Ghi điểm (Points), sự tranh chấp bóng (Usage Share) là yếu tố quyết định thắng thua:

### 1. Phân Vùng Line Điểm Số (Line Zones)

| Phân vùng | Ngưỡng Line | Mức độ rủi ro | Lời khuyên thực chiến |
| :--- | :--- | :--- | :--- |
| **Vùng Tử Thần** | $\le 7.5$ (như 4.5, 5.5, 6.5) | 🔴 Cực cao | **CẤM ĐÁNH OVER**. Số phận vé bị định đoạt bởi đúng 1 cú ném rổ duy nhất (trúng 3P = ăn, trượt = gãy). |
| **Vùng Rủi Ro Cao** | $8.5 - 12.5$ | 🟡 Trung bình cao | Cầu thủ dự bị hoặc phòng ngự (3&D). Chỉ đánh khi họ chắc chắn được thi đấu $\ge 26$ phút. |
| **Vùng Ngọt Ngào (Sweet Spot)** | **$13.5 - 26.5$** | 🟢 **Lý tưởng nhất** | **ƯU TIÊN TUYỆT ĐỐI**. Cầu thủ là Option 2 hoặc Option 3 của đội, có 12 - 18 cú ném/trận, có ném phạt bảo hiểm. |
| **Vùng Ngôi Sao Gánh Đội** | $\ge 27.5$ (28.5, 30.5+) | 🟡 Khó lường | Thường bị hàng thủ đối phương chăm sóc đặc biệt (Double-team) và dễ bị rút ra nghỉ nếu cách biệt điểm quá lớn. |

### 2. Chiến Thuật Đánh 3 Leg Cùng 1 Trận Cho Kèo Only-Points
* **Quy tắc bất di bất dịch:** **TUYỆT ĐỐI KHÔNG CHỌN 3 OVER CÙNG 1 ĐỘI**. Tổng điểm 1 đội chỉ khoảng 110-120 điểm, 3 cầu thủ cùng Over điểm sẽ tự triệt tiêu cơ hội ném bóng của nhau.
* **Công thức chuẩn:** **2 Over Đội A + 1 Over Đội B**:
  * Đội A: Ngôi sao chính (Over 24.5+) + Trung phong dứt điểm cận rổ (Over 14.5+).
  * Đội B: Ngôi sao số 1 đáp trả (Over 22.5+).

---

## PHẦN IV: CÁC KINH NGHIỆM THỰC CHIẾN ĐẮT GIÁ (CHƯA ĐƯỢC NHẮC TỚI)

Đây là những kinh nghiệm nâng cao của giới cá cược chuyên nghiệp (Sharp Bettors) giúp bạn nhìn ra những cạm bẫy mà người chơi nghiệp dư thường mắc phải:

### 1. Yếu Tố Thể Lực & Lịch Thi Đấu Dày Đặc (Fatigue & Rest Advantage)
* **Trận thứ 2 trong 2 ngày (Back-to-Back - B2B):**
  * Hiệu suất ném xa (3PT%) của toàn đội giảm trung bình từ $3\% - 5\%$ do mỏi cơ chân (chân không còn bật cao khi ném).
  * Ngôi sao lớn tuổi hoặc có tiền sử chấn thương thường bị giới hạn số phút (chỉ đánh 28 phút thay vì 35 phút).
  * 👉 **Kinh nghiệm:** Tránh cược Over Points cho các tay ném phụ thuộc vào ném 3 điểm khi đội của họ đang đá trận B2B. Ưu tiên **UNDER Points** hoặc chuyển sang **OVER Rebounds** (vì ném trượt nhiều $\rightarrow$ nhiều cơ hội bắt bóng bật bảng).
* **Lịch thi đấu 3 trận trong 4 đêm (3-in-4) hoặc 4-in-5:**
  * Thể lực cạn kiệt, tỷ lệ mất bóng (Turnovers) tăng vọt, tốc độ trận đấu thường bị chậm lại ở hiệp 4.
* **Hiệu Ứng Sân Đấu Vùng Núi Cao (Altitude Effect - Denver & Utah):**
  * Sân của **Denver Nuggets (Ball Arena)** và **Utah Jazz (Delta Center)** nằm ở độ cao hơn 1.200 - 1.600m so với mực nước biển, không khí loãng.
  * Các đội khách bay đến đây thường bị hụt hơi nghiêm trọng từ nửa sau hiệp 3 và cả hiệp 4. Đội khách thường ném hụt rất nhiều ở cuối trận.

---

### 2. Bẫy Rác Trận (Blowout Risk Index) & Kèo Chấp (Spread)
* **Kèo chấp $\ge 10.5 - 14.5$ điểm:**
  * Đây là những trận đấu chênh lệch trình độ quá lớn (Ví dụ: Boston Celtics gặp Washington Wizards).
  * **Rủi ro chí mạng:** Nếu đội mạnh dẫn trước 25 - 30 điểm ở cuối hiệp 3, toàn bộ dàn sao chính sẽ ngồi ghế dự bị uống nước suốt hiệp 4. Cầu thủ dù đang đánh rất hay (được 24 điểm, Line 26.5) cũng sẽ không bao giờ được vào sân nữa.
  * 👉 **Quy tắc thép:** **Chỉ cược OVER Points cho các ngôi sao khi Kèo chấp Spread $\le 7.5$ điểm**. Trận đấu càng giằng co, ngôi sao càng ở lại sân lâu.

---

### 3. Bẫy Lỗi Cá Nhân Khi Chạm Trán "Máy Câu Lỗi" (Foul Trouble Trap)
* Một số cầu thủ tại NBA là chuyên gia câu lỗi đối phương (Free Throw Merchants) như: *Giannis Antetokounmpo, Joel Embiid, Jalen Brunson, Shai Gilgeous-Alexander, Jimmy Butler*.
* **Hậu quả:** Trung phong hoặc hậu vệ phòng ngự chính của đội đối thủ thường dính 2 lỗi cá nhân ngay trong 6 phút đầu tiên của hiệp 1.
* Khi dính 2 lỗi sớm, HLV bắt buộc phải rút cầu thủ đó ra sân để bảo tồn cho hiệp 2. Cầu thủ bị mất nhịp thi đấu và tụt giảm từ 6 - 10 phút thi đấu cả trận.
* 👉 **Kinh nghiệm:** Không bao giờ đánh Over Points/Rebounds cho một trung phong phòng ngự khi anh ta phải kèm cặp trực tiếp Giannis hoặc Embiid.

---

### 4. Hiệu Ứng "Sân Nhà / Sân Khách" Của Cầu Thủ Phụ (Role Player Home Buff)
* Các siêu sao đẳng cấp (Curry, Tatum, Jokic, Doncic) có thể ghi 30 điểm ở bất kỳ sân vận động nào.
* **Tuy nhiên, các cầu thủ phụ (Role Players, Catch-and-Shoot Shooters)** lại phụ thuộc cực lớn vào thị giác sân nhà quen thuộc:
  * Thống kê toàn giải NBA cho thấy: Tỷ lệ ném 3 điểm của các cầu thủ phụ trên **Sân Nhà cao hơn Sân Khách từ 5% đến 8%**.
  * Vai trò của khán giả nhà giúp họ tự tin ra tay dứt khoát hơn.
* 👉 **Kinh nghiệm:** Chỉ cân nhắc đánh Over Points cho cầu thủ phụ (như KCP, Derrick White, Malik Monk, Donte DiVincenzo) khi họ được chơi trên **SÂN NHÀ**. Khi đá sân khách, cửa Under của nhóm này sáng hơn nhiều.

---

### 5. Khung Giờ Vàng Vào Tiền (Late-Breaking News & Market Timing)
* **Khung giờ vàng: 30 - 45 phút trước giờ bóng lăn (Tip-off).**
* Đây là thời điểm NBA bắt buộc các đội phải nộp danh sách thi đấu chính thức (Official Starting Lineups):
  * Tình trạng cầu thủ từ `Questionable` (50/50) sẽ được cập nhật thành `OUT` hoặc `AVAILABLE`.
  * Nếu một ngôi sao bất ngờ bị `OUT`, cầu thủ đóng thế sẽ có giá trị cực lớn trong vòng 5-10 phút trước khi nhà cái kịp khóa kèo hoặc điều chỉnh tăng đường Line.
* **Chỉ số CLV (Closing Line Value):**
  * Nếu bạn đặt cược Over 24.5 lúc 17:00, và đến 19:30 giờ thi đấu nhà cái nâng line lên 26.5 $\rightarrow$ Bạn đã thắng về mặt kỳ vọng toán học (Beat the Market). Những người chơi liên tục có CLV dương luôn là người có lãi dài hạn.

---

### 6. Các Cạm Bẫy Tâm Lý Học Nhận Thức (Cognitive Biases)
* **Thiên kiến vừa xảy ra (Recency Bias):**  
  * *Bẫy:* Thấy một cầu thủ vừa ghi 42 điểm trận trước $\rightarrow$ Háo hức đặt cược Over trận hôm nay.
  * *Thực tế:* Nhà cái biết tâm lý đám đông sẽ dồn vào cầu thủ này, nên họ thường nâng đường Line cao hơn giá trị thực từ 2 - 3 điểm. Đây thường là cơ hội để các tay chơi sắc bén đánh **UNDER** (Hiệu ứng hồi quy về giá trị trung bình - Regression to the Mean).
* **Ảo tưởng con bạc (Gambler's Fallacy):**  
  * *Bẫy:* "Cầu thủ này đã ném trượt 4 trận liên tiếp rồi, hôm nay chắc chắn phải nổ tài!".
  * *Thực tế:* Quả bóng không có trí nhớ. Nếu một cầu thủ đang mất tự tin hoặc chấn thương ngón tay âm thầm, chuỗi trận xịt có thể kéo dài 10 trận. Hãy luôn tin vào phân phối xác suất và số phút thi đấu thực tế trên mô hình.
* **Tâm lý gỡ gạc (Chasing Losses / Tilt):**  
  * Sau khi gãy 1 vé xiên do thua nửa điểm, người chơi thường có xu hướng cược gấp đôi vào các trận khuya để gỡ vốn. Đây là nguyên nhân số 1 dẫn đến việc cháy tài khoản trong vòng 1 tuần.

---

## PHẦN V: QUẢN LÝ VỐN & KỶ LUẬT TÂM LÝ (BANKROLL & MINDSET)

Cho dù mô hình của bạn chuẩn xác đến đâu, bóng rổ luôn tồn tại phương sai (Variance) như chấn thương giữa trận, dính lỗi sớm, hoặc rác trận ngoài dự kiến. Quản lý vốn là chiếc áo phao duy nhất giữ bạn sống sót.

### 1. Quy Tắc Fractional Kelly (1/4 Kelly)
* Hệ thống máy học trên web có tính toán mức cược Kelly Criterion tối ưu. Tuy nhiên trong thực tế, bạn chỉ nên đánh **$25\%$ (Một phần tư) mức Kelly đề xuất**.
* **Mức cược tiêu chuẩn:**
  * Kèo Đơn (Single Bet): **$1.5\% - 2.5\%$** tổng vốn.
  * Vé Xiên 3 Chân (3-Leg Parlay): **$0.5\% - 1.0\%$** tổng vốn (Ví dụ: Vốn 10.000.000đ thì vé 3 chân chỉ nên đánh 50.000đ - 100.000đ như vé 60.000đ của bạn là rất chuẩn mực).

### 2. Phân Bổ Ngân Sách Thông Minh (Portfolio Allocation)
Nếu bạn có ngân sách 100% cho mỗi tuần cược:
* **70% Ngân sách:** Dành cho Kèo Đơn hoặc Vé Xiên 2 Chân có Edge toán học cao nhất ($\ge +7\%$). Đây là nguồn tạo ra lợi nhuận ổn định.
* **25% Ngân sách:** Dành cho Vé Xiên 3 Chân (SGP hoặc Cross-Game). Đây là nguồn nhân vốn có tính toán.
* **5% Ngân sách:** Dành cho Vé Xiên Dài (4+ chân) đánh vui vẻ giải trí.

---

## CHECKLIST 60 GIÂY TRƯỚC KHI ĐẶT CƯỢC

Trước khi bấm xác nhận bất kỳ vé cược nào, hãy tự trả lời 7 câu hỏi sau:

- [ ] **1. Line điểm số:** Có nằm trong vùng ngọt ngào **$13.5 - 26.5$** không? (Tránh xa các line $\le 7.5$).
- [ ] **2. FastCheck:** Xác suất thắng $P \ge 56\%$ và Edge $\ge +5\%$ chưa?
- [ ] **3. Đồng thuận thống kê:** Cả Expected Value ($\mu$) và Median có cùng cao hơn Line ít nhất 1.5 điểm không?
- [ ] **4. Kèo chấp (Spread):** Trận đấu có Spread $\le 7.5$ điểm không? (Đảm bảo không bị ngồi ngoài hiệp 4 do blowout).
- [ ] **5. Đối thủ & DvP:** Đối thủ có phải là khắc tinh phòng ngự của vị trí này không? (Né bẫy DvP Top 1-8).
- [ ] **6. Bảng 10 trận:** Có ít nhất 7 hàng màu xanh (Hit rate $\ge 70\%$) không?
- [ ] **7. Cấu trúc vé xiên:** Nếu là 3 leg cùng trận, có bị dính bẫy "3 người cùng đội tranh bóng nhau" không?

> **TÔN CHỈ CUỐI CÙNG:**  
> *"Nhà cái kiếm tiền từ cảm xúc và sự thiếu kiên nhẫn của người chơi. Người chơi sắc bén kiếm tiền từ kỷ luật, toán học xác suất và việc kiên nhẫn chờ đợi những kèo có sai số định giá."*
