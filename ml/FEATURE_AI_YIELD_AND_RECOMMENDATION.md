# Feature: Pipeline AI/ML Dự đoán Năng suất & Gợi ý Cây trồng (`ml/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 2, 3.2, 7, 7.1, 8.1, 8.2, 8.3, 14, 15, 16 (M5); `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Xây dựng pipeline AI/ML cho **bài toán duy nhất** của GreenHub (`task = 'yield'`): dự đoán năng suất cây trồng (`yield_kg_m2`) từ vector đặc trưng khí hậu tổng hợp theo vụ trồng trên nhiều nhà kính gộp lại, và dùng chung mô hình toàn cục đó để xếp hạng **gợi ý cây nên trồng (`crop_recommendation`)** phù hợp với điều kiện khí hậu hiện tại của từng nhà kính.

- **Trong phạm vi (MUST):**
  - Một mô hình toàn cục duy nhất (`task = 'yield'`, LightGBM regressor với `crop_code` categorical) phục vụ mọi farm/nhà kính.
  - Dữ liệu huấn luyện gộp từ nhiều nhà kính (`yield_samples`: `synthetic`, `sim`, `real`, `public`).
  - Hàm trích đặc trưng khí hậu dùng chung (`feature_version = 1`) viết bằng Python thuần tại `platform/core/climate_features.py`.
  - Chia dữ liệu theo nhà kính (`GroupShuffleSplit` theo `greenhouse_key`), hai baseline bắt buộc (`B0`, `B1`), cổng kích hoạt chặt chẽ theo MAE trên tập test.
  - CLI nhập/xuất dữ liệu (`ml/dataset.py`), huấn luyện (`ml/train.py`), đánh giá (`ml/evaluate.py`).
- **Ngoài phạm vi (KHÔNG xây):**
  - Không dùng LLM, mạng nơ-ron sâu/lớn, học tăng cường (RL), phân loại bệnh từ ảnh, hay *federated learning* (lưu ý: huấn luyện **tập trung** trên dữ liệu gộp nhiều nhà kính là trong phạm vi).
  - Không dùng GPU khi huấn luyện hoặc suy luận.
  - Mô hình AI **tuyệt đối không** điều khiển thiết bị chấp hành (`pump_1`, `pump_2`, `fan`, `mist`).
  - Không làm các bài toán dự báo rủi ro bằng ML hay học phản hồi cảnh báo; kiểm tra chất lượng dữ liệu là tầng tiền xử lý bằng luật xác định (xem `platform/core/FEATURE_MICROCLIMATE_AND_QUALITY.md`).

## 2. Trạng thái hiện thực trong repo

- **Đã có (khung khởi tạo M2):**
  - `ml/requirements.txt`: kế thừa trực tiếp phiên bản từ `platform/requirements.txt` (`numpy==2.5.4`, `pandas==3.1.1`, `scikit-learn==1.9.1`, `lightgbm==4.7.0`, `joblib==1.6.0` + `matplotlib==3.11.2`) để artifact `.joblib` tương thích tuyệt đối giữa môi trường huấn luyện trên laptop và container `worker`.
  - `ml/train.py`, `ml/evaluate.py`, `ml/features.py`: hiện mới là khung cũ từ M2 (cần viết lại cho `task = 'yield'`).
- **Cần hiện thực / viết lại đầy đủ (M5):**
  - `platform/core/climate_features.py`: triển khai Python thuần bộ 16 đặc trưng số (`feature_version = 1`), dùng chung cho `ml/`, `platform/worker/inference.py` và `tools/simulator`.
  - `ml/dataset.py`: CLI nhập dữ liệu `synthetic`/`public` vào bảng `yield_samples` và xuất dữ liệu phục vụ phân tích.
  - `ml/train.py`: viết lại toàn bộ cho `--task yield`, chia `GroupShuffleSplit` theo `greenhouse_key`, fit LightGBM + B0 + B1, ước lượng khoảng tin cậy p10/p90 từ validation residuals, đóng gói bundle `/models/yield/v{n}.joblib`, ghi `ml_models`, áp dụng cổng kích hoạt và phát `NOTIFY worker_events`.
  - `ml/evaluate.py`: viết lại các hàm tính MAE (kg/m²), RMSE, R², MAPE (tổng, theo cây, tách theo `source`), Top-1 accuracy và NDCG@3.
  - Phối hợp cùng migration bảng `crop_cycles`, `yield_samples`, và cập nhật bảng `ml_models`, `predictions` ở `platform/migrations/` & `platform/core/models.py`.

