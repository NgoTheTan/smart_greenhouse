// GreenHub - Firmware Sensor Node (ESP32 & ESP8266)
// Đặc tả: firmware/node/FEATURE_SENSOR_NODE.md
// Hỗ trợ:
//   - ESP32: AHT20 (mặc định), SHT30 (-DUSE_SHT30), DHT11 (-DUSE_DHT11), BH1750 (tự phát hiện)
//   - ESP8266: cảm biến ẩm đất v1.2 trên A0 (-DNO_AIR_SENSOR -DNO_LIGHT_SENSOR)

#include <Arduino.h>
#include <math.h>
#include <string.h>

#ifdef ESP8266
#include <EEPROM.h>
#include <ESP8266WiFi.h>
extern "C" {
#include <espnow.h>
#include <user_interface.h>
}
#else
#include <Preferences.h>
#include <WiFi.h>
#include <esp_arduino_version.h>
#include <esp_idf_version.h>
#include <esp_now.h>
#include <esp_sleep.h>
#include <esp_wifi.h>
#endif

#if !defined(NO_LIGHT_SENSOR) || (!defined(NO_AIR_SENSOR) && !defined(USE_DHT11))
#include <Wire.h>
#endif

#ifndef NO_LIGHT_SENSOR
#include <BH1750.h>
#endif

#if defined(NO_AIR_SENSOR)
// Node không gắn cảm biến nhiệt-ẩm (vd ESP8266 Zone 2 dùng chung DHT11 qua Gateway)
#elif defined(USE_DHT11)
#include <DHT.h>
#elif defined(USE_SHT30)
#include <Adafruit_SHT31.h>
#else
#include <Adafruit_AHTX0.h>
#endif

#include "gh_config.h"
#include "gh_packets.h"

