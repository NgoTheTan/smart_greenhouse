// GreenHub - Sensor Node (khung khởi tạo, M1 sẽ hiện thực đầy đủ)
// Vòng đo (spec 4.2): bật nguồn ẩm đất -> đọc ADC median 5 mẫu -> tắt nguồn
// -> đọc AHT20 (+BH1750 ở node 1) -> đóng gói TelemetryPkt -> gửi ESP-NOW
// -> nghe CFG ~200 ms -> chờ chu kỳ kế.
#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>

#include "gh_config.h"
#include "gh_packets.h"

void setup() {
  Serial.begin(115200);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_SOIL_VCC, OUTPUT);
  digitalWrite(PIN_SOIL_VCC, LOW);

  WiFi.mode(WIFI_STA);
  Serial.printf("[node] GreenHub node fw %d.%d, MAC %s, interval %us\n", GH_FW_MAJOR,
                GH_FW_MINOR, WiFi.macAddress().c_str(), gh::DEFAULT_SAMPLE_INTERVAL_S);

  if (esp_now_init() != ESP_OK) {
    Serial.println("[node] esp_now_init failed");
  }
  // TODO(M1): quét kênh HELLO/HELLO_ACK, đọc cảm biến, gửi TelemetryPkt, nhận CfgPkt
}

void loop() {
  digitalWrite(PIN_LED, !digitalRead(PIN_LED));
  delay(gh::DEFAULT_SAMPLE_INTERVAL_S * 1000UL);
}