## 3. Đặc trưng khí hậu (`feature_version = 1`, `platform/core/climate_features.py`)

### 3.1 Nguyên tắc dùng chung (Zero Training-Serving Skew)
- Hàm tính đặc trưng **MUST** đặt duy nhất tại `platform/core/climate_features.py` và viết bằng **Python thuần** (không import `pandas`/`numpy`/`sklearn`/`lightgbm`), để tiến trình `api` hoặc các module `core` không bị kéo thư viện ML nặng vào RAM, đồng thời bảo đảm `worker`, `ml/` và `tools/simulator` dùng cùng một logic tính toán.
- **Đầu vào:** chuỗi bản ghi tổng hợp từ `readings_1h` (khi cửa sổ `< 6 giờ`, dùng `readings_1m`) đã lọc `quality = 'ok'`.
- **Múi giờ địa phương:** `Asia/Ho_Chi_Minh` (`TZ=Asia/Ho_Chi_Minh`) dùng để tách khung giờ ban ngày (`06:00–18:00`) và ban đêm (`18:00–06:00`); timestamp trong DB vẫn lưu chuẩn UTC.

### 3.2 Danh sách 16 đặc trưng số + `crop_code`

| STT | Tên đặc trưng | Kiểu | Định nghĩa |
|---|---|---|---|
| 1 | `t_mean` | float | Nhiệt độ không khí trung bình (°C) |
| 2 | `t_day_mean` | float | Nhiệt độ trung bình trong khung `06:00–18:00` giờ địa phương (°C) |
| 3 | `t_night_mean` | float | Nhiệt độ trung bình trong khung `18:00–06:00` giờ địa phương (°C) |
| 4 | `t_p95` | float | Phân vị 95 của nhiệt độ (°C) |
| 5 | `t_p05` | float | Phân vị 5 của nhiệt độ (°C) |
| 6 | `rh_mean` | float | Độ ẩm tương đối trung bình (%) |
| 7 | `vpd_mean` | float | VPD trung bình (kPa) |
| 8 | `vpd_std` | float | Độ lệch chuẩn VPD (kPa) |
| 9 | `frac_vpd_low` | float | Tỉ lệ thời gian/bucket có `VPD < 0.4` kPa |
| 10 | `frac_vpd_high` | float | Tỉ lệ thời gian/bucket có `VPD > 1.6` kPa |
| 11 | `frac_t_gt_30` | float | Tỉ lệ thời gian/bucket có `air_temp > 30` °C |
| 12 | `frac_t_lt_12` | float | Tỉ lệ thời gian/bucket có `air_temp < 12` °C |
| 13 | `gdd_per_day` | float | Trung bình ngày của `max(air_temp - 10, 0)` (°C·ngày/ngày) |
| 14 | `dli_mean` | float \| null | `mean(PPFD) * 86400 / 1e6` (mol/m²/ngày), với `PPFD = lux * 0.0185` |
| 15 | `soil_mean` | float | Độ ẩm đất trung bình (%) |
| 16 | `soil_std` | float | Độ lệch chuẩn độ ẩm đất (%) |
| 17 | `crop_code` | categorical | `tomato_cherry \| strawberry \| lettuce \| cucumber \| bell_pepper` |

- **Xử lý `lux` thiếu (`null`):** Zone không có BH1750 (ví dụ node 2) mượn giá trị `lux` ở **cùng bucket thời gian** của zone khác trong **cùng nhà kính**. Nếu cả nhà kính không có dữ liệu `lux` hợp lệ trong cửa sổ → `dli_mean = null` (`NaN` được LightGBM xử lý tự nhiên; với baseline B1 Ridge cần `SimpleImputer(strategy="median")` fit trên tập train).
- **Bất biến `feature_version`:** Các hằng số trong định nghĩa đặc trưng (`0.4`, `1.6`, `30`, `12`, `10`) là một phần định nghĩa của `feature_version = 1` (không phải ngưỡng sinh học của `crop_profiles`). Nếu thay đổi bất kỳ công thức hay hằng số nào ở bảng trên, **MUST** tăng `feature_version`.
- **Kiểm tra độ phủ (`coverage`):** `coverage = số_bucket_hợp_lệ / tổng_số_bucket_kỳ_vọng` trong cửa sổ. Nếu `coverage < ai.min_coverage` (mặc định `0.7`), **MUST** bỏ qua suy luận và không tạo mẫu `yield_samples`.
- **Cờ `low_confidence`:** Gắn `low_confidence = true` khi cửa sổ `< 24 h` (chế độ demo, các đại lượng `/ngày` là ngoại suy), hoặc `coverage` thấp, hoặc có ít nhất một đặc trưng số nằm ngoài khoảng `[min, max]` của tập train (kiểm tra OOD đơn giản).

