# Feature: Rule & Control Engine (`platform/worker/rules.py`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 3.2, 6.4, 7.1, 8.2, 8.3, 12, 15, Phụ lục B; `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Thực hiện vòng lặp điều khiển tự động trên cloud cho mỗi nhà kính:
1. Tưới nước theo từng zone (hỗ trợ cả chiến lược `fixed` và `adaptive` lấy `pump_gain_pct_per_s` từ mô hình A2).
2. Điều khiển quạt thông gió chung cho cả nhà kính dựa trên zone nguy hiểm nhất (hỗ trợ `fixed` và `adaptive` lấy `fan_vpd_rate_kpa_per_s` từ A2).
3. Điều khiển máy tạo ẩm (auto khi quá khô VPD > `high_crit`, và ép tắt ngay cả khi đang `manual` + lockout khi quạt tự bật vì rủi ro).
4. Tính tích luỹ `fungal_minutes` và kích hoạt/resolve các cảnh báo theo luật (`DISEASE_RISK`, `HEAT_STRESS`, `SOIL_DRY`, `SENSOR_FAULT`).

- **Ngoài phạm vi:** Dự báo AI (`DISEASE_RISK_FORECAST`) **không** tự động điều khiển thiết bị; AI chỉ nằm trong vòng điều khiển ở bước tính `duration_s` cho `adaptive` (bị chặn bởi `max_run_s`/`max_on_s` ở cả cloud và gateway).

## 2. Trạng thái hiện thực trong repo

- **Chưa hiện thực (`platform/worker/rules.py` hiện mới chỉ có docstring 1 dòng!).**
- Các khối phụ trợ đã sẵn sàng để `rules.py` dùng ngay:
  - `core.crop_templates.CropParameters` / `SYSTEM_CROP_TEMPLATES`
  - `core.vpd.calc_risk_vpd_low`, `core.vpd.calc_risk_heat`
  - `core.models.Command`, `ActuatorLog`, `DeviceState`, `Zone`, `CropProfile`, `Reading`, `Alert`, `MlModel`
  - `worker.commands.dispatch_pending_commands`
  - `worker.shadow.ensure_device_state`

## 3. Kích hoạt & Trạng thái ngắn hạn trong RAM

- **Thời điểm kích hoạt (MUST):**
  1. Ngay khi `IngestService.handle_telemetry()` lưu xong một bản tin telemetry mới của một zone.
  2. Trong **tick 5 s** của `worker/scheduler.py` để kiểm tra hết hạn timer, settle cooldown, đánh giá lại quạt/ẩm khi hết `min_on_s`, hoặc phát hiện mất telemetry kéo dài.
- **Trạng thái ngắn hạn giữ trong RAM (`ZoneRuleState`, `GreenhouseRuleState`):**
  - Theo spec 3.2: giữ trong bộ nhớ và **dựng lại (`warm_up`) từ N phút `readings` & `actuator_logs` gần nhất khi `worker` khởi động lại**:
    - `fungal_minutes` (số phút tích luỹ điều kiện nấm của từng zone).
    - `vpd_low_streak_s` (thời gian liên tục có `vpd < vpd.low_crit` của từng zone).
    - `soil_low_streak_s` (thời gian liên tục `soil < soil_moisture_critical_low_pct` để phát `SOIL_DRY`).
    - `last_pump_end_at` / `pump_hourly_runs` / `soil_settle_until` theo từng zone/bơm.
    - `fan_on_since`, `fan_auto_reason` (bật vì rủi ro hay nhiệt), `mist_lockout_until`, `last_mist_end_at`.
    - `last_valid_reading` (dùng làm dự phòng cảm biến khí giữa các zone cùng nhà kính).

## 4. Xử lý dữ liệu lỗi A1 & Mất cảm biến (MUST)

