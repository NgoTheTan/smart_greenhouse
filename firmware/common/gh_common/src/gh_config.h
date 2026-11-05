// GreenHub - hằng số dùng chung node/gateway
#pragma once
#include <stdint.h>

namespace gh {

// Kênh Wi-Fi quét khi tìm gateway (spec 4.2)
constexpr uint8_t WIFI_CH_MIN = 1;
constexpr uint8_t WIFI_CH_MAX = 13;
constexpr uint8_t SEND_FAIL_RESCAN = 5;        // N lần gửi lỗi liên tiếp -> quét lại kênh
constexpr uint32_t HELLO_UNPAIRED_MS = 30000;  // HELLO định kỳ khi chưa ghép

// Chu kỳ đo
#ifdef DEMO_MODE
constexpr uint16_t DEFAULT_SAMPLE_INTERVAL_S = 10;
#else
constexpr uint16_t DEFAULT_SAMPLE_INTERVAL_S = 60;
#endif

// Dải vật lý hợp lệ (spec 8.2 A1)
constexpr float AIR_T_MIN = -10.0f, AIR_T_MAX = 60.0f;
constexpr float AIR_RH_MIN = 0.0f, AIR_RH_MAX = 100.0f;

inline uint8_t clampPct(int v) { return v < 0 ? 0 : (v > 100 ? 100 : (uint8_t)v); }

// Hiệu chuẩn 2 điểm ẩm đất: dry_raw -> 0%, wet_raw -> 100%
inline uint8_t soilPct(uint16_t raw, uint16_t dryRaw, uint16_t wetRaw) {
  if (dryRaw == wetRaw) return 0;
  long pct = ((long)dryRaw - (long)raw) * 100L / ((long)dryRaw - (long)wetRaw);
  return clampPct((int)pct);
}

}  // namespace gh

