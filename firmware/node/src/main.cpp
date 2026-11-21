// GreenHub - Firmware Sensor Node 1 ESP32 (DevKit 38-pin) + Màn hình ST7789 240x240
// Phần cứng cố định:
//   - DHT11: GPIO26
//   - BH1750 (I2C): SDA = GPIO21, SCL = GPIO22
//   - Độ ẩm đất Node 1: AOUT = GPIO34 (ADC1, dùng analogRead trực tiếp)
//   - ST7789 SPI (8-pin: GND, VCC, SCL, SDA, RST, DC, CS, BL):
//       SCL -> GPIO18 (VSPI SCLK)
//       SDA -> GPIO23 (VSPI MOSI)
//       RST -> GPIO4
//       DC  -> GPIO16
//       CS  -> GPIO5
//       BL  -> GPIO17 (hoặc 3V3)
//   - LED: GPIO2
// Kết nối Wi-Fi "Greenhouse-IOT" (pass "12345678"):
//   - Gửi UDP JSON telemetry của Node 1 mỗi 5 giây tới Broadcast IP (port 4210)
//   - Chạy UDP Server (port 4210) nhận gói độ ẩm đất từ Node 2 và hiển thị trực tiếp lên ST7789.

#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <Arduino.h>
#include <ArduinoJson.h>
#include <ArduinoOTA.h>
#include <BH1750.h>
#include <DHT.h>
#include <SPI.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <Wire.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "gh_config.h"
#include "gh_packets.h"

