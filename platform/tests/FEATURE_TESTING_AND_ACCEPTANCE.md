# Feature: Kiểm thử Đơn vị, Tích hợp & Tiêu chí Chấp nhận Demo (`platform/tests/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 6.4, 8.1–8.4, 15, 16; `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Đảm bảo chất lượng kỹ thuật của toàn bộ hệ thống GreenHub qua 3 tầng kiểm thử:
1. **Unit tests (nhanh, không cần Docker):** VPD/DLI, kiểm tra chất lượng dữ liệu (luật), an toàn gateway, bảo mật/RBAC/ACL, command/shadow, rule engine hysteresis, alert dedupe/leo thang, đặc trưng khí hậu (`climate_features`), mô hình sinh trưởng tất định, và pipeline AI/ML dự đoán năng suất & gợi ý cây trồng.
2. **Integration tests (`@pytest.mark.integration`):** chạy trọn vòng trên Docker Compose (`timescaledb` + `mosquitto` TLS + `api` + `worker` + `caddy`).
3. **Tiêu chí chấp nhận theo 5 kịch bản Demo (A–E)** và tiêu chí khởi động sạch trên mọi milestone.

## 2. Trạng thái hiện thực & Danh mục Test (M2–M5)

### 2.1 Các test nền tảng (M2 – giữ & cập nhật đồng bộ schema mới)
- `conftest.py`: cấu hình `WindowsSelectorEventLoopPolicy` trên Windows.
- `test_smoke.py`: kiểm tra `Settings`, routes FastAPI OpenAPI, MQTT subscriptions của worker.
- `test_vpd_dli.py`: kiểm tra `T=20, RH=94, leaf_offset=0 -> VPD ≈ 0.1403 kPa`, `leaf_offset`, ngưng tụ clamp 0, `lux_to_ppfd`, `integrate_dli` + chặn `max_gap_s`, `calc_risk_vpd_low`, `calc_risk_heat`.
- `test_quality.py`: kiểm tra `ok`, `dropout` (flags + null, miễn trừ `FLAG_BH_ERR`), `out_of_range` (bao gồm rút dây ADC `soil_raw=0` và `4095`), `spike` (và miễn trừ sau mất mạng `> 3 * sample_interval_s`), `stuck` (`air=30`, `soil_raw=60`), `is_neighbor_divergent`.
- `test_gateway_sim_safety.py`: kiểm tra `GatewaySafetyEngine` (interlock `fan` tắt `mist` + `side_effects=["mist_off"]`, chặn `mist` khi `fan` bật `reason="interlock"`, chặn `duration_s` ở `max_run_s`, auto-off khi `tick`, `min_gap_s`, `max_total_s_per_hour`, `expired`, idempotent `cmd_id`).
- `test_core_and_api_unit.py`: Argon2 + JWT, **10 system crop templates** (5 cây × `real`/`demo`, `schema_version = 2`, có `crop_code`, `light.dli_optimal`, `cycle.days`, `yield.reference_kg_m2`, `ai.*`), chuẩn hoá MAC & validation lệnh, DynSec ACL isolation, topic parser, và `test_api_process_does_not_import_heavy_ml_libraries` (bảo vệ ngân sách RAM trên VPS 2 GB: tiến trình `api` không import `lightgbm`/`sklearn`/`pandas`).
- `test_worker_and_routers_unit.py`: 401/403 RBAC, `409 gateway_offline`, ghép MAC thủ công + bump `cfg_version`, `handle_ack` + `side_effects` + `actuator_logs`, `expire_manual_modes`.
- `test_m2_integration.py`: end-to-end từ login → tạo greenhouse & gateway DynSec → kết nối MQTT TLS `:8883` → `discovery` → `pair` (cả discovered lẫn MAC nhập tay) → `config-sync` → telemetry + rút dây `out_of_range` → lệnh `mist` + `fan` interlock → `DLI` → kill tiến trình con kiểm tra Mosquitto LWT `online=false` + `409 gateway_offline`.

