# Feature: AI Runtime Inference, Yield Sample & Scheduler trong Worker (`platform/worker/inference.py`, `scheduler.py`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 3.2, 6.1, 6.6, 7, 7.1, 8.2, 8.3, 13.3, 15, 16 (M5); `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Vận hành lớp AI runtime trong tiến trình `worker` cho **bài toán duy nhất `task = 'yield'`** (dự đoán năng suất cây trồng & gợi ý cây nên trồng):
1. Nạp và cache **một mô hình toàn cục `yield` active** (`/models/yield/v{n}.joblib`) khi khởi động, hot-reload khi nhận `NOTIFY worker_events {"type": "model_activated"}` và kiểm tra bù mỗi **10 phút**.
2. Tiếp nhận `NOTIFY worker_events {"type": "cycle_harvested", "cycle_id": ...}` để tổng hợp đặc trưng khí hậu trên toàn vụ và tạo mẫu huấn luyện vào `yield_samples` (`source = 'sim'` nếu `gateway.is_simulated`, ngược lại `'real'`).
3. Chạy suy luận định kỳ theo `ai.inference_interval_s` (trong `asyncio.to_thread` để không chặn event loop):
   - **`yield_forecast`**: cho mọi zone có vụ `status = 'active'` chạy `>= ai.min_cycle_hours` (dùng ẩm đất thực tế).
   - **`crop_recommendation`**: cho mọi nhà kính có dữ liệu trong `recommend_window_h` gần nhất (gộp `quality = 'ok'` các zone, đặt `soil_mean` ở trung điểm của từng cây ứng viên).
4. Xử lý làm mới gợi ý theo yêu cầu (`NOTIFY worker_events {"type": "recommend", "greenhouse_id": ...}`).
5. *(MAY)* Phát alert `YIELD_FORECAST_LOW` (`info`) khi `relative_yield < 0.6`.
6. **Bất biến an toàn & kiến trúc:** Dự báo và gợi ý **TUYỆT ĐỐI KHÔNG** gửi lệnh điều khiển tới thiết bị; tiến trình `api` **KHÔNG** import `inference.py` hay `pandas`/`scikit-learn`/`lightgbm`/`joblib` (giữ ngân sách RAM trên VPS 2 GB RAM).

## 2. Trạng thái hiện thực trong repo

- **Hạ tầng đã sẵn sàng:**
  - `platform/requirements.txt`: đã ghim `numpy==2.5.4`, `pandas==3.1.1`, `scikit-learn==1.9.1`, `lightgbm==4.7.0`, `joblib==1.6.0`.
  - `platform/Dockerfile`: đã cài `libgomp1`, `COPY ml/ /app/ml/` và `ENV MODELS_DIR=/models`.
  - `platform/worker/scheduler.py`: đã có job `_tick_5s` (timeout lệnh, expire manual modes, `rule_engine.tick_5s`, `escalate_alerts`, dispatch pending commands, sync unsynced cfg).
- **Cần viết lại / bổ sung ở M5:**
  - `platform/worker/inference.py` và `scheduler.py`: hiện đang mang khung M2 cũ; cần viết lại hoàn toàn cho `yield` toàn cục, `cycle_harvested`, `yield_forecast`, `crop_recommendation`, `recommend`, và kiểm tra bù model 10 phút.
  - `platform/worker/main.py`: hiện `on_worker_event` return sớm nếu `self._mqtt_client is None` — cần sửa để các sự kiện AI (`model_activated`, `cycle_harvested`, `recommend`) luôn được xử lý kể cả khi MQTT đang tạm mất kết nối.
  - `platform/core/climate_features.py`: hàm tính 16 đặc trưng khí hậu Python thuần (`feature_version = 1`).
  - `platform/core/models.py` & `migrations/`: cập nhật bảng `crop_cycles`, `yield_samples`, `ml_models`, `predictions` theo spec mục 7.

## 3. Cơ chế Nạp, Cache & Hot-Reload Mô hình Toàn cục

### 3.1 Nạp mô hình (`load_active_model`)
1. Truy vấn DB:
   ```sql
   SELECT * FROM ml_models
   WHERE task = 'yield' AND is_active = TRUE
   ORDER BY version DESC
   LIMIT 1;
   ```
