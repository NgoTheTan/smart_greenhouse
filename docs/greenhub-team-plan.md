# GreenHub – Kế hoạch triển khai cho nhóm

Tài liệu theo dõi tiến độ cho đồ án môn IoT: nền tảng IoT chuyên biệt cho nhà kính thông minh. Bao gồm phần tổng quan hệ thống (để cả nhóm cùng hiểu), phần cứng, lộ trình 6 tuần, kịch bản demo/video, kiểm thử, rủi ro và checklist nộp bài.

Tài liệu đồng hành: `greenhub-spec.md` (đặc tả kỹ thuật chi tiết cho Coding agent: topic MQTT, schema CSDL, API, thuật toán...). Khi cần chi tiết kỹ thuật, tra ở đó.

---

## 1. Mục tiêu và yêu cầu chấm điểm

Sản phẩm demo (6 điểm), có prototype bằng bìa fomex:

| Tiêu chí | Điểm | Cách đáp ứng |
|---|---|---|
| Ý tưởng | 1 | Nền tảng IoT đa tenant: quyết định ở cloud, quản lý thiết bị từ xa, phân tích dữ liệu. Không phải tự động hoá nhúng |
| Kiến trúc IoT | 2 | Node → ESP-NOW → Gateway → MQTT TLS → Cloud (AWS) → Web console |
| Tự xây IoT platform | 1 | Firmware node/gateway, backend, web console đều tự viết. Không dùng Blynk/ThingsBoard/AWS IoT Core |
| Độ hoàn thiện | 1 | Prototype chạy trọn vòng: cảm biến → quyết định → chấp hành → cảnh báo; 3 kịch bản demo |
| AI/ML hoặc cloud | 1 | Làm cả hai: AI (3 tầng) và triển khai trên AWS |
| Video demo 5–7 phút có thuyết minh | −0,5 nếu thiếu | Kịch bản ở mục 8 |

---

## 2. Tổng quan hệ thống (đã thống nhất)

### 2.1 Ý tưởng
**GreenHub** là nền tảng IoT chuyên biệt cho giám sát và điều khiển nhà kính đa vùng, đa loại cây. Nhà kính mini bằng fomex là một "site" thật; các farm/nhà kính khác được script giả lập đăng ký và gửi dữ liệu qua đúng luồng của thiết bị thật.

Vì sao đây là IoT chứ không phải nhúng/tự động hoá:
- Vòng quyết định nằm ở **cloud**; ngưỡng/crop profile chỉnh từ xa trên web rồi đồng bộ xuống gateway. Vi điều khiển chỉ giữ failsafe.
- Có **quản lý thiết bị**: cấp phát, ghép node vào zone, online/offline (LWT), RSSI, last seen, đổi chu kỳ đo/hiệu chuẩn từ xa.
- **Đa tenant**: nhiều farm dùng chung một nền tảng, dữ liệu tách theo `farm_id`.
- **Dữ liệu quay lại cải thiện điều khiển**: mô hình học đặc tính từng zone từ nhật ký thiết bị và phản hồi người dùng.

### 2.2 Kiến trúc

```
 Node 1 (Zone 1) ─┐
 Node 2 (Zone 2) ─┴─ ESP-NOW ─► Gateway ESP32 + relay 4 kênh
                                    │ MQTT over TLS :8883
                                    ▼
                       AWS EC2 (Docker Compose)
          Mosquitto (TLS+ACL) ─ TimescaleDB ─ api + worker (FastAPI)
          Caddy (HTTPS) ─► Web console (React PWA, Web Push)
```

| Khối | Công nghệ |
|---|---|
| Node ×2 | ESP32 + cảm biến ẩm đất + AHT20 (+ BH1750 ở 1 node); PlatformIO/Arduino; ESP-NOW |
| Gateway | ESP32 + relay 4 kênh; ESP-NOW → MQTT TLS; failsafe, interlock, hàng đợi RAM |
| Broker | Mosquitto (TLS, user + ACL theo gateway) |
| Backend | Python FastAPI, hai tiến trình `api` + `worker`, PostgreSQL + TimescaleDB |
| Web | React + Vite + TypeScript, PWA, Web Push |
| AI | scikit-learn, LightGBM; huấn luyện offline, suy luận trong worker |
| Cloud | AWS EC2 t3.small (Singapore), Docker Compose, Caddy, DuckDNS |