## 4. Nguồn dữ liệu Đa nhà kính & CLI `ml/dataset.py` (MUST)

### 4.1 Bốn nguồn dữ liệu trong bảng `yield_samples`

| `source` | Nguồn phát sinh | Vai trò trong pipeline |
|---|---|---|
| `synthetic` | Sinh offline bằng `python -m tools.simulator synth-yield` (hàng trăm nhà kính × nhiều vụ qua mô hình sinh trưởng ẩn `tools/simulator/growth.py` + `crops_growth.json` across 6 vùng khí hậu `dalat`, `hanoi_winter`, `hanoi_summer`, `hcm`, `mekong`, `central_coast` và đa dạng trang bị) | **Nguồn huấn luyện chính**; lưu kèm `meta.oracle_relative_yields` để đánh giá gợi ý |
| `sim` | Các farm giả lập chạy trực tuyến qua `tools/simulator`, tạo vụ & báo thu hoạch qua REST API; `worker` tự tạo `yield_samples` khi `gateway.is_simulated = True` | Kiểm thử end-to-end pipeline, bổ sung mẫu từ luồng thực thi đầy đủ |
| `real` | Vụ trồng thật trên nhà kính mini (SHOULD chạy ≥ 1 vụ ngắn **xà lách baby leaf** ~3–4 tuần ở 2 zone, cân khối lượng tươi khi thu hoạch) | Kiểm chứng thực tế; **báo cáo riêng, trung thực** |
| `public` *(MAY)* | Bộ dữ liệu công khai (ví dụ Autonomous Greenhouse Challenge – WUR) qua adapter chuẩn hoá | Đối chiếu bổ sung |

- **Lưu ý cô lập:** Mô hình ML **tuyệt đối không** được đọc `tools/simulator/growth.py` hay `crops_growth.json` khi huấn luyện/suy luận. Bảng `yield_samples` chỉ phục vụ huấn luyện nội bộ và **không bao giờ** lộ qua bất kỳ endpoint REST API nào.

### 4.2 Hợp đồng CLI `ml/dataset.py`

```powershell
$env:PYTHONPATH = "platform;."

# Nhập dữ liệu tổng hợp hoặc công khai vào bảng yield_samples
python -m ml.dataset import --source synthetic --file data/synthetic_yield.csv
python -m ml.dataset import --source public --file data/public_wur.csv

# Xuất dữ liệu từ yield_samples để khám phá (tùy chọn)
python -m ml.dataset export --out data/yield_samples_export.csv [--sources synthetic,sim,real]
```

- **Quy trình `import`:**
  1. Đọc file CSV đầu vào; kiểm tra đầy đủ cột bắt buộc (`greenhouse_key`, `crop_code`, `yield_kg_m2`, `feature_version`, `coverage`, 16 đặc trưng số, và `meta` JSON nếu có).
  2. Nếu nguồn `public` cung cấp chuỗi đọc theo giờ thay vì vector đã tổng hợp, adapter của `public` gọi trực tiếp `core.climate_features` để tính đúng 16 đặc trưng chuẩn `feature_version = 1`.
  3. Loại bỏ các dòng có `coverage < 0.7` hoặc `yield_kg_m2 < 0` hoặc thiếu đặc trưng cốt lõi (log rõ số dòng hợp lệ / bị loại).
  4. Chèn idempotent vào bảng `yield_samples` (`farm_id = NULL`, `crop_cycle_id = NULL`, `source = args.source`).

## 5. Mô hình, Nhãn chuẩn hoá, Chia dữ liệu & Baseline (MUST)

### 5.1 Nhãn chuẩn hoá (`relative_yield`)
- Mỗi loại cây có mức năng suất tham chiếu khác nhau (`yield.reference_kg_m2` trong system template `crop_profiles`: cà chua bi `10.0`, dâu tây `4.0`, xà lách `3.0`, dưa leo `15.0`, ớt chuông `8.0` kg/m²).
- **Nhãn huấn luyện:**
  $$\text{relative\_yield} = \frac{\text{yield\_kg\_m2}}{\text{reference\_kg\_m2}(\text{crop\_code})}$$