2. Nếu chưa có bản ghi active: đặt cache về rỗng (`None`), log info và bỏ qua suy luận an toàn (UI hiển thị *"Chưa có mô hình"*).
3. Nếu có bản ghi active (và khác `model_id` đang giữ trong cache):
   - Xác định đường dẫn: `Path(m.artifact_path)` (hoặc `Settings.models_dir / m.artifact_path` nếu là đường dẫn tương đối; chuẩn là `/models/yield/v{n}.joblib`).
   - Đọc bundle qua `await asyncio.to_thread(joblib.load, art_path)` (chỉ import `joblib` trong `worker/inference.py`).
   - Xác nhận `bundle["feature_version"] == 1` (tương thích với `core.climate_features`).
   - Lưu vào cache RAM dưới `asyncio.Lock`:
     - `model_meta`: `MlModel` (`id`, `version`, `feature_version`, `crops`, `metrics`)
     - `estimator`: `bundle["model"]` (LightGBM regressor)
     - `feature_names`: `bundle["feature_names"]`
     - `crops`: `bundle["crops"]` (`crop_code → reference_kg_m2`)
     - `residual_quantiles`: `bundle["residual_quantiles"]` (`p10`, `p90`)
     - `train_feature_bounds`: `bundle["train_feature_bounds"]` (`min`, `max`, `median` theo đặc trưng)
     - `train_stats`: `bundle["train_stats"]` (`mean`, `std` phục vụ kiểm tra drift)

### 3.2 Ba cơ chế đồng bộ & Ngân sách RAM trên VPS 2 GB RAM
- **3 thời điểm nạp/reload (MUST):**
  1. Lúc `WorkerRuntime.run()` khởi động.
  2. Tức thời khi nhận `NOTIFY worker_events {"type": "model_activated", ...}` do `ml/train.py` phát.
  3. Job định kỳ **mỗi 10 phút** trong `worker/scheduler.py` (`check_and_reload_active_model`) phòng trường hợp thông báo `LISTEN/NOTIFY` bị lỡ khi kết nối DB chập chờn.
- **Tương thích RAM (512 MB cho `worker`, ≤ 384 MB cho `api` trên VPS 2 GB RAM):**
  - Chỉ giữ **1** bundle mô hình `yield` toàn cục trong RAM (không nạp N mô hình theo từng zone).
  - Ép `n_jobs=1` (hoặc `model.set_params(n_jobs=1)` nếu hỗ trợ) và chạy mọi lệnh `predict` trong `await asyncio.to_thread(...)` để tránh tạo nhiều thread tranh CPU trên VPS 2 vCPU và không làm nghẽn vòng MQTT/rule engine.
  - Tiến trình `api` tuyệt đối không import `worker/inference.py` (đảm bảo `test_api_process_does_not_import_heavy_ml_libraries` luôn pass).

## 4. Tạo mẫu huấn luyện khi Thu hoạch (`cycle_harvested` → `yield_samples`)

### 4.1 Kích hoạt
- Khi operator gọi `POST /api/cycles/{id}/harvest`, API cập nhật `crop_cycles.status = 'harvested'`, `harvested_at`, `yield_kg` và phát `NOTIFY worker_events {"type": "cycle_harvested", "cycle_id": "<uuid>"}`.
- `WorkerRuntime.on_worker_event` gọi `InferenceService.handle_cycle_harvested(session, cycle_id)` (bổ sung quét bù trong job 10 phút nếu có vụ `harvested` chưa có bản ghi tương ứng trong `yield_samples` và chưa có ghi chú lỗi coverage).

### 4.2 Quy trình xử lý chi tiết (MUST)
1. Nạp `CropCycle`, `Zone`, `Greenhouse`, `Gateway`, `CropProfile`. Kiểm tra:
   - `cycle.status == 'harvested'`, `cycle.harvested_at is not None`, `cycle.yield_kg is not None`, `cycle.area_m2 > 0`.
   - Chưa tồn tại dòng `yield_samples` với `crop_cycle_id = cycle.id` (idempotent).
2. Xác định nguồn bucket cho cửa sổ `[cycle.started_at, cycle.harvested_at]`:
   - Thời lượng `duration_h = (harvested_at - started_at).total_seconds() / 3600.0`.
   - Nếu `duration_h < 6.0` → truy vấn `readings_1m` (đã lọc `quality = 'ok'`).
   - Nếu `duration_h >= 6.0` → truy vấn `readings_1h` (đã lọc `quality = 'ok'`).
   - Tải thêm cột `lux` của các zone anh em trong cùng `greenhouse_id` ở cùng dải thời gian để `climate_features` mượn `lux` theo bucket khi zone hiện tại không có cảm biến BH1750.
