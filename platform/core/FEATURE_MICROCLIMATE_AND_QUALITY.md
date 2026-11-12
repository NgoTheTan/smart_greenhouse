# Feature: Công thức Vi khí hậu (VPD, PPFD, DLI), Chất lượng dữ liệu (luật) & Đặc trưng khí hậu (`platform/core/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 6.4, 8.1, 8.2, 15, Phụ lục A, Phụ lục B; `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Tính toán các đại lượng vi khí hậu chuyên biệt cho nông nghiệp nhà kính (VPD, PPFD, DLI, chỉ số rủi ro chuẩn hoá), đánh giá chất lượng từng mẫu telemetry bằng hệ luật xác định nhằm ngăn rule engine tưới/quạt sai khi cảm biến lỗi hoặc đứt dây, đồng thời cung cấp bộ trích xuất **đặc trưng khí hậu (`climate_features.py`, `feature_version = 1`)** bằng Python thuần dùng chung cho suy luận (`worker`), huấn luyện (`ml/`) và sinh dữ liệu (`tools/simulator`).

## 2. Trạng thái hiện thực trong repo

- **Đã hoàn thiện (M2):**
  - `platform/core/vpd.py`: `clamp`, `calc_vpsat`, `calc_vpd`, `lux_to_ppfd`, `integrate_dli`, `calc_risk_vpd_low`, `calc_risk_heat`.
  - `platform/core/quality.py`: `QualityConfig`, `ReadingSample`, `ZoneQualityTracker` (hỗ trợ `warm_up`, `evaluate`) và `is_neighbor_divergent`.
  - `platform/tests/test_vpd_dli.py` và `platform/tests/test_quality.py`: đã kiểm chứng toàn bộ công thức và bộ luật kiểm tra chất lượng dữ liệu.
- **Cần bổ sung / tích hợp (M3–M5):**
  - `platform/core/climate_features.py` (M5): hiện thực `FEATURE_VERSION = 1` và hàm trích 16 đặc trưng số + `coverage` bằng Python thuần (không import `pandas`, `numpy`, `scikit-learn`, `lightgbm`).
  - Trong `worker/ingest.py`, biến `neighbor_suspect` đã được tính khi ingest và gửi kèm trên WS `telemetry` (xem `FEATURE_RULE_CONTROL_ENGINE.md` khi kết hợp fallback cảm biến khí giữa 2 zone).
  - Chỉ số bảo trì (MAY trong spec 8.1): có thể bổ sung theo dõi xu hướng RSSI, tỉ lệ mất gói, độ lệch kéo dài giữa 2 zone → phát alert `MAINTENANCE`.

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
- **DLI** (Daily Light Integral, `mol/m²/ngày` trong 1 ngày hoặc theo ngày chỉ định):
  $$\text{DLI} = \frac{\sum \frac{\text{PPFD}_{i-1} + \text{PPFD}_i}{2} \times \min(\Delta t_i, \, \text{max\_gap\_s})}{10^6}$$
  - Chỉ tích luỹ các mẫu `readings.quality == 'ok'` và `lux IS NOT NULL` sắp xếp tăng dần theo `ts`.
  - **Chống cộng dồn giả khi mất kết nối (`max_gap_s`):** chặn trên mỗi khoảng $\Delta t$ ở `3 * sample_interval_s` (mặc định `180 s` cho chu kỳ 60 s, `30 s` cho chu kỳ 10 s demo) để khoảng mất mạng buổi trưa không nhân sai ánh sáng suốt nhiều giờ.

### 3.3 Chỉ số rủi ro chuẩn hoá (Phụ lục B)
Dùng cho xếp hạng zone nguy hiểm nhất khi quyết định bật quạt chung và hiển thị UI:
- `risk_vpd_low = clamp((vpd.optimal[0] - vpd) / (vpd.optimal[0] - vpd.low_crit), 0.0, 1.0)`
- `risk_heat = clamp((air_t - temp_c.optimal[1]) / (failsafe.temp_critical_high_c - temp_c.optimal[1]), 0.0, 1.0)`

## 4. Kiểm tra chất lượng dữ liệu (luật) (`core/quality.py`, MUST)

