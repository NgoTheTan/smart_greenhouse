# Hướng dẫn Coding Assistant – `platform/migrations/`

Thư mục này chứa Alembic migrations cho **PostgreSQL 16 + TimescaleDB**.

- Tài liệu chi tiết: [FEATURE_DATABASE_TIMESCALEDB.md](./FEATURE_DATABASE_TIMESCALEDB.md)
- Bất biến quan trọng:
  - Không sửa các migration đã áp dụng ở M2 (`0001`, `0002`, `0003`); mọi thay đổi schema mới (`crop_cycles`, `yield_samples`, `crop_profiles.crop_code`, `zones.area_m2`, `ml_models`, `predictions`) thực hiện bằng migration kế tiếp (`0004`, `down_revision = "0003"`).
  - Migration tạo continuous aggregates (`readings_1m`, `readings_1h`) bắt buộc dùng `with op.get_context().autocommit_block():` (TimescaleDB cấm tạo continuous aggregate trong transaction block).
  - Mọi thay đổi schema phải đồng bộ 1-1 giữa `platform/core/models.py` và migration mới trong `platform/migrations/versions/` (giữ nguyên các ràng buộc `CHECK`, `crop_cycles_one_active`, `alerts_open_dedupe`).
  - Container `api` tự chạy `alembic upgrade head` lúc khởi động trước khi `worker` chạy (`depends_on: api: condition: service_healthy`).