namespace {

constexpr uint8_t PIN_DHT_DATA = 26;
constexpr uint8_t PIN_SDA = 21;
constexpr uint8_t PIN_SCL = 22;
constexpr uint8_t PIN_SOIL_ADC = 34;
constexpr uint8_t PIN_STATUS_LED = 2;

// Chân màn hình ST7789 (SPI) trên ESP32 DevKit 38-pin
constexpr int8_t TFT_SCLK_PIN = 18;
constexpr int8_t TFT_MOSI_PIN = 23;
constexpr int8_t TFT_RST_PIN = 4;
constexpr int8_t TFT_DC_PIN = 16;
constexpr int8_t TFT_CS_PIN = 5;
constexpr int8_t TFT_BL_PIN = 17;

constexpr uint8_t BH1750_ADDR = 0x23;
constexpr uint8_t SOIL_SAMPLES = 5;
constexpr unsigned long NODE2_TIMEOUT_MS = 20000UL;  // Quá 20s không nhận gói xem như stale

// Bảng màu RGB565 cho giao diện ST7789
constexpr uint16_t COL_BG = 0x0841;             // Nền xanh đen đậm
constexpr uint16_t COL_CARD = 0x10A3;           // Nền ô thẻ thông số
constexpr uint16_t COL_CARD_BORDER = 0x2165;    // Viền thẻ tinh tế
constexpr uint16_t COL_HEADER = 0x02E5;         // Xanh lá đậm thanh tiêu đề
constexpr uint16_t COL_HEADER_ACCENT = 0x07E8;  // Viền sáng dưới thanh tiêu đề
constexpr uint16_t COL_FOOTER = 0x1082;         // Nền thanh trạng thái dưới
constexpr uint16_t COL_BAR_BG = 0x2124;         // Nền thanh tiến trình
constexpr uint16_t COL_WHITE = 0xFFFF;          // Trắng
constexpr uint16_t COL_MUTED = 0x9CD3;          // Xám nhạt
constexpr uint16_t COL_TEMP = 0xFD20;           // Cam (Nhiệt độ)
constexpr uint16_t COL_TEMP_BULB = 0xF986;      // Đỏ cam (Bầu nhiệt kế)
constexpr uint16_t COL_HUM = 0x05FF;            // Xanh cyan (Độ ẩm KK)
constexpr uint16_t COL_SOIL1 = 0x07E8;          // Xanh lục sáng (Độ ẩm đất Node 1)
constexpr uint16_t COL_SOIL2 = 0x07F3;          // Xanh ngọc sáng (Độ ẩm đất Node 2)
constexpr uint16_t COL_EARTH = 0xB463;          // Nâu đất cho icon mầm cây
constexpr uint16_t COL_LUX = 0xFFE0;            // Vàng (Ánh sáng)
constexpr uint16_t COL_DANGER = 0xF986;         // Đỏ cảnh báo

WiFiUDP g_udp;
bool g_udp_started = false;
bool g_ota_started = false;

DHT g_dht(PIN_DHT_DATA, DHT11);
BH1750 g_bh1750(BH1750_ADDR);
bool g_bh_init_ok = false;

Adafruit_ST7789 g_tft(&SPI, TFT_CS_PIN, TFT_DC_PIN, TFT_RST_PIN);
bool g_tft_ready = false;

uint8_t g_zone = 1;
uint16_t g_interval_s = gh::SENSOR_MEASURE_INTERVAL_S;  // Chu kỳ gửi UDP (5 giây)
uint16_t g_dry_raw = gh::DEFAULT_SOIL_DRY_RAW;
uint16_t g_wet_raw = gh::DEFAULT_SOIL_WET_RAW;
uint16_t g_seq = 0;
IPAddress g_gateway_ip(0, 0, 0, 0);
unsigned long g_last_sensor_ms = 0;
unsigned long g_last_udp_ms = 0;

// Dữ liệu cảm biến tại Node 1
uint16_t g_soil_raw = 0;
uint8_t g_soil_pct = 0;
int16_t g_air_t_x100 = 0;
uint16_t g_air_rh_x100 = 0;
uint32_t g_lux = GH_LUX_NONE;

// Dữ liệu độ ẩm đất nhận từ Node 2 qua UDP Server
bool g_node2_has_data = false;
uint8_t g_node2_zone = 2;
uint8_t g_node2_soil_pct = 0;
uint16_t g_node2_soil_raw = 0;
bool g_node2_has_raw = false;
unsigned long g_node2_last_rx_ms = 0;
uint32_t g_node2_rx_count = 0;

// ============================================================================
// Hàm vẽ Icon đồ họa & Thanh mức trực quan trên ST7789
// ============================================================================

void drawLeafHeaderIcon(int16_t x, int16_t y) {
  // Lá cây cách điệu trên thanh tiêu đề (16x16)
  g_tft.fillCircle(x + 8, y + 8, 6, COL_HEADER_ACCENT);
  g_tft.fillTriangle(x + 8, y + 2, x + 15, y + 2, x + 14, y + 9, COL_HEADER_ACCENT);
  g_tft.drawLine(x + 3, y + 14, x + 11, y + 6, COL_HEADER);
  g_tft.drawLine(x + 2, y + 15, x + 4, y + 13, COL_HEADER_ACCENT);
}

void drawThermometerIcon(int16_t x, int16_t y) {
  // Icon nhiệt kế (18x22)
  g_tft.drawRoundRect(x + 5, y + 1, 7, 14, 3, COL_WHITE);
  g_tft.fillCircle(x + 8, y + 16, 5, COL_TEMP_BULB);
  g_tft.fillRect(x + 7, y + 6, 3, 8, COL_TEMP);
  g_tft.fillCircle(x + 7, y + 15, 1, COL_WHITE);  // Điểm bóng sáng
  // Vạch chia độ bên phải
  g_tft.drawFastHLine(x + 14, y + 3, 3, COL_MUTED);
  g_tft.drawFastHLine(x + 14, y + 7, 2, COL_MUTED);
  g_tft.drawFastHLine(x + 14, y + 11, 3, COL_MUTED);
}

void drawDropletIcon(int16_t x, int16_t y) {
  // Icon giọt nước độ ẩm không khí (18x22)
  g_tft.fillTriangle(x + 8, y + 1, x + 2, y + 12, x + 14, y + 12, COL_HUM);
  g_tft.fillCircle(x + 8, y + 14, 6, COL_HUM);
  // Điểm phản quang trắng trong giọt nước
  g_tft.fillCircle(x + 6, y + 15, 2, COL_WHITE);
  g_tft.fillCircle(x + 7, y + 14, 2, COL_HUM);
}

void drawSproutIcon(int16_t x, int16_t y, uint16_t leaf_col, bool is_remote_udp) {
  // Icon mầm cây trên đất (20x22)
  // 1. Mô đất phía dưới
  g_tft.fillRoundRect(x + 2, y + 17, 16, 4, 2, COL_EARTH);
  g_tft.fillRoundRect(x + 5, y + 15, 10, 3, 1, COL_EARTH);
  // 2. Thân cây
  g_tft.fillRect(x + 9, y + 8, 2, 8, leaf_col);
  // 3. Lá trái & lá phải
  g_tft.fillCircle(x + 6, y + 10, 3, leaf_col);
  g_tft.fillTriangle(x + 2, y + 8, x + 6, y + 7, x + 6, y + 13, leaf_col);
  g_tft.fillCircle(x + 13, y + 8, 3, leaf_col);
  g_tft.fillTriangle(x + 17, y + 6, x + 13, y + 5, x + 13, y + 11, leaf_col);

  if (is_remote_udp) {
    // Sóng UDP không dây phía trên mầm cây (Node 2)
    g_tft.drawFastHLine(x + 8, y + 3, 4, COL_HUM);
    g_tft.drawPixel(x + 7, y + 4, COL_HUM);
    g_tft.drawPixel(x + 12, y + 4, COL_HUM);
    g_tft.drawFastHLine(x + 6, y + 1, 8, COL_HUM);
    g_tft.drawPixel(x + 5, y + 2, COL_HUM);
    g_tft.drawPixel(x + 14, y + 2, COL_HUM);
  } else {
    // Giọt nước nhỏ bên cạnh mầm cây (Node 1)
    g_tft.fillTriangle(x + 16, y + 1, x + 14, y + 4, x + 18, y + 4, COL_HUM);
    g_tft.fillCircle(x + 16, y + 5, 2, COL_HUM);
  }
}

void drawSunIcon(int16_t x, int16_t y) {
  // Icon mặt trời 8 tia nắng (22x22)
  const int16_t cx = x + 11;
  const int16_t cy = y + 11;
  // 4 tia chính (ngang/dọc)
  g_tft.drawFastVLine(cx, cy - 10, 3, COL_LUX);
  g_tft.drawFastVLine(cx, cy + 8, 3, COL_LUX);
  g_tft.drawFastHLine(cx - 10, cy, 3, COL_LUX);
  g_tft.drawFastHLine(cx + 8, cy, 3, COL_LUX);
  // 4 tia chéo
  g_tft.drawLine(cx - 7, cy - 7, cx - 5, cy - 5, COL_LUX);
  g_tft.drawLine(cx + 5, cy - 5, cx + 7, cy - 7, COL_LUX);
  g_tft.drawLine(cx - 7, cy + 7, cx - 5, cy + 5, COL_LUX);
  g_tft.drawLine(cx + 5, cy + 5, cx + 7, cy + 7, COL_LUX);
  // Tâm mặt trời
  g_tft.fillCircle(cx, cy, 6, COL_TEMP);
  g_tft.fillCircle(cx, cy, 5, COL_LUX);
}

void drawWifiBarsIcon(int16_t x, int16_t y, bool connected) {
  // Icon 4 cột sóng Wi-Fi ở footer (14x11)
  const uint16_t active_col = connected ? COL_SOIL1 : COL_MUTED;
  g_tft.fillRect(x, y + 8, 2, 3, active_col);
  g_tft.fillRect(x + 4, y + 6, 2, 5, active_col);
  g_tft.fillRect(x + 8, y + 3, 2, 8, active_col);
  g_tft.fillRect(x + 12, y, 2, 11, active_col);
  if (!connected) {
    g_tft.drawLine(x, y, x + 13, y + 10, COL_DANGER);
  }
}

void drawProgressBar(int16_t x, int16_t y, int16_t w, int16_t h, uint8_t pct, uint16_t fill_col) {
  if (pct > 100) pct = 100;
  g_tft.fillRoundRect(x, y, w, h, 2, COL_BAR_BG);
  const int16_t fill_w = static_cast<int16_t>((static_cast<int32_t>(w) * pct) / 100);
  if (fill_w >= 4) {
    g_tft.fillRoundRect(x, y, fill_w, h, 2, fill_col);
  } else if (fill_w > 0) {
    g_tft.fillRect(x, y, fill_w, h, fill_col);
  }
}

uint16_t pickSoilBarColor(uint8_t pct) {
  if (pct < 30) return COL_DANGER;
  if (pct < 45) return COL_TEMP;
  return COL_SOIL1;
}

void drawCardFrame(int16_t x, int16_t y, int16_t w, int16_t h) {
  g_tft.fillRoundRect(x, y, w, h, 6, COL_CARD);
  g_tft.drawRoundRect(x, y, w, h, 6, COL_CARD_BORDER);
}

void initDisplay() {
  pinMode(TFT_BL_PIN, OUTPUT);
  digitalWrite(TFT_BL_PIN, HIGH);  // Bật đèn nền màn hình

  SPI.begin(TFT_SCLK_PIN, -1, TFT_MOSI_PIN, TFT_CS_PIN);
  // Khởi tạo ST7789 240x240 với SPI_MODE0 (chuẩn cho module 8 chân có CS)
  g_tft.init(240, 240, SPI_MODE0);
  // Hạ tốc độ SPI xuống 20 MHz để chạy ổn định trên dây cắm jumper breadboard
  g_tft.setSPISpeed(20000000);
  // Xoay màn hình 90 độ sang phải (Landscape 240x240)
  g_tft.setRotation(1);
  g_tft.fillScreen(COL_BG);

  // 1. Thanh tiêu đề (y: 0..27)
  g_tft.fillRect(0, 0, 240, 27, COL_HEADER);
  g_tft.drawFastHLine(0, 27, 240, COL_HEADER_ACCENT);
  drawLeafHeaderIcon(6, 5);
  g_tft.setTextColor(COL_WHITE, COL_HEADER);
  g_tft.setTextSize(2);
  g_tft.setCursor(26, 6);
  g_tft.print("GREENHUB");

  // 2. Hàng 1 (y: 32..95, h=64): Nhiệt độ (trái) & Độ ẩm KK (phải)
  drawCardFrame(5, 32, 112, 64);
  drawCardFrame(123, 32, 112, 64);
  drawThermometerIcon(10, 38);
  drawDropletIcon(128, 38);

  g_tft.setTextSize(1);
  g_tft.setTextColor(COL_MUTED, COL_CARD);
  g_tft.setCursor(32, 38);
  g_tft.print("NHIET DO");
  g_tft.setCursor(150, 38);
  g_tft.print("DO AM KK");

  // 3. Hàng 2 (y: 100..171, h=72): Độ ẩm đất Node 2 UDP (trái) & Độ ẩm đất Node 1 (phải)
  drawCardFrame(5, 100, 112, 72);
  drawCardFrame(123, 100, 112, 72);
  drawSproutIcon(9, 105, COL_SOIL2, true);
  drawSproutIcon(127, 105, COL_SOIL1, false);

  g_tft.setCursor(33, 106);
  g_tft.print("AM DAT N2");
  g_tft.setCursor(151, 106);
  g_tft.print("AM DAT N1");

  // 4. Hàng 3 (y: 176..213, h=38): Ánh sáng BH1750 (thẻ ngang toàn màn hình)
  drawCardFrame(5, 176, 230, 38);
  drawSunIcon(11, 184);
  g_tft.setCursor(38, 182);
  g_tft.print("ANH SANG (BH1750)");

  // 5. Thanh trạng thái Wi-Fi & UDP Server dưới cùng (y: 218..239, h=22)
  g_tft.fillRect(0, 218, 240, 22, COL_FOOTER);
  drawWifiBarsIcon(6, 223, false);
  g_tft.setTextColor(COL_MUTED, COL_FOOTER);
  g_tft.setCursor(24, 226);
  g_tft.print("WiFi: Connecting...");

  g_tft_ready = true;
}

void updateNode2DisplayCard() {
  if (!g_tft_ready) return;

  char buf[32];
  const unsigned long now = millis();
  const bool is_fresh = g_node2_has_data && ((now - g_node2_last_rx_ms) <= NODE2_TIMEOUT_MS);

  // Badge trạng thái Node 2 trên thanh Header (góc phải)
  g_tft.fillRect(142, 4, 94, 20, COL_HEADER);
  const uint16_t dot_col = is_fresh ? COL_HEADER_ACCENT : (g_node2_has_data ? COL_TEMP : COL_MUTED);
  g_tft.fillCircle(150, 13, 4, dot_col);
  g_tft.setTextSize(1);
  g_tft.setTextColor(COL_WHITE, COL_HEADER);
  g_tft.setCursor(158, 10);
  if (is_fresh) {
    snprintf(buf, sizeof(buf), "N2:UDP %u%%", g_node2_soil_pct);
  } else if (g_node2_has_data) {
    snprintf(buf, sizeof(buf), "N2:STALE");
  } else {
    snprintf(buf, sizeof(buf), "N2:WAIT UDP");
  }
  g_tft.print(buf);

  // Nội dung thẻ Độ ẩm đất Node 2 (x: 5..116, y: 100..171)
  g_tft.fillRect(32, 118, 80, 26, COL_CARD);
  g_tft.fillRect(12, 147, 98, 10, COL_CARD);

  if (g_node2_has_data) {
    const uint16_t val_col = is_fresh ? COL_SOIL2 : COL_TEMP;
    g_tft.setTextColor(val_col, COL_CARD);
    g_tft.setTextSize(3);
    g_tft.setCursor(33, 119);
    snprintf(buf, sizeof(buf), "%u", g_node2_soil_pct);
    g_tft.print(buf);
    g_tft.setTextSize(2);
    g_tft.print("%");

    const unsigned long age_s = (now - g_node2_last_rx_ms) / 1000UL;
    g_tft.setTextSize(1);
    g_tft.setTextColor(is_fresh ? COL_MUTED : COL_TEMP, COL_CARD);
    g_tft.setCursor(13, 148);
    if (g_node2_has_raw) {
      snprintf(buf, sizeof(buf), "ADC:%u|%lus", g_node2_soil_raw, age_s);
    } else {
      snprintf(buf, sizeof(buf), "Z%u|UDP:%lus ago", g_node2_zone, age_s);
    }
    g_tft.print(buf);

    drawProgressBar(13, 160, 96, 5, g_node2_soil_pct, pickSoilBarColor(g_node2_soil_pct));
  } else {
    g_tft.setTextColor(COL_MUTED, COL_CARD);
    g_tft.setTextSize(2);
    g_tft.setCursor(33, 123);
    g_tft.print("-- %");

    g_tft.setTextSize(1);
    g_tft.setCursor(13, 148);
    g_tft.print("UDP:4210 Wait..");
    drawProgressBar(13, 160, 96, 5, 0, COL_MUTED);
  }
}

void updateDisplay(int16_t air_t_x100, uint16_t air_rh_x100, uint8_t soil_pct,
                   uint16_t soil_raw, uint32_t lux) {
  if (!g_tft_ready) return;

  char buf[36];

  // 1. Nhiệt độ (°C) - Thẻ trái Hàng 1
  g_tft.fillRect(32, 50, 80, 24, COL_CARD);
  g_tft.setTextColor(COL_TEMP, COL_CARD);
  g_tft.setTextSize(2);
  g_tft.setCursor(32, 54);
  const float temp_c = air_t_x100 / 100.0f;
  snprintf(buf, sizeof(buf), "%.1f", temp_c);
  g_tft.print(buf);
  const int16_t deg_x = g_tft.getCursorX() + 2;
  g_tft.drawCircle(deg_x, 56, 2, COL_TEMP);
  g_tft.setCursor(deg_x + 5, 54);
  g_tft.print("C");
  // Thanh mức nhiệt độ (0..50°C -> 0..100%)
  const uint8_t temp_bar_pct = gh::clampPct(static_cast<int>(temp_c * 2.0f));
  drawProgressBar(12, 83, 96, 5, temp_bar_pct, (temp_c > 35.0f) ? COL_DANGER : COL_TEMP);

  // 2. Độ ẩm không khí (%) - Thẻ phải Hàng 1
  g_tft.fillRect(150, 50, 80, 24, COL_CARD);
  g_tft.setTextColor(COL_HUM, COL_CARD);
  g_tft.setTextSize(2);
  g_tft.setCursor(150, 54);
  const uint8_t rh_pct = gh::clampPct(static_cast<int>(lroundf(air_rh_x100 / 100.0f)));
  snprintf(buf, sizeof(buf), "%u %%", rh_pct);
  g_tft.print(buf);
  drawProgressBar(131, 83, 96, 5, rh_pct, COL_HUM);

  // 3. Độ ẩm đất Node 1 (% + ADC raw) - Thẻ phải Hàng 2
  g_tft.fillRect(150, 118, 80, 26, COL_CARD);
  g_tft.setTextColor(COL_SOIL1, COL_CARD);
  g_tft.setTextSize(3);
  g_tft.setCursor(151, 119);
  snprintf(buf, sizeof(buf), "%u", soil_pct);
  g_tft.print(buf);
  g_tft.setTextSize(2);
  g_tft.print("%");

  g_tft.fillRect(130, 147, 98, 10, COL_CARD);
  g_tft.setTextSize(1);
  g_tft.setTextColor(COL_MUTED, COL_CARD);
  g_tft.setCursor(131, 148);
  snprintf(buf, sizeof(buf), "Z%u|ADC:%u", g_zone, soil_raw);
  g_tft.print(buf);
  drawProgressBar(131, 160, 96, 5, soil_pct, pickSoilBarColor(soil_pct));

  // 4. Độ ẩm đất Node 2 (từ UDP Server) - Thẻ trái Hàng 2
  updateNode2DisplayCard();

  // 5. Ánh sáng (Lux) - Thẻ ngang Hàng 3
  g_tft.fillRect(128, 182, 102, 26, COL_CARD);
  g_tft.setTextColor(COL_LUX, COL_CARD);
  g_tft.setTextSize(2);
  g_tft.setCursor(130, 188);
  uint8_t lux_bar_pct = 0;
  if (lux == GH_LUX_NONE) {
    g_tft.print("ERR");
  } else {
    snprintf(buf, sizeof(buf), "%lu", static_cast<unsigned long>(lux));
    g_tft.print(buf);
    g_tft.setTextSize(1);
    g_tft.setTextColor(COL_MUTED, COL_CARD);
    g_tft.setCursor(g_tft.getCursorX() + 3, 194);
    g_tft.print("Lx");
    // Quy đổi hiển thị thanh sáng (0..10000 Lux -> 0..100%)
    lux_bar_pct = gh::clampPct(static_cast<int>((lux * 100UL) / 10000UL));
    if (lux > 0 && lux_bar_pct == 0) lux_bar_pct = 4;
  }
  drawProgressBar(38, 198, 84, 6, lux_bar_pct, COL_LUX);

  // 6. Thanh trạng thái Wi-Fi & UDP Server dưới cùng
  const bool wifi_ok = (WiFi.status() == WL_CONNECTED);
  g_tft.fillRect(0, 218, 240, 22, COL_FOOTER);
  drawWifiBarsIcon(6, 223, wifi_ok);
  g_tft.setTextSize(1);
  g_tft.setTextColor(wifi_ok ? COL_WHITE : COL_MUTED, COL_FOOTER);
  g_tft.setCursor(24, 226);
  if (wifi_ok) {
    snprintf(buf, sizeof(buf), "IP:%s | UDP:%u",
             WiFi.localIP().toString().c_str(), gh::UDP_PORT);
  } else {
    snprintf(buf, sizeof(buf), "WiFi: Disconnected");
  }
  g_tft.print(buf);
}

IPAddress getBroadcastIp() {
  IPAddress local = WiFi.localIP();
  IPAddress mask = WiFi.subnetMask();
  if (static_cast<uint32_t>(local) == 0 || static_cast<uint32_t>(mask) == 0) {
    return IPAddress(255, 255, 255, 255);
  }
  return IPAddress((static_cast<uint32_t>(local) & static_cast<uint32_t>(mask)) |
                   (~static_cast<uint32_t>(mask)));
}

void initOta() {
  if (g_ota_started) return;
  ArduinoOTA.setHostname("node1");
  ArduinoOTA.onStart([]() {
    Serial.println("[node] OTA Update Start");
  });
  ArduinoOTA.onEnd([]() {
    Serial.println("\n[node] OTA Update End");
  });
  ArduinoOTA.onError([](ota_error_t error) {
    Serial.printf("[node] OTA Error[%u]\n", error);
  });
  ArduinoOTA.begin();
  g_ota_started = true;
  Serial.println("[node] ArduinoOTA ready (hostname: node1.local)");
}

void ensureWifiConnected() {
  if (WiFi.status() == WL_CONNECTED) {
    if (!g_udp_started) {
      g_udp_started = (g_udp.begin(gh::UDP_PORT) != 0);
      if (g_udp_started) {
        Serial.printf("[node] UDP Server listening on port %u\n", gh::UDP_PORT);
      }
    }
    initOta();
    return;
  }

  g_udp_started = false;
  g_ota_started = false;
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.setSleep(false);

  while (WiFi.status() != WL_CONNECTED) {
    Serial.printf("[node] Connecting Wi-Fi \"%s\"...\n", gh::WIFI_SSID);
    WiFi.begin(gh::WIFI_SSID, gh::WIFI_PASS);
    unsigned long start_ms = millis();
    while (WiFi.status() != WL_CONNECTED && (millis() - start_ms) < 10000UL) {
      digitalWrite(PIN_STATUS_LED, !digitalRead(PIN_STATUS_LED));
      delay(200);
    }
  }
  digitalWrite(PIN_STATUS_LED, LOW);
  g_udp_started = (g_udp.begin(gh::UDP_PORT) != 0);

  Serial.printf("[node] Wi-Fi connected: IP=%s | UDP Server port=%u\n",
                WiFi.localIP().toString().c_str(), gh::UDP_PORT);
  initOta();
}

void pollUdpServer() {
  if (!g_udp_started) return;
  int pkt_size = g_udp.parsePacket();
  while (pkt_size > 0) {
    char buf[384];
    int len = g_udp.read(buf, (pkt_size < static_cast<int>(sizeof(buf) - 1))
                                  ? pkt_size
                                  : static_cast<int>(sizeof(buf) - 1));
    if (len > 0) {
      buf[len] = '\0';
      const IPAddress remote_ip = g_udp.remoteIP();
      JsonDocument doc;
      if (deserializeJson(doc, buf, len) == DeserializationError::Ok) {
        const char* type_str = doc["type"] | "";
        const uint8_t pkt_zone = doc["zone"] | 0;

        if (strcmp(type_str, "node2") == 0 ||
            (strcmp(type_str, "telemetry") == 0 && pkt_zone == 2) ||
            (type_str[0] == '\0' && pkt_zone == 2)) {
          const int raw_pct = !doc["soil_pct"].isNull()
                                  ? (doc["soil_pct"] | 0)
                                  : (doc["soil_m"] | 0);
          g_node2_soil_pct = gh::clampPct(raw_pct);
          g_node2_zone = (pkt_zone > 0) ? pkt_zone : 2;
          if (!doc["soil_raw"].isNull()) {
            g_node2_soil_raw = doc["soil_raw"] | 0;
            g_node2_has_raw = true;
          }
          g_node2_has_data = true;
          g_node2_last_rx_ms = millis();
          ++g_node2_rx_count;

          Serial.printf("[node] UDP RX Node 2 (%s): zone=%u soil_pct=%u%% (#%lu)\n",
                        remote_ip.toString().c_str(), g_node2_zone, g_node2_soil_pct,
                        static_cast<unsigned long>(g_node2_rx_count));

          // Hiển thị ngay độ ẩm đất Node 2 lên màn hình khi vừa nhận gói UDP
          updateNode2DisplayCard();
        } else if (strcmp(type_str, "cfg") == 0) {
          if (pkt_zone == 0 || pkt_zone == g_zone) {
            if (static_cast<uint32_t>(remote_ip) != 0) {
              g_gateway_ip = remote_ip;
            }
            uint16_t dry = doc["soil_dry_raw"] | g_dry_raw;
            uint16_t wet = doc["soil_wet_raw"] | g_wet_raw;
            if (dry != wet && dry > 0 && wet > 0) {
              g_dry_raw = dry;
              g_wet_raw = wet;
            }
          }
        }
      }
    }
    pkt_size = g_udp.parsePacket();
  }
}

void initSensors() {
  g_dht.begin();
  Wire.begin(PIN_SDA, PIN_SCL);
  g_bh_init_ok = g_bh1750.begin(BH1750::CONTINUOUS_HIGH_RES_MODE, BH1750_ADDR, &Wire);
  if (!g_bh_init_ok) {
    Serial.println("[node] BH1750 begin failed on I2C (SDA=21, SCL=22)");
  } else {
    Serial.println("[node] DHT11 (GPIO26) & BH1750 (SDA=21, SCL=22) initialized");
  }
  delay(200);
}

uint16_t readSoilRaw() {
  uint32_t sum = 0;
  for (uint8_t i = 0; i < SOIL_SAMPLES; ++i) {
    sum += static_cast<uint16_t>(analogRead(PIN_SOIL_ADC));
    delay(2);
  }
  return static_cast<uint16_t>(sum / SOIL_SAMPLES);
}

void readDht11(int16_t* out_temp_x100, uint16_t* out_rh_x100) {
  float t = g_dht.readTemperature();
  float rh = g_dht.readHumidity();
  if (isnan(t) || isnan(rh)) {
    delay(250);
    t = g_dht.readTemperature();
    rh = g_dht.readHumidity();
  }

  if (isnan(t) || isnan(rh) || t < -40.0f || t > 85.0f || rh < 0.0f || rh > 100.0f) {
    *out_temp_x100 = 0;
    *out_rh_x100 = 0;
    return;
  }
  *out_temp_x100 = static_cast<int16_t>(lroundf(t * 100.0f));
  *out_rh_x100 = static_cast<uint16_t>(lroundf(rh * 100.0f));
}

uint32_t readBh1750Lux() {
  if (!g_bh_init_ok) {
    g_bh_init_ok = g_bh1750.begin(BH1750::CONTINUOUS_HIGH_RES_MODE, BH1750_ADDR, &Wire);
    delay(180);
  }
  if (!g_bh_init_ok) {
    return GH_LUX_NONE;
  }

  float lux_val = g_bh1750.readLightLevel();
  if (isnan(lux_val) || lux_val < 0.0f) {
    return GH_LUX_NONE;
  }
  if (lux_val > static_cast<float>(gh::LUX_MAX)) {
    lux_val = static_cast<float>(gh::LUX_MAX);
  }
  return static_cast<uint32_t>(lroundf(lux_val));
}

void readSensorsAndUpdateDisplay() {
  g_soil_raw = readSoilRaw();
  g_soil_pct = gh::soilPct(g_soil_raw, g_dry_raw, g_wet_raw);
  readDht11(&g_air_t_x100, &g_air_rh_x100);
  g_lux = readBh1750Lux();

  // Cập nhật lên màn hình ST7789 (1 giây / lần)
  updateDisplay(g_air_t_x100, g_air_rh_x100, g_soil_pct, g_soil_raw, g_lux);
}

void sendUdpTelemetry() {
  ensureWifiConnected();
  if (++g_seq == 0) g_seq = 1;

  JsonDocument doc;
  doc["type"] = "node1";
  doc["zone"] = g_zone;
  doc["seq"] = g_seq;
  doc["mac"] = WiFi.macAddress();
  doc["air_t_x100"] = g_air_t_x100;
  doc["air_rh_x100"] = g_air_rh_x100;
  doc["soil_pct"] = g_soil_pct;
  doc["soil_raw"] = g_soil_raw;
  if (g_lux == GH_LUX_NONE) {
    doc["lux"] = nullptr;
  } else {
    doc["lux"] = g_lux;
  }

  char payload[384];
  const size_t len = serializeJson(doc, payload, sizeof(payload));
  const IPAddress bcast = getBroadcastIp();
  g_udp.beginPacket(bcast, gh::UDP_PORT);
  g_udp.write(reinterpret_cast<const uint8_t*>(payload), len);
  g_udp.endPacket();

  if (static_cast<uint32_t>(g_gateway_ip) != 0 && g_gateway_ip != bcast) {
    g_udp.beginPacket(g_gateway_ip, gh::UDP_PORT);
    g_udp.write(reinterpret_cast<const uint8_t*>(payload), len);
    g_udp.endPacket();
  }

  Serial.printf("[node] UDP JSON: %s\n", payload);

  digitalWrite(PIN_STATUS_LED, HIGH);
  delay(40);
  digitalWrite(PIN_STATUS_LED, LOW);
}

}  // namespace

void setup() {
  pinMode(PIN_STATUS_LED, OUTPUT);
  digitalWrite(PIN_STATUS_LED, LOW);
  pinMode(PIN_SOIL_ADC, INPUT);
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_SOIL_ADC, ADC_11db);

  Serial.begin(115200);
  initDisplay();
  initSensors();
  ensureWifiConnected();
  readSensorsAndUpdateDisplay();
  sendUdpTelemetry();
  g_last_sensor_ms = millis();
  g_last_udp_ms = millis();
}

void loop() {
  ensureWifiConnected();
  ArduinoOTA.handle();
  pollUdpServer();

  const unsigned long now = millis();
  // Đọc cảm biến & cập nhật màn hình ST7789 mỗi 1 giây (1000 ms)
  if ((now - g_last_sensor_ms) >= 1000UL) {
    g_last_sensor_ms = now;
    readSensorsAndUpdateDisplay();
  }
  // Gửi gói UDP JSON mỗi 5 giây (g_interval_s * 1000 ms)
  if ((now - g_last_udp_ms) >= static_cast<unsigned long>(g_interval_s) * 1000UL) {
    g_last_udp_ms = now;
    sendUdpTelemetry();
  }
  delay(20);
}
