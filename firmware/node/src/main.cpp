// GreenHub - Firmware Sensor Node ESP32 (DevKit 38-pin) + Màn hình ST7789 240x240
// Phần cứng cố định:
//   - DHT11: GPIO26
//   - BH1750 (I2C): SDA = GPIO21, SCL = GPIO22
//   - Độ ẩm đất: AOUT = GPIO34 (ADC1, dùng analogRead trực tiếp)
//   - ST7789 SPI (8-pin: GND, VCC, SCL, SDA, RST, DC, CS, BL):
//       SCL -> GPIO18 (VSPI SCLK)
//       SDA -> GPIO23 (VSPI MOSI)
//       RST -> GPIO4
//       DC  -> GPIO16
//       CS  -> GPIO5
//       BL  -> GPIO17 (hoặc 3V3)
//   - LED: GPIO2
// Kết nối Wi-Fi "Greenhouse-IOT" (pass "12345678") và gửi UDP JSON mỗi 5 giây.

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

// Bảng màu RGB565 cho giao diện ST7789
constexpr uint16_t COL_BG = 0x0841;        // Nền xanh đen đậm
constexpr uint16_t COL_CARD = 0x10A3;      // Nền ô thẻ thông số
constexpr uint16_t COL_HEADER = 0x03E0;    // Xanh lá cây đậm
constexpr uint16_t COL_WHITE = 0xFFFF;     // Trắng
constexpr uint16_t COL_MUTED = 0xAD55;     // Xám nhạt
constexpr uint16_t COL_TEMP = 0xFD20;      // Cam (Nhiệt độ)
constexpr uint16_t COL_HUM = 0x05FF;       // Xanh dương sáng (Độ ẩm KK)
constexpr uint16_t COL_SOIL = 0x07E8;      // Xanh lục sáng (Độ ẩm đất)
constexpr uint16_t COL_LUX = 0xFFE0;       // Vàng (Ánh sáng)

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
unsigned long g_last_sensor_ms = 0;
unsigned long g_last_udp_ms = 0;

uint16_t g_soil_raw = 0;
uint8_t g_soil_pct = 0;
int16_t g_air_t_x100 = 0;
uint16_t g_air_rh_x100 = 0;
uint32_t g_lux = GH_LUX_NONE;

void initDisplay() {
  pinMode(TFT_BL_PIN, OUTPUT);
  digitalWrite(TFT_BL_PIN, HIGH);  // Bật đèn nền màn hình

  SPI.begin(TFT_SCLK_PIN, -1, TFT_MOSI_PIN, TFT_CS_PIN);
  // Khởi tạo ST7789 240x240 với SPI_MODE0 (chuẩn cho module 8 chân có CS)
  g_tft.init(240, 240, SPI_MODE0);
  // Hạ tốc độ SPI xuống 20 MHz để chạy ổn định trên dây cắm jumper breadboard
  g_tft.setSPISpeed(20000000);
  // Xoay màn hình 90 độ sang phải (Landscape)
  g_tft.setRotation(1);
  g_tft.fillScreen(COL_BG);

  // Thanh tiêu đề
  g_tft.fillRect(0, 0, 240, 34, COL_HEADER);
  g_tft.setTextColor(COL_WHITE, COL_HEADER);
  g_tft.setTextSize(2);
  g_tft.setCursor(10, 9);
  g_tft.print("GREENHUB NODE 1");

  // Vẽ 4 khung thẻ hiển thị: Nhiệt độ, Độ ẩm KK, Độ ẩm Đất, Ánh sáng
  // Hàng 1: Nhiệt độ (trái) & Độ ẩm KK (phải)
  g_tft.fillRoundRect(6, 42, 111, 78, 6, COL_CARD);
  g_tft.fillRoundRect(123, 42, 111, 78, 6, COL_CARD);
  // Hàng 2: Độ ẩm Đất (trái) & Ánh sáng (phải)
  g_tft.fillRoundRect(6, 126, 111, 78, 6, COL_CARD);
  g_tft.fillRoundRect(123, 126, 111, 78, 6, COL_CARD);

  g_tft.setTextSize(1);
  g_tft.setTextColor(COL_MUTED, COL_CARD);
  g_tft.setCursor(14, 50);
  g_tft.print("NHIET DO (DHT11)");
  g_tft.setCursor(131, 50);
  g_tft.print("DO AM KK (DHT11)");
  g_tft.setCursor(14, 134);
  g_tft.print("DO AM DAT (SOIL)");
  g_tft.setCursor(131, 134);
  g_tft.print("ANH SANG (BH1750)");

  // Thanh trạng thái Wi-Fi dưới cùng
  g_tft.fillRect(0, 212, 240, 28, COL_CARD);
  g_tft.setTextColor(COL_MUTED, COL_CARD);
  g_tft.setCursor(10, 222);
  g_tft.print("WiFi: Connecting...");

  g_tft_ready = true;
}