### 2.3 Các module platform
Device Registry & Provisioning · Device Shadow/Config · Ingestion · Rule & Control Engine · Command Service · Alert Service · Notification Service · Analytics (AI) · API/Auth/Tenant.

### 2.4 Thông báo (chỉ trên web)
In-app (WebSocket) → **Web Push** (service worker + VAPID) → email (leo thang alert `critical` chưa xác nhận) → buzzer tại gateway. Không dùng Telegram, không dùng FCM, không làm app di động. iPhone chỉ nhận push khi Add to Home Screen.

### 2.5 Logic điều khiển (tóm tắt)
- **Tưới:** hysteresis theo zone (bật khi dưới ngưỡng min, tắt khi đạt max), giới hạn thời gian chạy/khoảng nghỉ/tổng mỗi giờ.
- **Quạt:** bật khi VPD thấp kéo dài (nguy cơ nấm) hoặc nhiệt độ cao. **Máy tạo ẩm** bật tay hoặc auto khi VPD cao.
- **Interlock:** quạt và máy tạo ẩm không chạy cùng lúc; quạt bật vì rủi ro thì ép tắt máy tạo ẩm (kể cả đang manual).
- Mọi lệnh bật đều có thời lượng; gateway tự tắt khi hết giờ. Mất cloud hơn 60 s thì failsafe cục bộ.
- Hai chiến lược: `fixed` (thời lượng cố định) và `adaptive` (thời lượng tính từ mô hình học từ dữ liệu).

### 2.6 AI (3 tầng)

