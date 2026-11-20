// GreenHub - cấu trúc dữ liệu telemetry & cờ lỗi dùng chung giữa node và gateway
#pragma once
#include <stdint.h>

#define GH_FW_MAJOR 1
#define GH_FW_MINOR 0
#define GH_FW_PATCH 0
#define GH_FW_VERSION_STR "1.0.0"
#define GH_NODE_FW_STR "1.0"

#define GH_LUX_NONE 0xFFFFFFFFu  // node không có BH1750
#define GH_AIR_T_NONE (-32768)   // node không có cảm biến nhiệt độ (INT16_MIN)
#define GH_AIR_RH_NONE 0xFFFFu   // node không có cảm biến độ ẩm (UINT16_MAX)

enum PktType : uint8_t {
  PKT_TELEMETRY = 1,
  PKT_CFG = 4,
};

// bit trong TelemetryPkt.flags (khớp platform/core/quality.py)
enum TelemetryFlag : uint8_t {
  FLAG_AHT_ERR = 1 << 0,
  FLAG_SOIL_ERR = 1 << 1,
  FLAG_BH_ERR = 1 << 2,
};

struct __attribute__((packed)) TelemetryPkt {
  uint8_t type;          // PKT_TELEMETRY
  uint8_t zone;          // zone_index (1..N) từ cfg; 0 nếu chưa ghép
  uint16_t seq;
  int16_t air_t_x100;    // °C * 100
  uint16_t air_rh_x100;  // %RH * 100
  uint16_t soil_raw;     // ADC thô
  uint8_t soil_pct;      // 0..100 (đã hiệu chuẩn)
  uint8_t flags;         // bit0 aht_err, bit1 soil_err, bit2 bh_err
  uint32_t lux;          // GH_LUX_NONE = không có
  uint16_t vbat_mv;      // 0 nếu cấp nguồn USB
  uint8_t fw_major, fw_minor;
};

struct __attribute__((packed)) CfgPkt {
  uint8_t type;  // PKT_CFG
  uint8_t zone;
  uint16_t sample_interval_s;
  uint16_t soil_dry_raw;
  uint16_t soil_wet_raw;
  uint16_t cfg_version;
};