3. Gọi `core.climate_features.compute_climate_features(...)` (múi giờ `Asia/Ho_Chi_Minh`) → thu được 16 đặc trưng số và `coverage`.
4. Đọc `min_coverage` từ `crop_profile.parameters_json["ai"]["min_coverage"]` (mặc định `0.7`).
5. **Nhánh đạt (`coverage >= min_coverage`):**
   - `source = "sim" if gateway.is_simulated else "real"`.
   - `yield_kg_m2 = cycle.yield_kg / cycle.area_m2`.
   - Chèn bản ghi `YieldSample(source=source, greenhouse_key=str(greenhouse.id), farm_id=greenhouse.farm_id, crop_cycle_id=cycle.id, crop_code=crop_profile.crop_code, started_at=cycle.started_at, ended_at=cycle.harvested_at, cycle_days=duration_h / 24.0, feature_version=1, features=features_dict, coverage=coverage, yield_kg_m2=yield_kg_m2, meta=...)`.
6. **Nhánh thiếu dữ liệu (`coverage < min_coverage`):**
   - **Không** tạo bản ghi `yield_samples`.
   - Ghi rõ lý do vào `crop_cycles.notes` (ví dụ: `"Không tạo mẫu yield_samples: độ phủ dữ liệu 0.48 < ngưỡng 0.70"`).

## 5. Suy luận Định kỳ & Theo yêu cầu

### 5.1 Điều phối lịch chạy (`worker/scheduler.py`)
- Nếu chưa có mô hình active trong cache → bỏ qua bước suy luận.
- Job scheduler kiểm tra định kỳ (ví dụ mỗi **60 giây**):
  - Với mỗi zone có vụ `active`: kiểm tra `now - last_yield_forecast_ts >= ai.inference_interval_s` của crop profile đang gán (`3600 s` cho `real`, `60 s` cho `demo`). Chỉ suy luận khi đến hạn.
  - Với mỗi nhà kính: tính `gh_interval_s = min(ai.inference_interval_s)` trong các zone thuộc nhà kính (mặc định `3600 s` nếu không có crop profile); kiểm tra `now - last_recommend_ts >= gh_interval_s` để chạy gợi ý định kỳ.
- Job kiểm tra bù model active chạy mỗi **10 phút** (`600 s`).
- Khi nhận `NOTIFY worker_events {"type": "recommend", "greenhouse_id": "<uuid>"}` (từ `POST /api/greenhouses/{id}/recommendations/refresh`): chạy ngay `run_recommendation_for_greenhouse(session, greenhouse_id)` bỏ qua bộ đếm chu kỳ.

### 5.2 Dự báo năng suất vụ đang trồng (`yield_forecast`)
Với mỗi `Zone` có `CropCycle` với `status = 'active'`:
1. Kiểm tra thời gian chạy vụ: `elapsed_h = (now - cycle.started_at).total_seconds() / 3600.0`. Nếu `elapsed_h < ai.min_cycle_hours` (`72` h cho `real`, `0.5` h cho `demo`) → chưa đủ dữ liệu vụ, bỏ qua.
2. Kiểm tra `crop_profile.crop_code` có nằm trong `crops` của mô hình active không; nếu không có → bỏ qua.
3. Đọc chuỗi bucket trên `[cycle.started_at, now]` từ `readings_1h` (hoặc `readings_1m` nếu `elapsed_h < 6.0`), kèm `lux` các zone cùng nhà kính.
4. Tính 16 đặc trưng số + `coverage` bằng `core.climate_features` (**giữ nguyên ẩm đất thực tế** `soil_mean`, `soil_std` của zone).
5. Nếu `coverage < ai.min_coverage` (`0.7`) → bỏ qua (không ghi dự báo thiếu dữ liệu).
6. Chạy dự đoán trong `await asyncio.to_thread(...)`:
   - `rel_yield = max(0.0, float(estimator.predict(df_one_row)[0]))`.
   - Khoảng tin cậy: `low_rel = max(0.0, rel_yield + q10)`, `high_rel = max(0.0, rel_yield + q90)`.
   - Quy đổi `kg/m²`: `expected_kg_m2 = rel_yield * ref_kg_m2`, `interval = [low_rel * ref_kg_m2, high_rel * ref_kg_m2]`.
