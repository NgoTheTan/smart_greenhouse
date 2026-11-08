# Feature: Pipeline AI/ML 3 Tầng & Thí nghiệm Fixed vs Adaptive (`ml/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 6.4, 8.1, 8.2, 8.3, 8.4, 9, 12, 15, 16 (M5); `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Xây dựng vòng lặp dữ liệu khép kín cho nhà kính: thu thập dữ liệu quá khứ (`readings`, `actuator_logs`, `alerts.feedback`) → huấn luyện mô hình ML cổ điển offline → so sánh trực tiếp với baseline toán học/luật → chỉ kích hoạt khi vượt trội → đưa vào suy luận thời gian thực (cảnh báo sớm & điều khiển `adaptive`) → đánh giá hiệu quả thực tế qua thí nghiệm `fixed vs adaptive`.

- **Ngoài phạm vi:** Không dùng LLM, học tăng cường (RL), phân loại bệnh từ ảnh, học liên farm (federated learning), hay mạng nơ-ron sâu.

## 2. Trạng thái hiện thực trong repo

- **Đã có (khung khởi tạo M2):**
  - `ml/requirements.txt`: định nghĩa kế thừa phiên bản runtime từ `platform/requirements.txt` (`numpy==2.5.4`, `pandas==3.1.1`, `scikit-learn==1.9.1`, `lightgbm==4.7.0`, `joblib==1.6.0` + `SQLAlchemy`, `asyncpg`/`psycopg` nếu cần đọc DB đồng bộ/bất đồng bộ).
  - `ml/train.py`: mới có CLI `argparse` cho `--task {risk_forecast, irrigation_eta, pump_response, fan_response}`, `--zone <id|all>`, `--from`, `--to` và `TODO(M5)`.
  - `ml/features.py` & `ml/evaluate.py`: mới có docstring 1 dòng.
  - Bảng DB `ml_models`, `predictions`, `experiment_runs` đã được tạo sẵn trong migration `0002`.
- **Cần hiện thực đầy đủ (M5):**
  - Trích xuất đặc trưng & tạo nhãn không rò rỉ dữ liệu (`ml/features.py`).
  - Huấn luyện + baseline + chọn ngưỡng validation + so sánh trên test + lưu `.joblib` + ghi `ml_models` (`ml/train.py`, `ml/evaluate.py`).
  - Tích hợp suy luận vào `platform/worker/inference.py` và API `models`/`experiments` vào `platform/api/routers/`.

## 3. Nguyên tắc khoa học dữ liệu (MUST)

1. **Tách `real` vs `sim`:**
   - Mọi bản ghi `readings` có `source ∈ {'real', 'sim'}`.
   - Dữ liệu `real` bao gồm cả sự kiện vật lý thật tạo ra khi bật máy tạo ẩm/bơm thật (kể cả bật qua script gọi API).
   - **Chỉ số báo cáo chính (`metrics`, `baseline_metrics`) MUST tính trên dữ liệu `real`** (nếu chạy trên dữ liệu `sim` để test pipeline khi chưa đủ dữ liệu thật, phải ghi rõ `source_mix` và không coi đó là kết quả đánh giá thật; tốt nhất chỉ train chính thức trên `real`, hoặc hỗ trợ cờ `--allow-sim` khi test pipeline).
2. **Làm sạch:** Loại bỏ hoàn toàn `readings.quality != 'ok'`.
3. **Chia train/val/test theo thời gian:** Chia tuần tự `train | val | test` (ví dụ 60% / 20% / 20% theo trục thời gian `ts`, tuyệt đối không xáo trộn ngẫu nhiên).

## 4. Đặc tả chi tiết 3 Tầng AI (`A1`, `A2`, `A3`)

### 4.1 Tầng 1 – Chất lượng dữ liệu (`A1`)
- **Luật bắt buộc (`MUST`):** đã hiện thực tại `platform/core/quality.py` (xem `FEATURE_MICROCLIMATE_AND_QUALITY.md`).
- **Mở rộng tuỳ chọn (`MAY`):** nếu còn thời gian ở M5, phát hiện trôi chậm (sensor drift) và chỉ số bảo trì (xu hướng RSSI, tỉ lệ mất gói, độ lệch kéo dài giữa 2 zone) → alert `MAINTENANCE`.

### 4.2 Tầng 2 – Học đặc tính từng zone cho Điều khiển & Dự báo Tưới (`A2`, MUST)