- Việc chuẩn hoá giúp mô hình học chung trên nhiều loại cây và so sánh công bằng khi xếp hạng gợi ý cây trồng. Khi suy luận, nhân ngược lại `expected_kg_m2 = pred_relative_yield * reference_kg_m2(crop_code)`.

### 5.2 Chia dữ liệu theo nhà kính (Zero Greenhouse Leakage)
- **MUST** dùng `GroupShuffleSplit` theo `greenhouse_key` (tỉ lệ **70% train / 15% validation / 15% test** — thực hiện 2 bước: tách 15% test theo `greenhouse_key`, rồi tách phần còn lại theo `greenhouse_key` với tỉ lệ `0.15 / 0.85 ≈ 0.1765` cho validation, `random_state` cố định).
- **Bất biến:** Không một `greenhouse_key` nào được xuất hiện ở hai tập khác nhau (`set(train_gh) & set(val_gh) == ∅`, `set(train_gh) & set(test_gh) == ∅`, `set(val_gh) & set(test_gh) == ∅`). Tập test là các nhà kính **chưa từng thấy**.
- **Điều kiện tối thiểu theo cây (`min_samples_per_crop = 30`):** Chỉ giữ lại để huấn luyện (và đưa vào `ml_models.crops`) các `crop_code` có `>= 30` mẫu trên tập train.

### 5.3 Mô hình chính & Khoảng tin cậy
- **Mô hình:** `lightgbm.LGBMRegressor` với `crop_code` khai báo là categorical feature (`pandas.Categorical` với danh sách categories cố định lưu kèm bundle), `n_jobs=1` (hoặc số luồng an toàn trên máy train) và `random_state` cố định.
- **Khoảng tin cậy (p10, p90):**
  - Tính phần dư trên tập **validation**: $r_i = y_{\text{val}, i} - \hat{y}_{\text{val}, i}$ (theo đơn vị `relative_yield`).
  - Lưu phân vị `q10 = np.percentile(residuals, 10)` và `q90 = np.percentile(residuals, 90)` vào artifact bundle.
  - Khi suy luận: khoảng tin cậy tương đối `[max(0.0, pred_rel + q10), max(0.0, pred_rel + q90)]`, nhân `reference_kg_m2` để ra khoảng tin cậy `kg/m²` (ví dụ: *"6.2 kg/m² (5.1–7.3)"*).

### 5.4 Hai Baseline bắt buộc (`B0`, `B1`)
1. **B0 (Crop Median Baseline):** Dự đoán $\hat{y}_{\text{rel}} = \text{median}(\text{relative\_yield}_{\text{train}} \mid \text{crop\_code})$ trên tập train (fallback về median toàn tập train nếu gặp cây lạ).
2. **B1 (Ridge Regression Baseline):** `Pipeline([SimpleImputer(strategy="median"), StandardScaler(), OneHotEncoder/ColumnTransformer cho crop_code, Ridge(alpha=1.0)])` huấn luyện trên đúng tập train (16 đặc trưng số + one-hot `crop_code`). `SimpleImputer` xử lý sạch trường hợp `dli_mean = null`.

## 6. Đánh giá Mô hình (`ml/evaluate.py`, MUST)

Trên tập **test** (toàn nhà kính chưa từng thấy), quy đổi dự đoán `relative_yield` về `kg/m²` bằng `reference_kg_m2` của từng cây để tính bộ chỉ số:

| Nhóm chỉ số | Chỉ số | Ghi chú công thức |
|---|---|---|
| **Tổng thể (kg/m²)** | `mae_kg_m2`, `rmse_kg_m2`, `r2`, `mape` | `MAPE` tính trên các mẫu có `yield_kg_m2 > 0` (hoặc dùng `max(y_true, 1e-3)`) |
| **Theo từng cây** | `by_crop[crop_code]`: `n`, `mae_kg_m2`, `rmse_kg_m2`, `r2` | Cho phép phát hiện cây nào mô hình dự báo kém |
| **Tách theo `source`** | `by_source[source]`: `n`, `mae_kg_m2`, `rmse_kg_m2` | Tách riêng `synthetic`, `sim`, `real`, `public`. Mẫu `real` (rất ít) **MUST** báo cáo riêng, trung thực; không trộn hoặc làm đẹp số liệu `real` |
| **Gợi ý cây trồng** | `top1_accuracy`, `ndcg_at_3` | Tính trên các mẫu `synthetic` trong tập test có `meta.oracle_relative_yields`: gộp theo `(greenhouse_key, điều kiện khí hậu)` hoặc từng mẫu có oracle dict, xếp hạng tất cả ứng viên theo mô hình và so với thứ hạng oracle (tính `NDCG@3` với `relevance = max(0, oracle_relative_yield)` và `Top-1 accuracy` khi top-1 mô hình trùng top-1 oracle) |