7. Xác định cờ `low_confidence`: `True` nếu `elapsed_h < 24.0` (ngoại suy `/ngày`), hoặc có đặc trưng số nằm ngoài `[min, max]` trong `train_feature_bounds` (OOD; ghi danh sách `ood_features` vào `details`).
8. Lưu bản ghi vào `predictions`:
   - `ts = now`, `task = 'yield_forecast'`, `greenhouse_id = gh.id`, `zone_id = zone.id`, `crop_cycle_id = cycle.id`, `model_id = active_model.id`, `value = expected_kg_m2`, `score = rel_yield`, `details = {"crop_code": ..., "cycle_days_elapsed": ..., "interval": [...], "interval_relative": [...], "coverage": ..., "low_confidence": ..., "ood_features": [...], "features": {...}}`.
9. Phát sự kiện WS trong cùng transaction:
   - `pg_notify(session, CHANNEL_WS, {"farm_id": str(gh.farm_id), "type": "prediction", "data": {"task": "yield_forecast", "greenhouse_id": str(gh.id), "zone_id": str(zone.id), "crop_cycle_id": str(cycle.id), "ts": now.isoformat(), "value": expected_kg_m2, "score": rel_yield, "details": details}})`.
10. **Cảnh báo `YIELD_FORECAST_LOW` *(MAY)*:**
    - Nếu `rel_yield < 0.6` và `not low_confidence`: gọi `raise_alert(..., alert_type="YIELD_FORECAST_LOW", severity="info", dedupe_key=f"YIELD_FORECAST_LOW:{zone.id}", ...)` với thông điệp tiếng Việt.
    - Nếu `rel_yield >= 0.6` (hoặc vụ vừa chuyển `harvested`/`abandoned`): gọi `resolve_alert(session, dedupe_key=f"YIELD_FORECAST_LOW:{zone.id}", now=now)`.
    - **Không** gọi `rules.py`, **không** gửi lệnh điều khiển.

### 5.3 Gợi ý cây nên trồng (`crop_recommendation`)
Với một `Greenhouse`:
1. Xác định cửa sổ nhà kính: `recommend_window_h = min(zone_ai.recommend_window_h)` trên các zone của nhà kính (theo spec mục 7.1: `336 h` cho `real`, `1 h` cho `demo`; fallback `336 h` nếu chưa có profile).
2. Xác định `min_coverage = min(zone_ai.min_coverage)` (mặc định `0.7`).
3. Trên cửa sổ `[now - timedelta(hours=recommend_window_h), now]`:
   - Đọc `readings_1h` (hoặc `readings_1m` nếu `recommend_window_h < 6.0`) của **tất cả các zone** trong nhà kính (đều là `quality = 'ok'`).
   - Gộp theo bucket thời gian trong nhà kính (lấy trung bình giữa các zone ở mỗi bucket cho nhiệt độ, RH, VPD; `lux` lấy từ zone có cảm biến BH1750 ở bucket đó).
4. Tính 16 đặc trưng khí hậu + `coverage` bằng `core.climate_features`. Nếu `coverage < min_coverage` hoặc không có dữ liệu → bỏ qua (log debug).
5. Kiểm tra OOD (so các đặc trưng khí hậu với `train_feature_bounds` `[min, max]`) và kiểm tra `recommend_window_h < 24.0` → gán cờ `low_confidence`.
6. Chuẩn bị batch dự đoán cho toàn bộ ứng viên trong `model_bundle.crops`:
   - Nạp thông tin template hệ thống (`crop_profiles` có `farm_id IS NULL`, ưu tiên bản `real` để lấy `crop_name`, `soil_moisture_pct`, `temp_c.optimal`, `vpd.optimal`, `light.dli_optimal`).
   - Với mỗi cây ứng viên: dựng 1 dòng đặc trưng bằng cách sao chép đặc trưng khí hậu nhà kính, **thay `soil_mean = (soil_min + soil_max) / 2`** của cây đó và **`soil_std = train_feature_bounds["soil_std"]["median"]`**, gán `crop_code`.
   - Chạy `estimator.predict(...)` **một lượt cho toàn bộ ứng viên** trong `await asyncio.to_thread(...)` (`n_jobs=1`).