#### Bài toán 1: `pump_response` (mỗi zone)
- **Dữ liệu nguồn:** các lần bơm của zone có `actuator_logs` (hoặc `commands.status == 'applied'` kèm `duration_s > 0`, `action == 'on'`) nối với `readings(quality='ok')`.
- **Trích xuất mỗi sự kiện tưới `(t_start, d)`:**
  - `soil_before`: trung bình **3 điểm hợp lệ** gần nhất trong cửa sổ trước `t_start` (ví dụ `[t_start - 3*interval, t_start]`).
  - `soil_after`: giá trị **cực đại (`max`)** hợp lệ trong cửa sổ `[t_start + d, t_start + d + soil_settle_s]` (do độ ẩm đất ngấm chậm).
  - `Δsoil = soil_after - soil_before`. Bỏ qua sự kiện thiếu dữ liệu hoặc bị cắt ngang bởi lần bơm khác.
  - Tốc độ tăng tức thời: `gain = Δsoil / d` (`% / giây`).
- **Mô hình & Baseline:**
  - Ước lượng đơn giản bằng **median** của `K` sự kiện gần nhất (`gain > 0`), **HOẶC** hồi quy **Ridge** (`Δsoil ~ d + soil_before`) để ước lượng độ nhạy ẩm đất.
  - **Ngưỡng kích hoạt tối thiểu:** Cần `n_events >= min_events` (**5**) mới được kích hoạt dùng trong chiến lược `adaptive`.
  - **Đầu ra sử dụng bởi `worker/rules.py`:** `pump_gain_pct_per_s` → tính `duration_s = clamp((target - soil_now) / pump_gain, 3, irrigation.max_run_s)` với `target = (soil_min + soil_max) / 2`.

#### Bài toán 2: `fan_response` (theo zone / nhà kính)
- **Dữ liệu nguồn:** các lần quạt bật (`actuator='fan', action='on'`, `duration_s > 0`) nối với `readings(quality='ok')`.
- **Trích xuất:** `vpd_before` (trung bình 3 điểm trước bật), `vpd_after` (giá trị VPD cuối cửa sổ bật/ổn định ngay sau tắt), `ΔVPD = vpd_after - vpd_before`, `rate = ΔVPD / d` (`kPa / giây`, VPD tăng khi quạt hút ẩm).
- **Mô hình:** Median của K sự kiện gần nhất hoặc Ridge `ΔVPD ~ d + vpd_before + rh_before`. Cần `>= 5` sự kiện.
- **Đầu ra sử dụng bởi `worker/rules.py`:** `fan_vpd_rate_kpa_per_s` → tính `duration_s = clamp((vpd.low_off - vpd_now) / fan_vpd_rate, fan.min_on_s, fan.max_on_s)`.

#### Bài toán 3: `irrigation_eta` (dự báo phút còn lại tới khi chạm `soil_min`, MUST)
- **Cách tạo nhãn (Labels):**
  - Xét từng đoạn khô–tưới (từ lúc kết thúc settle của lần tưới trước tới lúc bắt đầu lần tưới kế tiếp).
  - Tại mỗi thời điểm `t` trong đoạn khô mà `soil_now > soil_min`: tìm thời điểm đầu tiên `t_hit > t` trong cùng đoạn đó có `soil_moisture <= soil_min`.
  - Nhãn: `y = (t_hit - t) / 60.0` (phút).
  - **Censoring (BẮT BUỘC):** nếu tới lần tưới kế tiếp (hoặc hết dữ liệu) mà `soil_moisture` **chưa** chạm `soil_min` → **bỏ mẫu** đó (censored), không gán nhãn sai!
- **Đặc trưng (`features.py`):**
  - `soil_now`
  - Tốc độ giảm ẩm đất hiện tại (`drying_rate_pct_per_min`: hệ số góc hồi quy tuyến tính `soil_moisture ~ t` trên cửa sổ gần nhất: demo `10–30 phút`, real `1–3 giờ`)
  - `air_temp`, `vpd`, `lux` (nếu có)
  - Giờ trong ngày (mã hóa chu kỳ `sin(2π*hour/24)`, `cos(2π*hour/24)` hoặc `hour`)
  - `minutes_since_last_irrigation` (thời gian từ lần tưới gần nhất)
- **Baseline:** Ngoại suy tuyến tính từ tốc độ giảm: `(soil_now - soil_min) / max(-slope, eps)`.
- **Mô hình:** **Ridge** hoặc **LightGBM Regressor** (`n_jobs=1`).
- **Chỉ số đánh giá (`evaluate.py`):** **MAE (phút)** trên các chu kỳ khô–tưới hoàn chỉnh trong tập test (chưa từng thấy khi train/val), so trực tiếp với MAE của baseline.

