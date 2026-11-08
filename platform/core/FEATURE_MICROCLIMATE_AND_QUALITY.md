# Feature: Công thức Vi khí hậu (VPD, PPFD, DLI) & Chất lượng dữ liệu Tầng 1 A1 (`platform/core/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 6.4, 8.2, 15, Phụ lục A, Phụ lục B.

## 1. Mục tiêu & Phạm vi

Tính toán các đại lượng vi khí hậu chuyên biệt cho nông nghiệp nhà kính (VPD, PPFD, DLI, chỉ số rủi ro chuẩn hoá) và đánh giá chất lượng từng mẫu telemetry bằng hệ luật xác định (Tầng 1 – A1) nhằm ngăn rule engine tưới/quạt sai khi cảm biến lỗi hoặc đứt dây, đồng thời loại bỏ dữ liệu nhiễu khỏi tập huấn luyện AI.

## 2. Trạng thái hiện thực trong repo

- **Đã hoàn thiện đầy đủ (M2):**
  - `platform/core/vpd.py`: `clamp`, `calc_vpsat`, `calc_vpd`, `lux_to_ppfd`, `integrate_dli`, `calc_risk_vpd_low`, `calc_risk_heat`.
  - `platform/core/quality.py`: `QualityConfig`, `ReadingSample`, `ZoneQualityTracker` (hỗ trợ `warm_up`, `evaluate`) và `is_neighbor_divergent`.
  - `platform/tests/test_vpd_dli.py` và `platform/tests/test_quality.py`: đã kiểm chứng toàn bộ công thức và bộ luật A1.
- **Tích hợp/Mở rộng (M3–M5):**
  - Tầng 1 mở rộng (MAY trong spec 8.2): nếu còn thời gian có thể bổ sung mô hình ML bắt lỗi trôi chậm (sensor drift) và chỉ số bảo trì (xu hướng RSSI, tỉ lệ mất gói, độ lệch kéo dài giữa 2 zone) → phát alert `MAINTENANCE`.
  - Trong `worker/ingest.py`, biến `neighbor_suspect` đã được tính khi ingest và gửi kèm trên WS `telemetry`, chưa tạo alert riêng (xem `FEATURE_RULE_CONTROL_ENGINE.md` khi kết hợp fallback cảm biến khí giữa 2 zone).

## 3. Công thức vi khí hậu (`core/vpd.py`, MUST)

### 3.1 Áp suất hơi bão hoà & VPD (kPa)
- **Công thức Tetens:**
  $$VP_{sat}(T) = 0.61078 \times \exp\left(\frac{17.27 \times T}{T + 237.3}\right) \quad (\text{kPa}, \, T \text{ tính bằng } ^\circ\text{C})$$
- **Áp suất hơi không khí & VPD:**
  $$VP_{air} = VP_{sat}(T_{air}) \times \frac{\text{clamp}(RH, 0, 100)}{100}$$
  $$T_{leaf} = T_{air} - \text{leaf\_offset\_c}$$
  $$VPD = \max\left(0.0, \; VP_{sat}(T_{leaf}) - VP_{air}\right)$$
  - `leaf_offset_c` mặc định `1.0 °C` (đọc từ `crop_profiles.parameters_json.vpd.leaf_offset_c`).
  - Khi không có cảm biến nhiệt độ lá (MLX90614 nằm ngoài phạm vi), giả định này phải được giữ nhất quán giữa backend, ML và báo cáo.
  - Kẹp biên dưới ở `0.0` khi ngưng tụ ($VP_{air} > VP_{sat}(T_{leaf})$).
  - **Ca kiểm thử chuẩn (spec 6.4 & 15):** $T_{air} = 20^\circ\text{C}, RH = 94\%, \text{leaf\_offset\_c} = 0 \implies VPD \approx 0.1403 \text{ kPa}$ (sai số `< 0.005`).

### 3.2 Ánh sáng PPFD & DLI
- **PPFD** (xấp xỉ ánh sáng mặt trời cho BH1750 đo lux, tối đa 65.535 lux):
  $$\text{PPFD} \approx \text{lux} \times 0.0185 \quad (\mu\text{mol}/\text{m}^2/\text{s})$$
  Nếu `lux is None` hoặc `lux < 0` → trả `None`.
- **DLI** (Daily Light Integral, `mol/m²/ngày` trong 1 ngày UTC hoặc theo ngày chỉ định):
  $$\text{DLI} = \frac{\sum \frac{\text{PPFD}_{i-1} + \text{PPFD}_i}{2} \times \min(\Delta t_i, \, \text{max\_gap\_s})}{10^6}$$
  - Chỉ tích luỹ các mẫu `readings.quality == 'ok'` và `lux IS NOT NULL` sắp xếp tăng dần theo `ts`.
  - **Chống cộng dồn giả khi mất kết nối (`max_gap_s`):** chặn trên mỗi khoảng $\Delta t$ ở `3 * sample_interval_s` (mặc định `180 s` cho chu kỳ 60 s, `30 s` cho chu kỳ 10 s demo) để khoảng mất mạng buổi trưa không nhân sai ánh sáng suốt nhiều giờ.