| Tầng | Nội dung | Đầu ra dùng để làm gì |
|---|---|---|
| 1. Chất lượng dữ liệu | Luật gắn nhãn `ok/stuck/spike/dropout/out_of_range`, đối chiếu node lân cận | Loại dữ liệu xấu khỏi điều khiển và huấn luyện |
| 2. Học đặc tính từng zone | Mức tăng ẩm đất theo mỗi giây bơm, mức giảm VPD theo mỗi giây quạt, tốc độ khô và dự báo "còn N phút cần tưới" (#2) | Chiến lược `adaptive` dùng để tính thời lượng tưới/quạt |
| 3. Dự báo rủi ro (#3) | LightGBM dự báo zone vào vùng nguy cơ trong 15 phút tới; nút phản hồi đúng/sai trên cảnh báo | Cảnh báo sớm `DISEASE_RISK_FORECAST`; đo precision |

Nguyên tắc: có baseline để so sánh; chia train/test theo thời gian; chỉ báo cáo chỉ số chính trên dữ liệu **thật** (dữ liệu giả lập chỉ để thử pipeline và tải); chỉ kích hoạt mô hình mới khi thắng baseline và bản cũ. Nhà kính mini phản ứng nhanh nên **thu nhỏ thang thời gian** (horizon 15 phút, VPD thấp ≥ 3 phút; ghi rõ trong báo cáo).

### 2.7 Phạm vi KHÔNG làm
Telegram, FCM, app di động, LLM, RLS (có thể thêm sau), OTA, CO₂/PAR/MLX90614/DS18B20, rèm cắt nắng, 4G, pin + pin mặt trời, Grafana, dịch vụ managed của AWS, học tăng cường, học liên farm.

---

## 3. Phân công (work package)

Điền tên người phụ trách; có thể gộp WP nếu nhóm ít người.

| WP | Nội dung | Người phụ trách |
|---|---|---|
| WP1 | Phần cứng và mô hình vật lý (mua linh kiện, lắp node/gateway/tủ relay, làm hộp fomex, hiệu chuẩn cảm biến) | ____ |
| WP2 | Firmware node + gateway (ESP-NOW, MQTT TLS, lệnh/ACK, failsafe, captive portal) | ____ |
| WP3 | Platform backend (MQTT ingest, DB, rule engine, command, alert, notify, API, provisioning) | ____ |
| WP4 | Web console PWA (dashboard, điều khiển, thiết bị, crop profile, cảnh báo, Model, Web Push) | ____ |
| WP5 | AI/Data (A1/A2/A3, pipeline huấn luyện, thí nghiệm fixed vs adaptive, thử tải) | ____ |
| WP6 | DevOps/AWS, simulator, kiểm thử tích hợp, video, báo cáo | ____ |

---

## 4. Lộ trình 6 tuần

Mỗi tuần kết thúc bằng một milestone (M1–M6, trùng `greenhub-spec.md` mục 16). Đánh dấu `[x]` khi xong.

### Tuần 1 – M1: Phần cứng và đường dữ liệu cơ bản
- [ ] (WP1) Mua linh kiện (mục 5), kiểm tra từng cảm biến
- [ ] (WP1) Lắp node 1, node 2 trên breadboard; hiệu chuẩn ẩm đất 2 điểm (khô/ướt)
- [ ] (WP1) Lắp tủ gateway: relay + bơm/quạt/máy tạo ẩm + diode + tụ + nguồn 5 V
- [ ] (WP2) Node: đọc cảm biến, đóng gói `TelemetryPkt`, gửi ESP-NOW, tìm kênh tự động
- [ ] (WP2) Gateway: nhận ESP-NOW, publish MQTT lên broker chạy trên laptop, nhận `cmd` điều khiển relay
- [ ] (WP6) Dựng repo, Docker Compose dev (Mosquitto + Timescale)
- **Đạt M1 khi:** số liệu 2 node hiện trên broker; gửi lệnh MQTT thủ công bật/tắt được 4 relay; relay tắt khi boot.

### Tuần 2 – M2: Ingestion, lệnh/ACK, shadow
- [ ] (WP3) Schema DB + Alembic; ingestion → `readings`, tính VPD
- [ ] (WP3) Gắn `quality` (luật A1)
- [ ] (WP3) Command Service: `cmd → ack`, trạng thái lệnh, `device_state` (shadow), publish `cfg` retained
- [ ] (WP2) Gateway: ACK, interlock, giới hạn thời gian, tự tắt khi hết `duration_s`, LWT/`status`
- [ ] (WP1) Hoàn thiện mô hình fomex (hộp, cửa sổ nhựa, lỗ quạt/ống hơi/dây, bồn nước)
- [ ] (WP6) Unit test VPD/DLI/quality
- **Đạt M2 khi:** dữ liệu vào DB đúng; gọi API/script tạo lệnh → relay chạy → ACK cập nhật `reported`; ngắt gateway thì `status` offline qua LWT.

### Tuần 3 – M3: Web console cơ bản, rule engine, alert, Web Push (localhost)
- [ ] (WP3) Rule engine chiến lược `fixed` (tưới, quạt, máy tạo ẩm, interlock, auto/manual)
- [ ] (WP3) Alert Service: dedupe, vòng đời, leo thang; API + JWT + vai trò
- [ ] (WP4) Web: đăng nhập, dashboard zone (biểu đồ realtime qua WebSocket), điều khiển, crop profile
- [ ] (WP4) PWA + service worker + đăng ký Web Push; thử trên localhost
- [ ] (WP2) Gateway: failsafe cục bộ, buffer RAM, nhận `cfg` và đẩy xuống node
- [ ] (WP6) **Đăng ký tài khoản AWS** (mục 6), đặt Budgets, tạo thử EC2
- **Đạt M3 khi:** từ web bật quạt/bơm và thấy trạng thái `pending → applied`; kịch bản A chạy cục bộ (VPD thấp → quạt bật, máy tạo ẩm bị ép tắt, alert hiện trên web và thông báo push trên localhost).

### Tuần 4 – M4: Provisioning, deploy AWS, simulator, bắt đầu thu dữ liệu
- [ ] (WP3) Provisioning: tạo gateway + credential MQTT (Dynamic Security), ghép node lạ vào zone (fallback: nhập MAC tay)
- [ ] (WP2) Gateway: captive portal, TLS với kiểm tra chứng chỉ, kết nối bằng tên miền
- [ ] (WP6) Triển khai EC2: Docker Compose prod, Caddy HTTPS, DuckDNS, Mosquitto TLS, Security Group, swap, backup `pg_dump`
- [ ] (WP4) Thử Web Push trên **điện thoại thật** qua HTTPS (iPhone: Add to Home Screen)
- [ ] (WP6) Simulator: đăng ký farm B, C qua API, publish qua TLS
- [ ] (WP5) Chuẩn bị chạy thu dữ liệu; (tuỳ chọn) script bật/tắt máy tạo ẩm qua API để có đủ sự kiện rủi ro thật
- **Đạt M4 khi:** gateway thật kết nối EC2 qua TLS; web truy cập qua HTTPS; push tới điện thoại; farm giả lập hiển thị và cô lập đúng; **hệ thống bắt đầu chạy liên tục để thu dữ liệu 3–5 ngày**.

### Tuần 5 – M5: AI, thí nghiệm, thử tải
- [ ] (WP5) Huấn luyện A2 (`pump_response`, `fan_response`, `irrigation_eta`) và A3 (`risk_forecast`); so với baseline; lưu `ml_models`
- [ ] (WP3) Rule engine `adaptive` dùng `pump_response`/`fan_response` (fallback `fixed` nếu chưa đủ sự kiện)
- [ ] (WP3) Suy luận định kỳ → `predictions`; alert `DISEASE_RISK_FORECAST`; nút feedback đúng/sai
- [ ] (WP4) Trang Model và Thí nghiệm (metrics, KPI fixed vs adaptive)
- [ ] (WP5) Thí nghiệm fixed vs adaptive trong điều kiện tương tự; thu KPI
- [ ] (WP6) Thử tải simulator 50–100 gateway; đo bản tin/s, độ trễ p50/p95, CPU/RAM (chạy theo đợt ngắn, theo dõi CPU credit)
- [ ] (WP3) Email leo thang alert `critical` chưa ack
- **Đạt M5 khi:** có bảng so sánh mô hình vs baseline (trên dữ liệu thật); có bảng KPI fixed vs adaptive; có số liệu thử tải.

### Tuần 6 – M6: Chạy thử, quay video, nộp bài
- [ ] (cả nhóm) Chạy thử trọn kịch bản A/B/C/D/E ít nhất 2 lần theo kịch bản video
- [ ] (WP6) Quay và dựng video 5–7 phút có thuyết minh
- [ ] (WP6) Xuất dữ liệu, mô hình, sao lưu DB, lưu video **trước khi hết hạn Free plan**
- [ ] (cả nhóm) Báo cáo (ý tưởng, kiến trúc, platform, AI, kết quả test, hạn chế)
- [ ] (WP1) Hoàn thiện thẩm mỹ mô hình, nhãn dán các khối
- **Đạt M6 khi:** đủ checklist nộp bài (mục 10).

**Việc có thể trượt cần canh:** (1) Web Push trên điện thoại (thử từ tuần 4, không dồn sau); (2) thu dữ liệu cần ≥ 3 ngày chạy liên tục, nên bắt đầu ngay cuối tuần 4; (3) AWS Free plan tính từ ngày đăng ký, không đăng ký quá sớm.

---

## 6. Kế hoạch AWS

Điều kiện gói miễn phí có thể đổi; đọc lại trang đăng ký trước khi làm. Theo tài liệu AWS tại thời điểm trao đổi: tài khoản mới chọn **Free plan** nhận 100 USD khi đăng ký, thêm tối đa 100 USD khi làm các hoạt động đủ điều kiện; Free plan kéo dài tối đa 6 tháng hoặc đến khi hết credit; hết hạn thì tài khoản bị đóng. Tài khoản tạo trước tháng 7/2025 theo cơ chế cũ.

| Hạng mục | Giá trị |
|---|---|
| Region | ap-southeast-1 (Singapore) |
| Instance | t3.small (2 GB RAM), x86, Ubuntu 24.04 LTS |
| Ổ đĩa | gp3 20–30 GB; swap 2 GB |
| IP/tên miền | Elastic IP + DuckDNS |
| Chi phí ước tính | khoảng 22–27 USD/tháng (**cần kiểm tra bằng AWS Pricing Calculator**); với 100 USD credit chạy được khoảng 4 tháng, 200 USD thì tới hết 6 tháng |
| Không dùng | IoT Core, RDS (không có TimescaleDB), Lambda... |

**Checklist AWS:**
- [ ] Xác định loại tài khoản (mới/cũ), nhận đủ credit, bật MFA root, tạo IAM user
- [ ] Tạo AWS Budgets, cảnh báo email ở 50% và 80%
- [ ] Security Group: 22 (chỉ IP nhóm, key), 80/443, 8883; **không** mở 1883, 5432
- [ ] Cài Docker/Compose, swap 2 GB, `.env`, `docker compose up -d`
- [ ] Chứng chỉ Caddy + Mosquitto dùng lại file chứng chỉ, cron restart hàng tháng
- [ ] Cron `pg_dump` hằng ngày, kéo bản dump về máy nhóm
- [ ] Sau khi chấm điểm: huỷ instance và Elastic IP để không phát sinh phí

**Lưu ý t3.small là burstable:** CPU nền thấp, chạy tải cao kéo dài sẽ cạn CPU credit. Thử tải theo đợt ngắn, theo dõi `CPUCreditBalance` trên CloudWatch.

**Laptop:** môi trường phát triển (cùng file compose), huấn luyện offline, chạy simulator.

---

## 7. Phần cứng

### 7.1 Danh sách linh kiện và chi phí (nghìn đồng, là ước lượng, cần kiểm tra giá khi mua)

| Nhóm | Linh kiện | SL | Thành tiền |
|---|---|---|---|
| **Node** | ESP32 DevKit (mua cùng loại cho cả node và gateway) | 2 | 160–220 |
| | Cảm biến ẩm đất điện dung v1.2 | 2 | 40–70 |
| | AHT20/AHT21 (hoặc SHT30 nếu giá gần nhau) | 2 | 50–120 |
| | BH1750 (chỉ 1 node) | 1 | 25–45 |
| | Breadboard mini, jumper, cáp USB | | 40–60 |
| | *Tổng node* | | **≈ 315–515** |
| **Gateway** | ESP32 DevKit | 1 | 80–110 |
| | Relay 4 kênh cách ly quang 5 V (kích mức thấp) | 1 | 50–90 |
| | Bơm chìm mini 3–6 V | 2 | 50–100 |
| | Ống silicone 1–2 m | | 20–40 |
| | Quạt 5 V (80 mm hoặc quạt USB) | 1 | 30–60 |
| | Máy tạo ẩm USB mini 5 V | 1 | 60–120 |
| | Nguồn 5 V 3 A (hoặc dùng củ sạc có sẵn) | 1 | 0–70 |
| | Diode 1N4007 ×4, tụ 1000 µF, buzzer, domino, hộp nhựa | | 60–100 |
| | *Tổng gateway* | | **≈ 350–690** |
| **Mô hình** | Bìa fomex, keo nến, băng keo | | 60–100 |
| | Tấm nhựa trong (cửa sổ) | | 20–40 |
| | 2 chậu nhỏ, xơ dừa, cây giống (tuỳ chọn), chai nước làm bồn | | 50–100 |
| | *Tổng mô hình* | | **≈ 130–240** |
| **Tổng** | | | **≈ 0,8–1,45 triệu** |

Tiết kiệm: tận dụng củ sạc, breadboard, dây, cáp USB có sẵn. Node cấp nguồn USB (không dùng pin/pin mặt trời); firmware vẫn hỗ trợ deep sleep để nói "battery-ready" trong báo cáo.

### 7.2 Đấu nối

**Node (ESP32):**

| Linh kiện | Chân |
|---|---|
| AHT20 + BH1750 (I2C, 0x38 và 0x23) | SDA = GPIO21, SCL = GPIO22, VCC = 3V3 |
| Ẩm đất AOUT | GPIO34 (ADC1; không dùng ADC2) |
| Ẩm đất VCC | GPIO25 (bật khi đo) |

**Gateway (ESP32 + relay 4 kênh):**

| Relay | Chân | Tải |
|---|---|---|
| IN1 | GPIO25 | Bơm zone 1 |
| IN2 | GPIO26 | Bơm zone 2 |
| IN3 | GPIO27 | Quạt |
| IN4 | GPIO33 | Máy tạo ẩm |
| Buzzer | GPIO23 | Cảnh báo cục bộ |

- Relay kích mức thấp: firmware `digitalWrite(pin, HIGH)` **trước** `pinMode(pin, OUTPUT)`.
- Mỗi tải: +5 V → COM, NO → cực dương tải, cực âm tải → GND. Bơm có **diode 1N4007 song song tải** (cathode, đầu có vạch, về phía +).
- Một nguồn 5 V chung (nối chung GND), **tụ 1000 µF** ở rail để bơm khởi động không làm ESP32 reset. Nếu vẫn reset thì tách nguồn cho bơm.
- Chỉ dùng điện áp thấp 5 V, không đụng 220 V.

### 7.3 Lắp mô hình
1. Hộp fomex khoảng 40×30×30 cm, một mặt gắn tấm nhựa trong, mép dán kín bằng băng keo. Hộp phải **gần kín** để độ ẩm tăng được.
2. Khoét lỗ: quạt hút ở thành hộp, ống hơi từ máy tạo ẩm, dây cảm biến và ống nước.
3. Trong hộp: 2 chậu, mỗi chậu 1 cảm biến ẩm đất + 1 AHT20 treo cao hơn mặt chậu, **xa miệng phun hơi ẩm**. Seal phần mép mạch cảm biến điện dung bằng epoxy/sơn.
4. Bồn nước (chai/hộp) để ngoài, 2 bơm nhúng bên trong, mỗi bơm một ống vào một chậu.
5. Gateway + relay để trong hộp nhựa đặt ngoài nhà kính, tránh khu vực ẩm.
6. Hiệu chuẩn ẩm đất: ghi giá trị ADC khi cảm biến ở không khí khô và khi cắm trong đất ướt; nhập vào cấu hình zone trên web.

### 7.4 Checklist phần cứng
- [ ] Mỗi node đọc đúng nhiệt độ/RH/ẩm đất; node 1 có lux
- [ ] 4 relay đóng/mở đúng kênh; relay tắt khi mới cấp điện
- [ ] Quạt hút đủ để RH giảm trong hộp; máy tạo ẩm làm RH tăng trong vài phút
- [ ] Bơm đưa nước vào đúng chậu, không rò điện
- [ ] Ổn định: chạy 1 giờ liên tục không reset, không mất gói bất thường

---

## 8. Kịch bản demo và video (6–7 phút, có thuyết minh)

| Thời gian | Nội dung |
|---|---|
| 0:00–0:45 | Bài toán, ý tưởng GreenHub, điểm khác biệt với tự động hoá |
| 0:45–1:45 | Kiến trúc và prototype thật: node → gateway → cloud → web/push |
| 1:45–2:30 | Web console: 2 zone với 2 crop profile; chọn farm B, C để thấy đa tenant |
| 2:30–3:30 | **Kịch bản A:** bật máy tạo ẩm từ web → RH tăng, VPD giảm → AI cảnh báo trước → rule engine bật quạt, ép tắt máy tạo ẩm → push hiện trên điện thoại, bấm vào mở trang zone |
| 3:30–4:30 | **Kịch bản B:** ẩm đất giảm → dự báo "cần tưới sau ~N phút" → bơm chạy theo hysteresis → chuyển Auto/Manual |
| 4:30–5:15 | **Kịch bản C:** rút dây cảm biến → `quality` lỗi, không tưới sai, alert; (tuỳ thời gian) cắt Wi-Fi gateway → offline + failsafe, nối lại thì dữ liệu gửi bù và `cfg` đồng bộ |
| 5:15–6:30 | Kết quả AI so với baseline, KPI fixed vs adaptive, thử tải, triển khai trên AWS, kết luận và hạn chế |

**Lưu ý chuẩn bị:**
- Đất khô chậm (hàng giờ). Cho kịch bản B: chuyển cảm biến sang chậu đất đã sấy khô, hoặc tua nhanh đoạn đã ghi. Quyết định trước khi quay và nói rõ trong video.
- Nên dùng điện thoại thật để thấy Web Push; quay màn hình điện thoại cùng cảnh nhà kính.
- Dùng hotspot điện thoại hoặc router riêng cho Wi-Fi (Wi-Fi trường có captive portal/WPA2-Enterprise thường không kết nối được).
- Chạy thử toàn bộ kịch bản ít nhất 2 lần trước khi quay; bật `demo` profile (thang thời gian đã thu nhỏ).
- Checklist quay: [ ] kịch bản có thuyết minh [ ] âm thanh rõ [ ] ghi lại số đo thử tải [ ] ghi rõ phần nào là dữ liệu thật/giả lập.

---

## 9. Kiểm thử

| ID | Nội dung | Kết quả mong đợi |
|---|---|---|
| T1 | VPD: T=20 °C, RH=94% (T_lá = T_khí) | ≈ 0.14 kPa |
| T2 | Khởi động gateway | Mọi relay tắt |
| T3 | Bật quạt khi máy tạo ẩm đang chạy | Máy tạo ẩm tắt, ACK có `side_effects` |
| T4 | Bật máy tạo ẩm khi quạt đang chạy | Lệnh bị `rejected` (`interlock`) |
| T5 | Bơm chạy quá `max_run` / vi phạm `min_gap` | Gateway chặn hoặc tự tắt |
| T6 | Mất cloud khi bơm đang chạy | Bơm vẫn tự tắt đúng thời lượng |
| T7 | Rút dây cảm biến ẩm đất (đọc ≈ 0) | `quality` lỗi; **không** tưới; alert `SENSOR_FAULT` |
| T8 | Mất Wi-Fi gateway > 60 s | `DEVICE_OFFLINE`; failsafe đúng giới hạn; online lại thì gửi bù dữ liệu |
| T9 | Đổi crop profile trên web | `cfg_version` tăng; gateway báo đã đồng bộ |
| T10 | Lệnh hết hạn (`expires_at`) | Gateway bỏ qua; lệnh `timeout`/`expired` |
| T11 | Alert `critical` không ack sau N phút | Gửi lại push + email |
| T12 | User farm A truy cập dữ liệu farm B | `403`/không thấy |
| T13 | Web Push khi đóng tab | Điện thoại/desktop nhận thông báo, bấm mở đúng trang zone |
| T14 | Mô hình mới không thắng baseline | Không được kích hoạt |
| T15 | Thử tải 50–100 gateway giả lập | Ghi bản tin/s, độ trễ p50/p95, CPU/RAM |

---

## 10. Checklist nộp bài (Definition of Done)

**Sản phẩm**
- [ ] Prototype fomex hoàn chỉnh, chạy ổn định
- [ ] Đủ ba khối: IoT nodes, Gateway, Cloud (AWS)
- [ ] Firmware node/gateway, backend, web console đều tự viết
- [ ] 3 kịch bản demo A/B/C chạy trọn vòng; farm giả lập chạy; cô lập tenant
- [ ] Web Push nhận được trên điện thoại thật
- [ ] Hệ thống khởi động sạch bằng `docker compose up -d`

**AI/Cloud**
- [ ] Mô hình có so sánh với baseline (chỉ số chính trên dữ liệu thật; nêu rõ phần giả lập)
- [ ] Bảng KPI fixed vs adaptive
- [ ] Số liệu thử tải
- [ ] Triển khai trên AWS đang chạy

**Tài liệu**
- [ ] Video demo 5–7 phút có thuyết minh (thiếu bị trừ 0,5 điểm)
- [ ] Báo cáo có: ý tưởng, kiến trúc, mô tả platform, AI, kết quả test, hạn chế, giả định (T_lá = T_khí − 1 °C; thu nhỏ thang thời gian; ngưỡng sinh học là giá trị khởi tạo)
- [ ] Dữ liệu, mô hình, DB dump, video đã sao lưu ngoài AWS

---

## 11. Rủi ro và phương án dự phòng

| Rủi ro | Phương án |
|---|---|
| Wi-Fi trường có captive portal/WPA2-Enterprise, ESP32 không kết nối được (chỉ hỗ trợ 2.4 GHz) | Dùng hotspot điện thoại hoặc router riêng |
| ESP-NOW và kênh Wi-Fi lệch nhau | Node tự quét kênh 1–13 bằng `HELLO` và lưu NVS; kiểm tra khi đổi mạng |
| Bơm khởi động làm ESP32 reset | Diode, tụ 1000 µF ở rail 5 V; nếu vẫn lỗi tách nguồn cho bơm |
| Máy tạo ẩm USB phải bấm nút mới chạy sau khi cấp điện | Chọn loại tự chạy khi có điện, hoặc dùng module tạo sương |
| Cảm biến RH sai khi bị đọng nước | Đặt xa miệng phun; chờ phục hồi |
| Đất khô quá chậm cho demo | Chuyển cảm biến sang chậu đất sấy khô hoặc tua nhanh đoạn đã ghi (nói rõ trong video) |
| Thang thời gian nhà kính mini khác nhà kính thật | Dùng template `demo` có thời gian thu nhỏ; ghi rõ trong báo cáo |
| Mô hình ML không thắng baseline | Vẫn báo cáo trung thực; mô hình không được kích hoạt, hệ thống dùng `fixed` |
| Dữ liệu thật quá ít sự kiện | Chạy script bật/tắt máy tạo ẩm qua API trong lúc thu dữ liệu (sự kiện vẫn là dữ liệu vật lý thật); kéo dài thời gian thu |
| Dữ liệu giả lập làm đẹp kết quả | Gắn nhãn `real`/`sim`; chỉ số chính chỉ trên `real` |
| Web Push không tới (iOS, chế độ Không làm phiền) | iOS: Add to Home Screen; giữ lớp email và buzzer; thử sớm từ tuần 4 |
| Hết credit/hết hạn Free plan, tài khoản đóng | Đặt Budgets; sao lưu hằng ngày; xuất dữ liệu và video trước hạn |
| t3.small cạn CPU credit khi thử tải | Thử tải theo đợt ngắn; theo dõi CPUCreditBalance |
| Mất dữ liệu thu nhiều ngày | `pg_dump` hằng ngày về máy nhóm |
| Mất mạng/laptop sập khi demo | Gateway có buffer RAM + failsafe; demo ưu tiên chạy trên AWS; có video ghi sẵn dự phòng |

---

## 12. Điểm cần nhóm chốt

1. Phân công WP1–WP6 (mục 3).
2. Cảm biến nhiệt-ẩm: AHT20 hay SHT30 (tuỳ giá lúc mua).
3. Loại tài khoản AWS và credit thực nhận; ngày dự kiến đăng ký (khuyến nghị tuần 3).
4. Nhà cung cấp SMTP cho email leo thang.
5. Ghép node: tự phát hiện hay nhập MAC thủ công cho MVP.
6. Có làm script tự bật/tắt máy tạo ẩm khi thu dữ liệu hay làm tay.
7. Có làm cảnh báo bảo trì (`MAINTENANCE`) và ML cho A1 hay không (tuỳ chọn, chỉ khi còn thời gian).
8. Kịch bản B dùng cách nào: chậu đất sấy khô hay tua nhanh đoạn ghi sẵn.
