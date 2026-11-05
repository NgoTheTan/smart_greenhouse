// GreenHub - Gateway (khung khởi tạo, M1 sẽ hiện thực đầy đủ)
// Luồng (spec 4.3): captive portal -> Wi-Fi -> NTP -> MQTT TLS (LWT status)
// ESP-NOW -> telemetry; cmd/# -> relay + ack; cfg retained -> NVS -> CfgPkt;
// heartbeat status 30 s; failsafe cục bộ khi mất MQTT.
#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>

#include "gh_config.h"
#include "gh_packets.h"

static const uint8_t RELAY_PINS[] = {PIN_RELAY_PUMP1, PIN_RELAY_PUMP2, PIN_RELAY_FAN,
                                     PIN_RELAY_MIST};

static void initRelaysOff() {
  // Relay kích mức thấp: ghi HIGH TRƯỚC pinMode để không nháy relay khi boot
  for (uint8_t pin : RELAY_PINS) {
    digitalWrite(pin, HIGH);
    pinMode(pin, OUTPUT);
  }
}

void setup() {
  initRelaysOff();
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_BUZZER, LOW);
  pinMode(PIN_LED, OUTPUT);

  Serial.begin(115200);
  WiFi.mode(WIFI_STA);
  Serial.printf("[gw] GreenHub gateway fw %d.%d, MAC %s\n", GH_FW_MAJOR, GH_FW_MINOR,
                WiFi.macAddress().c_str());
  // TODO(M1): WiFiManager, NTP, MQTT TLS, ESP-NOW, cmd/ack, cfg, failsafe
}

void loop() {
  digitalWrite(PIN_LED, !digitalRead(PIN_LED));
  delay(1000);
}

