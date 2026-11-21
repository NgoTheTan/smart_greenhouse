// GreenHub - Firmware Sensor Node 2 (ESP32-C3 Super Mini)
// Phần cứng:
//   - Cảm biến độ ẩm đất: AOUT -> GPIO0 (ADC1_CH0, 12-bit 0..4095)
//   - LED trạng thái trên board ESP32-C3 Super Mini: GPIO8 (kích mức LOW)
// Tích hợp:
//   - Kết nối Wi-Fi "Greenhouse-IOT" (pass "12345678") cùng mạng với Node 1 & Gateway
//   - Đọc ADC1 12-bit trên GPIO0 (không xung đột Wi-Fi RF như ESP8266), lấy median 5 mẫu
//   - Gửi gói UDP JSON {"type":"node2","zone":2,"soil_pct":...} mỗi 5 giây
//   - Hỗ trợ nạp code không dây qua ArduinoOTA (hostname: node2.local)

#include <Arduino.h>
#include <ArduinoJson.h>
#include <ArduinoOTA.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <stdio.h>
#include <string.h>

#include "gh_config.h"
#include "gh_packets.h"

namespace {

#ifdef PIN_SOIL_AOUT
constexpr uint8_t PIN_SOIL_ADC = PIN_SOIL_AOUT;
#else
constexpr uint8_t PIN_SOIL_ADC = 0;  // GPIO0 (ADC1_CH0 trên ESP32-C3)
#endif

#ifdef PIN_LED
constexpr uint8_t PIN_STATUS_LED = PIN_LED;
#else
constexpr uint8_t PIN_STATUS_LED = 8;  // LED tích hợp ESP32-C3 Super Mini (LOW = sáng, HIGH = tắt)
#endif

constexpr uint8_t SOIL_SAMPLES = 5;

WiFiUDP g_udp;
bool g_udp_started = false;
bool g_ota_started = false;

// Ngưỡng hiệu chuẩn ADC 12-bit trên ESP32-C3 (GPIO0, ADC_11db, Vmax ~ 2.5V):
// - Khi để KHÔ ngoài không khí (~1.9V-2.1V): GPIO0_raw12 ≈ 3100 -> DRY = 3100 (0% ẩm)
// - Khi nhúng ƯỚT (nước/đất bão hòa ~0.9V-1.0V): GPIO0_raw12 ≈ 1400 -> WET = 1400 (100% ẩm)
// (Khi đất ẩm vừa phải GPIO0_raw12 ≈ 1700-1800 -> ~75-82% ẩm)
constexpr uint16_t ESP32C3_DEFAULT_DRY_RAW = 3100;
constexpr uint16_t ESP32C3_DEFAULT_WET_RAW = 1400;

uint8_t g_zone = 2;
uint16_t g_interval_s = gh::SENSOR_MEASURE_INTERVAL_S;  // 5 giây
uint16_t g_dry_raw = ESP32C3_DEFAULT_DRY_RAW;
uint16_t g_wet_raw = ESP32C3_DEFAULT_WET_RAW;
unsigned long g_last_udp_ms = 0;

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
  ArduinoOTA.setHostname("node2");
  ArduinoOTA.onStart([]() {
    Serial.println("[node2] OTA Update Start");
  });
  ArduinoOTA.onEnd([]() {
    Serial.println("\n[node2] OTA Update End");
  });
  ArduinoOTA.onError([](ota_error_t error) {
    Serial.printf("[node2] OTA Error[%u]\n", error);
  });
  ArduinoOTA.begin();
  g_ota_started = true;
  Serial.println("[node2] ArduinoOTA ready (hostname: node2.local)");
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
    Serial.printf("[node2] Connecting Wi-Fi \"%s\"...\n", gh::WIFI_SSID);
    WiFi.begin(gh::WIFI_SSID, gh::WIFI_PASS);
    unsigned long start_ms = millis();
    while (WiFi.status() != WL_CONNECTED && (millis() - start_ms) < 10000UL) {
      digitalWrite(PIN_STATUS_LED, !digitalRead(PIN_STATUS_LED));
      delay(200);
    }
  }
  digitalWrite(PIN_STATUS_LED, HIGH);  // Tắt LED (active-low)
  g_udp_started = (g_udp.begin(gh::UDP_PORT) != 0);

  Serial.printf("[node2] Wi-Fi connected: IP=%s\n",
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
          if (dry != wet && dry > 0 && wet > 0) {
            g_dry_raw = dry;
            g_wet_raw = wet;
          }
        }
      }
    }
    pkt_size = g_udp.parsePacket();
  }
}

uint16_t readSoilRaw() {
  uint16_t samples[SOIL_SAMPLES] = {0};
  for (uint8_t i = 0; i < SOIL_SAMPLES; ++i) {
    samples[i] = static_cast<uint16_t>(analogRead(PIN_SOIL_ADC));
    if (i + 1 < SOIL_SAMPLES) {
      delay(2);
    }
  }

  // Insertion sort 5 mẫu và lấy median
  for (uint8_t i = 1; i < SOIL_SAMPLES; ++i) {
    uint16_t key = samples[i];
    int j = i - 1;
    while (j >= 0 && samples[j] > key) {
      samples[j + 1] = samples[j];
      --j;
    }
    samples[j + 1] = key;
  }
  return samples[SOIL_SAMPLES / 2];
}

void measureAndSendUdp() {
  ensureWifiConnected();

  const uint16_t soil_raw = readSoilRaw();
  const uint8_t soil_pct = gh::soilPct(soil_raw, g_dry_raw, g_wet_raw);

  JsonDocument doc;
  doc["type"] = "node2";
  doc["zone"] = g_zone;
  doc["soil_pct"] = soil_pct;

  char payload[192];
  const size_t len = serializeJson(doc, payload, sizeof(payload));
  const IPAddress bcast = getBroadcastIp();
  g_udp.beginPacket(bcast, gh::UDP_PORT);
  g_udp.write(reinterpret_cast<const uint8_t*>(payload), len);
  g_udp.endPacket();

  Serial.printf("[node2] GPIO0_raw12=%u (dry=%u, wet=%u) -> soil_pct=%u%% | UDP JSON: %s\n",
                soil_raw, g_dry_raw, g_wet_raw, soil_pct, payload);

  // Nháy ngắn LED trên board ESP32-C3 Super Mini (LOW = sáng)
  digitalWrite(PIN_STATUS_LED, LOW);
  delay(40);
  digitalWrite(PIN_STATUS_LED, HIGH);
}

}  // namespace

void setup() {
  pinMode(PIN_STATUS_LED, OUTPUT);
  digitalWrite(PIN_STATUS_LED, HIGH);  // Tắt LED
  pinMode(PIN_SOIL_ADC, INPUT);
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_SOIL_ADC, ADC_11db);

  Serial.begin(115200);
  ensureWifiConnected();
  measureAndSendUdp();
  g_last_udp_ms = millis();
}

void loop() {
  ensureWifiConnected();
  ArduinoOTA.handle();
  pollIncomingCfg();

  const unsigned long now = millis();
  if ((now - g_last_udp_ms) >= static_cast<unsigned long>(g_interval_s) * 1000UL) {
    g_last_udp_ms = now;
    measureAndSendUdp();
  }
  delay(20);
}
