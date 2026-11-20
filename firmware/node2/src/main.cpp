// GreenHub - Firmware Sensor Node 2 (ESP8266 NodeMCU / Wemos D1 Mini)
// Phần cứng:
//   - Cảm biến độ ẩm đất: AOUT -> A0
//   - LED trạng thái trên board: GPIO2 (D4, kích mức LOW)
// Tích hợp:
//   - Kết nối Wi-Fi "Greenhouse-IOT" (pass "12345678") cùng mạng với Node 1 & Gateway
//   - Xử lý xung đột A0 (TOUT) và Wi-Fi RF của ESP8266:
//       + Tắt Wi-Fi Modem Sleep (WIFI_NONE_SLEEP) để RF không hiệu chuẩn đột ngột trên kênh ADC
//       + Đọc 7 mẫu cách nhau 12 ms (với yield() cho Wi-Fi stack), loại bỏ 2 mẫu cực trị
//         (spike khi Wi-Fi phát beacon) và lấy trung bình 3 mẫu giữa trước khi quy đổi sang 12-bit.
//   - Gửi gói UDP JSON {"type":"node2","zone":2,"soil_pct":...} mỗi 5 giây
//   - Hỗ trợ nạp code không dây qua ArduinoOTA (hostname: node2.local)

#include <Arduino.h>
#include <ArduinoJson.h>
#include <ArduinoOTA.h>
#include <ESP8266WiFi.h>
#include <WiFiUdp.h>
#include <stdio.h>
#include <string.h>

#include "gh_config.h"
#include "gh_packets.h"

namespace {

constexpr uint8_t PIN_SOIL_ADC = A0;
constexpr uint8_t PIN_STATUS_LED = 2;  // LED tích hợp ESP8266 (LOW = sáng, HIGH = tắt)
constexpr uint8_t SOIL_SAMPLES = 7;

WiFiUDP g_udp;
bool g_udp_started = false;
bool g_ota_started = false;

// Trên ESP8266 với cầu phân áp thực tế tại chân A0:
// - Khi để KHÔ ngoài không khí: A0_raw10 ≈ 315 -> đặt mốc DRY = 315 (0% ẩm)
// - Khi nhúng ƯỚT (nước/đất bão hòa): điện áp cảm biến giảm còn ~45% lúc khô -> đặt mốc WET = 140 (100% ẩm)
constexpr uint16_t ESP8266_DEFAULT_DRY_RAW10 = 315;
constexpr uint16_t ESP8266_DEFAULT_WET_RAW10 = 140;

uint8_t g_zone = 2;
uint16_t g_interval_s = gh::SENSOR_MEASURE_INTERVAL_S;  // 5 giây
uint16_t g_dry_raw10 = ESP8266_DEFAULT_DRY_RAW10;
uint16_t g_wet_raw10 = ESP8266_DEFAULT_WET_RAW10;
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
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  // Tắt Modem Sleep để bộ thu phát Wi-Fi không chiếm kênh ADC (TOUT/A0) khi thức dậy định kỳ
  WiFi.setSleepMode(WIFI_NONE_SLEEP);
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
          uint16_t dry = doc["soil_dry_raw"] | 0;
          uint16_t wet = doc["soil_wet_raw"] | 0;
          if (dry != wet && dry > 0 && wet > 0) {
            // Nếu Gateway gửi ngưỡng 12-bit của ESP32 (> 1024) thì chỉ áp dụng khi đã hiệu chuẩn riêng cho ESP8266 (<= 1024)
            if (dry <= 1024 && wet <= 1024) {
              g_dry_raw10 = dry;
              g_wet_raw10 = wet;
            }
          }
        }
      }
    }
    pkt_size = g_udp.parsePacket();
  }
}

// Đọc A0 trên ESP8266 (thang 10-bit gốc 0..1024) tránh nhiễu xung RF Wi-Fi:
// - Nhường CPU (yield + delay) trước khi đo để gói Wi-Fi đang truyền kết thúc.
// - Lấy 7 mẫu cách nhau 12 ms (lệch pha với chu kỳ beacon Wi-Fi), sắp xếp và lấy trung bình
//   3 mẫu ở giữa (trimmed median).
uint16_t readSoilA0Safe10Bit() {
  uint16_t samples[SOIL_SAMPLES] = {0};

  yield();
  delay(5);

  for (uint8_t i = 0; i < SOIL_SAMPLES; ++i) {
    uint16_t raw10 = static_cast<uint16_t>(analogRead(PIN_SOIL_ADC));
    if (raw10 > 1024) raw10 = 1024;
    samples[i] = raw10;
    if (i + 1 < SOIL_SAMPLES) {
      delay(12);  // delay() trên ESP8266 tự gọi yield() cho Wi-Fi stack
    }
  }

  // Insertion sort 7 mẫu
  for (uint8_t i = 1; i < SOIL_SAMPLES; ++i) {
    uint16_t key = samples[i];
    int j = i - 1;
    while (j >= 0 && samples[j] > key) {
      samples[j + 1] = samples[j];
      --j;
    }
    samples[j + 1] = key;
  }

  // Lấy trung bình 3 mẫu trung tâm (bỏ 2 mẫu thấp nhất và 2 mẫu cao nhất do gai RF Wi-Fi)
  uint32_t center_sum =
      static_cast<uint32_t>(samples[2]) + samples[3] + samples[4];
  return static_cast<uint16_t>(center_sum / 3UL);
}

void measureAndSendUdp() {
  ensureWifiConnected();

  // Đọc A0 TRƯỚC khi phát gói UDP để tránh gai dòng TX Wi-Fi làm lệch ADC
  const uint16_t raw10 = readSoilA0Safe10Bit();
  const uint8_t soil_pct = gh::soilPct(raw10, g_dry_raw10, g_wet_raw10);

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

  Serial.printf("[node2] A0_raw10=%u (~%.2fV) -> soil_pct=%u%% | UDP JSON: %s\n",
                raw10, (raw10 * 3.2f) / 1024.0f, soil_pct, payload);

  // Nháy ngắn LED trên board ESP8266 (LOW = sáng)
  digitalWrite(PIN_STATUS_LED, LOW);
  delay(40);
  digitalWrite(PIN_STATUS_LED, HIGH);
}

}  // namespace

void setup() {
  pinMode(PIN_STATUS_LED, OUTPUT);
  digitalWrite(PIN_STATUS_LED, HIGH);  // Tắt LED

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