void updateDisplay(int16_t air_t_x100, uint16_t air_rh_x100, uint8_t soil_pct,
                   uint16_t soil_raw, uint32_t lux) {
  if (!g_tft_ready) return;

  char buf[32];

  // 1. Nhiệt độ (°C)
  g_tft.fillRect(12, 66, 100, 48, COL_CARD);
  g_tft.setTextColor(COL_TEMP, COL_CARD);
  g_tft.setTextSize(3);
  g_tft.setCursor(14, 72);
  snprintf(buf, sizeof(buf), "%.1f", air_t_x100 / 100.0f);
  g_tft.print(buf);
  g_tft.setTextSize(2);
  g_tft.print("C");

  // 2. Độ ẩm không khí (%)
  g_tft.fillRect(129, 66, 100, 48, COL_CARD);
  g_tft.setTextColor(COL_HUM, COL_CARD);
  g_tft.setTextSize(3);
  g_tft.setCursor(131, 72);
  snprintf(buf, sizeof(buf), "%.0f", air_rh_x100 / 100.0f);
  g_tft.print(buf);
  g_tft.setTextSize(2);
  g_tft.print("%");

  // 3. Độ ẩm đất (% + ADC raw)
  g_tft.fillRect(12, 148, 100, 52, COL_CARD);
  g_tft.setTextColor(COL_SOIL, COL_CARD);
  g_tft.setTextSize(3);
  g_tft.setCursor(14, 152);
  snprintf(buf, sizeof(buf), "%u", soil_pct);
  g_tft.print(buf);
  g_tft.setTextSize(2);
  g_tft.print("%");
  g_tft.setTextSize(1);
  g_tft.setTextColor(COL_MUTED, COL_CARD);
  g_tft.setCursor(14, 186);
  snprintf(buf, sizeof(buf), "ADC: %u", soil_raw);
  g_tft.print(buf);

  // 4. Ánh sáng (Lux)
  g_tft.fillRect(129, 148, 100, 52, COL_CARD);
  g_tft.setTextColor(COL_LUX, COL_CARD);
  g_tft.setTextSize(2);
  g_tft.setCursor(131, 156);
  if (lux == GH_LUX_NONE) {
    g_tft.print("ERR");
  } else {
    snprintf(buf, sizeof(buf), "%lu", static_cast<unsigned long>(lux));
    g_tft.print(buf);
  }
  g_tft.setTextSize(1);
  g_tft.setTextColor(COL_MUTED, COL_CARD);
  g_tft.setCursor(131, 186);
  g_tft.print("don vi: Lux");

  // 5. Thanh trạng thái Wi-Fi & IP
  g_tft.fillRect(0, 212, 240, 28, COL_CARD);
  g_tft.setTextSize(1);
  g_tft.setTextColor(COL_WHITE, COL_CARD);
  g_tft.setCursor(8, 222);
  if (WiFi.status() == WL_CONNECTED) {
    snprintf(buf, sizeof(buf), "IP: %s | Z%u", WiFi.localIP().toString().c_str(), g_zone);
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
    }
    initOta();
    return;
  }

  g_udp_started = false;
  g_ota_started = false;
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);

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

  Serial.printf("[node] Wi-Fi connected: IP=%s\n",
                WiFi.localIP().toString().c_str());
  initOta();
}

void pollIncomingCfg() {
  if (!g_udp_started) return;
  int pkt_size = g_udp.parsePacket();
  while (pkt_size > 0) {
    char buf[384];
    int len = g_udp.read(buf, (pkt_size < static_cast<int>(sizeof(buf) - 1))
                                  ? pkt_size
                                  : static_cast<int>(sizeof(buf) - 1));
    if (len > 0) {
      buf[len] = '\0';
      JsonDocument doc;
      if (deserializeJson(doc, buf, len) == DeserializationError::Ok) {
        const char* type_str = doc["type"] | "";
        if (strcmp(type_str, "cfg") == 0) {
          g_zone = doc["zone"] | g_zone;
          uint16_t dry = doc["soil_dry_raw"] | g_dry_raw;
          uint16_t wet = doc["soil_wet_raw"] | g_wet_raw;
          if (dry != wet) {
            g_dry_raw = dry;
            g_wet_raw = wet;
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

  JsonDocument doc;
  doc["type"] = "node1";
  doc["zone"] = g_zone;
  doc["air_t_x100"] = g_air_t_x100;
  doc["air_rh_x100"] = g_air_rh_x100;
  doc["soil_pct"] = g_soil_pct;
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
  pollIncomingCfg();

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
