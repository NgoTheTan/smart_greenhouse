// GreenHub - gói tin ESP-NOW (spec mục 4.4)
// Nhị phân, little-endian, packed, <= 250 byte.
#pragma once
#include <stdint.h>

#define GH_FW_MAJOR 1
#define GH_FW_MINOR 0

#define GH_LUX_NONE 0xFFFFFFFFu  // node không có BH1750

enum PktType : uint8_t {
  PKT_TELEMETRY = 1,
  PKT_HELLO = 2,
  PKT_HELLO_ACK = 3,
  PKT_CFG = 4,
};

// bit trong TelemetryPkt.flags
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

struct __attribute__((packed)) HelloPkt {
  uint8_t type;
  uint8_t fw_major, fw_minor;
};

struct __attribute__((packed)) HelloAckPkt {
  uint8_t type;
  uint8_t channel;
};

struct __attribute__((packed)) CfgPkt {
  uint8_t type;  // PKT_CFG
  uint8_t zone;
  uint16_t sample_interval_s;
  uint16_t soil_dry_raw;
  uint16_t soil_wet_raw;
  uint16_t cfg_version;
};

static_assert(sizeof(TelemetryPkt) <= 250, "ESP-NOW payload limit");
static_assert(sizeof(CfgPkt) <= 250, "ESP-NOW payload limit");