> Đây là bước tiền xử lý xác định theo luật (không phải mô hình AI) nhằm bảo vệ Rule Engine và đảm bảo đầu vào sạch cho đặc trưng khí hậu.

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
  - Trả về `True` (cờ `neighbor_suspect`, nghi ngờ 1 trong 2 node sai/hỏng cảm biến khí) để cảnh báo và đối chiếu khi rule engine chọn zone dự phòng.

## 5. Đặc trưng khí hậu dùng chung (`core/climate_features.py`, `feature_version = 1`, MUST)

> Tài liệu mô hình sử dụng vector đặc trưng này: [ml/FEATURE_AI_YIELD_AND_RECOMMENDATION.md](../../ml/FEATURE_AI_YIELD_AND_RECOMMENDATION.md).

### 5.1 Ràng buộc kiến trúc & Đầu vào
- **Python thuần:** chỉ dùng thư viện chuẩn (`math`, `statistics`, `datetime`, `zoneinfo`, `dataclasses`…), **không bắt buộc `pandas`/`numpy`**, tuyệt đối không import `scikit-learn` hay `lightgbm`. Dùng chung một hàm duy nhất cho `worker` (suy luận), `ml/` (huấn luyện) và `tools/simulator` (sinh dữ liệu `synthetic`) để đảm bảo nhất quán tuyệt đối giữa train và inference.
- **Độ phân giải bucket đầu vào:**
  - Mặc định dùng chuỗi bucket 1 giờ từ **`readings_1h`** (đã lọc `WHERE quality = 'ok'`).
  - Khi cửa sổ thời gian `< 6 giờ` (ví dụ chế độ `demo` với `ai.recommend_window_h = 1` hoặc `ai.min_cycle_hours = 0.5`) → dùng chuỗi bucket 1 phút từ **`readings_1m`** (`WHERE quality = 'ok'`).
- **Múi giờ địa phương:** chuyển timestamp bucket (UTC) sang **`Asia/Ho_Chi_Minh`** trước khi phân tách ngày/đêm.

### 5.2 Danh sách 16 đặc trưng số + `coverage` (`FEATURE_VERSION = 1`)

| Tên trường | Định nghĩa | Ghi chú |
|---|---|---|
| `t_mean` | Trung bình `air_temp` (°C) | Trên các bucket hợp lệ |
| `t_day_mean` | Trung bình `air_temp` trong khung `06:00–18:00` giờ `Asia/Ho_Chi_Minh` (°C) | `6 <= local_dt.hour < 18` |
| `t_night_mean` | Trung bình `air_temp` phần còn lại (`hour < 6` hoặc `hour >= 18`) (°C) | Nếu cửa sổ ngắn thiếu toàn bộ ban ngày/đêm → `None` |
| `t_p95` | Phân vị 95 của `air_temp` (°C) | Nội suy tuyến tính trên danh sách đã sắp xếp |
| `t_p05` | Phân vị 5 của `air_temp` (°C) | Nội suy tuyến tính trên danh sách đã sắp xếp |
| `rh_mean` | Trung bình `air_rh` (%) | — |
| `vpd_mean` | Trung bình `vpd` (kPa) | — |
| `vpd_std` | Độ lệch chuẩn `vpd` (kPa) | Nếu `< 2` mẫu hợp lệ → `0.0` |
| `frac_vpd_low` | Tỉ lệ bucket có `vpd < 0.4` kPa | Trong `[0.0, 1.0]` |
| `frac_vpd_high` | Tỉ lệ bucket có `vpd > 1.6` kPa | Trong `[0.0, 1.0]` |
| `frac_t_gt_30` | Tỉ lệ bucket có `air_temp > 30.0` °C | Trong `[0.0, 1.0]` |
| `frac_t_lt_12` | Tỉ lệ bucket có `air_temp < 12.0` °C | Trong `[0.0, 1.0]` |
| `gdd_per_day` | Trung bình `max(air_temp - 10.0, 0.0)` (°C·ngày/ngày) | Thang nhiệt sinh trưởng cơ sở 10 °C |
| `dli_mean` | `mean(PPFD) * 86400 / 1e6` (mol/m²/ngày), `PPFD = lux * 0.0185` | Xem quy tắc xử lý `lux` null bên dưới |
| `soil_mean` | Trung bình `soil_moisture` (%) | Khi gợi ý cây trồng (`crop_recommendation`), bị ghi đè bằng trung điểm `soil_moisture_pct` của cây ứng viên |
| `soil_std` | Độ lệch chuẩn `soil_moisture` (%) | Khi gợi ý cây trồng, bị ghi đè bằng median tập train; nếu `< 2` mẫu → `0.0` |
| `coverage` | Tỉ lệ bucket có dữ liệu hợp lệ trên tổng số bucket kỳ vọng trong cửa sổ `[start, end]` | `clamp(n_valid_buckets / expected_buckets, 0.0, 1.0)`; không đưa vào vector X khi train nếu không dùng làm feature, dùng để lọc chất lượng mẫu |

