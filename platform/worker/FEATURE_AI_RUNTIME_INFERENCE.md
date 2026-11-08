# Feature: AI Runtime Inference & Scheduler trong Worker (`platform/worker/inference.py`, `scheduler.py`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 3.2, 6.1, 6.4, 8.2, 8.3, 9, 12, 16 (M5); `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Tích hợp các mô hình ML đã huấn luyện offline (`ml/train.py`) vào vòng vận hành thời gian thực của `worker`:
1. Nạp các artifact `.joblib` đang được đánh dấu `ml_models.is_active == True` từ `Settings.models_dir` (`/models`).
2. Chạy suy luận định kỳ **60 s/lần cho từng zone** để dự báo xác suất rủi ro nấm (`risk_forecast`) và thời gian còn lại tới khi cần tưới (`irrigation_eta`).
3. Cung cấp ước lượng đặc tính phản ứng (`pump_response` → `pump_gain_pct_per_s`; `fan_response` → `fan_vpd_rate_kpa_per_s`) cho `worker/rules.py` khi zone chạy chế độ `adaptive`.
4. Phát sinh alert cảnh báo sớm `DISEASE_RISK_FORECAST` (`warning`) khi `score >= Settings.risk_forecast_threshold` (mặc định `0.7`), nhưng **TUYỆT ĐỐI KHÔNG** tự kích hoạt thiết bị từ kết quả dự báo.

## 2. Trạng thái hiện thực trong repo

- **Đã có:**
  - `platform/worker/scheduler.py`: `create_worker_scheduler` đã có job `_tick_5s` (timeout lệnh, expire manual modes, dispatch pending commands, sync unsynced cfg).
  - `platform/requirements.txt`: đã ghim `numpy==2.5.4`, `pandas==3.1.1`, `scikit-learn==1.9.1`, `lightgbm==4.7.0`, `joblib==1.6.0` trong cùng Docker image của `worker` (`libgomp1` đã cài trong `platform/Dockerfile`).
  - `platform/core/models.py`: bảng `MlModel` (`is_active`, `artifact_path`, `metrics`, `baseline_metrics`) và `Prediction` (`zone_id, task, ts` PK).
- **Chưa hiện thực (`platform/worker/inference.py` hiện mới có docstring 1 dòng!):**
  - Cần xây dựng `InferenceService` (quản lý cache model trong RAM, `load_active_models`, `reload_models`, `run_cycle`, getter cho `pump_response` / `fan_response`).
  - Cần bổ sung job `60s` vào `worker/scheduler.py` (cộng thêm job kiểm tra leo thang cảnh báo `escalate_alerts` và watchdog offline nếu tách riêng) và lắng nghe sự kiện reload model (qua PG `NOTIFY` hoặc kiểm tra định kỳ `ml_models`).

## 3. Cơ chế Nạp & Cache Mô hình

1. **Khi `worker` khởi động (`load_active_models`):**
   - Truy vấn `SELECT * FROM ml_models WHERE is_active = TRUE`.
   - Với mỗi bản ghi, đọc file từ `Path(model.artifact_path)` (hoặc tương đối theo `Settings.models_dir`) bằng `joblib.load(...)` trong `asyncio.to_thread(...)`.
   - Lưu vào cache RAM theo khóa `(zone_id, task)`: gồm `model_id`, `version`, `estimator/params`, `feature_names`, `threshold` (cho `risk_forecast`), `train_stats` (mean/std đặc trưng lúc train để phục vụ kiểm tra drift).
2. **Hot-reload không cần restart container:**
   - Khi `ml.train` kích hoạt model mới: có thể phát `pg_notify` `CHANNEL_WORKER` `{"type": "model_activated", ...}` **và/hoặc** `InferenceService` tự kiểm tra `ml_models.is_active` thay đổi định kỳ mỗi 5 phút (phòng trường hợp `ml.train` chạy ngoài tiến trình API).

## 4. Chu kỳ Suy luận 60 giây (`run_cycle`)

Với mỗi `Zone` đang có dữ liệu `readings` (`quality = 'ok'`) gần đây:
1. **Lấy lịch sử đầu vào:**
   - Nạp cửa sổ `readings` (`quality = 'ok'`) và `actuator_logs` / `device_state.reported` gần nhất (đủ cho cửa sổ lớn nhất trong `crop_profile.risk.trend_windows_min`, ví dụ 60 phút cho `real` hoặc 15 phút cho `demo`).
   - Gọi hàm trích đặc trưng **dùng chung** từ `ml/features.py` (đảm bảo **zero training-serving skew** — đặc trưng lúc suy luận giống hệt lúc `ml/train.py` huấn luyện!). Lưu ý `ml/` đã được `COPY ml/ /app/ml/` trong `platform/Dockerfile` và nằm trong `PYTHONPATH`.