- **CHỈ sử dụng dữ liệu có `quality == 'ok'`.**
- Khi bản tin mới có `quality != 'ok'`:
  - **Cảm biến đất lỗi** (`quality ∈ {'dropout', 'out_of_range', 'spike', 'stuck'}` liên quan đất hoặc tổng quát khi `soil_raw` ngoài `[50, 4090]` / `FLAG_SOIL_ERR` / không có dữ liệu quá `3 * sample_interval_s`):
    - **TUYỆT ĐỐI KHÔNG** phát lệnh tưới cho zone đó.
    - Mở (hoặc duy trì) alert `SENSOR_FAULT` (severity `warning` hoặc `critical`, `dedupe_key = "SENSOR_FAULT:{zone_id}"`).
  - **Cảm biến khí lỗi** (`FLAG_AHT_ERR`, `air_temp`/`air_rh` `out_of_range` / `stuck` / `dropout`):
    - Mở alert `SENSOR_FAULT` cho zone đó.
    - Nếu trong cùng nhà kính có zone lân cận có bản tin khí `quality == 'ok'` còn mới (trong vòng `3 * sample_interval_s`) và **không** bị gắn `neighbor_suspect` sai lệch bất thường → dùng tạm giá trị khí (`air_temp`, `air_rh`, `vpd`) của zone lân cận cho quyết định quạt/máy tạo ẩm; nếu không có zone lân cận hợp lệ → **bỏ qua** quyết định khí hậu cho zone đó (không bật quạt/tạo ẩm mù).
- Khi cảm biến gửi lại liên tục dữ liệu `quality == 'ok'` ổn định (ví dụ 2–3 mẫu liên tiếp) → tự động `resolve` alert `SENSOR_FAULT`.

## 5. Logic Điều khiển từng Thiết bị (MUST)

Trước khi phát lệnh cho một actuator bất kỳ (`pump_1`, `pump_2`, `fan`, `mist`), phải kiểm tra:
1. Gateway đang `online == True`.
2. Actuator không bị kẹt bởi lệnh `pending`/`sent` đang chờ ACK cùng loại để tránh tạo lệnh trùng lặp.
3. Chế độ tại `device_state.desired["modes"][actuator]` là `"auto"` (ngoại trừ trường hợp ép tắt `mist` vì an toàn bên dưới!).

### 5.1 Tưới nước theo Zone (`pump_1` / `pump_2` theo `zone.pump_channel`)

Lấy tham số từ `CropProfile`: `soil_min = soil_moisture_pct.min`, `soil_max = soil_moisture_pct.max`, `irr = irrigation.*`.
- **Tắt sớm (Hysteresis trên):**
  - Nếu bơm của zone đang `"on"` (trong `reported.actuators`) và `soil_moisture >= soil_max` → phát lệnh `action = "off"`, `reason = f"soil_reached_max:{soil:.1f}>={soil_max}"`.
- **Chặn an toàn & Cooldown trước khi bật:**
  - Nếu đang trong thời gian chờ đất thấm (`now < last_pump_end + irr.soil_settle_s`) → **không tưới** (tránh tưới lặp do cảm biến ẩm đất phản ứng chậm).
  - Nếu chưa qua khoảng nghỉ tối thiểu (`now < last_pump_end + irr.min_gap_s`) → không tưới.
  - Nếu tổng `duration_s` bơm đã `applied`/chạy trong 3600 s gần nhất `+ duration_s > irr.max_total_s_per_hour` → không tưới (chỉ cho phép tối đa phần còn lại nếu hợp lý, hoặc đợi hết cửa sổ 1 giờ).
- **Điều kiện BẬT:** `soil_moisture < soil_min` và bơm đang `"off"`:
  - **Chiến lược `fixed` (`zone.control_strategy == 'fixed'`):**
    - `duration_s = irr.max_run_s`.
    - `reason = f"fixed_soil_low:{soil:.1f}<{soil_min}"`.
  - **Chiến lược `adaptive` (`zone.control_strategy == 'adaptive'`):**
    - Kiểm tra mô hình `ml_models` active cho `(zone_id, task='pump_response')` có số sự kiện `n_samples >= min_events` (mặc định `5`) và `pump_gain_pct_per_s > 0`.
    - Nếu **không đủ** điều kiện / chưa có model → **tự động fallback về `fixed`** (`duration_s = irr.max_run_s`, ghi rõ `reason` có `fallback_fixed`).
    - Nếu **đủ**:
      - `target = (soil_min + soil_max) / 2.0`
      - `raw_d = (target - soil_now) / pump_gain_pct_per_s`
      - `duration_s = int(round(clamp(raw_d, 3, irr.max_run_s)))`
      - `reason = f"adaptive_gain:{pump_gain:.3f}_target:{target:.1f}"`.

### 5.2 Quạt thông gió chung cho cả Nhà kính (`fan`)

Một nhà kính chỉ có **1 quạt** dùng chung cho toàn bộ các zone. Do đó **MUST đánh giá trên tập tất cả các zone hợp lệ trong nhà kính, ưu tiên zone nguy hiểm nhất** (xếp hạng bằng `max(risk_vpd_low, risk_heat)` theo Phụ lục B).