namespace {

constexpr uint8_t BROADCAST_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
constexpr uint8_t SOIL_SAMPLES = 5;

#ifndef NO_LIGHT_SENSOR
constexpr uint8_t BH1750_ADDR = 0x23;
#endif

#ifdef USE_SHT30
constexpr uint8_t SHT30_ADDR = 0x44;
#endif

#ifdef ESP8266
#define GH_RTC_ATTR
#define GH_ENTER_CRIT() noInterrupts()
#define GH_EXIT_CRIT() interrupts()
#define GH_ENTER_CRIT_ISR() noInterrupts()
#define GH_EXIT_CRIT_ISR() interrupts()

constexpr uint32_t EEPROM_MAGIC = 0x47484E31u;  // "GHN1"
struct EepromNodeCfg {
  uint32_t magic;
  uint8_t gw_mac[6];
  uint8_t wifi_ch;
  uint8_t zone;
  uint16_t interval_s;
  uint16_t dry_raw;
  uint16_t wet_raw;
  uint16_t cfg_ver;
  uint8_t checksum;
};
#else
#define GH_RTC_ATTR RTC_DATA_ATTR
constexpr char NVS_NAMESPACE[] = "gh_node";
portMUX_TYPE g_rx_mux = portMUX_INITIALIZER_UNLOCKED;
#define GH_ENTER_CRIT() portENTER_CRITICAL(&g_rx_mux)
#define GH_EXIT_CRIT() portEXIT_CRITICAL(&g_rx_mux)
#define GH_ENTER_CRIT_ISR() portENTER_CRITICAL_ISR(&g_rx_mux)
#define GH_EXIT_CRIT_ISR() portEXIT_CRITICAL_ISR(&g_rx_mux)
#endif

// Trạng thái giữ qua deep sleep (trên ESP32 lưu trong RTC slow memory)
GH_RTC_ATTR bool rtc_initialized = false;
GH_RTC_ATTR uint8_t rtc_gw_mac[6] = {0, 0, 0, 0, 0, 0};
GH_RTC_ATTR uint8_t rtc_wifi_ch = 0;
GH_RTC_ATTR uint8_t rtc_zone = 0;
GH_RTC_ATTR uint16_t rtc_interval_s = gh::SENSOR_MEASURE_INTERVAL_S;
GH_RTC_ATTR uint16_t rtc_dry_raw = gh::DEFAULT_SOIL_DRY_RAW;
GH_RTC_ATTR uint16_t rtc_wet_raw = gh::DEFAULT_SOIL_WET_RAW;
GH_RTC_ATTR uint16_t rtc_cfg_ver = 0;
GH_RTC_ATTR uint16_t rtc_seq = 0;
GH_RTC_ATTR uint8_t rtc_send_fail_count = 0;

// Đồng bộ dữ liệu nhận từ callback Wi-Fi/ESP-NOW về vòng lặp chính
volatile bool g_has_hello_ack = false;
HelloAckPkt g_rx_hello_ack = {};
uint8_t g_rx_hello_mac[6] = {0};

volatile bool g_has_cfg = false;
CfgPkt g_rx_cfg = {};

volatile bool g_tx_done = false;
volatile bool g_tx_ok = false;

// Đối tượng cảm biến
#if defined(NO_AIR_SENSOR)
// Không khởi tạo cảm biến nhiệt-ẩm
#elif defined(USE_DHT11)
#ifndef PIN_DHT
#define PIN_DHT 4
#endif
DHT g_dht(PIN_DHT, DHT11);
#elif defined(USE_SHT30)
Adafruit_SHT31 g_sht31;
bool g_air_init_ok = false;
#else
Adafruit_AHTX0 g_aht;
bool g_air_init_ok = false;
#endif

#ifndef NO_LIGHT_SENSOR
BH1750 g_bh1750;
bool g_has_bh1750 = false;
bool g_bh_init_ok = false;
unsigned long g_bh_init_ms = 0;
#endif

bool isValidMac(const uint8_t mac[6]) {
  uint8_t or_all = 0;
  uint8_t and_all = 0xFF;
  for (int i = 0; i < 6; ++i) {
    or_all |= mac[i];
    and_all &= mac[i];
  }
  return or_all != 0x00 && and_all != 0xFF;
}

bool isValidChannel(uint8_t ch) {
  return ch >= gh::WIFI_CH_MIN && ch <= gh::WIFI_CH_MAX;
}

void formatMac(const uint8_t mac[6], char* out, size_t out_len) {
  snprintf(out, out_len, "%02X:%02X:%02X:%02X:%02X:%02X", mac[0], mac[1], mac[2],
           mac[3], mac[4], mac[5]);
}

void blinkLed(uint8_t times, uint16_t on_ms, uint16_t off_ms) {
  for (uint8_t i = 0; i < times; ++i) {
    digitalWrite(PIN_LED, HIGH);
    delay(on_ms);
    digitalWrite(PIN_LED, LOW);
    if (i + 1 < times) {
      delay(off_ms);
    }
  }
}

#ifdef ESP8266
uint8_t calcEepromChecksum(const EepromNodeCfg& cfg) {
  const uint8_t* bytes = reinterpret_cast<const uint8_t*>(&cfg);
  uint8_t sum = 0;
  for (size_t i = 0; i < offsetof(EepromNodeCfg, checksum); ++i) {
    sum ^= bytes[i];
  }
  return sum;
}

void loadConfigFromNvs() {
  if (rtc_initialized) return;
  EEPROM.begin(64);
  EepromNodeCfg cfg = {};
  EEPROM.get(0, cfg);
  if (cfg.magic == EEPROM_MAGIC && cfg.checksum == calcEepromChecksum(cfg)) {
    memcpy(rtc_gw_mac, cfg.gw_mac, 6);
    rtc_wifi_ch = cfg.wifi_ch;
    rtc_zone = cfg.zone;
    rtc_interval_s = (cfg.interval_s > 0) ? cfg.interval_s : gh::SENSOR_MEASURE_INTERVAL_S;
#ifdef DEMO_MODE
    if (rtc_interval_s > gh::SENSOR_MEASURE_INTERVAL_S) {
      rtc_interval_s = gh::SENSOR_MEASURE_INTERVAL_S;
    }
#endif
    rtc_dry_raw = (cfg.dry_raw != cfg.wet_raw) ? cfg.dry_raw : gh::DEFAULT_SOIL_DRY_RAW;
    rtc_wet_raw = (cfg.dry_raw != cfg.wet_raw) ? cfg.wet_raw : gh::DEFAULT_SOIL_WET_RAW;
    rtc_cfg_ver = cfg.cfg_ver;
  }
  rtc_initialized = true;
}

void saveConfigIfChanged() {
  EepromNodeCfg current = {};
  EEPROM.get(0, current);

  EepromNodeCfg next = {};
  next.magic = EEPROM_MAGIC;
  memcpy(next.gw_mac, rtc_gw_mac, 6);
  next.wifi_ch = rtc_wifi_ch;
  next.zone = rtc_zone;
  next.interval_s = rtc_interval_s;
  next.dry_raw = rtc_dry_raw;
  next.wet_raw = rtc_wet_raw;
  next.cfg_ver = rtc_cfg_ver;
  next.checksum = calcEepromChecksum(next);

  if (memcmp(&current, &next, sizeof(EepromNodeCfg)) != 0) {
    EEPROM.put(0, next);
    EEPROM.commit();
  }
}
#else
void loadConfigFromNvs() {
  if (rtc_initialized) {
    return;
  }
  Preferences prefs;
  if (prefs.begin(NVS_NAMESPACE, true)) {
    if (prefs.getBytesLength("gw_mac") == 6) {
      prefs.getBytes("gw_mac", rtc_gw_mac, 6);
    }
    rtc_wifi_ch = prefs.getUChar("wifi_ch", 0);
    rtc_zone = prefs.getUChar("zone", 0);
    rtc_interval_s = prefs.getUShort("interval_s", gh::SENSOR_MEASURE_INTERVAL_S);
    if (rtc_interval_s == 0) {
      rtc_interval_s = gh::SENSOR_MEASURE_INTERVAL_S;
    }
#ifdef DEMO_MODE
    if (rtc_interval_s > gh::SENSOR_MEASURE_INTERVAL_S) {
      rtc_interval_s = gh::SENSOR_MEASURE_INTERVAL_S;
    }
#endif
    rtc_dry_raw = prefs.getUShort("dry_raw", gh::DEFAULT_SOIL_DRY_RAW);
    rtc_wet_raw = prefs.getUShort("wet_raw", gh::DEFAULT_SOIL_WET_RAW);
    rtc_cfg_ver = prefs.getUShort("cfg_ver", 0);
    prefs.end();
  }
  rtc_initialized = true;
}

void saveConfigIfChanged() {
  Preferences prefs;
  if (!prefs.begin(NVS_NAMESPACE, false)) {
    return;
  }

  uint8_t stored_mac[6] = {0};
  bool mac_changed = (prefs.getBytesLength("gw_mac") != 6);
  if (!mac_changed) {
    prefs.getBytes("gw_mac", stored_mac, 6);
    mac_changed = (memcmp(stored_mac, rtc_gw_mac, 6) != 0);
  }
  if (mac_changed && isValidMac(rtc_gw_mac)) {
    prefs.putBytes("gw_mac", rtc_gw_mac, 6);
  }

  if (prefs.getUChar("wifi_ch", 0) != rtc_wifi_ch) {
    prefs.putUChar("wifi_ch", rtc_wifi_ch);
  }
  if (prefs.getUChar("zone", 0) != rtc_zone) {
    prefs.putUChar("zone", rtc_zone);
  }
  if (prefs.getUShort("interval_s", 0) != rtc_interval_s) {
    prefs.putUShort("interval_s", rtc_interval_s);
  }
  if (prefs.getUShort("dry_raw", 0) != rtc_dry_raw) {
    prefs.putUShort("dry_raw", rtc_dry_raw);
  }
  if (prefs.getUShort("wet_raw", 0) != rtc_wet_raw) {
    prefs.putUShort("wet_raw", rtc_wet_raw);
  }
  if (prefs.getUShort("cfg_ver", 0) != rtc_cfg_ver) {
    prefs.putUShort("cfg_ver", rtc_cfg_ver);
  }
  prefs.end();
}
#endif

void handleEspNowRecv(const uint8_t* mac, const uint8_t* data, int len) {
  if (!mac || !data || len < 1) {
    return;
  }
  const uint8_t pkt_type = data[0];
  if (pkt_type == PKT_HELLO_ACK && len == static_cast<int>(sizeof(HelloAckPkt))) {
    GH_ENTER_CRIT_ISR();
    memcpy(&g_rx_hello_ack, data, sizeof(HelloAckPkt));
    memcpy(g_rx_hello_mac, mac, 6);
    g_has_hello_ack = true;
    GH_EXIT_CRIT_ISR();
  } else if (pkt_type == PKT_CFG && len == static_cast<int>(sizeof(CfgPkt))) {
    GH_ENTER_CRIT_ISR();
    memcpy(&g_rx_cfg, data, sizeof(CfgPkt));
    g_has_cfg = true;
    GH_EXIT_CRIT_ISR();
  }
}

void setRadioChannel(uint8_t ch) {
#ifdef ESP8266
  wifi_set_channel(ch);
#else
  esp_wifi_set_channel(ch, WIFI_SECOND_CHAN_NONE);
#endif
}

bool ensurePeer(const uint8_t mac[6], uint8_t channel) {
#ifdef ESP8266
  uint8_t* m = const_cast<uint8_t*>(mac);
  if (esp_now_is_peer_exist(m) > 0) {
    esp_now_del_peer(m);
  }
  return esp_now_add_peer(m, ESP_NOW_ROLE_COMBO, channel, nullptr, 0) == 0;
#else
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, mac, 6);
  peer.channel = channel;
  peer.encrypt = false;
  if (esp_now_is_peer_exist(mac)) {
    return esp_now_mod_peer(&peer) == ESP_OK;
  }
  return esp_now_add_peer(&peer) == ESP_OK;
#endif
}