### 2.2 Các test M3–M5 (bắt buộc cập nhật / bổ sung)
- `test_rules_engine.py`: unit test cho `worker/rules.py` với **chiến lược hysteresis cố định duy nhất** (`soil < soil_min` bật `max_run_s`, tắt sớm khi `soil >= soil_max`, `soil_settle_s`, `min_gap_s`, `max_total_s_per_hour`, quạt theo zone nguy hiểm nhất, chặn quạt khi `vpd > high_crit`, ép tắt `mist` khi đang `manual` + `lockout_s`, `fungal_minutes`, bỏ qua khi `quality != 'ok'`).
- `test_alerts_and_notify.py`: unit test cho `worker/alerts.py` & `worker/notify.py` (vòng đời 4 trạng thái, `dedupe_key` & partial index, cooldown 10 phút, auto-resolve hysteresis, leo thang `critical` gửi email, `pywebpush` 404/410 xóa subscription).
- `test_ws_and_tenancy.py`:
  - Xác thực `WS /ws?token=`, fan-out đúng `farm_id` cho 7 loại thông điệp (gồm `prediction` với `task ∈ {yield_forecast, crop_recommendation}` và `crop_cycle`).
  - Cô lập `farm_id` trên toàn bộ API mới (`alerts`, `cycles`, `predictions`, `recommendations`, `models`), kiểm tra tuyệt đối không có endpoint đọc `yield_samples` và `GET /models*` chỉ trả số liệu tổng hợp.
- `test_climate_and_growth.py` *(MUST)*:
  - `climate_features` (`platform/core/climate_features.py`): đầu vào biết trước (`readings_1h` và `readings_1m` với giờ địa phương `Asia/Ho_Chi_Minh`) → kiểm tra chính xác toàn bộ 16 đặc trưng số (`t_mean`, `t_day_mean`, `t_night_mean`, `t_p95`, `t_p05`, `rh_mean`, `vpd_mean`, `vpd_std`, `frac_vpd_low`, `frac_vpd_high`, `frac_t_gt_30`, `frac_t_lt_12`, `gdd_per_day`, `dli_mean` gồm trường hợp mượn lux cùng nhà kính & `null`, `soil_mean`, `soil_std`), kiểm tra ngưỡng `coverage < ai.min_coverage` (`0.7`) và cờ `low_confidence` (khi cửa sổ `< 24 h` hoặc khi đặc trưng vượt ngoài `[min, max]` tập train — OOD).
  - Mô hình sinh trưởng (`tools/simulator/growth.py`): kiểm tra tính tất định (deterministic) theo `seed`, tạo `oracle_relative_yields` nhất quán qua các vùng khí hậu.
- `test_ml_pipeline.py` *(MUST)*:
  - Chia dữ liệu **theo nhà kính** (`GroupShuffleSplit` theo `greenhouse_key`, 70/15/15 train/val/test) **không rò rỉ**: xác nhận không có `greenhouse_key` nào xuất hiện ở cả hai tập train và val/test.
  - Kiểm tra baseline **B0** (median `relative_yield` theo từng cây trên train) và **B1** (Ridge trên cùng đặc trưng + one-hot `crop_code`).
  - Quy tắc kích hoạt mô hình (Activation Gate): chỉ `is_active = True` (tắt bản cũ + `NOTIFY worker_events model_activated`) khi mô hình mới thắng **cả B0, B1 và bản đang active** về MAE trên test; nếu không thắng vẫn lưu artifact + bản ghi `ml_models(is_active=False)` và ghi rõ lý do vào `notes`.
  - Thuật toán gợi ý cây trồng (`crop_recommendation`): cố định `soil_mean` ở trung điểm `soil_moisture_pct` của từng cây và `soil_std` ở median tập train, xếp hạng giảm dần theo `relative_yield`, lấy top-3 và sinh tối đa 3 lý do giải thích bằng luật tiếng Việt.
- `test_cycles_and_inference.py` *(MUST)*:
  - Vòng đời vụ trồng (`POST /zones/{id}/cycles` tự cập nhật `zones.crop_profile_id` + bump `cfg_version`, trả `409` nếu zone đã có vụ active; `POST /cycles/{id}/abandon`).
  - Luồng thu hoạch `harvest → yield_samples`: `POST /cycles/{id}/harvest` → worker xử lý `cycle_harvested` → tạo `yield_samples` (`source = 'sim'` nếu `gateway.is_simulated`, ngược lại `'real'`; bỏ qua nếu `coverage < ai.min_coverage` và ghi lý do vào `crop_cycles.notes`).
  - Worker `InferenceService`: suy luận `yield_forecast` cho zone có vụ `active` đủ `ai.min_cycle_hours`, suy luận `crop_recommendation` khi định kỳ hoặc nhận `recommend` refresh, không phát lệnh điều khiển tới actuator.

