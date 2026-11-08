# Hướng dẫn Coding Assistant – `platform/core/`

Thư mục này chứa lõi dùng chung cho cả tiến trình `api` và `worker`: cấu hình, kết nối DB async, models SQLAlchemy 2, schemas Pydantic v2, template cây trồng, công thức vi khí hậu, luật chất lượng dữ liệu A1, bảo mật JWT/Argon2 và PostgreSQL `LISTEN/NOTIFY`.

- Tài liệu chi tiết:
  - [FEATURE_CROP_PROFILES_AND_DATA_MODEL.md](./FEATURE_CROP_PROFILES_AND_DATA_MODEL.md)
  - [FEATURE_MICROCLIMATE_AND_QUALITY.md](./FEATURE_MICROCLIMATE_AND_QUALITY.md)
- Bất biến quan trọng:
  - Không import `pandas`, `scikit-learn`, `lightgbm` vào `platform/core/` (vì `api` import `core`, và `api` bị giới hạn RAM 384 MB).
  - Gốc import là `platform/` (`from core...`).
  - Mọi tham số sinh học/thời gian phải qua `CropParameters` trong `crop_templates.py`, không hard-code vào code nghiệp vụ.