#ifdef ESP8266
void onDataRecv8266(uint8_t* mac, uint8_t* data, uint8_t len) {
  handleEspNowRecv(mac, data, static_cast<int>(len));
}
void onDataSent8266(uint8_t* mac, uint8_t status) {
  (void)mac;
  g_tx_ok = (status == 0);
  g_tx_done = true;
}
#else
void handleEspNowSent(esp_now_send_status_t status) {
  g_tx_ok = (status == ESP_NOW_SEND_SUCCESS);
  g_tx_done = true;
}

#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
void onDataRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
  if (!info) return;
  handleEspNowRecv(info->src_addr, data, len);
}
#if ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(5, 5, 0)
void onDataSent(const esp_now_send_info_t* tx_info, esp_now_send_status_t status) {
  (void)tx_info;
  handleEspNowSent(status);
}
#else
void onDataSent(const uint8_t* mac, esp_now_send_status_t status) {
  (void)mac;
  handleEspNowSent(status);
}
#endif
#else
void onDataRecv(const uint8_t* mac, const uint8_t* data, int len) {
  handleEspNowRecv(mac, data, len);
}
void onDataSent(const uint8_t* mac, esp_now_send_status_t status) {
  (void)mac;
  handleEspNowSent(status);
}
#endif
#endif

