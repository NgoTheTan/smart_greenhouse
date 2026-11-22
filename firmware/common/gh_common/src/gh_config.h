// GreenHub - hằng số dùng chung node/gateway
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace gh {

// Cấu hình Wi-Fi & UDP dùng chung giữa Sensor Node (client) và Gateway (server)
constexpr char WIFI_SSID[] = "Greenhouse-IOT";
constexpr char WIFI_PASS[] = "12345678";
constexpr uint16_t UDP_PORT = 4210;

// Chu kỳ đo & hiệu chuẩn ẩm đất mặc định (cảm biến xuất ~1.9V khi khô -> ADC 12-bit ESP32 ≈ 2230)
constexpr uint16_t SENSOR_MEASURE_INTERVAL_S = 5;  // Chu kỳ đo cảm biến tại biên (5 giây)
constexpr uint16_t DEFAULT_SAMPLE_INTERVAL_S = 5;
constexpr uint16_t DEFAULT_SOIL_DRY_RAW = 2230;
constexpr uint16_t DEFAULT_SOIL_WET_RAW = 1000;

// Dải vật lý hợp lệ & ngưỡng spike (spec 8.2 A1, khớp platform/core/quality.py)
constexpr float AIR_T_MIN = -10.0f, AIR_T_MAX = 60.0f;
constexpr float AIR_RH_MIN = 0.0f, AIR_RH_MAX = 100.0f;
constexpr uint16_t SOIL_RAW_MIN = 50;
constexpr uint16_t SOIL_RAW_MAX = 4090;
constexpr uint32_t LUX_MAX = 65535u;
constexpr uint32_t LUX_NONE = 0xFFFFFFFFu;
constexpr float SPIKE_AIR_T_C = 5.0f;
constexpr float SPIKE_AIR_RH_PCT = 25.0f;
constexpr uint8_t SPIKE_SOIL_PCT = 20;

inline bool isValidAirTemp(float t) { return t >= AIR_T_MIN && t <= AIR_T_MAX; }

inline bool isValidAirRh(float rh) { return rh >= AIR_RH_MIN && rh <= AIR_RH_MAX; }

inline bool isValidSoilRaw(uint16_t raw) {
  return raw >= SOIL_RAW_MIN && raw <= SOIL_RAW_MAX;
}

inline bool isValidLux(uint32_t lux) { return lux == LUX_NONE || lux <= LUX_MAX; }

inline uint8_t clampPct(int v) { return v < 0 ? 0 : (v > 100 ? 100 : (uint8_t)v); }

// Hiệu chuẩn 2 điểm ẩm đất: dry_raw -> 0%, wet_raw -> 100%
inline uint8_t soilPct(uint16_t raw, uint16_t dryRaw, uint16_t wetRaw) {
  if (dryRaw == wetRaw) return 0;
  long pct = ((long)dryRaw - (long)raw) * 100L / ((long)dryRaw - (long)wetRaw);
  return clampPct((int)pct);
}

}  // namespace gh