- **Điều kiện BẬT quạt** (chỉ cần **ít nhất 1 zone** thỏa một trong 3 điều kiện):
  1. `vpd < vpd.low_crit` liên tục `>= risk.vpd_low_duration_min` phút; **HOẶC**
  2. Đang có alert `DISEASE_RISK` mở (`state != 'resolved'`) ở zone thuộc nhà kính này; **HOẶC**
  3. `air_temp > temp_c.optimal[1]` ở zone nào đó.
- **Kiểm tra tác dụng phụ (Side-effect Guard, MUST):**
  - Không bật quạt nếu bất kỳ zone kích hoạt điều kiện hoặc zone nhạy cảm đang có `vpd > vpd.high_crit` (quạt thổi làm giảm ẩm và tăng VPD thêm, gây héo cây), *trừ trường hợp quá nhiệt cực đoan vượt `temp_c.optimal[1]` cần cân nhắc ưu tiên nhiệt, nhưng theo spec 6.4: "không bật quạt nếu VPD của zone đó đang > `vpd.high_crit` (quạt làm tăng VPD)"* → kiểm tra chặt trên zone đó!
- **Ép tắt máy tạo ẩm (An toàn thắng thủ công, MUST):**
  - Khi quạt tự động bật vì rủi ro (`fan` sẽ bật từ auto rule) và `mist` hiện đang `"on"` (bất kể `mist` đang ở mode `auto` hay `manual`!):
    1. Gateway sẽ thực thi interlock `mist_off` ngay khi nhận lệnh `fan on`, **đồng thời** Rule Engine đặt `mist_lockout_until = now + mist.lockout_s` (có thể chủ động phát `mist off` nếu cần chắc chắn hoặc dựa vào interlock `fan on` + lockout không cho bật lại `mist` trong `lockout_s`).
    2. Đặt `mist` lockout trong `mist.lockout_s` để rule `auto` (và cảnh báo nếu manual cố bật lại) không bật `mist` ngay sau đó.
- **Tính `duration_s` khi BẬT quạt** (dựa trên thông số của zone nguy hiểm nhất):
  - **`fixed`:** `duration_s = fan.min_on_s` (nếu điều kiện vẫn còn khi sắp hết/vừa tắt sau `min_on_s`, rule engine phát lệnh mới để duy trì).
  - **`adaptive`:** nếu zone kích hoạt có `control_strategy == 'adaptive'` và model `fan_response` active (`>= 5` sự kiện, `fan_vpd_rate_kpa_per_s > 0`):
    - `raw_d = (vpd.low_off - vpd_now) / fan_vpd_rate_kpa_per_s`
    - `duration_s = int(clamp(round(raw_d), fan.min_on_s, fan.max_on_s))`
    - Nếu thiếu model/dữ liệu → fallback `fan.min_on_s`.
- **Điều kiện TẮT quạt (Hysteresis):**
  - Khi quạt đang `"on"` (do `auto`), chỉ gửi `action = "off"` khi **tất cả** các điều kiện sau đều đạt:
    1. Đã chạy tối thiểu `fan.min_on_s` kể từ lúc bật (`now - fan_on_since >= fan.min_on_s`).
    2. Với mọi zone có dữ liệu khí hợp lệ: `vpd >= vpd.low_off` **VÀ** `air_temp <= temp_c.optimal[1]` (nhiệt độ ổn định, có thể thêm hysteresis nhẹ ví dụ `optimal[1] - 0.5`).
    3. Không còn alert `DISEASE_RISK` cần thông gió cưỡng bức (lưu ý `DISEASE_RISK` cũng tự resolve theo hysteresis khi `vpd >= vpd.low_off` và `fungal_minutes` giảm về 0).

### 5.3 Máy tạo ẩm (`mist`)

- **Auto BẬT:** Chỉ khi:
  - `modes["mist"] == "auto"`
  - Có ít nhất 1 zone `vpd > vpd.high_crit`
  - Quạt (`fan`) hiện đang `"off"` (tôn trọng interlock)
  - Đã hết thời gian khóa `now >= mist_lockout_until` (do quạt bật trước đó) và đã qua `min_gap` (ví dụ `mist.lockout_s` hoặc `min_gap` cấu hình sau lần phun trước)
  - Thời lượng: `duration_s = mist.max_on_s`.