bool initEspNow() {
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  delay(10);

#ifdef ESP8266
  if (esp_now_init() != 0) {
    Serial.println("[node] esp_now_init failed");
    return false;
  }
  esp_now_set_self_role(ESP_NOW_ROLE_COMBO);
  esp_now_register_recv_cb(onDataRecv8266);
  esp_now_register_send_cb(onDataSent8266);
#else
  if (esp_now_init() != ESP_OK) {
    Serial.println("[node] esp_now_init failed");
    return false;
  }
  esp_now_register_recv_cb(onDataRecv);
  esp_now_register_send_cb(onDataSent);
#endif

  ensurePeer(BROADCAST_MAC, 0);
  if (isValidChannel(rtc_wifi_ch) && isValidMac(rtc_gw_mac)) {
    setRadioChannel(rtc_wifi_ch);
    ensurePeer(rtc_gw_mac, rtc_wifi_ch);
  }
  return true;
}

bool sendPacketSync(const uint8_t* dst_mac, const void* pkt, size_t size) {
  g_tx_done = false;
  g_tx_ok = false;
#ifdef ESP8266
  const int res = esp_now_send(
      const_cast<uint8_t*>(dst_mac),
      const_cast<uint8_t*>(reinterpret_cast<const uint8_t*>(pkt)),
      static_cast<int>(size));
  if (res != 0) {
    return false;
  }
#else
  if (esp_now_send(dst_mac, reinterpret_cast<const uint8_t*>(pkt), size) != ESP_OK) {
    return false;
  }
#endif
  const unsigned long start_ms = millis();
  while (!g_tx_done && (millis() - start_ms) < 100UL) {
    delay(2);
  }
  return g_tx_done && g_tx_ok;
}