2. **Task `risk_forecast` (Tầng 3 – A3):**
   - Nếu có model active cho `(zone.id, 'risk_forecast')`: chạy `predict_proba` (hoặc lấy `score ∈ [0, 1]`).
   - Nếu chưa có model active → có thể dùng baseline ngoại suy tuyến tính VPD (tuỳ chọn ghi rõ `model_id = None, details = {"mode": "baseline"}` để trang Zone vẫn hoạt động trước khi train) hoặc bỏ qua.
   - Ghi/upsert vào bảng `predictions(ts=now_rounded, zone_id, task='risk_forecast', model_id, horizon_min, score, details)`.
   - Phát WS `prediction` lên `CHANNEL_WS`.
   - **Sinh Alert dự báo (MUST):**
     - So sánh `score >= threshold` (lấy ngưỡng tối ưu từ artifact validation hoặc `Settings.risk_forecast_threshold = 0.7`):
     - Nếu đạt **VÀ** zone hiện tại **chưa** ở trạng thái `DISEASE_RISK` thực tế → gọi `AlertService.raise_alert(alert_type="DISEASE_RISK_FORECAST", severity="warning", dedupe_key=f"DISEASE_RISK_FORECAST:{zone.id}", ...)` với thông điệp tiếng Việt (ví dụ: *"CẢNH BÁO SỚM: Nguy cơ nấm bệnh trong 15 phút tới (xác suất 82%)"*).
     - Nếu `score < threshold - 0.15` (hysteresis) → tự resolve `DISEASE_RISK_FORECAST`.
     - **Bắt buộc:** Dự báo này **KHÔNG** gọi `rules.py` để bật quạt ngay (spec 8.2: *"Dự báo không tự điều khiển thiết bị"*).
3. **Task `irrigation_eta` (Tầng 2 – A2):**
   - Dùng model active `(zone.id, 'irrigation_eta')` hoặc fallback baseline hồi quy tuyến tính tốc độ giảm ẩm đất (`(soil_now - soil_min) / drying_rate`).
   - Nếu độ ẩm đất đã `<= soil_min` → `value = 0.0`. Nếu tốc độ giảm `<= 0` (đất đang ẩm lên hoặc ổn định) → trả `null` hoặc giá trị trần hợp lý kèm `details`.
   - Ghi vào `predictions(zone_id, task='irrigation_eta', value=<phút_còn_lại>, ...)` và phát WS `prediction` để trang Zone hiển thị *"Cần tưới sau ~N phút"*.
4. **Cung cấp A2 `pump_response` & `fan_response` cho Rule Engine:**
   - Cung cấp phương thức `get_pump_gain(zone_id, soil_before) -> tuple[float, int] | None` (trả về `(gain_pct_per_s, n_events)`) và `get_fan_rate(zone_id) -> tuple[float, int] | None` cho `rules.py`.
   - Artifact của `pump_response` / `fan_response` có thể lưu median gain hoặc mô hình Ridge `Δ ~ d + before` + số mẫu `n_samples`. Nếu `n_samples < 5` hoặc không có model active, `rules.py` tự động fallback về chiến lược `fixed`.

## 5. Lưu ý Hiệu năng & Bộ nhớ (`t3.small` 512 MB cho `worker`)

- Giới hạn số dòng truy vấn khi trích đặc trưng mỗi 60 s (chỉ lấy tối đa 2 giờ gần nhất cho từng zone thay vì quét toàn bộ bảng `readings`).
- Đặt `n_jobs=1` khi suy luận LightGBM/scikit-learn để tránh tạo hàng loạt thread trên container `t3.small` 2 vCPU.
- Với simulator thử tải 100 gateway (200 zone), có thể lọc chỉ chạy inference cho zone có telemetry mới trong 5 phút gần nhất hoặc batch nhẹ để giữ CPU ổn định.

## 6. Kiểm tra & Xác nhận

- `test_api_process_does_not_import_heavy_ml_libraries` vẫn phải pass (không kéo `inference.py` vào `api`).
- Kịch bản A: khi tăng RH (bật máy tạo ẩm), `risk_forecast` tăng trước và kích hoạt `DISEASE_RISK_FORECAST` trước khi `DISEASE_RISK` thật xảy ra.
- Kịch bản B: khi đất khô dần, `predictions(task='irrigation_eta')` ghi nhận số phút giảm dần và hiển thị trên Web Console.