- Tính song song `metrics` cho mô hình mới và `baseline_metrics = {"B0": {...}, "B1": {...}}` trên cùng tập test để lưu vào `ml_models`.

## 7. Thuật toán Gợi ý Cây trồng & Giải thích tiếng Việt

Dùng chung mô hình `yield` active để xếp hạng cây phù hợp nhất cho điều kiện khí hậu hiện tại của một nhà kính (chi tiết runtime tại `platform/worker/FEATURE_AI_RUNTIME_INFERENCE.md`):
1. Tính vector 16 đặc trưng khí hậu từ dữ liệu `quality = 'ok'` gộp các zone của nhà kính trong cửa sổ `recommend_window_h` gần nhất.
2. Tập ứng viên = danh sách `crop_code` có trong `ml_models.crops` của mô hình active (`>= 30` mẫu train).
3. Với mỗi cây ứng viên `c`:
   - **Thay `soil_mean`** bằng trung điểm `(soil_moisture_pct.min + soil_moisture_pct.max) / 2` từ crop profile template của cây `c` (giả định tưới đủ vì hệ thống điều khiển được tưới), và **`soil_std`** bằng median `soil_std` của tập train (lưu trong bundle).
   - Giữ nguyên 14 đặc trưng khí hậu còn lại (nhiệt độ, RH, VPD, GDD, DLI).
   - Chạy mô hình dự đoán `relative_yield`, tính `expected_kg_m2` và khoảng tin cậy `(p10, p90)`.
4. Xếp hạng giảm dần theo `relative_yield` (vì đã chuẩn hoá theo `reference_kg_m2`, so sánh được công bằng giữa cà chua, xà lách, dâu tây, dưa leo, ớt chuông) và trích `top_k = 3` (lưu đủ danh sách trong `ranking`).
5. **Giải thích bằng luật tiếng Việt (tối đa 3 lý do / cây):** So sánh `t_mean`, `vpd_mean`, `dli_mean` của nhà kính với `temp_c.optimal`, `vpd.optimal`, `light.dli_optimal` trong template của cây ứng viên:
   - Ví dụ không phù hợp: `"Nhiệt độ TB 31.2 °C cao hơn khoảng tối ưu 18–24 °C"`, `"VPD TB 0.35 kPa thấp hơn khoảng tối ưu 0.8–1.2 kPa"`, `"Ánh sáng DLI 9.5 thấp hơn mức tối ưu 20–30 mol/m²/ngày"`.
   - Ví dụ phù hợp: `"Nhiệt độ TB 20.5 °C nằm trong khoảng tối ưu 15–22 °C"`, `"VPD TB 0.82 kPa phù hợp khoảng tối ưu 0.6–1.0 kPa"`.
   - *(MAY)*: Có thể bổ sung top đặc trưng đóng góp từ LightGBM `pred_contrib` để làm giàu giải thích.

## 8. Vòng đời Mô hình & CLI `ml/train.py` (MUST)

### 8.1 Lệnh CLI
```powershell
$env:PYTHONPATH = "platform;."
python -m ml.train --task yield [--sources synthetic,sim,real,public] [--feature-version 1]
```