bool processPendingCfg() {
  CfgPkt cfg = {};
  bool has_new = false;
  GH_ENTER_CRIT();
  if (g_has_cfg) {
    cfg = g_rx_cfg;
    g_has_cfg = false;
    has_new = true;
  }
  GH_EXIT_CRIT();

  if (!has_new || cfg.type != PKT_CFG) {
    return false;
  }

  bool changed = false;
  if (cfg.zone != rtc_zone) {
    rtc_zone = cfg.zone;
    changed = true;
  }
  if (cfg.sample_interval_s > 0) {
    uint16_t target_interval = cfg.sample_interval_s;
#ifdef DEMO_MODE
    if (target_interval > gh::SENSOR_MEASURE_INTERVAL_S) {
      target_interval = gh::SENSOR_MEASURE_INTERVAL_S;
    }
#endif
    if (target_interval != rtc_interval_s) {
      rtc_interval_s = target_interval;
      changed = true;
    }
  }
  if (cfg.soil_dry_raw != cfg.soil_wet_raw) {
    if (cfg.soil_dry_raw != rtc_dry_raw) {
      rtc_dry_raw = cfg.soil_dry_raw;
      changed = true;
    }
    if (cfg.soil_wet_raw != rtc_wet_raw) {
      rtc_wet_raw = cfg.soil_wet_raw;
      changed = true;
    }
  }
  if (cfg.cfg_version != rtc_cfg_ver) {
    rtc_cfg_ver = cfg.cfg_version;
    changed = true;
  }

  if (changed) {
    saveConfigIfChanged();
    Serial.printf("[node] CfgPkt applied: zone=%u interval=%us dry=%u wet=%u ver=%u\n",
                  rtc_zone, rtc_interval_s, rtc_dry_raw, rtc_wet_raw, rtc_cfg_ver);
  }
  return true;
}

void waitCfgWindow(uint32_t window_ms) {
  const unsigned long start_ms = millis();
  while ((millis() - start_ms) < window_ms) {
    processPendingCfg();
    delay(5);
  }
}

bool scanForGatewayOnce() {
  Serial.println("[node] Scanning Wi-Fi channels 1..13 for gateway...");
  ensurePeer(BROADCAST_MAC, 0);

  GH_ENTER_CRIT();
  g_has_hello_ack = false;
  GH_EXIT_CRIT();

  HelloPkt hello = {PKT_HELLO, GH_FW_MAJOR, GH_FW_MINOR};

  for (uint8_t ch = gh::WIFI_CH_MIN; ch <= gh::WIFI_CH_MAX; ++ch) {
    setRadioChannel(ch);
    sendPacketSync(BROADCAST_MAC, &hello, sizeof(hello));

    const unsigned long start_ms = millis();
    while ((millis() - start_ms) < gh::SCAN_CH_WAIT_MS) {
      bool got_ack = false;
      HelloAckPkt ack = {};
      uint8_t src_mac[6] = {0};

      GH_ENTER_CRIT();
      if (g_has_hello_ack) {
        ack = g_rx_hello_ack;
        memcpy(src_mac, g_rx_hello_mac, 6);
        g_has_hello_ack = false;
        got_ack = true;
      }
      GH_EXIT_CRIT();

      if (got_ack && ack.type == PKT_HELLO_ACK && isValidChannel(ack.channel) &&
          isValidMac(src_mac)) {
        rtc_wifi_ch = ack.channel;
        memcpy(rtc_gw_mac, src_mac, 6);
        rtc_send_fail_count = 0;

        setRadioChannel(rtc_wifi_ch);
        ensurePeer(rtc_gw_mac, rtc_wifi_ch);
        saveConfigIfChanged();

        char mac_str[18];
        formatMac(rtc_gw_mac, mac_str, sizeof(mac_str));
        Serial.printf("[node] Gateway found at ch=%u MAC=%s\n", rtc_wifi_ch, mac_str);

        waitCfgWindow(gh::CFG_RX_WINDOW_MS);
        return true;
      }
      processPendingCfg();
      delay(5);
    }
  }
  return false;
}