### 4.3 Tầng 3 – Dự báo rủi ro nấm & Học từ phản hồi (`A3`: `risk_forecast`, MUST)

- **Mục tiêu:** Dự đoán zone có **chuyển** sang vùng nguy cơ trong `H = risk.horizon_min` phút tới hay không (demo: `15 phút`, real: `120 phút`).
- **Định nghĩa sự kiện nguy cơ:** `VPD < vpd.low_crit` liên tục `>= risk.vpd_low_duration_min` phút **HOẶC** `air_temp >= failsafe.temp_critical_high_c`.
- **Tạo nhãn `(t, t+H]` & Chống rò rỉ dữ liệu (Data Leakage Prevention, MUST):**
  - **Chỉ lấy các mẫu tại thời điểm `t` mà trạng thái hiện tại ở `t` CHƯA nằm trong vùng nguy cơ!** (Nếu tại `t` đang nguy cơ rồi thì bài toán không còn là dự báo chuyển trạng thái).
  - Nhãn `y = 1` nếu trong khoảng tương lai `(t, t + H]` có xảy ra sự kiện chuyển sang vùng nguy cơ; ngược lại `y = 0`.
  - Đảm bảo khoảng đệm giữa tập `train`, `val`, `test` ít nhất `H` phút để nhãn cuối tập train không gối vào đầu tập val/test.
- **Đặc trưng (`features.py`, dùng chung với `worker/inference.py`):**
  - Giá trị hiện tại: `air_temp`, `air_rh`, `vpd`, `lux` (hoặc 0/missing flag nếu node 2 không có BH1750).
  - Xu hướng theo các cửa sổ `risk.trend_windows_min` (ví dụ `[5, 15]` phút cho demo; `[30, 60]` cho real): độ biến thiên (`delta`), tốc độ thay đổi (`slope`), giá trị `mean`/`min`/`max` trong cửa sổ của `air_temp`, `air_rh`, `vpd`, `lux`.
  - Thời gian: giờ trong ngày (`sin/cos`).
  - Trạng thái chấp hành hiện tại: `fan_on` (0/1), `mist_on` (0/1) lấy từ `actuator_logs` tại thời điểm `t`.
  - `fungal_minutes` tích luỹ tính tới `t`.
  - *(Tuỳ chọn nếu gộp nhiều zone)*: thông tin loại cây / ngưỡng `low_crit` của crop profile.
- **Mô hình & Baseline:**
  - **Mô hình:** **LightGBM Classifier** (`class_weight='balanced'` hoặc tuning trọng số; fallback Random Forest nếu mẫu ít), một mô hình riêng cho mỗi zone.
  - **Baseline:** Luật ngưỡng + ngoại suy tuyến tính xu hướng VPD hiện tại sau `H` phút có cắt xuống dưới `vpd.low_crit` không (hoặc đạt ngưỡng `fungal_minutes` sắp tới).
- **Đánh giá (`evaluate.py`):**
  - **PR-AUC** (Average Precision) và **F1** trên tập **test** (dữ liệu `real`).
  - Ngưỡng phân loại tối ưu (`threshold`, mặc định tham khảo `0.7`) được chọn trên tập **validation** (tối đa F1 trên val), sau đó áp dụng cố định lên tập test và lưu kèm trong artifact `.joblib`.
- **Tích hợp phản hồi (`alerts.feedback`):**
  - Dùng `alerts.feedback` (`true_positive` / `false_positive`) làm nhãn bổ sung (nếu đồng bộ timestamp) **VÀ** tính **Alert Precision** (`TP / (TP + FP)`) để so sánh chất lượng cảnh báo của mô hình AI so với chỉ dùng luật ngưỡng tĩnh.

## 5. Vòng đời Mô hình & CLI `ml/train.py` (MUST)

- **Lệnh CLI:**
  ```powershell
  $env:PYTHONPATH = "platform;."
  python -m ml.train --task risk_forecast --zone all [--from 2026-11-01T00:00:00Z] [--to 2026-11-08T00:00:00Z]
  ```
