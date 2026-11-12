# Hướng dẫn Coding Assistant – `platform/tests/`

Thư mục này chứa toàn bộ unit tests và integration tests của GreenHub (cấu hình chạy trong `pyproject.toml`: `pythonpath = ["platform", "."]`, `asyncio_mode = "auto"`).

- Tài liệu chi tiết: [FEATURE_TESTING_AND_ACCEPTANCE.md](./FEATURE_TESTING_AND_ACCEPTANCE.md)
- Bất biến quan trọng:
  - Test tích hợp cần Docker stack thật phải gắn `@pytest.mark.integration` và tự `skip` nếu cổng `8000` / `8883` chưa mở.
  - Trên Windows, `conftest.py` đặt `WindowsSelectorEventLoopPolicy` để `aiomqtt` hoạt động trong test async.
  - Khi unit test coroutine trên máy không muốn mở socket loop, giữ helper `_run_coro` hoặc pytest-asyncio hợp lệ; luôn giữ unit test chạy nhanh, không phụ thuộc mạng ngoài.
  - Luôn giữ `test_api_process_does_not_import_heavy_ml_libraries` và bộ test bắt buộc cho `climate_features`, chống rò rỉ theo `greenhouse_key`, baseline B0/B1, activation gate, `harvest → yield_samples`, và cô lập tenant (không lộ `yield_samples` qua API).