## 3. Tiêu chí chấp nhận Kịch bản Demo (A–E, MUST)

Mọi thay đổi ở M3–M6 đều phải giữ hệ thống đáp ứng đầy đủ 5 kịch bản trong spec mục 15:

| Kịch bản | Kịch bản thực thi | Tiêu chí đạt bắt buộc |
|---|---|---|
| **A. Rủi ro nấm** | Bật `mist` thủ công từ web (chế độ `manual`) → RH tăng, VPD giảm dưới `low_crit` | 1. Khi điều kiện thật xảy ra (`vpd_low_duration_min` hoặc `fungal_minutes`), `DISEASE_RISK` mở, **quạt tự bật** và **máy tạo ẩm bị ép tắt** (kể cả đang `manual` + `lockout_s`).<br/>2. Web Push hiển thị trên điện thoại/desktop; bấm vào thông báo mở đúng trang `/zones/{id}`. |
| **B. Ẩm đất** | Đất khô dần xuống dưới `soil_min` | 1. Bơm chạy đúng hysteresis (`soil < soil_min` bật, `>= soil_max` tắt sớm) và giới hạn thời gian (`max_run_s`, `min_gap_s`, `max_total_s_per_hour`, `soil_settle_s`).<br/>2. Chuyển Auto/Manual từ web hoạt động đúng. |
| **C. Cảm biến & Mất kết nối** | 1. Rút dây cảm biến ẩm đất.<br/>2. Cắt Wi-Fi Gateway > `offline_failsafe_after_s`. | 1. Rút dây → `quality != 'ok'` (`out_of_range`/`dropout`), **không** tưới sai, bật alert `SENSOR_FAULT`.<br/>2. Cắt Wi-Fi → LWT báo `DEVICE_OFFLINE`, gateway vào failsafe (bơm/quạt đúng giới hạn + buzzer), khi online lại dữ liệu trong RAM buffer được gửi bù vào `readings`/`actuator_logs` và `cfg_version` tự đồng bộ. |
| **D. Đa farm** | Chạy simulator đăng ký thêm farm/nhà kính mới | Farm giả lập hiển thị trên web của farm sở hữu; cô lập tenant tuyệt đối (user Farm A không xem/tác động được dữ liệu Farm B; không lộ `yield_samples` qua API). |
| **E. AI (Năng suất & Gợi ý cây)** | Huấn luyện mô hình toàn cục `yield` + chạy worker suy luận trên nhà kính thật và các nhà kính giả lập nhiều vùng khí hậu | 1. Trang **Mô hình AI** hiển thị phiên bản active, ngày train, `source_mix`, số nhà kính, metrics trên nhà kính chưa thấy so với **B0/B1**, MAE theo cây, `Top-1` / `NDCG@3` và dấu hiệu drift.<br/>2. Zone có vụ đang trồng hiển thị năng suất dự kiến (`kg/m²` + khoảng tin cậy, cờ độ tin cậy).<br/>3. Trang **Gợi ý cây trồng** hiển thị top-3 cho nhà kính thật; các nhà kính giả lập ở vùng khí hậu khác nhau cho gợi ý khác nhau hợp lý (vd `dalat` → dâu tây/xà lách, `hcm` → dưa leo/ớt chuông).<br/>4. Thay đổi khí hậu nhà kính thật (bật máy tạo ẩm/quạt/đèn) rồi bấm **Làm mới** → tóm tắt khí hậu và xếp hạng gợi ý cập nhật. |

## 4. Tiêu chí khởi động sạch (Mọi Milestone)

- Từ thư mục gốc với file `.env` hợp lệ và chứng chỉ dev/prod:
  `docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up -d --build`
  khởi động toàn bộ 5 container (`timescaledb`, `mosquitto`, `api`, `worker`, `caddy`) khỏe mạnh (`healthy`), migration Alembic chạy tự động, không cần thao tác thủ công ngoài `.env` (và `seed_dev` nếu cần dữ liệu mẫu dev).

## 5. Lệnh chạy kiểm thử

```powershell
# Unit tests (nhanh, chạy mọi lúc)
.venv\Scripts\pytest.exe -m "not integration"

# Integration test (yêu cầu Docker dev stack đang chạy)
.venv\Scripts\pytest.exe -v -m integration

# Lint Python & Build Web
.venv\Scripts\ruff.exe check .
npm run build --prefix web
```