- **Quy trình thực thi trong `ml/train.py`:**
  1. Xác định danh sách `zone_id` (`--zone all` hoặc UUID cụ thể).
  2. Tải dữ liệu `readings(quality='ok')`, `actuator_logs`, `crop_profiles` từ DB (lọc theo `--from`/`--to` nếu có).
  3. Chia theo thời gian (`train` / `val` / `test`). Kiểm tra đủ mẫu tối thiểu; nếu thiếu mẫu/thiếu cả 2 lớp (`y=1` và `y=0`), log rõ lý do và không crash.
  4. Huấn luyện mô hình & tính metrics trên tập test (`real`) cho **cả mô hình mới lẫn baseline** (`metrics`, `baseline_metrics`).
  5. Lưu artifact dạng dict vào `{MODELS_DIR}/{task}/{zone_id}/v{next_version}.joblib`:
     - Chứa: `model`, `feature_names`, `threshold`, `train_stats` (`{"feature": {"mean": ..., "std": ...}}` dùng để tính **Feature Drift**!), `task`, `zone_id`, `version`, `trained_at`.
  6. **Cổng kích hoạt (Activation Gate, MUST):**
     - So sánh `metrics` trên test với `baseline_metrics` (PR-AUC/F1 cao hơn cho `risk_forecast`; MAE thấp hơn cho `irrigation_eta`; đủ `>= 5` sự kiện và sai số hợp lý cho `pump_response`/`fan_response`) **VÀ** thắng (hoặc tốt hơn/bằng theo tiêu chuẩn rõ ràng) mô hình đang `is_active = True` hiện tại (nếu có).
     - Nếu **thắng cả hai**: trong transaction DB, tắt `is_active = False` ở bản cũ của `(zone_id, task)`, chèn bản mới với `is_active = True`, và gửi `pg_notify(CHANNEL_WORKER, {"type": "model_activated", ...})`.
     - Nếu **không thắng**: vẫn lưu artifact và ghi bản ghi vào `ml_models` với `is_active = False` và ghi rõ lý do vào cột `notes` (ví dụ `"Không kích hoạt: PR-AUC 0.62 <= baseline 0.68"`). Báo cáo trung thực!
- **Dấu hiệu lệch dữ liệu (Feature Drift):**
  - So sánh `mean` và `std` của các đặc trưng chính (`air_temp`, `air_rh`, `vpd`, `soil_moisture`) trong cửa sổ gần đây (ví dụ 24 giờ gần nhất) với `train_stats` lúc huấn luyện (ví dụ z-score `|mean_recent - mean_train| / max(std_train, 1e-6)` hoặc tỉ lệ thay đổi độ lệch chuẩn) → hiển thị trên trang Model & Thí nghiệm.

## 6. Thí nghiệm "Fixed vs Adaptive" (`experiment_runs`)

- **Vận hành:** Bật/tắt `control_strategy` của nhà kính/zone qua `POST /api/experiments` (`strategy='fixed'` hoặc `'adaptive'`), chạy lần lượt trong điều kiện môi trường tương đương, rồi dừng bằng `POST /api/experiments/{id}/stop`.
- **5 KPI tính bằng SQL trên `[started_at, ended_at]` (spec mục 8.4):**

| KPI | Cách tính SQL chi tiết |
|---|---|
| **1. Số lần bật/tắt bơm, quạt mỗi giờ** | Đếm số dòng `actuator_logs` (lọc `actuator IN ('pump_1','pump_2','fan')`, `action='on'` hoặc tổng chuyển trạng thái) trong khoảng `[started_at, ended_at]`, chia cho số giờ `(ended_at - started_at) / 3600.0`. |
| **2. % thời gian VPD trong dải tối ưu** | Với mỗi zone trong nhà kính: `(COUNT(*) FILTER (WHERE r.vpd BETWEEN vpd_opt_low AND vpd_opt_high)::float / NULLIF(COUNT(*), 0)) * 100` trên `readings` có `quality='ok'`. |
| **3. Overshoot ẩm đất (%)** | Với mỗi lần bơm (`actuator_logs` `pump_1`/`pump_2`, `action='on'`) trong khoảng thí nghiệm: tìm `MAX(r.soil_moisture)` trong cửa sổ `[log.created_at, log.created_at + interval '<duration_s + soil_settle_s> seconds']`, tính `GREATEST(0, max_soil - soil_max)` rồi lấy `MAX` (và/hoặc `AVG`) qua các lần tưới. |
| **4. Tổng thời gian bơm (giây)** | `COALESCE(SUM(duration_s), 0)` trên `actuator_logs` với `actuator IN ('pump_1','pump_2')` và `action = 'on'` (proxy lượng nước tiêu thụ). |
| **5. Số cảnh báo sai** | `COUNT(*)` trên `alerts` của nhà kính trong `[started_at, ended_at]` có `feedback = 'false_positive'`. |

- Nếu kết quả thí nghiệm cho thấy `adaptive` không tốt hơn `fixed`, hệ thống vẫn ghi nhận và hiển thị trung thực toàn bộ số liệu.