7. Với mỗi ứng viên: tính `expected_kg_m2 = rel_yield * ref_kg_m2`, `interval = [max(0, rel_yield + q10) * ref_kg_m2, max(0, rel_yield + q90) * ref_kg_m2]`, và sinh tối đa **3 lý do tiếng Việt** bằng luật (so `t_mean`, `vpd_mean`, `dli_mean` với khoảng tối ưu của cây; MAY bổ sung top đặc trưng đóng góp từ LightGBM `pred_contrib`).
8. Sắp xếp `ranking` giảm dần theo `relative_yield`. Top-3 là 3 phần tử đầu (`ranking[:3]`), đồng thời giữ đủ danh sách ứng viên trong `details["ranking"]` để trang Gợi ý cây trồng hiển thị cả 3 thẻ top lẫn bảng tất cả ứng viên.
9. Lưu vào bảng `predictions`:
   - `ts = now`, `task = 'crop_recommendation'`, `greenhouse_id = gh.id`, `zone_id = None`, `crop_cycle_id = None`, `model_id = active_model.id`, `value = None`, `score = ranking[0]["relative_yield"]`, `details = {"window_h": recommend_window_h, "coverage": coverage, "features": features_dict, "ranking": ranking, "low_confidence": low_confidence, "ood_features": ood_features}`.
10. Phát sự kiện WS trong cùng transaction:
    - `pg_notify(session, CHANNEL_WS, {"farm_id": str(gh.farm_id), "type": "prediction", "data": {"task": "crop_recommendation", "greenhouse_id": str(gh.id), "ts": now.isoformat(), "score": ranking[0]["relative_yield"], "details": details}})`.

## 6. Kiểm tra Drift & Lưu ý vận hành trên VPS

- **Lưu vector đặc trưng cho Feature Drift:** Việc lưu `features` (16 đặc trưng số) trong `predictions.details` cho phép `GET /api/models/active` tính `mean`/`std` 7 ngày gần nhất bằng SQL/Python thuần và đối chiếu với `ml_models.metrics["train_stats"]` mà `api` không cần chạm tới file `.joblib`.
- **Độ trễ Continuous Aggregates:** Do `readings_1h` có `schedule_interval = 15 phút` và `end_offset = 1 giờ` (`FEATURE_DATABASE_TIMESCALEDB.md`), với cửa sổ `< 6 giờ` (mọi nhà kính chạy bộ `demo`) bắt buộc dùng `readings_1m` (`end_offset = 1 phút`, `schedule_interval = 1 phút`). Với cửa sổ `>= 6 giờ` dùng `readings_1h`.
- **Thử tải 50–100 gateway:** Với 100 nhà kính `demo` chạy đồng thời (`ai.inference_interval_s = 60`), batching dự đoán ứng viên theo lượt và `n_jobs=1` trong `asyncio.to_thread` giúp tránh nghẽn luồng MQTT ingest và giữ RAM `worker` dưới giới hạn **512 MB** trên VPS 2 GB RAM.

## 7. Kiểm tra & Xác nhận

- **Unit & Integration tests (spec mục 15):**
  - `test_api_process_does_not_import_heavy_ml_libraries` vẫn pass.
  - `handle_cycle_harvested`: tạo `yield_samples` với đúng `source` (`real`/`sim`) khi `coverage >= 0.7`, bỏ qua và ghi lý do vào `crop_cycles.notes` khi `coverage < 0.7`.
  - `load_active_model` + hot-reload qua `NOTIFY worker_events {"type": "model_activated"}` và fallback 10 phút.
  - `yield_forecast` & `crop_recommendation`: ghi đúng `predictions`, phát `ws_events`, thay `soil_mean` bằng trung điểm từng cây khi gợi ý, gắn `low_confidence` khi `< 24 h` hoặc OOD, và **không** phát bất kỳ `Command` nào tới actuator.
- **Kịch bản E (AI):**
  - Zone có vụ đang trồng hiển thị năng suất dự kiến + khoảng tin cậy.
  - Các nhà kính giả lập ở vùng khí hậu khác nhau (`dalat` vs `hcm`) cho gợi ý khác nhau hợp lý.
  - Thay đổi khí hậu nhà kính thật (bật máy tạo ẩm/quạt/đèn) rồi bấm Làm mới (`POST /api/greenhouses/{id}/recommendations/refresh`) → nhận phản hồi `202`, `worker` chạy ngay và WebSocket cập nhật tóm tắt khí hậu cùng thứ hạng mới.
