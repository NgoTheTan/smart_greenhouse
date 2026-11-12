# Hướng dẫn Coding Assistant – `platform/core/`

Thư mục này chứa lõi dùng chung cho cả tiến trình `api` và `worker`: cấu hình, kết nối DB async, models SQLAlchemy 2, schemas Pydantic v2, template cây trồng (`schema_version = 2`), công thức vi khí hậu, luật kiểm tra chất lượng dữ liệu, đặc trưng khí hậu dùng chung (`climate_features.py`, `feature_version = 1`), bảo mật JWT/Argon2 và PostgreSQL `LISTEN/NOTIFY`.

- Tài liệu chi tiết:
  - [FEATURE_CROP_PROFILES_AND_DATA_MODEL.md](./FEATURE_CROP_PROFILES_AND_DATA_MODEL.md)
  - [FEATURE_MICROCLIMATE_AND_QUALITY.md](./FEATURE_MICROCLIMATE_AND_QUALITY.md)
  - Liên kết chéo pipeline AI sử dụng `climate_features.py`: [ml/FEATURE_AI_YIELD_AND_RECOMMENDATION.md](../../ml/FEATURE_AI_YIELD_AND_RECOMMENDATION.md)
- Bất biến quan trọng:
  - Không import `pandas`, `scikit-learn`, `lightgbm` vào `platform/core/` (vì `api` import `core`, và `api` bị giới hạn RAM 384 MB trên VPS 2 GB). Riêng `climate_features.py` viết bằng Python thuần để dùng chung cho `worker`, `ml/` và `tools/simulator`.
  - Gốc import là `platform/` (`from core...`).
  - Mọi tham số sinh học/thời gian phải qua `CropParameters` trong `crop_templates.py` (`schema_version = 2`), không hard-code vào code nghiệp vụ (trừ các hằng số thuộc định nghĩa `feature_version = 1` trong `climate_features.py`).
