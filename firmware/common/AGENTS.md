# Hướng dẫn Coding Assistant – `firmware/common/`

Thư mục này chứa thư viện PlatformIO dùng chung (`gh_common`) giữa `firmware/node` và `firmware/gateway` (qua `lib_extra_dirs = ../common`).

- Tài liệu chi tiết: [FEATURE_ESP_NOW_PROTOCOL.md](./FEATURE_ESP_NOW_PROTOCOL.md)
- Bất biến quan trọng:
  - Mọi struct gói tin ESP-NOW phải giữ `__attribute__((packed))`, little-endian, tổng kích thước `<= 250` byte (`static_assert` đã có sẵn trong `gh_packets.h`).
  - Khi thêm/sửa trường hoặc hằng số trong `gh_packets.h` / `gh_config.h`, phải đối chiếu khớp với `platform/core/quality.py` (cờ `FLAG_*`) và biên dịch kiểm tra cả `firmware/node` lẫn `firmware/gateway`.