### 8.2 Quy trình thực thi trong `ml/train.py`
1. **Tải dữ liệu:** Truy vấn `yield_samples` khớp `feature_version` và `source IN args.sources`; tải danh mục `reference_kg_m2` từ system templates (`crop_profiles` với `farm_id IS NULL` hoặc `core.crop_templates`).
2. **Chia tập & Lọc cây đủ mẫu:** Chia `GroupShuffleSplit` theo `greenhouse_key` (70/15/15); lọc các `crop_code` có `>= 30` mẫu ở train. Nếu không đủ dữ liệu/nhà kính để chia hoặc thiếu mẫu → log rõ nguyên nhân và thoát sạch không crash.
3. **Huấn luyện & Đánh giá:** Fit `B0`, `B1` và `LightGBM` trên train; tính `residual_quantiles` (`p10`, `p90`) trên val; đánh giá toàn bộ chỉ số ở mục 6 trên test.
4. **Đóng gói Bundle Artifact (`.joblib`):**
   - Đường dẫn chuẩn: `{MODELS_DIR}/yield/v{next_version}.joblib` (trong Docker mặc định `/models/yield/v{n}.joblib`).
   - Nội dung dict bundle:
     ```python
     {
         "task": "yield",
         "version": next_version,
         "feature_version": 1,
         "trained_at": now_iso,
         "model": lgbm_regressor,
         "feature_names": [...],          # 16 đặc trưng số + ["crop_code"]
         "categorical_features": ["crop_code"],
         "crops": [{"crop_code": ..., "n": ..., "reference_kg_m2": ...}, ...],
         "residual_quantiles": {"p10": ..., "p90": ...},
         "train_feature_bounds": {        # dùng cho OOD check & soil_std median
             "t_mean": {"min": ..., "max": ..., "median": ...},
             ...
         },
         "train_stats": {                 # dùng cho kiểm tra feature drift
             "t_mean": {"mean": ..., "std": ...},
             ...
         },
     }
     ```
5. **Cổng kích hoạt (Activation Gate, MUST):**
   - Lấy `mae_new = metrics["mae_kg_m2"]`, `mae_b0 = baseline_metrics["B0"]["mae_kg_m2"]`, `mae_b1 = baseline_metrics["B1"]["mae_kg_m2"]`, và `mae_active` của bản `ml_models` đang `is_active = True` (nếu có).
   - Điều kiện kích hoạt: `mae_new < mae_b0` **VÀ** `mae_new < mae_b1` **VÀ** (`current_active is None` hoặc `mae_new < mae_active`).
   - **Nếu đạt:** Trong transaction DB, đặt `is_active = False` cho bản active cũ (`task = 'yield'`), chèn bản ghi mới `ml_models(..., is_active=True)`, và phát `pg_notify("worker_events", {"type": "model_activated", "task": "yield", "version": next_version})` để `worker` hot-reload ngay.
   - **Nếu không đạt:** Vẫn giữ file `.joblib` và chèn bản ghi `ml_models(..., is_active=False)` kèm lý do chi tiết trong `notes` (ví dụ: `"Không kích hoạt: MAE test 0.85 >= B1 0.81"`).
6. **Lưu metadata cho kiểm tra Feature Drift:** Lưu `train_stats` vào `ml_models.metrics["train_stats"]` (ngoài file `.joblib`) để `api` đọc được trực tiếp từ DB (so sánh `mean`/`std` 16 đặc trưng của `predictions.details['features']` trong 7 ngày gần nhất với `train_stats`) mà không cần nạp `.joblib` hay import thư viện ML.

## 9. Kiểm tra & Xác nhận

- **Unit tests bắt buộc (spec mục 15):**
  - `climate_features`: đầu vào cố định cho ra đúng 16 đặc trưng số; tách giờ ngày/đêm theo `Asia/Ho_Chi_Minh`; mượn `lux` từ zone cùng nhà kính khi zone hiện tại `lux = null`; trả `dli_mean = null` khi cả nhà kính không có `lux`; tính `coverage` và gắn `low_confidence` khi `< 24 h` hoặc OOD ngoài `[min, max]` train.
  - Chia dữ liệu `GroupShuffleSplit`: `set(train_gh) & set(val_gh) & set(test_gh)` rỗng (không rò rỉ nhà kính).
  - Baseline `B0`, `B1` (kể cả xử lý `dli_mean = null`), hàm tính `MAE`, `RMSE`, `R²`, `MAPE`, `Top-1 accuracy`, `NDCG@3`.
  - Quy tắc cổng kích hoạt (`is_active = True` chỉ khi thắng cả `B0`, `B1` và bản đang active; ngược lại `is_active = False` + ghi `notes`).
  - Thuật toán xếp hạng gợi ý cây trồng (thay `soil_mean` bằng trung điểm của từng cây) và sinh lý do tiếng Việt.
- **Lệnh xác nhận pipeline offline:**
  ```powershell
  $env:PYTHONPATH = "platform;."
  python -m tools.simulator synth-yield --greenhouses 200 --cycles-per-gh 5 --seed 42 --out data/synthetic_yield.csv
  python -m ml.dataset import --source synthetic --file data/synthetic_yield.csv
  python -m ml.train --task yield --sources synthetic --feature-version 1
  ```