- **Auto TẮT:** Khi `mist` đang `"on"` (auto) và mọi zone đều có `vpd <= vpd.high_crit` (hoặc `<= vpd.optimal[1]`) → gửi `off`.
- **Điều khiển tay (Demo kịch bản A):** Khi user đặt `mist` ở `manual` và bật `mist` qua API để tạo hơi ẩm nâng RH > 90% làm VPD tụt xuống `< 0.4 kPa`, Rule Engine không được tự ý tắt `mist` **cho tới khi** điều kiện rủi ro nấm xảy ra khiến quạt tự bật — lúc đó quạt tự bật và **ép tắt** `mist` + khóa `mist.lockout_s`.

## 6. Đánh giá Rủi ro nấm & Sinh Alert theo Luật (MUST)

### 6.1 Tích luỹ `fungal_minutes` (theo từng zone)
- Tại mỗi bản tin `quality == 'ok'`, tính khoảng thời gian `dt_min = min(dt_s, 3 * sample_interval_s) / 60.0`:
  - Nếu `air_rh >= disease.rh_gt` **VÀ** `disease.temp_range_c[0] <= air_temp <= disease.temp_range_c[1]`:
    - `fungal_minutes += dt_min`
  - Ngược lại (hết điều kiện thuận lợi cho bào tử nấm):
    - Giảm dần hoặc đưa về 0 theo hysteresis (ví dụ giảm tốc độ `2 * dt_min` hoặc reset về 0 khi `vpd >= vpd.low_off` và `air_rh < disease.rh_gt - 5` để tránh bật/tắt chập chờn).
- **Alert `DISEASE_RISK`** (`dedupe_key = "DISEASE_RISK:{zone_id}"`, severity `critical` hoặc `warning` — khuyến nghị `critical` khi kết hợp VPD < `low_crit` kéo dài để kích hoạt leo thang & push yêu cầu tương tác theo Kịch bản A):
  - **Mở khi:** `fungal_minutes >= disease.fungal_minutes_alert` **HOẶC** `vpd_low_streak_s >= risk.vpd_low_duration_min * 60`.
  - **Tự Resolve khi:** `vpd >= vpd.low_off` **VÀ** `fungal_minutes < disease.fungal_minutes_alert * 0.5` (hoặc `== 0`).

### 6.2 Các cảnh báo theo luật khác
- **`HEAT_STRESS`** (`dedupe_key = "HEAT_STRESS:{zone_id}"`, severity `critical`):
  - **Mở khi:** `air_temp >= failsafe.temp_critical_high_c`.
  - **Tự Resolve khi:** `air_temp <= failsafe.temp_critical_high_c - 2.0` (hysteresis 2 °C).
- **`SOIL_DRY`** (`dedupe_key = "SOIL_DRY:{zone_id}"`, severity `warning` / `critical` nếu kéo dài):
  - **Mở khi:** `soil_moisture < failsafe.soil_moisture_critical_low_pct` kéo dài qua nhiều chu kỳ (ví dụ `>= 3 * sample_interval_s` hoặc không tăng sau thời gian chờ).
  - **Tự Resolve khi:** `soil_moisture >= soil_moisture_pct.min`.
- **`SENSOR_FAULT`** (`dedupe_key = "SENSOR_FAULT:{zone_id}"`, severity `warning`):
  - **Mở khi:** `quality != 'ok'` (hoặc mất telemetry `> 3 * sample_interval_s` khi gateway vẫn online).
  - **Tự Resolve khi:** nhận được dữ liệu `quality == 'ok'` liên tiếp (ví dụ 2–3 mẫu).

## 7. Kiểm tra & Xác nhận

- Unit tests bắt buộc (spec mục 15):
  - Hysteresis tưới (`soil < min` bật, `soil >= max` tắt sớm), `min_gap_s`, `max_total_s_per_hour`, `soil_settle_s`.
  - Adaptive fallback về `fixed` khi số sự kiện `< 5` hoặc chưa có model; tính đúng `duration_s` được clamp `[3, max_run_s]` khi có `pump_gain`.
  - Quạt ưu tiên zone nguy hiểm nhất; không bật quạt khi VPD > `high_crit`; tắt sau `min_on_s` khi `vpd >= low_off`.
  - **Kịch bản A (quan trọng):** `mist` đang bật ở chế độ `manual` → `vpd < low_crit` kéo dài `vpd_low_duration_min` → phát `DISEASE_RISK` → quạt tự bật + ép tắt `mist` + khóa `mist.lockout_s`.
  - **Kịch bản C:** cảm biến đất `out_of_range` (`soil_raw=0`) → **không** phát lệnh tưới, phát `SENSOR_FAULT`.