- **Hằng số bất biến của `feature_version = 1`:** các ngưỡng `0.4`, `1.6`, `30.0`, `12.0`, `10.0` và hệ số `0.0185` là một phần định nghĩa của `feature_version = 1` (không phải ngưỡng sinh học trong `crop_profiles`), được phép cố định trong `climate_features.py`. Nếu thay đổi các hằng số hoặc danh sách đặc trưng này, **bắt buộc** tăng `FEATURE_VERSION`.

### 5.3 Xử lý `lux` null, `coverage` & cờ `low_confidence`
- **Xử lý `lux` null (chỉ node 1 có BH1750):**
  - Nếu một zone không có `lux` ở một bucket, mượn giá trị `lux` (hợp lệ `>= 0`) của **zone khác trong cùng nhà kính** tại đúng timestamp bucket đó.
  - Nếu cả nhà kính không có `lux` ở các bucket trong cửa sổ → `dli_mean = None` (LightGBM xử lý `NaN`/`None` trực tiếp).
- **Quy tắc `coverage`:**
  - Khi `coverage < min_coverage` (lấy từ `crop_profiles.parameters_json.ai.min_coverage`, mặc định `0.7`) → đánh dấu mẫu không đạt độ phủ; worker **không** chạy suy luận và **không** tạo `yield_samples` khi thu hoạch.
- **Quy tắc `low_confidence`:**
  - Gắn `low_confidence = True` nếu **độ dài cửa sổ `< 24 giờ`** (ví dụ chế độ `demo`, các đại lượng `/ngày` như `gdd_per_day`, `dli_mean` là ngoại suy) **hoặc** `coverage < min_coverage` (nếu có hiển thị) **hoặc** có đặc trưng nằm ngoài dải `[min, max]` của tập huấn luyện (kiểm tra OOD tại `worker/inference.py`).

## 6. Ràng buộc sử dụng ở các module khác

- **Ingestion (`worker/ingest.py`):** mọi mẫu đều lưu vào bảng `readings` kèm cột `quality` (không vứt bỏ bản ghi lỗi, để còn phục vụ chẩn đoán và kiểm thử T7).
- **Rule Engine (`worker/rules.py`):** **CHỈ** ra quyết định từ bản ghi `quality == 'ok'`.
- **Continuous Aggregates (`readings_1m`, `readings_1h`), DLI (`GET /zones/{id}/dli`), `climate_features.py` & ML (`ml/train.py`):** lọc `WHERE quality = 'ok'`.

## 7. Kiểm tra & Xác nhận

- Chạy `pytest platform/tests/test_vpd_dli.py platform/tests/test_quality.py` (và test `climate_features` ở M5):
  - `T=20, RH=94, leaf_offset_c=0` → VPD `0.14 kPa`;
  - Rút dây `soil_raw=0` → `out_of_range`;
  - `spike` có miễn trừ khi đứt quãng `> 3 * sample_interval_s`;
  - `stuck` đúng ngưỡng `30` (air) và `60` (soil_raw);
  - `climate_features`: đầu vào biết trước → khớp chính xác 16 đặc trưng và `coverage`, tách đúng giờ `06:00–18:00` theo `Asia/Ho_Chi_Minh`, mượn `lux` giữa các zone cùng nhà kính, trả `dli_mean = None` khi không có BH1750 nào, gắn `low_confidence = True` khi cửa sổ `< 24h`.