void ensureGatewayBound() {
  while (!isValidChannel(rtc_wifi_ch) || !isValidMac(rtc_gw_mac)) {
    blinkLed(2, 40, 60);
    if (!scanForGatewayOnce()) {
      Serial.println("[node] Gateway not found, retry in 2s...");
      delay(2000);
    }
  }
}

void initSensors() {
#if !defined(NO_LIGHT_SENSOR) || (!defined(NO_AIR_SENSOR) && !defined(USE_DHT11))
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
#endif

#if defined(NO_AIR_SENSOR)
  // Không có cảm biến nhiệt-ẩm
#elif defined(USE_DHT11)
  g_dht.begin();
#elif defined(USE_SHT30)
  g_air_init_ok = g_sht31.begin(SHT30_ADDR);
  if (!g_air_init_ok) {
    Serial.println("[node] SHT30 init failed");
  }
#else
  g_air_init_ok = g_aht.begin(&Wire);
  if (!g_air_init_ok) {
    Serial.println("[node] AHT20 init failed");
  }
#endif

#ifndef NO_LIGHT_SENSOR
  // Tự phát hiện BH1750 trên bus I2C (Node không gắn BH1750 không báo lỗi)
  Wire.beginTransmission(BH1750_ADDR);
  if (Wire.endTransmission() == 0) {
    g_has_bh1750 = true;
    g_bh_init_ok = g_bh1750.begin(BH1750::CONTINUOUS_HIGH_RES_MODE, BH1750_ADDR, &Wire);
    g_bh_init_ms = millis();
    if (!g_bh_init_ok) {
      Serial.println("[node] BH1750 detected but begin() failed");
    }
  } else {
    g_has_bh1750 = false;
    g_bh_init_ok = false;
  }
#endif
}