### 3.3 Chỉ số rủi ro chuẩn hoá (Phụ lục B)
Dùng cho xếp hạng zone nguy hiểm nhất khi quyết định bật quạt chung và hiển thị UI:
- `risk_vpd_low = clamp((vpd.optimal[0] - vpd) / (vpd.optimal[0] - vpd.low_crit), 0.0, 1.0)`
- `risk_heat = clamp((air_t - temp_c.optimal[1]) / (failsafe.temp_critical_high_c - temp_c.optimal[1]), 0.0, 1.0)`

## 4. Chất lượng dữ liệu Tầng 1 A1 (`core/quality.py`, MUST)

`ZoneQualityTracker` giữ cửa sổ `deque(maxlen=max(stuck_soil_cycles, stuck_air_cycles))` trong RAM cho mỗi zone (được `warm_up()` từ 60 mẫu gần nhất trong DB khi worker khởi động).

### 4.1 Thứ tự đánh giá và các nhãn `quality`

Khi có `ReadingSample(ts_epoch, air_t, air_rh, soil_m, soil_raw, lux, flags)`, phân loại theo thứ tự ưu tiên sau (dừng ở nhãn lỗi đầu tiên):

1. **`dropout`** (mất cảm biến / thiếu dữ liệu):
   - `flags & (FLAG_AHT_ERR | FLAG_SOIL_ERR)` khác `0` (`bit0 = AHT/SHT lỗi`, `bit1 = Soil lỗi`).
   - Lưu ý: `FLAG_BH_ERR` (`bit2`, cảm biến ánh sáng phụ) **không** làm hỏng mẫu khí hậu/ẩm đất → không đánh `dropout` toàn bản ghi.
   - Hoặc một trong 3 trường cốt lõi (`air_t`, `air_rh`, `soil_m`) là `None`.
   - *(Lưu ý nhận biết offline)*: nếu không có bản tin quá `3 * sample_interval_s`, trạng thái mất dữ liệu kéo dài còn kết hợp với `DEVICE_OFFLINE` / watchdog của rule engine.
2. **`out_of_range`** (ngoài dải vật lý hoặc đứt/chập dây ADC):
   - `air_t` ngoài `[-10.0, 60.0]` °C.
   - `air_rh` ngoài `[0.0, 100.0]` %.
   - `soil_m` ngoài `[0.0, 100.0]` %.
   - `soil_raw` (nếu có) ngoài `[50, 4090]` trên ADC 12-bit `0..4095` → **bắt trường hợp rút/đứt dây cảm biến đất đọc `0` hoặc `4095`** (mặc dù công thức 2 điểm có thể biến `soil_raw=0` thành `soil_m=100%` hoặc `0%`, vẫn bị chặn ngay ở đây!).
   - `lux` (nếu không phải `None`) ngoài `[0.0, 65535.0]`.
3. **`spike`** (nhảy vọt phi vật lý giữa 2 mẫu liên tiếp):
   - Chỉ kiểm tra khi khoảng cách thời gian với mẫu liền trước `0 <= (ts - prev.ts) <= max(3 * sample_interval_s, 1.0)` (tránh gắn nhầm `spike` khi vừa khôi phục sau mất mạng dài).
   - `|air_t - prev.air_t| > 5.0` °C; HOẶC
   - `|air_rh - prev.air_rh| > 25.0` %; HOẶC
   - `|soil_m - prev.soil_m| > 20.0` %.
4. **`stuck`** (cảm biến kẹt cứng giá trị):
   - `soil_raw` giữ nguyên y hệt trong `>= 60` chu kỳ liên tiếp (59 mẫu trước + mẫu hiện tại).
   - HOẶC cặp `(air_t, air_rh)` giữ nguyên y hệt trong `>= 30` chu kỳ liên tiếp (29 mẫu trước + mẫu hiện tại).
5. **`ok`**: đạt toàn bộ các kiểm tra trên.

### 4.2 Đối chiếu giữa các zone cùng nhà kính (`is_neighbor_divergent`)
- So sánh hai zone thuộc cùng nhà kính (cùng khối không khí) nếu chênh lệch thời gian hai mẫu `<= 3 * sample_interval_s`:
  - `|air_t_a - air_t_b| > 8.0` °C HOẶC `|air_rh_a - air_rh_b| > 35.0` %.
  - Trả về `True` (nghi ngờ 1 trong 2 node sai/hỏng cảm biến khí) để cảnh báo và đối chiếu khi rule engine chọn zone dự phòng.

## 5. Ràng buộc sử dụng ở các module khác

- **Ingestion (`worker/ingest.py`):** mọi mẫu đều lưu vào bảng `readings` kèm cột `quality` (không vứt bỏ bản ghi lỗi, để còn phục vụ chẩn đoán và kiểm thử T7).
- **Rule Engine (`worker/rules.py`):** **CHỈ** ra quyết định từ bản ghi `quality == 'ok'`.
- **Continuous Aggregates (`readings_1m`, `readings_1h`) & DLI (`GET /zones/{id}/dli`) & ML (`ml/train.py`):** lọc `WHERE quality = 'ok'`.

## 6. Kiểm tra & Xác nhận

- Chạy `pytest platform/tests/test_vpd_dli.py platform/tests/test_quality.py` (100% pass).
- Đảm bảo kiểm thử bắt buộc: T=20, RH=94, `leaf_offset_c=0` → `0.14 kPa`; rút dây `soil_raw=0` → `out_of_range`; spike có miễn trừ khi đứt quãng `> 3 * sample_interval_s`; stuck đúng ngưỡng 30 (air) và 60 (soil_raw).
