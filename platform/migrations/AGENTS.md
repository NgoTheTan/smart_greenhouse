# Hướng dẫn Coding Assistant – `platform/migrations/`

Thư mục này chứa Alembic migrations cho **PostgreSQL 16 + TimescaleDB**.

- Tài liệu chi tiết: [FEATURE_DATABASE_TIMESCALEDB.md](./FEATURE_DATABASE_TIMESCALEDB.md)
- Bất biến quan trọng:
  - Migration tạo continuous aggregates (`readings_1m`, `readings_1h`) bắt buộc dùng `with op.get_context().autocommit_block():` (TimescaleDB cấm tạo continuous aggregate trong transaction block).
  - Mọi thay đổi schema phải đồng bộ 1-1 giữa `platform/core/models.py` và migration mới trong `platform/migrations/versions/`.
  - Container `api` tự chạy `alembic upgrade head` lúc khởi động trước khi `worker` chạy (`depends_on: api: condition: service_healthy`).