uint16_t readSoilMedianRaw() {
  uint16_t samples[SOIL_SAMPLES] = {0};

  // Bật nguồn ẩm đất ngắn hạn để tránh ăn mòn điện hóa
  digitalWrite(PIN_SOIL_VCC, HIGH);
  delay(50);

  for (uint8_t i = 0; i < SOIL_SAMPLES; ++i) {
    uint16_t raw = static_cast<uint16_t>(analogRead(PIN_SOIL_AOUT));
#ifdef ESP8266
    // Quy đổi ADC 10-bit (0..1023) của ESP8266 sang thang 12-bit (0..4095)
    raw = static_cast<uint16_t>((static_cast<uint32_t>(raw) * 4095UL) / 1023UL);
#endif
    samples[i] = raw;
    if (i + 1 < SOIL_SAMPLES) {
      delay(4);
    }
  }
  digitalWrite(PIN_SOIL_VCC, LOW);

  // Insertion sort 5 phần tử để lấy median
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

void readAirSensor(int16_t* out_temp_x100, uint16_t* out_rh_x100, uint8_t* flags) {
#if defined(NO_AIR_SENSOR)
  (void)flags;
  *out_temp_x100 = GH_AIR_T_NONE;
  *out_rh_x100 = GH_AIR_RH_NONE;
  return;
#else
  float t = NAN;
  float rh = NAN;
  bool ok = false;

#if defined(USE_DHT11)
  t = g_dht.readTemperature();
  rh = g_dht.readHumidity();
  if (isnan(t) || isnan(rh)) {
    delay(250);
    t = g_dht.readTemperature();
    rh = g_dht.readHumidity();
  }
  ok = !isnan(t) && !isnan(rh);
#elif defined(USE_SHT30)
  if (!g_air_init_ok) {
    g_air_init_ok = g_sht31.begin(SHT30_ADDR);
  }
  if (g_air_init_ok) {
    t = g_sht31.readTemperature();
    rh = g_sht31.readHumidity();
    ok = !isnan(t) && !isnan(rh);
  }
#else
  if (!g_air_init_ok) {
    g_air_init_ok = g_aht.begin(&Wire);
  }
  if (g_air_init_ok) {
    sensors_event_t humidity_ev;
    sensors_event_t temp_ev;
    if (g_aht.getEvent(&humidity_ev, &temp_ev)) {
      t = temp_ev.temperature;
      rh = humidity_ev.relative_humidity;
      ok = !isnan(t) && !isnan(rh);
    }
  }
#endif

  if (!ok || t < -40.0f || t > 85.0f || rh < 0.0f || rh > 100.0f) {
    *flags |= FLAG_AHT_ERR;
    *out_temp_x100 = 0;
    *out_rh_x100 = 0;
    return;
  }
  *out_temp_x100 = static_cast<int16_t>(lroundf(t * 100.0f));
  *out_rh_x100 = static_cast<uint16_t>(lroundf(rh * 100.0f));
#endif
}

uint32_t readLightLux(uint8_t* flags) {
#ifdef NO_LIGHT_SENSOR
  (void)flags;
  return GH_LUX_NONE;
#else
  if (!g_has_bh1750) {
    return GH_LUX_NONE;
  }
  if (!g_bh_init_ok) {
    g_bh_init_ok = g_bh1750.begin(BH1750::CONTINUOUS_HIGH_RES_MODE, BH1750_ADDR, &Wire);
    g_bh_init_ms = millis();
  }
  if (!g_bh_init_ok) {
    *flags |= FLAG_BH_ERR;
    return GH_LUX_NONE;
  }
  const unsigned long elapsed = millis() - g_bh_init_ms;
  if (elapsed < 180UL) {
    delay(180UL - elapsed);
  }

  float lux_val = g_bh1750.readLightLevel();
  if (isnan(lux_val) || lux_val < 0.0f) {
    *flags |= FLAG_BH_ERR;
    return GH_LUX_NONE;
  }
  if (lux_val > static_cast<float>(gh::LUX_MAX)) {
    lux_val = static_cast<float>(gh::LUX_MAX);
  }
  return static_cast<uint32_t>(lroundf(lux_val));
#endif
}

void trackSendResult(bool ok) {
  if (ok) {
    rtc_send_fail_count = 0;
  } else {
    if (rtc_send_fail_count < 255) {
      ++rtc_send_fail_count;
    }
    Serial.printf("[node] ESP-NOW send fail (%u/%u)\n", rtc_send_fail_count,
                  gh::SEND_FAIL_RESCAN);
    if (rtc_send_fail_count >= gh::SEND_FAIL_RESCAN) {
      rtc_wifi_ch = 0;
      rtc_send_fail_count = 0;
      ensureGatewayBound();
    }
  }
}

void sendUnpairedHello() {
  HelloPkt hello = {PKT_HELLO, GH_FW_MAJOR, GH_FW_MINOR};
  const bool ok = sendPacketSync(rtc_gw_mac, &hello, sizeof(hello));
  trackSendResult(ok);
  waitCfgWindow(gh::CFG_RX_WINDOW_MS);
  blinkLed(2, 40, 60);
}

void measureAndSendTelemetry() {
  uint8_t flags = 0;

  // Bước 1: Đo ẩm đất
  const uint16_t soil_raw = readSoilMedianRaw();
  if (soil_raw == 0 || soil_raw >= 4095) {
    flags |= FLAG_SOIL_ERR;
  }
  const uint8_t soil_pct = gh::soilPct(soil_raw, rtc_dry_raw, rtc_wet_raw);

  // Bước 2: Đọc nhiệt-ẩm & ánh sáng
  int16_t air_t_x100 = 0;
  uint16_t air_rh_x100 = 0;
  readAirSensor(&air_t_x100, &air_rh_x100, &flags);
  const uint32_t lux = readLightLux(&flags);

  // Bước 3: Đóng gói & gửi TelemetryPkt
  ++rtc_seq;
  TelemetryPkt pkt = {};
  pkt.type = PKT_TELEMETRY;
  pkt.zone = rtc_zone;
  pkt.seq = rtc_seq;
  pkt.air_t_x100 = air_t_x100;
  pkt.air_rh_x100 = air_rh_x100;
  pkt.soil_raw = soil_raw;
  pkt.soil_pct = soil_pct;
  pkt.flags = flags;
  pkt.lux = lux;
  pkt.vbat_mv = 0;
  pkt.fw_major = GH_FW_MAJOR;
  pkt.fw_minor = GH_FW_MINOR;

  const bool sent_ok = sendPacketSync(rtc_gw_mac, &pkt, sizeof(pkt));
  Serial.printf("[node] seq=%u zone=%u T=%.2fC RH=%.2f%% soil=%u%%(%u) lux=%lu flags=0x%02X %s\n",
                pkt.seq, pkt.zone,
                (air_t_x100 == GH_AIR_T_NONE) ? -999.0f : (air_t_x100 / 100.0f),
                (air_rh_x100 == GH_AIR_RH_NONE) ? -1.0f : (air_rh_x100 / 100.0f),
                pkt.soil_pct, pkt.soil_raw, static_cast<unsigned long>(pkt.lux),
                pkt.flags, sent_ok ? "OK" : "FAIL");
  trackSendResult(sent_ok);

  // Bước 4: Cửa sổ nhận CfgPkt ~200 ms
  waitCfgWindow(gh::CFG_RX_WINDOW_MS);

  if (sent_ok) {
    blinkLed(1, 50, 0);
  }
}

void sleepUntilNextCycle(uint32_t wait_ms) {
#ifdef DEMO_MODE
  const unsigned long start_ms = millis();
  while ((millis() - start_ms) < wait_ms) {
    if (processPendingCfg() && rtc_zone > 0) {
      break;
    }
    delay(25);
  }
#elif defined(ESP8266)
  esp_now_deinit();
  WiFi.mode(WIFI_OFF);
  ESP.deepSleep(static_cast<uint64_t>(wait_ms) * 1000ULL);
#else
  esp_now_deinit();
  WiFi.mode(WIFI_OFF);
  esp_deep_sleep(static_cast<uint64_t>(wait_ms) * 1000ULL);
#endif
}

}  // namespace

