# Feature: Kiểm thử Đơn vị, Tích hợp & Tiêu chí Chấp nhận Demo (`platform/tests/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 6.4, 8.2, 8.4, 15, 16; `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Đảm bảo chất lượng kỹ thuật của toàn bộ hệ thống GreenHub qua 3 tầng kiểm thử:
1. **Unit tests (nhanh, không cần Docker):** VPD/DLI, chất lượng dữ liệu A1, an toàn gateway, bảo mật/RBAC/ACL, command/shadow, và (M3–M5) rule engine, alert dedupe/leo thang, ML pipeline/metrics.
2. **Integration tests (`@pytest.mark.integration`):** chạy trọn vòng trên Docker Compose (`timescaledb` + `mosquitto` TLS + `api` + `worker` + `caddy`).
3. **Tiêu chí chấp nhận theo 5 kịch bản Demo (A–E)** và tiêu chí khởi động sạch trên mọi milestone.

## 2. Trạng thái hiện thực trong repo

- **Đã có (M2):**
  - `conftest.py`: cấu hình `WindowsSelectorEventLoopPolicy` trên Windows.
  - `test_smoke.py`: kiểm tra `Settings`, routes FastAPI OpenAPI, MQTT subscriptions của worker.
  - `test_vpd_dli.py`: kiểm tra `T=20, RH=94, leaf_offset=0 -> VPD ≈ 0.1403 kPa`, `leaf_offset`, ngưng tụ clamp 0, `lux_to_ppfd`, `integrate_dli` + chặn `max_gap_s`, `calc_risk_vpd_low`, `calc_risk_heat`.
  - `test_quality.py`: kiểm tra `ok`, `dropout` (flags + null, miễn trừ `FLAG_BH_ERR`), `out_of_range` (bao gồm rút dây ADC `soil_raw=0` và `4095`), `spike` (và miễn trừ sau mất mạng `> 3 * sample_interval_s`), `stuck` (`air=30`, `soil_raw=60`), `is_neighbor_divergent`.
  - `test_gateway_sim_safety.py`: kiểm tra `GatewaySafetyEngine` (interlock `fan` tắt `mist` + `side_effects=["mist_off"]`, chặn `mist` khi `fan` bật `reason="interlock"`, chặn `duration_s` ở `max_run_s`, auto-off khi `tick`, `min_gap_s`, `max_total_s_per_hour`, `expired`, idempotent `cmd_id`).
  - `test_core_and_api_unit.py`: Argon2 + JWT, 4 system crop templates, chuẩn hoá MAC & validation lệnh, DynSec ACL isolation, topic parser, kiểm tra `api.main` không import `lightgbm`/`sklearn`/`pandas`.
  - `test_worker_and_routers_unit.py`: 401/403 RBAC, `409 gateway_offline`, ghép MAC thủ công + bump `cfg_version`, `handle_ack` + `side_effects` + `actuator_logs`, `expire_manual_modes`.
  - `test_m2_integration.py`: end-to-end từ login → tạo greenhouse & gateway DynSec → kết nối MQTT TLS `:8883` → `discovery` → `pair` (cả discovered lẫn MAC nhập tay) → `config-sync` → telemetry + rút dây `out_of_range` → lệnh `mist` + `fan` interlock → `DLI` → kill tiến trình con kiểm tra Mosquitto LWT `online=false` + `409 gateway_offline`.
- **Cần bổ sung khi làm M3–M5:**
  - `test_rules_engine.py`: unit test cho `worker/rules.py` (tưới `fixed`/`adaptive`/fallback `<5` sự kiện, `soil_settle_s`, `min_gap`, `max_total`, quạt theo zone nguy hiểm nhất, chặn quạt khi `vpd > high_crit`, ép tắt `mist` khi đang `manual` + `lockout_s`, `fungal_minutes`, bỏ qua khi `quality != ok`).
  - `test_alerts_and_notify.py`: unit test cho `worker/alerts.py` & `worker/notify.py` (vòng đời 4 trạng thái, `dedupe_key` & partial index, cooldown 10 phút, auto-resolve hysteresis, leo thang `critical` gửi email, `pywebpush` 404/410 xóa subscription).
  - `test_ws_and_tenancy.py`: unit test xác thực `WS /ws?token=`, cô lập `farm_id` trên WS và trên toàn bộ API mới (`alerts`, `models`, `experiments`).
  - `test_ml_pipeline.py`: unit test `ml/features.py`, `ml/train.py`, `ml/evaluate.py` (time-based split không leak, loại `quality != ok`, baseline comparison, chỉ `is_active=True` khi thắng cả baseline & active cũ, KPI SQL `experiment_runs`).

## 3. Tiêu chí chấp nhận Kịch bản Demo (A–E, MUST)

Mọi thay đổi ở M3–M6 đều phải giữ hệ thống đáp ứng đầy đủ 5 kịch bản trong spec mục 15:

| Kịch bản | Kịch bản thực thi | Tiêu chí đạt bắt buộc |
|---|---|---|
| **A. Rủi ro nấm** | Bật `mist` thủ công từ web (hoặc chế độ `manual`) → RH tăng, VPD giảm dưới `low_crit` | 1. Xuất hiện cảnh báo sớm `DISEASE_RISK_FORECAST` trước.<br/>2. Khi điều kiện thật xảy ra (`vpd_low_duration_min` hoặc `fungal_minutes`), `DISEASE_RISK` mở, **quạt tự bật** và **máy tạo ẩm bị ép tắt** (kể cả đang `manual` + `lockout_s`).<br/>3. Web Push hiển thị trên điện thoại/desktop; bấm vào thông báo mở đúng trang `/zones/{id}`. |
| **B. Ẩm đất** | Đất khô dần xuống dưới `soil_min` | 1. Web hiển thị `"cần tưới sau ~N phút"` (từ `irrigation_eta`).<br/>2. Bơm chạy đúng hysteresis (`soil < soil_min` bật, `>= soil_max` tắt sớm) và giới hạn thời gian (`max_run_s`, `min_gap_s`, `max_total_s_per_hour`, `soil_settle_s`).<br/>3. Chuyển Auto/Manual từ web hoạt động đúng. |
| **C. Cảm biến & Mất kết nối** | 1. Rút dây cảm biến ẩm đất.<br/>2. Cắt Wi-Fi Gateway > `offline_failsafe_after_s`. | 1. Rút dây → `quality != 'ok'` (`out_of_range`/`dropout`), **không** tưới sai, bật alert `SENSOR_FAULT`.<br/>2. Cắt Wi-Fi → LWT báo `DEVICE_OFFLINE`, gateway vào failsafe (bơm/quạt đúng giới hạn + buzzer), khi online lại dữ liệu trong RAM buffer được gửi bù vào `readings`/`actuator_logs` và `cfg_version` tự đồng bộ. |
| **D. Đa farm** | Chạy simulator đăng ký thêm farm/nhà kính mới | Farm giả lập hiển thị trên web của farm sở hữu; cô lập tenant tuyệt đối (user Farm A không xem/tác động được dữ liệu Farm B). |
| **E. AI & Thí nghiệm** | Huấn luyện model + chạy 2 phiên `fixed` và `adaptive` | Trang Model & Thí nghiệm hiển thị version, ngày train, metrics vs baseline, dấu hiệu lệch dữ liệu; bảng KPI so sánh `fixed` vs `adaptive` tính từ SQL (báo cáo trung thực kể cả khi adaptive chưa thắng). |

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