void setup() {
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);
  pinMode(PIN_SOIL_VCC, OUTPUT);
  digitalWrite(PIN_SOIL_VCC, LOW);
#ifndef ESP8266
  analogReadResolution(12);
#endif

  Serial.begin(115200);
  WiFi.mode(WIFI_STA);
  loadConfigFromNvs();
  initSensors();

  Serial.printf("[node] GreenHub node fw %d.%d, MAC %s, zone=%u, interval=%us\n",
                GH_FW_MAJOR, GH_FW_MINOR, WiFi.macAddress().c_str(), rtc_zone,
                rtc_interval_s);

  if (!initEspNow()) {
    delay(2000);
    ESP.restart();
  }
  ensureGatewayBound();
}

void loop() {
  ensureGatewayBound();
  if (rtc_zone == 0) {
    sendUnpairedHello();
    if (rtc_zone == 0) {
      sleepUntilNextCycle(gh::HELLO_UNPAIRED_MS);
      return;
    }
  }

  measureAndSendTelemetry();
  const uint32_t interval_ms =
      static_cast<uint32_t>(rtc_interval_s > 0 ? rtc_interval_s : gh::DEFAULT_SAMPLE_INTERVAL_S) *
      1000UL;
  sleepUntilNextCycle(interval_ms);
}
