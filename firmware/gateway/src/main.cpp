// GreenHub - Firmware Gateway ESP32 (M1)
// Đặc tả: firmware/gateway/FEATURE_GATEWAY_AND_FAILSAFE.md
// Luồng: initActuatorsOff -> NVS/WiFiManager (Wi-Fi "Greenhouse-IOT" / "12345678") -> Wi-Fi STA -> NTP
// -> Wi-Fi UDP JSON Server + MQTT TLS -> Command & Safety Engine (ack) -> cfg sync
// -> Heartbeat status 30 s -> Failsafe + Buzzer.

#include <Arduino.h>
#include <ArduinoJson.h>
#include <ArduinoOTA.h>
#include <Preferences.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <WiFiManager.h>
#include <WiFiUdp.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "gh_config.h"
#include "gh_packets.h"

#ifndef MQTT_QUEUE_SIZE
#define MQTT_QUEUE_SIZE 150
#endif

#ifndef MQTT_MAX_PACKET_SIZE
#define MQTT_MAX_PACKET_SIZE 2048
#endif

namespace {

constexpr char NVS_NAMESPACE[] = "gh_gw";
constexpr uint8_t PIN_BOOT_BTN = 0;

constexpr uint8_t ACT_PUMP_1 = 0;
constexpr uint8_t ACT_PUMP_2 = 1;
constexpr uint8_t ACT_FAN = 2;
constexpr uint8_t ACT_LIGHT = 3;
constexpr uint8_t ACT_COUNT = 4;
constexpr uint8_t MOTOR_PWM_DUTY = 80;

constexpr uint8_t MAX_ZONES = 8;
constexpr uint8_t MAX_NODES = 16;
constexpr uint8_t SEEN_CMD_CAP = 50;
constexpr uint8_t PUMP_HIST_CAP = 48;
constexpr uint32_t HEARTBEAT_INTERVAL_MS = 30000;
constexpr uint32_t DISCOVERY_THROTTLE_MS = 10000;
constexpr uint32_t SENSOR_EVENT_THROTTLE_MS = 60000;
constexpr uint8_t STUCK_SOIL_CYCLES = 60;
constexpr uint8_t STUCK_AIR_CYCLES = 30;
constexpr uint8_t FILTER_WIN = 3;
constexpr float FILTER_EMA_ALPHA = 0.5f;

const uint8_t ACTUATOR_PINS[ACT_COUNT] = {
    PIN_PUMP1,
    PIN_PUMP2,
    PIN_FAN,
    PIN_LIGHT,
};

const char* const ACTUATOR_NAMES[ACT_COUNT] = {
    "pump_1",
    "pump_2",
    "fan",
    "light",
};

// Bundle CA gồm GreenHub Dev CA (deploy/certs/ca.crt) + ISRG Root X1 (Let's Encrypt prod)
const char GH_CA_CERT_BUNDLE_PEM[] =
    "-----BEGIN CERTIFICATE-----\n"
    "MIIC1TCCAb2gAwIBAgIUZeZrZoTy6rO1Vno18S3fbzKJKCIwDQYJKoZIhvcNAQEL\n"
    "BQAwGjEYMBYGA1UEAwwPR3JlZW5IdWIgRGV2IENBMB4XDTI2MTEwNTA0MjU1MVoX\n"
    "DTM2MTEwMjA0MzA1MVowGjEYMBYGA1UEAwwPR3JlZW5IdWIgRGV2IENBMIIBIjAN\n"
    "BgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA21CagxUrTx555debNRaDAZB2ym9/\n"
    "aStxSfLIH9tGH3+lYEFXJYQ8GhMT2T6gRwqMZ9iujc3EfwiqsDL5nak9oKUc0snB\n"
    "NNi0alj3Dl7TJLKhtTGFiFzTu/aGoGTQBWLBu606TLUtj5XNuI7AOAns1sISAqDE\n"
    "c0VPOtLcIjTWu0594khDor+0toRAd+T74mlV00WpqJ3Th5y1R5oWQjch8xtVJAtc\n"
    "TrRnxz2kGE9zgKBBho350SChz2W1pjxpd9OYqCfLZBdDicqZA3B3NKsoP7+4YcB5\n"
    "D3BOhCyC7cSC0tzapd+V5eOX/341Z2eHAlQ2jRNX/cMhfKxoR8CyJEwLNwIDAQAB\n"
    "oxMwETAPBgNVHRMBAf8EBTADAQH/MA0GCSqGSIb3DQEBCwUAA4IBAQCBJJFzjCJt\n"
    "1B3NuJ+C8kflBoT7zpA15cYFV8ZhCF1GSp8/7gpTLn7AbqFq15eOai9s9j3vgL9M\n"
    "XcuZjltiTMB5h7oaBdn7JEIDueDrw4TS014DWcmb5k9cHkd5PlVddbfQARP+cUao\n"
    "c/fTVigI95OAEZFVWzMBRrr18FPaCBUVf7dAY4kur6ffMBrmTUZ5+g0BXvB2q1fj\n"
    "gWVHx2wb9v0Yx+wuQ4fXw3L/mmpDCl/A4nQU+cpn5qqHGmi3yHx6ZhyGfCY/T2UX\n"
    "aawIkF+gwtZleDHZLRGCZKdy8gI8c5j77FNLd5Y1Q65zmW0DezZYnJmtZhwVSu1X\n"
    "LC16tN4uIX4g\n"
    "-----END CERTIFICATE-----\n"
    "-----BEGIN CERTIFICATE-----\n"
    "MIIFazCCA1OgAwIBAgIRAIIQz7DSQONZRGPgu2OCiwAwDQYJKoZIhvcNAQELBQAw\n"
    "TzELMAkGA1UEBhMCVVMxKTAnBgNVBAoTIEludGVybmV0IFNlY3VyaXR5IFJlc2Vh\n"
    "cmNoIEdyb3VwMRUwEwYDVQQDEwxJU1JHIFJvb3QgWDEwHhcNMTUwNjA0MTEwNDM4\n"
    "WhcNMzUwNjA0MTEwNDM4WjBPMQswCQYDVQQGEwJVUzEpMCcGA1UEChMgSW50ZXJu\n"
    "ZXQgU2VjdXJpdHkgUmVzZWFyY2ggR3JvdXAxFTATBgNVBAMTDElTUkcgUm9vdCBY\n"
    "MTCCAiIwDQYJKoZIhvcNAQEBBQADggIPADCCAgoCggIBAK3oJHP0FDfzm54rVygc\n"
    "h77ct984kIxuPOZXoHj3dcKi/vVqbvYATyjb3miGbESTtrFj/RQSa78f0uoxmyF+\n"
    "0TM8ukj13Xnfs7j/EvEhmkvBioZxaUpmZmyPfjxwv60pIgbz5MDmgK7iS4+3mX6U\n"
    "A5/TR5d8mUgjU+g4rk8Kb4Mu0UlXjIB0ttov0DiNewNwIRt18jA8+o+u3dpjq+sW\n"
    "T8KOEUt+zwvo/7V3LvSye0rgTBIlDHCNAymg4VMk7BPZ7hm/ELNKjD+Jo2FR3qyH\n"
    "B5T0Y3HsLuJvW5iB4YlcNHlsdu87kGJ55tukmi8mxdAQ4Q7e2RCOFvu396j3x+UC\n"
    "B5iPNgiV5+I3lg02dZ77DnKxHZu8A/lJBdiB3QW0KtZB6awBdpUKD9jf1b0SHzUv\n"
    "KBds0pjBqAlkd25HN7rOrFleaJ1/ctaJxQZBKT5ZPt0m9STJEadao0xAH0ahmbWn\n"
    "OlFuhjuefXKnEgV4We0+UXgVCwOPjdAvBbI+e0ocS3MFEvzG6uBQE3xDk3SzynTn\n"
    "jh8BCNAw1FtxNrQHusEwMFxIt4I7mKZ9YIqioymCzLq9gwQbooMDQaHWBfEbwrbw\n"
    "qHyGO0aoSCqI3Haadr8faqU9GY/rOPNk3sgrDQoo//fb4hVC1CLQJ13hef4Y53CI\n"
    "rU7m2Ys6xt0nUW7/vGT1M0NPAgMBAAGjQjBAMA4GA1UdDwEB/wQEAwIBBjAPBgNV\n"
    "HRMBAf8EBTADAQH/MB0GA1UdDgQWBBR5tFnme7bl5AFzgAiIyBpY9umbbjANBgkq\n"
    "hkiG9w0BAQsFAAOCAgEAVR9YqbyyqFDQDLHYGmkgJykIrGF1XIpu+ILlaS/V9lZL\n"
    "ubhzEFnTIZd+50xx+7LSYK05qAvqFyFWhfFQDlnrzuBZ6brJFe+GnY+EgPbk6ZGQ\n"
    "3BebYhtF8GaV0nxvwuo77x/Py9auJ/GpsMiu/X1+mvoiBOv/2X/qkSsisRcOj/KK\n"
    "NFtY2PwByVS5uCbMiogziUwthDyC3+6WVwW6LLv3xLfHTjuCvjHIInNzktHCgKQ5\n"
    "ORAzI4JMPJ+GslWYHb4phowim57iaztXOoJwTdwJx4nLCgdNbOhdjsnvzqvHu7Ur\n"
    "TkXWStAmzOVyyghqpZXjFaH3pO3JLF+l+/+sKAIuvtd7u+Nxe5AW0wdeRlN8NwdC\n"
    "jNPElpzVmbUq4JUagEiuTDkHzsxHpFKVK7q4+63SM1N95R1NbdWhscdCb+ZAJzVc\n"
    "oyi3B43njTOQ5yOf+1CceWxG1bQVs5ZufpsMljq4Ui0/1lvh+wjChP4kqKOJ2qxq\n"
    "4RgqsahDYVvTH9w7jXbyLeiNdd8XM2w9U/t7y0Ff/9yi0GE44Za4rF2LN9d11TPA\n"
    "mRGunUHBcnWEvgJBQl9nJEiU0Zsnvgc/ubhPgXRR4Xq37Z0j4r7g1SgEEzwxA57d\n"
    "emyPxgcYxn/eR44/KJ4EBs+lVDR3veyJm+kXQ99b21/+jh5Xos1AnX5iItreGCc=\n"
    "-----END CERTIFICATE-----\n";

struct ProvisionConfig {
  char mqtt_host[65];
  uint16_t mqtt_port;
  char mqtt_user[65];
  char mqtt_pass[65];
  char farm_id[41];
  char gh_id[41];
};

struct NodeMapEntry {
  bool in_use;
  uint8_t mac[6];
  char mac_str[18];
  uint8_t zone;
  bool has_last_seq;
  uint16_t last_seq;
  bool has_seen;
  uint64_t last_seen_ms;
  uint64_t last_discovery_ms;
};

struct ZoneConfig {
  bool in_use;
  uint8_t zone;
  uint8_t pump_idx;
  uint16_t sample_interval_s;
  uint16_t soil_dry_raw;
  uint16_t soil_wet_raw;
  uint16_t irrigation_max_run_s;
  uint16_t irrigation_min_gap_s;
  uint16_t irrigation_max_total_s_per_hour;
  uint16_t fan_max_on_s;
  float temp_critical_high_c;
  float soil_moisture_critical_low_pct;
};

struct ZoneTelemetryState {
  bool has_sample;
  bool has_own_air;
  uint64_t last_rx_ms;
  float air_t;
  float air_rh;
  uint8_t soil_pct;
  uint16_t soil_raw;
  uint8_t flags;
  uint16_t prev_soil_raw;
  uint8_t stuck_soil_count;
  int16_t prev_air_t_x100;
  uint16_t prev_air_rh_x100;
  uint8_t stuck_air_count;
  uint64_t last_invalid_event_ms;
};

struct ZoneFilterState {
  bool air_init;
  float air_t_win[FILTER_WIN];
  float air_rh_win[FILTER_WIN];
  uint8_t air_count;
  uint8_t air_idx;
  float ema_air_t;
  float ema_air_rh;
  uint8_t air_spike_streak;

  bool soil_init;
  uint16_t soil_win[FILTER_WIN];
  uint8_t soil_pct_win[FILTER_WIN];
  uint8_t soil_count;
  uint8_t soil_idx;
  float ema_soil_raw;
  float ema_soil_pct;
  uint8_t soil_spike_streak;

  bool lux_init;
  uint32_t lux_win[FILTER_WIN];
  uint8_t lux_count;
  uint8_t lux_idx;
  float ema_lux;
};

struct PumpRunRecord {
  uint32_t start_s;
  uint16_t dur_s;
};

struct MqttQueueItem {
  char suffix[48];
  char payload[320];
};

// Biến toàn cục trạng thái Gateway
ProvisionConfig g_prov = {
    "10.11.154.220",
    8883,
    "gw_d290e571f00e",
    "BCHxXzTe7pEVGMSh-U85-o06Q8A",
    "b038cbf3-922d-4dfa-98bb-8fbc322db837",
    "d290e571-f00e-4888-a917-af986bed555c"};
char g_topic_prefix[96] = {0};

WiFiClientSecure g_tls_client;
PubSubClient g_mqtt(g_tls_client);

uint32_t g_cfg_version = 0;
uint32_t g_offline_failsafe_after_s = 60;
NodeMapEntry g_nodes[MAX_NODES] = {};
ZoneConfig g_zones[MAX_ZONES] = {};
ZoneTelemetryState g_zone_state[MAX_ZONES] = {};
ZoneFilterState g_zone_filter[MAX_ZONES] = {};

// Theo dõi discovery node lạ (throttle theo MAC)
struct UnknownMacThrottle {
  bool in_use;
  uint8_t mac[6];
  uint64_t last_ms;
};
UnknownMacThrottle g_unknown_throttle[MAX_NODES] = {};

// Trạng thái thiết bị chấp hành (transistor 8050) & an toàn
bool g_actuator_on[ACT_COUNT] = {false, false, false, false};
bool g_has_off_deadline[ACT_COUNT] = {false, false, false, false};
uint64_t g_off_deadline_ms[ACT_COUNT] = {0, 0, 0, 0};
bool g_has_last_pump_end[2] = {false, false};
uint64_t g_last_pump_end_ms[2] = {0, 0};
PumpRunRecord g_pump_hist[2][PUMP_HIST_CAP] = {};
uint8_t g_pump_hist_count[2] = {0, 0};

// Idempotency cho cmd_id
char g_seen_cmds[SEEN_CMD_CAP][40] = {};
uint8_t g_seen_cmd_head = 0;

// RAM Ring Buffer cho MQTT khi mất mạng (150 mục)
MqttQueueItem g_mqtt_queue[MQTT_QUEUE_SIZE] = {};
uint16_t g_queue_head = 0;
uint16_t g_queue_count = 0;

// Socket Wi-Fi UDP JSON lắng nghe các Sensor Node trên cổng gh::UDP_PORT
WiFiUDP g_udp;
bool g_udp_started = false;

// Trạng thái kết nối MQTT & Failsafe & Buzzer
bool g_boot_event_sent = false;
bool g_mqtt_was_connected = false;
uint64_t g_mqtt_disconnected_since_ms = 0;
uint64_t g_next_reconnect_ms = 0;
uint32_t g_reconnect_backoff_ms = 1000;
uint64_t g_last_heartbeat_ms = 0;
bool g_failsafe_offline_active = false;
bool g_failsafe_fan_active = false;
uint64_t g_last_failsafe_eval_ms = 0;
uint64_t g_last_buzzer_toggle_ms = 0;
bool g_buzzer_on = false;
uint64_t g_last_led_toggle_ms = 0;
bool g_led_on = false;

// Quản lý millis 64-bit chống tràn sau 49.7 ngày
uint64_t millis64() {
  static uint32_t last_low = 0;
  static uint32_t high = 0;
  uint32_t low = millis();
  if (low < last_low) {
    ++high;
  }
  last_low = low;
  return (static_cast<uint64_t>(high) << 32) | low;
}

uint32_t uptimeSeconds() { return static_cast<uint32_t>(millis64() / 1000ULL); }

void initActuatorsOff() {
  // Đệm transistor 8050 kích mức HIGH: ghi LOW/0 TRƯỚC pinMode để tắt tuyệt đối khi boot
  for (uint8_t i = 0; i < ACT_COUNT; ++i) {
    digitalWrite(ACTUATOR_PINS[i], LOW);
    pinMode(ACTUATOR_PINS[i], OUTPUT);
    if (i != ACT_LIGHT) {
      analogWrite(ACTUATOR_PINS[i], 0);
    }
    g_actuator_on[i] = false;
    g_has_off_deadline[i] = false;
  }
}

void setActuatorPin(uint8_t act_idx, bool turn_on) {
  if (act_idx >= ACT_COUNT) {
    return;
  }
  if (act_idx == ACT_LIGHT) {
    digitalWrite(ACTUATOR_PINS[act_idx], turn_on ? HIGH : LOW);
  } else {
    analogWrite(ACTUATOR_PINS[act_idx], turn_on ? MOTOR_PWM_DUTY : 0);
  }
  g_actuator_on[act_idx] = turn_on;
}

void formatMac(const uint8_t mac[6], char* out, size_t out_len) {
  snprintf(out, out_len, "%02X:%02X:%02X:%02X:%02X:%02X", mac[0], mac[1], mac[2],
           mac[3], mac[4], mac[5]);
}

bool parseMacString(const char* str, uint8_t out_mac[6]) {
  if (!str) return false;
  unsigned int b[6] = {0};
  if (sscanf(str, "%2x:%2x:%2x:%2x:%2x:%2x", &b[0], &b[1], &b[2], &b[3], &b[4],
             &b[5]) != 6) {
    return false;
  }
  for (int i = 0; i < 6; ++i) {
    out_mac[i] = static_cast<uint8_t>(b[i]);
  }
  return true;
}

bool isNtpSynced() { return time(nullptr) > 1700000000L; }

void formatIso8601Utc(time_t t, char* buf, size_t len) {
  struct tm tm_utc = {};
  gmtime_r(&t, &tm_utc);
  snprintf(buf, len, "%04d-%02d-%02dT%02d:%02d:%02dZ", tm_utc.tm_year + 1900,
           tm_utc.tm_mon + 1, tm_utc.tm_mday, tm_utc.tm_hour, tm_utc.tm_min,
           tm_utc.tm_sec);
}

void currentIso8601Utc(char* buf, size_t len) {
  time_t now = time(nullptr);
  if (now < 1700000000L) {
    snprintf(buf, len, "1970-01-01T00:00:00Z");
    return;
  }
  formatIso8601Utc(now, buf, len);
}

// Chuyển ngày UTC sang số ngày kể từ 1970-01-01 (Howard Hinnant algorithm)
int64_t daysFromCivil(int64_t y, unsigned m, unsigned d) {
  y -= m <= 2;
  const int64_t era = (y >= 0 ? y : y - 399) / 400;
  const unsigned yoe = static_cast<unsigned>(y - era * 400);
  const unsigned doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
  const unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  return era * 146097 + static_cast<int64_t>(doe) - 719468;
}

bool parseIso8601Utc(const char* s, int64_t* out_epoch) {
  if (!s || strlen(s) < 19) return false;
  int year = 0, mon = 0, day = 0, hour = 0, min = 0, sec = 0;
  if (sscanf(s, "%4d-%2d-%2dT%2d:%2d:%2d", &year, &mon, &day, &hour, &min, &sec) !=
      6) {
    return false;
  }
  if (mon < 1 || mon > 12 || day < 1 || day > 31 || hour < 0 || hour > 23 ||
      min < 0 || min > 59 || sec < 0 || sec > 60) {
    return false;
  }

  int tz_offset_s = 0;
  const char* p = s + 19;
  if (*p == '.') {
    ++p;
    while (*p >= '0' && *p <= '9') ++p;
  }
  if (*p == '+' || *p == '-') {
    int sign = (*p == '+') ? 1 : -1;
    int tzh = 0, tzm = 0;
    if (sscanf(p + 1, "%2d:%2d", &tzh, &tzm) == 2 ||
        sscanf(p + 1, "%2d%2d", &tzh, &tzm) == 2) {
      tz_offset_s = sign * (tzh * 3600 + tzm * 60);
    }
  }

  const int64_t days =
      daysFromCivil(year, static_cast<unsigned>(mon), static_cast<unsigned>(day));
  *out_epoch = days * 86400LL + hour * 3600LL + min * 60LL + sec - tz_offset_s;
  return true;
}

int actuatorIndexByName(const char* name) {
  if (!name) return -1;
  for (int i = 0; i < ACT_COUNT; ++i) {
    if (strcmp(name, ACTUATOR_NAMES[i]) == 0) {
      return i;
    }
  }
  return -1;
}

void buildTopic(char* buf, size_t len, const char* suffix) {
  snprintf(buf, len, "%s/%s", g_topic_prefix, suffix);
}

void enqueueMqtt(const char* suffix, const char* payload) {
  uint16_t slot = 0;
  if (g_queue_count < MQTT_QUEUE_SIZE) {
    slot = (g_queue_head + g_queue_count) % MQTT_QUEUE_SIZE;
    ++g_queue_count;
  } else {
    // Đầy ring buffer: ghi đè phần tử cũ nhất
    slot = g_queue_head;
    g_queue_head = (g_queue_head + 1) % MQTT_QUEUE_SIZE;
  }
  snprintf(g_mqtt_queue[slot].suffix, sizeof(g_mqtt_queue[slot].suffix), "%s", suffix);
  snprintf(g_mqtt_queue[slot].payload, sizeof(g_mqtt_queue[slot].payload), "%s",
           payload);
}

void publishOrEnqueue(const char* suffix, const char* payload, bool allow_queue) {
  char topic[160];
  buildTopic(topic, sizeof(topic), suffix);
  if (g_mqtt.connected() && g_queue_count == 0) {
    if (g_mqtt.publish(topic, payload, false)) {
      return;
    }
  }
  if (allow_queue) {
    enqueueMqtt(suffix, payload);
  }
}

void flushMqttQueue() {
  uint8_t burst = 0;
  while (g_mqtt.connected() && g_queue_count > 0 && burst < 2) {
    const MqttQueueItem& item = g_mqtt_queue[g_queue_head];
    char topic[160];
    buildTopic(topic, sizeof(topic), item.suffix);
    if (!g_mqtt.publish(topic, item.payload, false)) {
      break;
    }
    g_queue_head = (g_queue_head + 1) % MQTT_QUEUE_SIZE;
    --g_queue_count;
    ++burst;
  }
}

void publishStatusNow() {
  if (!g_mqtt.connected()) {
    return;
  }
  JsonDocument doc;
  doc["online"] = true;
  doc["fw"] = GH_FW_VERSION_STR;
  doc["rssi"] = WiFi.RSSI();
  doc["uptime_s"] = uptimeSeconds();
  doc["heap"] = ESP.getFreeHeap();
  doc["queue_len"] = g_queue_count;
  doc["cfg_version"] = g_cfg_version;

  JsonObject acts = doc["actuators"].to<JsonObject>();
  for (int i = 0; i < ACT_COUNT; ++i) {
    acts[ACTUATOR_NAMES[i]] = g_actuator_on[i] ? "on" : "off";
  }

  JsonArray nodes = doc["nodes"].to<JsonArray>();
  const uint64_t now_ms = millis64();
  for (uint8_t i = 0; i < MAX_NODES; ++i) {
    if (!g_nodes[i].in_use) continue;
    JsonObject n = nodes.add<JsonObject>();
    n["mac"] = g_nodes[i].mac_str;
    n["zone"] = g_nodes[i].zone;
    if (g_nodes[i].has_seen) {
      n["last_seen_s"] = static_cast<uint32_t>((now_ms - g_nodes[i].last_seen_ms) / 1000ULL);
    } else {
      n["last_seen_s"] = 0;
    }
  }

  char payload[1024];
  const size_t n = serializeJson(doc, payload, sizeof(payload));
  if (n > 0 && n < sizeof(payload)) {
    char topic[160];
    buildTopic(topic, sizeof(topic), "status");
    g_mqtt.publish(topic, payload, true);
  }
}

void emitEvent(const char* type, int zone, const char* actuator, const char* action,
               const char* source, JsonDocument* detail_doc) {
  JsonDocument doc;
  char ts[32];
  currentIso8601Utc(ts, sizeof(ts));
  doc["ts"] = ts;
  doc["type"] = type;
  if (zone > 0) {
    doc["zone"] = zone;
  }
  if (actuator) {
    doc["actuator"] = actuator;
  }
  if (action) {
    doc["action"] = action;
  }
  if (source) {
    doc["source"] = source;
  }
  if (detail_doc) {
    doc["detail"] = detail_doc->as<JsonVariantConst>();
  } else {
    doc["detail"].to<JsonObject>();
  }

  char payload[310];
  const size_t n = serializeJson(doc, payload, sizeof(payload));
  if (n > 0 && n < sizeof(payload)) {
    publishOrEnqueue("event", payload, true);
  }
}

void initDefaultZones() {
  for (uint8_t i = 0; i < MAX_ZONES; ++i) {
    g_zones[i].in_use = false;
    g_zones[i].zone = i + 1;
    g_zones[i].pump_idx = (i == 1) ? ACT_PUMP_2 : ACT_PUMP_1;
    g_zones[i].sample_interval_s = gh::SENSOR_MEASURE_INTERVAL_S;
    g_zones[i].soil_dry_raw = gh::DEFAULT_SOIL_DRY_RAW;
    g_zones[i].soil_wet_raw = gh::DEFAULT_SOIL_WET_RAW;
    g_zones[i].irrigation_max_run_s = 15;
    g_zones[i].irrigation_min_gap_s = 90;
    g_zones[i].irrigation_max_total_s_per_hour = 120;
    g_zones[i].fan_max_on_s = 60;
    g_zones[i].temp_critical_high_c = 38.0f;
    g_zones[i].soil_moisture_critical_low_pct = 30.0f;
  }
}

ZoneConfig* findZoneConfig(uint8_t zone_idx) {
  for (uint8_t i = 0; i < MAX_ZONES; ++i) {
    if (g_zones[i].in_use && g_zones[i].zone == zone_idx) {
      return &g_zones[i];
    }
  }
  return nullptr;
}

ZoneConfig* findZoneByPump(uint8_t pump_idx) {
  for (uint8_t i = 0; i < MAX_ZONES; ++i) {
    if (g_zones[i].in_use && g_zones[i].pump_idx == pump_idx) {
      return &g_zones[i];
    }
  }
  return nullptr;
}

int findZoneSlot(uint8_t zone_idx) {
  if (zone_idx >= 1 && zone_idx <= MAX_ZONES) {
    return zone_idx - 1;
  }
  return -1;
}

NodeMapEntry* findNodeByMac(const uint8_t mac[6]) {
  for (uint8_t i = 0; i < MAX_NODES; ++i) {
    if (g_nodes[i].in_use && memcmp(g_nodes[i].mac, mac, 6) == 0) {
      return &g_nodes[i];
    }
  }
  return nullptr;
}

NodeMapEntry* findNodeByZone(uint8_t zone_idx) {
  if (zone_idx == 0) return nullptr;
  for (uint8_t i = 0; i < MAX_NODES; ++i) {
    if (g_nodes[i].in_use && g_nodes[i].zone == zone_idx) {
      return &g_nodes[i];
    }
  }
  return nullptr;
}

bool applyCfgJson(const char* json_str, size_t len, bool save_to_nvs) {
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, json_str, len);
  if (err) {
    Serial.printf("[gw] cfg JSON parse failed: %s\n", err.c_str());
    return false;
  }

  const uint32_t new_ver = doc["cfg_version"] | 0U;
  if (new_ver == 0) {
    return false;
  }
  const bool ver_changed = (new_ver != g_cfg_version);
  g_cfg_version = new_ver;
  g_offline_failsafe_after_s = doc["offline_failsafe_after_s"] | 60U;
  if (g_offline_failsafe_after_s < 10) {
    g_offline_failsafe_after_s = 10;
  }

  // Giữ lại last_seq và last_seen_ms cho các MAC tiếp tục tồn tại
  static NodeMapEntry prev_nodes[MAX_NODES];
  memcpy(prev_nodes, g_nodes, sizeof(prev_nodes));
  memset(g_nodes, 0, sizeof(g_nodes));

  JsonArrayConst nodes_arr = doc["nodes"].as<JsonArrayConst>();
  uint8_t node_count = 0;
  if (!nodes_arr.isNull()) {
    for (JsonVariantConst item : nodes_arr) {
      if (node_count >= MAX_NODES) break;
      const char* mac_s = item["mac"] | "";
      uint8_t zone_val = item["zone"] | 0;
      uint8_t mac_bytes[6] = {0};
      if (!parseMacString(mac_s, mac_bytes) || zone_val == 0) continue;

      NodeMapEntry& dst = g_nodes[node_count++];
      dst.in_use = true;
      memcpy(dst.mac, mac_bytes, 6);
      formatMac(mac_bytes, dst.mac_str, sizeof(dst.mac_str));
      dst.zone = zone_val;

      for (uint8_t k = 0; k < MAX_NODES; ++k) {
        if (prev_nodes[k].in_use && memcmp(prev_nodes[k].mac, mac_bytes, 6) == 0) {
          dst.has_last_seq = prev_nodes[k].has_last_seq;
          dst.last_seq = prev_nodes[k].last_seq;
          dst.has_seen = prev_nodes[k].has_seen;
          dst.last_seen_ms = prev_nodes[k].last_seen_ms;
          break;
        }
      }
    }
  }

  initDefaultZones();
  JsonArrayConst zones_arr = doc["zones"].as<JsonArrayConst>();
  if (!zones_arr.isNull()) {
    for (JsonVariantConst z : zones_arr) {
      const uint8_t z_idx = z["zone"] | 0;
      const int slot = findZoneSlot(z_idx);
      if (slot < 0) continue;

      ZoneConfig& zc = g_zones[slot];
      zc.in_use = true;
      zc.zone = z_idx;
      const char* pump_name = z["pump"] | "";
      zc.pump_idx = (strcmp(pump_name, "pump_2") == 0) ? ACT_PUMP_2 : ACT_PUMP_1;
      zc.sample_interval_s = z["sample_interval_s"] | gh::DEFAULT_SAMPLE_INTERVAL_S;
      if (zc.sample_interval_s == 0) {
        zc.sample_interval_s = gh::DEFAULT_SAMPLE_INTERVAL_S;
      }

      JsonObjectConst cal = z["soil_cal"].as<JsonObjectConst>();
      if (!cal.isNull()) {
        zc.soil_dry_raw = cal["dry_raw"] | gh::DEFAULT_SOIL_DRY_RAW;
        zc.soil_wet_raw = cal["wet_raw"] | gh::DEFAULT_SOIL_WET_RAW;
      }

      JsonObjectConst lim = z["limits"].as<JsonObjectConst>();
      if (!lim.isNull()) {
        zc.irrigation_max_run_s = lim["irrigation_max_run_s"] | 15;
        zc.irrigation_min_gap_s = lim["irrigation_min_gap_s"] | 90;
        zc.irrigation_max_total_s_per_hour = lim["irrigation_max_total_s_per_hour"] | 120;
        zc.fan_max_on_s = lim["fan_max_on_s"] | 60;
        if (zc.fan_max_on_s > 60) {
          zc.fan_max_on_s = 60;
        }
      }

      JsonObjectConst fs = z["failsafe"].as<JsonObjectConst>();
      if (!fs.isNull()) {
        zc.temp_critical_high_c = fs["temp_critical_high_c"] | 38.0f;
        zc.soil_moisture_critical_low_pct = fs["soil_moisture_critical_low_pct"] | 30.0f;
      }
    }
  }

  // Chỉ ghi vào NVS khi cfg_version thay đổi để bảo vệ flash
  if (save_to_nvs && ver_changed && len < 1900) {
    static char cfg_buf[1901];
    memcpy(cfg_buf, json_str, len);
    cfg_buf[len] = '\0';
    Preferences prefs;
    if (prefs.begin(NVS_NAMESPACE, false)) {
      if (prefs.getUInt("cfg_ver", 0) != g_cfg_version) {
        prefs.putUInt("cfg_ver", g_cfg_version);
        prefs.putString("cfg_json", cfg_buf);
      }
      prefs.end();
    }
  }

  Serial.printf("[gw] cfg applied: ver=%lu nodes=%u offline_fs=%lus\n",
                static_cast<unsigned long>(g_cfg_version), node_count,
                static_cast<unsigned long>(g_offline_failsafe_after_s));
  return ver_changed;
}

bool sendUdpJsonTo(IPAddress dst_ip, uint16_t dst_port, const JsonDocument& doc) {
  if (!g_udp_started || static_cast<uint32_t>(dst_ip) == 0 || dst_port == 0) {
    return false;
  }
  char buf[384];
  const size_t len = serializeJson(doc, buf, sizeof(buf));
  if (len == 0 || len >= sizeof(buf)) {
    return false;
  }
  if (g_udp.beginPacket(dst_ip, dst_port) == 0) {
    return false;
  }
  const size_t written = g_udp.write(reinterpret_cast<const uint8_t*>(buf), len);
  const int ok = g_udp.endPacket();
  return written == len && ok == 1;
}

void sendCfgJsonToNode(IPAddress dst_ip, uint16_t dst_port, const NodeMapEntry* node) {
  if (!node || node->zone == 0) return;
  const ZoneConfig* zc = findZoneConfig(node->zone);

  JsonDocument doc;
  doc["type"] = "cfg";
  doc["mac"] = node->mac_str;
  doc["zone"] = node->zone;
  doc["sample_interval_s"] = gh::SENSOR_MEASURE_INTERVAL_S;
  doc["soil_dry_raw"] = zc ? zc->soil_dry_raw : gh::DEFAULT_SOIL_DRY_RAW;
  doc["soil_wet_raw"] = zc ? zc->soil_wet_raw : gh::DEFAULT_SOIL_WET_RAW;
  doc["cfg_version"] = static_cast<uint16_t>(g_cfg_version & 0xFFFFu);

  sendUdpJsonTo(dst_ip, dst_port, doc);
}

void publishDiscovery(const uint8_t mac[6], int8_t rssi, uint8_t fw_maj, uint8_t fw_min) {
  const uint64_t now_ms = millis64();
  int free_slot = -1;
  for (uint8_t i = 0; i < MAX_NODES; ++i) {
    if (g_unknown_throttle[i].in_use && memcmp(g_unknown_throttle[i].mac, mac, 6) == 0) {
      if ((now_ms - g_unknown_throttle[i].last_ms) < DISCOVERY_THROTTLE_MS) {
        return;
      }
      g_unknown_throttle[i].last_ms = now_ms;
      free_slot = i;
      break;
    }
    if (!g_unknown_throttle[i].in_use && free_slot < 0) {
      free_slot = i;
    }
  }
  if (free_slot >= 0 && !g_unknown_throttle[free_slot].in_use) {
    g_unknown_throttle[free_slot].in_use = true;
    memcpy(g_unknown_throttle[free_slot].mac, mac, 6);
    g_unknown_throttle[free_slot].last_ms = now_ms;
  }

  char mac_str[18];
  formatMac(mac, mac_str, sizeof(mac_str));
  char ts[32];
  currentIso8601Utc(ts, sizeof(ts));
  char fw_str[16];
  snprintf(fw_str, sizeof(fw_str), "%u.%u", fw_maj, fw_min);

  JsonDocument doc;
  doc["ts"] = ts;
  doc["mac"] = mac_str;
  doc["fw"] = fw_str;
  doc["rssi"] = rssi;

  char payload[192];
  const size_t n = serializeJson(doc, payload, sizeof(payload));
  if (n > 0 && n < sizeof(payload)) {
    publishOrEnqueue("discovery", payload, true);
  }
}

// ============================================================================
// Command & Safety Engine (khớp GatewaySafetyEngine trong gateway_client.py)
// ============================================================================

bool hasSeenCmd(const char* cmd_id) {
  if (!cmd_id || cmd_id[0] == '\0') return true;
  for (uint8_t i = 0; i < SEEN_CMD_CAP; ++i) {
    if (g_seen_cmds[i][0] != '\0' && strcmp(g_seen_cmds[i], cmd_id) == 0) {
      return true;
    }
  }
  return false;
}

void markSeenCmd(const char* cmd_id) {
  snprintf(g_seen_cmds[g_seen_cmd_head], sizeof(g_seen_cmds[g_seen_cmd_head]), "%s",
           cmd_id);
  g_seen_cmd_head = (g_seen_cmd_head + 1) % SEEN_CMD_CAP;
}

uint32_t pumpUsedLastHour(uint8_t pump_idx, uint32_t now_s) {
  uint32_t total = 0;
  uint8_t keep = 0;
  for (uint8_t i = 0; i < g_pump_hist_count[pump_idx]; ++i) {
    const PumpRunRecord& rec = g_pump_hist[pump_idx][i];
    if (now_s >= rec.start_s && (now_s - rec.start_s) <= 3600U) {
      g_pump_hist[pump_idx][keep++] = rec;
      total += rec.dur_s;
    }
  }
  g_pump_hist_count[pump_idx] = keep;
  return total;
}

void recordPumpRun(uint8_t pump_idx, uint32_t now_s, uint16_t dur_s) {
  pumpUsedLastHour(pump_idx, now_s);
  if (g_pump_hist_count[pump_idx] >= PUMP_HIST_CAP) {
    memmove(&g_pump_hist[pump_idx][0], &g_pump_hist[pump_idx][1],
            sizeof(PumpRunRecord) * (PUMP_HIST_CAP - 1));
    --g_pump_hist_count[pump_idx];
  }
  g_pump_hist[pump_idx][g_pump_hist_count[pump_idx]++] = {now_s, dur_s};
}

void publishAck(const char* cmd_id, const char* status, const char* reason,
                const char* applied_at, const char* side_effect) {
  JsonDocument doc;
  doc["cmd_id"] = cmd_id;
  doc["status"] = status;
  if (reason) {
    doc["reason"] = reason;
  } else {
    doc["reason"] = nullptr;
  }
  if (applied_at) {
    doc["applied_at"] = applied_at;
  } else {
    doc["applied_at"] = nullptr;
  }
  JsonArray se = doc["side_effects"].to<JsonArray>();
  if (side_effect && side_effect[0] != '\0') {
    se.add(side_effect);
  }
  JsonObject st = doc["state"].to<JsonObject>();
  for (int i = 0; i < ACT_COUNT; ++i) {
    st[ACTUATOR_NAMES[i]] = g_actuator_on[i] ? "on" : "off";
  }

  char payload[320];
  const size_t n = serializeJson(doc, payload, sizeof(payload));
  if (n > 0 && n < sizeof(payload)) {
    char suffix[64];
    snprintf(suffix, sizeof(suffix), "ack/%s", cmd_id);
    publishOrEnqueue(suffix, payload, true);
  }
}

uint16_t getMaxRunForActuator(uint8_t act_idx) {
  if (act_idx == ACT_PUMP_1 || act_idx == ACT_PUMP_2) {
    const ZoneConfig* zc = findZoneByPump(act_idx);
    return zc ? zc->irrigation_max_run_s : 15;
  }
  // Lấy max của zone 1 (hoặc zone đầu tiên tìm thấy) cho fan/light (tối đa 60s)
  for (uint8_t i = 0; i < MAX_ZONES; ++i) {
    if (g_zones[i].in_use) {
      return (g_zones[i].fan_max_on_s > 60) ? 60 : g_zones[i].fan_max_on_s;
    }
  }
  return 60;
}

bool tryTurnOnPump(uint8_t pump_idx, uint16_t req_dur_s, const char** out_reject_reason,
                   uint16_t* out_eff_dur) {
  const ZoneConfig* zc = findZoneByPump(pump_idx);
  const uint16_t max_run = zc ? zc->irrigation_max_run_s : 15;
  const uint16_t min_gap = zc ? zc->irrigation_min_gap_s : 90;
  const uint16_t max_total = zc ? zc->irrigation_max_total_s_per_hour : 120;

  uint16_t eff = req_dur_s;
  if (eff > max_run) eff = max_run;
  if (eff == 0) {
    *out_reject_reason = "invalid";
    return false;
  }

  const uint64_t now_ms = millis64();
  const uint32_t now_s = static_cast<uint32_t>(now_ms / 1000ULL);
  if (!g_actuator_on[pump_idx] && g_has_last_pump_end[pump_idx]) {
    if ((now_ms - g_last_pump_end_ms[pump_idx]) < static_cast<uint64_t>(min_gap) * 1000ULL) {
      *out_reject_reason = "min_gap";
      return false;
    }
  }
  if (pumpUsedLastHour(pump_idx, now_s) + eff > max_total) {
    *out_reject_reason = "max_total";
    return false;
  }

  recordPumpRun(pump_idx, now_s, eff);
  setActuatorPin(pump_idx, true);
  g_has_off_deadline[pump_idx] = true;
  g_off_deadline_ms[pump_idx] = now_ms + static_cast<uint64_t>(eff) * 1000ULL;
  *out_eff_dur = eff;
  return true;
}

void handleCommandPayload(const uint8_t* raw, unsigned int len) {
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, raw, len);
  if (err) {
    Serial.printf("[gw] cmd JSON parse failed: %s\n", err.c_str());
    return;
  }

  const char* cmd_id = doc["cmd_id"] | "";
  if (hasSeenCmd(cmd_id)) {
    return;
  }
  markSeenCmd(cmd_id);

  // Kiểm tra hết hạn expires_at
  const char* exp_str = doc["expires_at"] | "";
  int64_t exp_epoch = 0;
  if (exp_str[0] != '\0' && isNtpSynced() && parseIso8601Utc(exp_str, &exp_epoch)) {
    if (exp_epoch <= static_cast<int64_t>(time(nullptr))) {
      publishAck(cmd_id, "expired", nullptr, nullptr, nullptr);
      return;
    }
  }

  const char* act_str = doc["actuator"] | "";
  const char* action_str = doc["action"] | "";
  const int act_idx = actuatorIndexByName(act_str);
  const bool is_on = (strcmp(action_str, "on") == 0);
  const bool is_off = (strcmp(action_str, "off") == 0);

  if (act_idx < 0 || (!is_on && !is_off)) {
    publishAck(cmd_id, "rejected", "invalid", nullptr, nullptr);
    return;
  }

  const uint64_t now_ms = millis64();
  char applied_ts[32];
  currentIso8601Utc(applied_ts, sizeof(applied_ts));

  if (is_off) {
    const bool was_on = g_actuator_on[act_idx];
    setActuatorPin(act_idx, false);
    g_has_off_deadline[act_idx] = false;
    if (was_on && (act_idx == ACT_PUMP_1 || act_idx == ACT_PUMP_2)) {
      g_has_last_pump_end[act_idx] = true;
      g_last_pump_end_ms[act_idx] = now_ms;
    }
    publishAck(cmd_id, "applied", nullptr, applied_ts, nullptr);
    publishStatusNow();
    return;
  }

  if (doc["duration_s"].isNull()) {
    publishAck(cmd_id, "rejected", "invalid", nullptr, nullptr);
    return;
  }
  const long req_dur_l = doc["duration_s"].as<long>();
  if (req_dur_l <= 0) {
    publishAck(cmd_id, "rejected", "invalid", nullptr, nullptr);
    return;
  }
  const uint16_t req_dur =
      (req_dur_l > 65535L) ? 65535U : static_cast<uint16_t>(req_dur_l);

  const char* side_effect = nullptr;

  if (act_idx == ACT_PUMP_1 || act_idx == ACT_PUMP_2) {
    const char* reject_reason = nullptr;
    uint16_t eff_dur = 0;
    if (!tryTurnOnPump(static_cast<uint8_t>(act_idx), req_dur, &reject_reason, &eff_dur)) {
      publishAck(cmd_id, "rejected", reject_reason, nullptr, nullptr);
      return;
    }
  } else {
    const uint16_t max_run = getMaxRunForActuator(static_cast<uint8_t>(act_idx));
    const uint16_t eff_dur = (req_dur > max_run) ? max_run : req_dur;
    setActuatorPin(static_cast<uint8_t>(act_idx), true);
    g_has_off_deadline[act_idx] = true;
    g_off_deadline_ms[act_idx] = now_ms + static_cast<uint64_t>(eff_dur) * 1000ULL;
  }

  publishAck(cmd_id, "applied", nullptr, applied_ts, side_effect);
  publishStatusNow();
}

void tickActuatorDeadlines() {
  const uint64_t now_ms = millis64();
  bool any_changed = false;
  for (uint8_t i = 0; i < ACT_COUNT; ++i) {
    if (g_has_off_deadline[i] && now_ms >= g_off_deadline_ms[i]) {
      g_has_off_deadline[i] = false;
      if (g_actuator_on[i]) {
        setActuatorPin(i, false);
        any_changed = true;
        if (i == ACT_PUMP_1 || i == ACT_PUMP_2) {
          g_has_last_pump_end[i] = true;
          g_last_pump_end_ms[i] = now_ms;
        }
        Serial.printf("[gw] Auto-off actuator %s\n", ACTUATOR_NAMES[i]);
      }
    }
  }
  if (any_changed) {
    publishStatusNow();
  }
}

// ============================================================================
// Xử lý gói Wi-Fi UDP JSON từ các Sensor Node (chạy trong loop())
// ============================================================================

template <typename T>
T medianWin(const T* arr, uint8_t count) {
  if (count <= 1) return arr[0];
  if (count == 2) {
    return static_cast<T>((static_cast<double>(arr[0]) + static_cast<double>(arr[1])) * 0.5);
  }
  T a = arr[0];
  T b = arr[1];
  T c = arr[2];
  if (a > b) {
    T t = a;
    a = b;
    b = t;
  }
  if (b > c) {
    T t = b;
    b = c;
    c = t;
  }
  if (a > b) {
    b = a;
  }
  return b;
}

void preprocessZoneTelemetry(uint8_t zone_idx, const TelemetryPkt& raw_pkt, bool has_own_air,
                             TelemetryPkt* out_pkt, float* out_air_t, float* out_air_rh) {
  *out_pkt = raw_pkt;
  const int slot = findZoneSlot(zone_idx);
  if (slot < 0) {
    *out_air_t = has_own_air ? (static_cast<float>(raw_pkt.air_t_x100) / 100.0f) : 0.0f;
    *out_air_rh = has_own_air ? (static_cast<float>(raw_pkt.air_rh_x100) / 100.0f) : 0.0f;
    return;
  }

  ZoneFilterState& zf = g_zone_filter[slot];

  // 1. Tiền xử lý Nhiệt độ & Độ ẩm không khí (khi node có cảm biến riêng)
  if (has_own_air) {
    const float raw_air_t = static_cast<float>(raw_pkt.air_t_x100) / 100.0f;
    const float raw_air_rh = static_cast<float>(raw_pkt.air_rh_x100) / 100.0f;
    const bool air_fault = (raw_pkt.flags & FLAG_AHT_ERR) ||
                           !gh::isValidAirTemp(raw_air_t) ||
                           !gh::isValidAirRh(raw_air_rh);
    if (air_fault) {
      // Bảo toàn mẫu lỗi/ngoài dải để backend phát hiện dropout/out_of_range
      *out_air_t = raw_air_t;
      *out_air_rh = raw_air_rh;
      zf.air_spike_streak = 0;
    } else {
      if (!zf.air_init) {
        zf.air_init = true;
        zf.air_count = 1;
        zf.air_idx = 1 % FILTER_WIN;
        zf.air_t_win[0] = raw_air_t;
        zf.air_rh_win[0] = raw_air_rh;
        zf.ema_air_t = raw_air_t;
        zf.ema_air_rh = raw_air_rh;
        zf.air_spike_streak = 0;
      } else {
        const bool is_spike = (fabsf(raw_air_t - zf.ema_air_t) > gh::SPIKE_AIR_T_C) ||
                              (fabsf(raw_air_rh - zf.ema_air_rh) > gh::SPIKE_AIR_RH_PCT);
        if (is_spike && zf.air_spike_streak == 0) {
          // Bỏ qua gai nhiễu đơn lẻ đầu tiên, giữ giá trị đã lọc gần nhất
          zf.air_spike_streak = 1;
        } else if (is_spike) {
          // Hai chu kỳ liên tiếp ở mức mới -> chấp nhận thay đổi thật
          zf.air_spike_streak = 0;
          zf.air_count = 1;
          zf.air_idx = 1 % FILTER_WIN;
          zf.air_t_win[0] = raw_air_t;
          zf.air_rh_win[0] = raw_air_rh;
          zf.ema_air_t = raw_air_t;
          zf.ema_air_rh = raw_air_rh;
        } else {
          zf.air_spike_streak = 0;
          zf.air_t_win[zf.air_idx] = raw_air_t;
          zf.air_rh_win[zf.air_idx] = raw_air_rh;
          zf.air_idx = (zf.air_idx + 1) % FILTER_WIN;
          if (zf.air_count < FILTER_WIN) ++zf.air_count;
          const float med_t = medianWin(zf.air_t_win, zf.air_count);
          const float med_rh = medianWin(zf.air_rh_win, zf.air_count);
          zf.ema_air_t = FILTER_EMA_ALPHA * med_t + (1.0f - FILTER_EMA_ALPHA) * zf.ema_air_t;
          zf.ema_air_rh = FILTER_EMA_ALPHA * med_rh + (1.0f - FILTER_EMA_ALPHA) * zf.ema_air_rh;
        }
      }
      *out_air_t = roundf(zf.ema_air_t * 100.0f) / 100.0f;
      *out_air_rh = roundf(zf.ema_air_rh * 100.0f) / 100.0f;
      out_pkt->air_t_x100 = static_cast<int16_t>(lroundf(*out_air_t * 100.0f));
      out_pkt->air_rh_x100 = static_cast<uint16_t>(lroundf(*out_air_rh * 100.0f));
    }
  }

  // 2. Tiền xử lý Độ ẩm đất (Median-of-3 + Spike Rejection + EMA trên cả soil_raw và soil_pct)
  const ZoneConfig* zc = findZoneConfig(zone_idx);
  const uint16_t dry_raw = zc ? zc->soil_dry_raw : gh::DEFAULT_SOIL_DRY_RAW;
  const uint16_t wet_raw = zc ? zc->soil_wet_raw : gh::DEFAULT_SOIL_WET_RAW;
  const bool soil_fault =
      (raw_pkt.flags & FLAG_SOIL_ERR) || !gh::isValidSoilRaw(raw_pkt.soil_raw);
  if (soil_fault) {
    zf.soil_spike_streak = 0;
  } else {
    // Ưu tiên % độ ẩm đất do Node đã hiệu chuẩn để tránh lệch thang ADC giữa các loại node
    const uint8_t raw_pct = (raw_pkt.soil_pct <= 100)
                                ? raw_pkt.soil_pct
                                : gh::soilPct(raw_pkt.soil_raw, dry_raw, wet_raw);
    if (!zf.soil_init) {
      zf.soil_init = true;
      zf.soil_count = 1;
      zf.soil_idx = 1 % FILTER_WIN;
      zf.soil_win[0] = raw_pkt.soil_raw;
      zf.soil_pct_win[0] = raw_pct;
      zf.ema_soil_raw = static_cast<float>(raw_pkt.soil_raw);
      zf.ema_soil_pct = static_cast<float>(raw_pct);
      zf.soil_spike_streak = 0;
    } else {
      const uint8_t prev_pct = gh::clampPct(static_cast<int>(lroundf(zf.ema_soil_pct)));
      const bool is_spike =
          abs(static_cast<int>(raw_pct) - static_cast<int>(prev_pct)) >
          static_cast<int>(gh::SPIKE_SOIL_PCT);
      if (is_spike && zf.soil_spike_streak == 0) {
        zf.soil_spike_streak = 1;
      } else if (is_spike) {
        zf.soil_spike_streak = 0;
        zf.soil_count = 1;
        zf.soil_idx = 1 % FILTER_WIN;
        zf.soil_win[0] = raw_pkt.soil_raw;
        zf.soil_pct_win[0] = raw_pct;
        zf.ema_soil_raw = static_cast<float>(raw_pkt.soil_raw);
        zf.ema_soil_pct = static_cast<float>(raw_pct);
      } else {
        zf.soil_spike_streak = 0;
        zf.soil_win[zf.soil_idx] = raw_pkt.soil_raw;
        zf.soil_pct_win[zf.soil_idx] = raw_pct;
        zf.soil_idx = (zf.soil_idx + 1) % FILTER_WIN;
        if (zf.soil_count < FILTER_WIN) ++zf.soil_count;
        const uint16_t med_s = medianWin(zf.soil_win, zf.soil_count);
        const uint8_t med_pct = medianWin(zf.soil_pct_win, zf.soil_count);
        zf.ema_soil_raw =
            FILTER_EMA_ALPHA * static_cast<float>(med_s) +
            (1.0f - FILTER_EMA_ALPHA) * zf.ema_soil_raw;
        zf.ema_soil_pct =
            FILTER_EMA_ALPHA * static_cast<float>(med_pct) +
            (1.0f - FILTER_EMA_ALPHA) * zf.ema_soil_pct;
      }
    }
    long filt_raw_l = lroundf(zf.ema_soil_raw);
    if (filt_raw_l < gh::SOIL_RAW_MIN) filt_raw_l = gh::SOIL_RAW_MIN;
    if (filt_raw_l > gh::SOIL_RAW_MAX) filt_raw_l = gh::SOIL_RAW_MAX;
    out_pkt->soil_raw = static_cast<uint16_t>(filt_raw_l);
    out_pkt->soil_pct = gh::clampPct(static_cast<int>(lroundf(zf.ema_soil_pct)));
  }

  // 3. Tiền xử lý Ánh sáng lux
  const bool lux_skip = (raw_pkt.lux == GH_LUX_NONE) || (raw_pkt.flags & FLAG_BH_ERR) ||
                        !gh::isValidLux(raw_pkt.lux);
  if (!lux_skip) {
    if (!zf.lux_init) {
      zf.lux_init = true;
      zf.lux_count = 1;
      zf.lux_idx = 1 % FILTER_WIN;
      zf.lux_win[0] = raw_pkt.lux;
      zf.ema_lux = static_cast<float>(raw_pkt.lux);
    } else {
      zf.lux_win[zf.lux_idx] = raw_pkt.lux;
      zf.lux_idx = (zf.lux_idx + 1) % FILTER_WIN;
      if (zf.lux_count < FILTER_WIN) ++zf.lux_count;
      const uint32_t med_lux = medianWin(zf.lux_win, zf.lux_count);
      zf.ema_lux = FILTER_EMA_ALPHA * static_cast<float>(med_lux) +
                   (1.0f - FILTER_EMA_ALPHA) * zf.ema_lux;
    }
    long filt_lux_l = lroundf(zf.ema_lux);
    if (filt_lux_l < 0) filt_lux_l = 0;
    if (filt_lux_l > static_cast<long>(gh::LUX_MAX)) filt_lux_l = static_cast<long>(gh::LUX_MAX);
    out_pkt->lux = static_cast<uint32_t>(filt_lux_l);
  }
}

void updateZoneTelemetryState(uint8_t zone_idx, const TelemetryPkt& raw_pkt,
                              const TelemetryPkt& filt_pkt, float air_t, float air_rh,
                              bool has_own_air) {
  const int slot = findZoneSlot(zone_idx);
  if (slot < 0) return;

  ZoneTelemetryState& zs = g_zone_state[slot];
  const uint64_t now_ms = millis64();

  // Phát hiện stuck dựa trên dữ liệu thô để EMA không che khuất lỗi treo cảm biến
  if (zs.has_sample) {
    if (raw_pkt.soil_raw == zs.prev_soil_raw) {
      if (zs.stuck_soil_count < 255) ++zs.stuck_soil_count;
    } else {
      zs.stuck_soil_count = 1;
    }
    if (raw_pkt.air_t_x100 == zs.prev_air_t_x100 &&
        raw_pkt.air_rh_x100 == zs.prev_air_rh_x100) {
      if (zs.stuck_air_count < 255) ++zs.stuck_air_count;
    } else {
      zs.stuck_air_count = 1;
    }
  } else {
    zs.stuck_soil_count = 1;
    zs.stuck_air_count = 1;
  }

  zs.has_sample = true;
  zs.has_own_air = has_own_air;
  zs.last_rx_ms = now_ms;
  zs.air_t = air_t;
  zs.air_rh = air_rh;
  zs.soil_pct = filt_pkt.soil_pct;
  zs.soil_raw = filt_pkt.soil_raw;
  zs.flags = filt_pkt.flags;
  zs.prev_soil_raw = raw_pkt.soil_raw;
  zs.prev_air_t_x100 = raw_pkt.air_t_x100;
  zs.prev_air_rh_x100 = raw_pkt.air_rh_x100;

  const bool invalid_air =
      (filt_pkt.flags & FLAG_AHT_ERR) || !gh::isValidAirTemp(air_t) ||
      !gh::isValidAirRh(air_rh) || zs.stuck_air_count >= STUCK_AIR_CYCLES;
  const bool invalid_soil =
      (filt_pkt.flags & FLAG_SOIL_ERR) || !gh::isValidSoilRaw(filt_pkt.soil_raw) ||
      zs.stuck_soil_count >= STUCK_SOIL_CYCLES;

  if ((invalid_air || invalid_soil) &&
      (now_ms - zs.last_invalid_event_ms) >= SENSOR_EVENT_THROTTLE_MS) {
    zs.last_invalid_event_ms = now_ms;
    JsonDocument detail;
    detail["flags"] = filt_pkt.flags;
    detail["soil_raw"] = filt_pkt.soil_raw;
    detail["air_t"] = air_t;
    detail["stuck_soil"] = (zs.stuck_soil_count >= STUCK_SOIL_CYCLES);
    detail["stuck_air"] = (zs.stuck_air_count >= STUCK_AIR_CYCLES);
    emitEvent("sensor_invalid", zone_idx, nullptr, nullptr, nullptr, &detail);
  }
}

bool findSharedAirSample(uint8_t exclude_zone, float* out_air_t, float* out_air_rh,
                         int16_t* out_t_x100, uint16_t* out_rh_x100) {
  const uint64_t now_ms = millis64();
  uint64_t best_rx_ms = 0;
  int best_slot = -1;

  for (uint8_t i = 0; i < MAX_ZONES; ++i) {
    if (i + 1 == exclude_zone) continue;
    const ZoneTelemetryState& zs = g_zone_state[i];
    if (!zs.has_sample || !zs.has_own_air) continue;
    if (zs.flags & FLAG_AHT_ERR) continue;
    if (!gh::isValidAirTemp(zs.air_t) || !gh::isValidAirRh(zs.air_rh)) continue;

    const uint16_t interval_s =
        g_zones[i].in_use ? g_zones[i].sample_interval_s : gh::SENSOR_MEASURE_INTERVAL_S;
    const uint64_t max_age_ms = static_cast<uint64_t>(interval_s) * 3000ULL;
    if ((now_ms - zs.last_rx_ms) > max_age_ms) continue;

    if (best_slot < 0 || zs.last_rx_ms > best_rx_ms) {
      best_rx_ms = zs.last_rx_ms;
      best_slot = i;
    }
  }

  if (best_slot < 0) return false;
  *out_air_t = g_zone_state[best_slot].air_t;
  *out_air_rh = g_zone_state[best_slot].air_rh;
  *out_t_x100 = static_cast<int16_t>(lroundf(g_zone_state[best_slot].air_t * 100.0f));
  *out_rh_x100 = static_cast<uint16_t>(lroundf(g_zone_state[best_slot].air_rh * 100.0f));
  return true;
}

void processUdpTelemetry(const uint8_t mac[6], bool has_mac, IPAddress remote_ip,
                         uint16_t remote_port, int8_t rssi, const TelemetryPkt& pkt) {
  NodeMapEntry* node = has_mac ? findNodeByMac(mac) : nullptr;
  if (!node && pkt.zone > 0) {
    node = findNodeByZone(pkt.zone);
  }
  if (!node && !has_mac && pkt.zone == 0) {
    publishDiscovery(mac, rssi, pkt.fw_major, pkt.fw_minor);
    return;
  }
  if (!node && has_mac && pkt.zone == 0) {
    publishDiscovery(mac, rssi, pkt.fw_major, pkt.fw_minor);
    return;
  }

  uint8_t zone_idx = node ? node->zone : pkt.zone;
  if (zone_idx == 0 || zone_idx > MAX_ZONES) {
    zone_idx = 1;
  }

  if (node) {
    sendCfgJsonToNode(remote_ip, remote_port, node);
    node->has_seen = true;
    node->last_seen_ms = millis64();
    if (pkt.seq != 0) {
      if (node->has_last_seq && node->last_seq == pkt.seq) {
        return;
      }
      node->has_last_seq = true;
      node->last_seq = pkt.seq;
    }
  }

  const bool no_air_sensor =
      (pkt.air_t_x100 == GH_AIR_T_NONE || pkt.air_rh_x100 == GH_AIR_RH_NONE);

  TelemetryPkt eff_pkt = {};
  float air_t = 0.0f;
  float air_rh = 0.0f;
  preprocessZoneTelemetry(zone_idx, pkt, !no_air_sensor, &eff_pkt, &air_t, &air_rh);

  if (no_air_sensor) {
    if (!findSharedAirSample(zone_idx, &air_t, &air_rh, &eff_pkt.air_t_x100,
                             &eff_pkt.air_rh_x100)) {
      eff_pkt.flags |= FLAG_AHT_ERR;
      eff_pkt.air_t_x100 = 0;
      eff_pkt.air_rh_x100 = 0;
    }
  }

  updateZoneTelemetryState(zone_idx, pkt, eff_pkt, air_t, air_rh, !no_air_sensor);

  JsonDocument doc;
  char ts[32];
  currentIso8601Utc(ts, sizeof(ts));
  doc["ts"] = ts;
  doc["zone"] = zone_idx;
  doc["air_t"] = air_t;
  doc["air_rh"] = air_rh;
  doc["soil_m"] = eff_pkt.soil_pct;
  doc["soil_raw"] = eff_pkt.soil_raw;
  if (eff_pkt.lux == GH_LUX_NONE) {
    doc["lux"] = nullptr;
  } else {
    doc["lux"] = eff_pkt.lux;
  }
  doc["batt"] = eff_pkt.vbat_mv;
  doc["rssi"] = rssi;
  doc["flags"] = eff_pkt.flags;
  doc["seq"] = eff_pkt.seq;

  char payload[310];
  const size_t n = serializeJson(doc, payload, sizeof(payload));
  if (n > 0 && n < sizeof(payload)) {
    char suffix[32];
    snprintf(suffix, sizeof(suffix), "telemetry/%u", zone_idx);
    publishOrEnqueue(suffix, payload, true);
  }
}

void pollUdpPackets() {
  if (!g_udp_started) {
    if (WiFi.status() == WL_CONNECTED) {
      g_udp_started = (g_udp.begin(gh::UDP_PORT) != 0);
    }
    if (!g_udp_started) return;
  }

  int pkt_size = g_udp.parsePacket();
  while (pkt_size > 0) {
    char rx_buf[512];
    const int read_len =
        g_udp.read(rx_buf, (pkt_size < static_cast<int>(sizeof(rx_buf) - 1))
                               ? pkt_size
                               : static_cast<int>(sizeof(rx_buf) - 1));
    if (read_len > 0) {
      rx_buf[read_len] = '\0';
      const IPAddress remote_ip = g_udp.remoteIP();
      const uint16_t remote_port = g_udp.remotePort();

      JsonDocument doc;
      if (deserializeJson(doc, rx_buf, read_len) == DeserializationError::Ok) {
        const char* mac_str = doc["mac"] | "";
        uint8_t mac[6] = {0};
        const bool has_mac = parseMacString(mac_str, mac);
        const char* type_str = doc["type"] | "";
        const uint8_t type_num = doc["type"] | 0;
        const int rssi_val = doc["rssi"] | -70;
        const int8_t rssi = static_cast<int8_t>(rssi_val);

        uint8_t inferred_zone = 0;
        if (strncmp(type_str, "node", 4) == 0 && type_str[4] >= '1' && type_str[4] <= '8') {
          inferred_zone = static_cast<uint8_t>(type_str[4] - '0');
        }

        if (inferred_zone > 0 || type_str[0] == '\0' ||
            strcmp(type_str, "telemetry") == 0 || type_num == PKT_TELEMETRY) {
          TelemetryPkt tpkt = {};
          tpkt.type = PKT_TELEMETRY;
          tpkt.zone = doc["zone"] | inferred_zone;
          if (tpkt.zone == 0 && inferred_zone > 0) {
            tpkt.zone = inferred_zone;
          }
          tpkt.seq = doc["seq"] | 0;

          if (!doc["air_t_x100"].isNull()) {
            tpkt.air_t_x100 = doc["air_t_x100"] | GH_AIR_T_NONE;
          } else if (doc["air_t"].isNull()) {
            tpkt.air_t_x100 = GH_AIR_T_NONE;
          } else {
            tpkt.air_t_x100 = static_cast<int16_t>(
                lroundf(doc["air_t"].as<float>() * 100.0f));
          }

          if (!doc["air_rh_x100"].isNull()) {
            tpkt.air_rh_x100 = doc["air_rh_x100"] | GH_AIR_RH_NONE;
          } else if (doc["air_rh"].isNull()) {
            tpkt.air_rh_x100 = GH_AIR_RH_NONE;
          } else {
            tpkt.air_rh_x100 = static_cast<uint16_t>(
                lroundf(doc["air_rh"].as<float>() * 100.0f));
          }

          tpkt.soil_pct = !doc["soil_pct"].isNull()
                              ? static_cast<uint8_t>(doc["soil_pct"] | 0)
                              : static_cast<uint8_t>(doc["soil_m"] | 0);
          if (!doc["soil_raw"].isNull()) {
            tpkt.soil_raw = doc["soil_raw"] | 0;
          } else {
            const ZoneConfig* zc = findZoneConfig(tpkt.zone > 0 ? tpkt.zone : 1);
            const long dry_r = zc ? zc->soil_dry_raw : gh::DEFAULT_SOIL_DRY_RAW;
            const long wet_r = zc ? zc->soil_wet_raw : gh::DEFAULT_SOIL_WET_RAW;
            long calc_raw = dry_r - (static_cast<long>(tpkt.soil_pct) * (dry_r - wet_r)) / 100L;
            if (calc_raw < gh::SOIL_RAW_MIN) calc_raw = gh::SOIL_RAW_MIN;
            if (calc_raw > gh::SOIL_RAW_MAX) calc_raw = gh::SOIL_RAW_MAX;
            tpkt.soil_raw = static_cast<uint16_t>(calc_raw);
          }
          tpkt.flags = doc["flags"] | 0;
          if (doc["lux"].isNull()) {
            tpkt.lux = GH_LUX_NONE;
          } else {
            tpkt.lux = doc["lux"] | GH_LUX_NONE;
          }
          tpkt.vbat_mv = 0;
          tpkt.fw_major = GH_FW_MAJOR;
          tpkt.fw_minor = GH_FW_MINOR;

          processUdpTelemetry(mac, has_mac, remote_ip, remote_port, rssi, tpkt);
        }
      }
    }
    pkt_size = g_udp.parsePacket();
  }
}

// ============================================================================
// Failsafe cục bộ & Buzzer khi mất MQTT quá lâu (spec 4.3, mục 8.2)
// ============================================================================

void tickFailsafeAndBuzzer() {
  const uint64_t now_ms = millis64();
  if (g_mqtt.connected()) {
    if (g_buzzer_on) {
      digitalWrite(PIN_BUZZER, LOW);
      g_buzzer_on = false;
    }
    return;
  }

  const uint64_t offline_ms = now_ms - g_mqtt_disconnected_since_ms;
  if (offline_ms < static_cast<uint64_t>(g_offline_failsafe_after_s) * 1000ULL) {
    return;
  }

  if (!g_failsafe_offline_active) {
    g_failsafe_offline_active = true;
    Serial.println("[gw] FAILSAFE ACTIVE (MQTT offline threshold exceeded)");
  }

  // Kêu còi ngắt quãng: bật 200 ms mỗi 3000 ms
  const uint32_t buzz_period = g_buzzer_on ? 200U : 2800U;
  if ((now_ms - g_last_buzzer_toggle_ms) >= buzz_period) {
    g_buzzer_on = !g_buzzer_on;
    digitalWrite(PIN_BUZZER, g_buzzer_on ? HIGH : LOW);
    g_last_buzzer_toggle_ms = now_ms;
  }

  if ((now_ms - g_last_failsafe_eval_ms) < 2000ULL) {
    return;
  }
  g_last_failsafe_eval_ms = now_ms;

  bool any_temp_high = false;
  bool all_temp_recovered = true;

  for (uint8_t i = 0; i < MAX_ZONES; ++i) {
    const ZoneConfig& zc = g_zones[i];
    const ZoneTelemetryState& zs = g_zone_state[i];
    if (!zc.in_use || !zs.has_sample) continue;

    // Dữ liệu phải còn mới trong vòng 3 chu kỳ đo
    const uint64_t max_age_ms =
        static_cast<uint64_t>(zc.sample_interval_s) * 3000ULL;
    if ((now_ms - zs.last_rx_ms) > max_age_ms) {
      continue;
    }

    // 1. Bảo vệ đất quá khô (chỉ chạy khi cảm biến ẩm đất hoàn toàn hợp lệ)
    const bool soil_valid =
        !(zs.flags & FLAG_SOIL_ERR) && gh::isValidSoilRaw(zs.soil_raw) &&
        zs.soil_pct <= 100 && zs.stuck_soil_count < STUCK_SOIL_CYCLES;
    if (soil_valid && static_cast<float>(zs.soil_pct) < zc.soil_moisture_critical_low_pct &&
        !g_actuator_on[zc.pump_idx]) {
      const char* reject_reason = nullptr;
      uint16_t eff_dur = 0;
      if (tryTurnOnPump(zc.pump_idx, zc.irrigation_max_run_s, &reject_reason, &eff_dur)) {
        JsonDocument fs_detail;
        fs_detail["trigger"] = "soil_low";
        fs_detail["soil_m"] = zs.soil_pct;
        emitEvent("failsafe_start", zc.zone, nullptr, nullptr, nullptr, &fs_detail);

        JsonDocument act_detail;
        act_detail["trigger"] = "soil_low";
        act_detail["duration_s"] = eff_dur;
        emitEvent("actuator_changed", zc.zone, ACTUATOR_NAMES[zc.pump_idx], "on", "failsafe",
                  &act_detail);
      }
    }

    // 2. Bảo vệ quá nhiệt (hysteresis 2 °C)
    const bool air_valid =
        !(zs.flags & FLAG_AHT_ERR) && gh::isValidAirTemp(zs.air_t) &&
        gh::isValidAirRh(zs.air_rh) && zs.stuck_air_count < STUCK_AIR_CYCLES;
    if (air_valid) {
      if (zs.air_t > zc.temp_critical_high_c) {
        any_temp_high = true;
        all_temp_recovered = false;
        if (!g_actuator_on[ACT_FAN]) {
          setActuatorPin(ACT_FAN, true);
          g_has_off_deadline[ACT_FAN] = true;
          g_off_deadline_ms[ACT_FAN] =
              now_ms + static_cast<uint64_t>(zc.fan_max_on_s) * 1000ULL;
          g_failsafe_fan_active = true;

          JsonDocument fs_detail;
          fs_detail["trigger"] = "temp_high";
          fs_detail["air_t"] = zs.air_t;
          emitEvent("failsafe_start", zc.zone, nullptr, nullptr, nullptr, &fs_detail);

          JsonDocument act_detail;
          act_detail["trigger"] = "temp_high";
          act_detail["duration_s"] = zc.fan_max_on_s;
          emitEvent("actuator_changed", zc.zone, "fan", "on", "failsafe", &act_detail);
        }
      } else if (zs.air_t >= (zc.temp_critical_high_c - 2.0f)) {
        all_temp_recovered = false;
      }
    }
  }

  if (g_failsafe_fan_active && !any_temp_high && all_temp_recovered) {
    if (g_actuator_on[ACT_FAN]) {
      setActuatorPin(ACT_FAN, false);
      g_has_off_deadline[ACT_FAN] = false;
      JsonDocument d;
      d["trigger"] = "temp_recovered";
      emitEvent("actuator_changed", 0, "fan", "off", "failsafe", &d);
    }
    g_failsafe_fan_active = false;
  }
}

// ============================================================================
// MQTT Callback, Reconnect & Provisioning
// ============================================================================

void onMqttMessage(char* topic, byte* payload, unsigned int length) {
  char cfg_topic[160];
  buildTopic(cfg_topic, sizeof(cfg_topic), "cfg");
  if (strcmp(topic, cfg_topic) == 0) {
    if (applyCfgJson(reinterpret_cast<const char*>(payload), length, true)) {
      publishStatusNow();
    }
    return;
  }

  char cmd_prefix[160];
  buildTopic(cmd_prefix, sizeof(cmd_prefix), "cmd/");
  if (strncmp(topic, cmd_prefix, strlen(cmd_prefix)) == 0) {
    handleCommandPayload(payload, length);
  }
}

bool hasValidProvisionConfig() {
  return g_prov.mqtt_host[0] != '\0' && g_prov.mqtt_port > 0 &&
         g_prov.mqtt_user[0] != '\0' && g_prov.farm_id[0] != '\0' &&
         g_prov.gh_id[0] != '\0';
}

void loadNvsStringIfSet(Preferences& prefs, const char* key, char* dst, size_t dst_size) {
  String val = prefs.getString(key, "");
  if (val.length() > 0) {
    snprintf(dst, dst_size, "%s", val.c_str());
  }
}

void loadProvisionFromNvs() {
  Preferences prefs;
  if (!prefs.begin(NVS_NAMESPACE, true)) return;

  loadNvsStringIfSet(prefs, "mqtt_host", g_prov.mqtt_host, sizeof(g_prov.mqtt_host));
  const uint16_t saved_port = prefs.getUShort("mqtt_port", g_prov.mqtt_port);
  if (saved_port > 0) g_prov.mqtt_port = saved_port;
  loadNvsStringIfSet(prefs, "mqtt_user", g_prov.mqtt_user, sizeof(g_prov.mqtt_user));
  loadNvsStringIfSet(prefs, "mqtt_pass", g_prov.mqtt_pass, sizeof(g_prov.mqtt_pass));
  loadNvsStringIfSet(prefs, "farm_id", g_prov.farm_id, sizeof(g_prov.farm_id));
  loadNvsStringIfSet(prefs, "gh_id", g_prov.gh_id, sizeof(g_prov.gh_id));

  String cached_cfg = prefs.getString("cfg_json", "");
  prefs.end();

  if (cached_cfg.length() > 0) {
    applyCfgJson(cached_cfg.c_str(), cached_cfg.length(), false);
  }
}

void saveProvisionToNvs() {
  Preferences prefs;
  if (!prefs.begin(NVS_NAMESPACE, false)) return;
  prefs.putString("mqtt_host", g_prov.mqtt_host);
  prefs.putUShort("mqtt_port", g_prov.mqtt_port);
  prefs.putString("mqtt_user", g_prov.mqtt_user);
  prefs.putString("mqtt_pass", g_prov.mqtt_pass);
  prefs.putString("farm_id", g_prov.farm_id);
  prefs.putString("gh_id", g_prov.gh_id);
  prefs.end();
}

void connectWifiAndPortal(bool force_portal) {
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);

  if (!force_portal) {
    Serial.printf("[gw] Connecting to Wi-Fi SSID \"%s\"...\n", gh::WIFI_SSID);
    WiFi.begin(gh::WIFI_SSID, gh::WIFI_PASS);
    const unsigned long start_ms = millis();
    while (WiFi.status() != WL_CONNECTED && (millis() - start_ms) < 15000UL) {
      delay(250);
    }
  }

  if (force_portal || !hasValidProvisionConfig() || WiFi.status() != WL_CONNECTED) {
    WiFiManager wm;
    wm.setConfigPortalTimeout(180);
    wm.preloadWiFi(gh::WIFI_SSID, gh::WIFI_PASS);

    char port_buf[8];
    snprintf(port_buf, sizeof(port_buf), "%u", g_prov.mqtt_port);

    WiFiManagerParameter p_host("mqtt_host", "MQTT Host (domain/IP)", g_prov.mqtt_host, 64);
    WiFiManagerParameter p_port("mqtt_port", "MQTT Port", port_buf, 6);
    WiFiManagerParameter p_user("mqtt_user", "MQTT Username", g_prov.mqtt_user, 64);
    WiFiManagerParameter p_pass("mqtt_pass", "MQTT Password", g_prov.mqtt_pass, 64);
    WiFiManagerParameter p_farm("farm_id", "Farm UUID", g_prov.farm_id, 40);
    WiFiManagerParameter p_gh("gh_id", "Greenhouse UUID", g_prov.gh_id, 40);

    wm.addParameter(&p_host);
    wm.addParameter(&p_port);
    wm.addParameter(&p_user);
    wm.addParameter(&p_pass);
    wm.addParameter(&p_farm);
    wm.addParameter(&p_gh);

    uint8_t mac[6];
    WiFi.macAddress(mac);
    char ap_name[32];
    snprintf(ap_name, sizeof(ap_name), "GreenHub-GW-%02X%02X", mac[4], mac[5]);

    bool connected = false;
    if (force_portal || !hasValidProvisionConfig()) {
      Serial.printf("[gw] Starting Captive Portal %s\n", ap_name);
      connected = wm.startConfigPortal(ap_name);
    } else {
      connected = wm.autoConnect(ap_name);
    }

    snprintf(g_prov.mqtt_host, sizeof(g_prov.mqtt_host), "%s", p_host.getValue());
    const long parsed_port = strtol(p_port.getValue(), nullptr, 10);
    g_prov.mqtt_port = (parsed_port > 0 && parsed_port <= 65535L)
                           ? static_cast<uint16_t>(parsed_port)
                           : 8883;
    snprintf(g_prov.mqtt_user, sizeof(g_prov.mqtt_user), "%s", p_user.getValue());
    snprintf(g_prov.mqtt_pass, sizeof(g_prov.mqtt_pass), "%s", p_pass.getValue());
    snprintf(g_prov.farm_id, sizeof(g_prov.farm_id), "%s", p_farm.getValue());
    snprintf(g_prov.gh_id, sizeof(g_prov.gh_id), "%s", p_gh.getValue());

    if (hasValidProvisionConfig()) {
      saveProvisionToNvs();
    }
    if (!connected && !hasValidProvisionConfig()) {
      Serial.println("[gw] Portal timeout without config, restarting...");
      delay(1000);
      ESP.restart();
    }
  }

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  if (WiFi.status() != WL_CONNECTED || WiFi.SSID() != gh::WIFI_SSID) {
    Serial.printf("[gw] Ensuring connection to Wi-Fi SSID \"%s\"...\n", gh::WIFI_SSID);
    WiFi.begin(gh::WIFI_SSID, gh::WIFI_PASS);
    const unsigned long start_ms = millis();
    while (WiFi.status() != WL_CONNECTED && (millis() - start_ms) < 15000UL) {
      delay(250);
    }
  }
  Serial.printf("[gw] Wi-Fi connected: SSID=%s IP=%s RSSI=%d dBm\n",
                WiFi.SSID().c_str(), WiFi.localIP().toString().c_str(),
                static_cast<int>(WiFi.RSSI()));

  snprintf(g_topic_prefix, sizeof(g_topic_prefix), "gh/%s/%s", g_prov.farm_id,
           g_prov.gh_id);
}

void syncNtpWait() {
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  const unsigned long start_ms = millis();
  while (!isNtpSynced() && (millis() - start_ms) < 10000UL) {
    delay(200);
  }
  if (isNtpSynced()) {
    char ts[32];
    currentIso8601Utc(ts, sizeof(ts));
    Serial.printf("[gw] NTP synced: %s\n", ts);
  } else {
    Serial.println("[gw] NTP sync timeout (will continue in background)");
  }
}

bool attemptMqttConnect() {
  if (WiFi.status() != WL_CONNECTED || !hasValidProvisionConfig()) {
    return false;
  }

  uint8_t mac[6];
  WiFi.macAddress(mac);
  char client_id[48];
  snprintf(client_id, sizeof(client_id), "gh-gw-%02X%02X%02X%02X%02X%02X", mac[0],
           mac[1], mac[2], mac[3], mac[4], mac[5]);

  char lwt_topic[160];
  buildTopic(lwt_topic, sizeof(lwt_topic), "status");

  Serial.printf("[gw] Connecting MQTT TLS %s:%u...\n", g_prov.mqtt_host,
                g_prov.mqtt_port);
  const bool ok =
      g_mqtt.connect(client_id, g_prov.mqtt_user, g_prov.mqtt_pass, lwt_topic, 1,
                     true, "{\"online\":false}");
  if (!ok) {
    Serial.printf("[gw] MQTT connect failed, state=%d\n", g_mqtt.state());
    return false;
  }

  char sub_cmd[160];
  char sub_cfg[160];
  buildTopic(sub_cmd, sizeof(sub_cmd), "cmd/#");
  buildTopic(sub_cfg, sizeof(sub_cfg), "cfg");
  g_mqtt.subscribe(sub_cmd, 1);
  g_mqtt.subscribe(sub_cfg, 1);

  publishStatusNow();
  g_last_heartbeat_ms = millis64();

  if (!g_boot_event_sent) {
    g_boot_event_sent = true;
    JsonDocument d;
    d["fw"] = GH_FW_VERSION_STR;
    d["channel"] = WiFi.channel();
    emitEvent("boot", 0, nullptr, nullptr, nullptr, &d);
  }

  if (g_failsafe_offline_active) {
    g_failsafe_offline_active = false;
    g_failsafe_fan_active = false;
    digitalWrite(PIN_BUZZER, LOW);
    g_buzzer_on = false;
    JsonDocument d;
    d["reason"] = "mqtt_reconnected";
    emitEvent("failsafe_stop", 0, nullptr, nullptr, nullptr, &d);
  }

  g_reconnect_backoff_ms = 1000;
  g_mqtt_was_connected = true;
  Serial.println("[gw] MQTT TLS connected");
  return true;
}

void tickMqttConnection() {
  const uint64_t now_ms = millis64();
  if (g_mqtt.connected()) {
    g_mqtt.loop();
    flushMqttQueue();
    if ((now_ms - g_last_heartbeat_ms) >= HEARTBEAT_INTERVAL_MS) {
      g_last_heartbeat_ms = now_ms;
      publishStatusNow();
    }
    return;
  }

  if (g_mqtt_was_connected) {
    g_mqtt_was_connected = false;
    g_mqtt_disconnected_since_ms = now_ms;
    g_next_reconnect_ms = now_ms + g_reconnect_backoff_ms;
  }

  if (now_ms >= g_next_reconnect_ms) {
    if (!attemptMqttConnect()) {
      g_next_reconnect_ms = now_ms + g_reconnect_backoff_ms;
      if (g_reconnect_backoff_ms < 60000U) {
        g_reconnect_backoff_ms *= 2U;
        if (g_reconnect_backoff_ms > 60000U) {
          g_reconnect_backoff_ms = 60000U;
        }
      }
    }
  }
}

void tickStatusLed() {
  const uint64_t now_ms = millis64();
  uint32_t period_ms = 1000;
  if (g_failsafe_offline_active) {
    period_ms = 150;
  } else if (g_mqtt.connected()) {
    period_ms = 1000;
  } else {
    period_ms = 350;
  }
  if ((now_ms - g_last_led_toggle_ms) >= period_ms) {
    g_led_on = !g_led_on;
    digitalWrite(PIN_LED, g_led_on ? HIGH : LOW);
    g_last_led_toggle_ms = now_ms;
  }
}

bool shouldForcePortalOnBoot() {
  if (digitalRead(PIN_BOOT_BTN) == LOW) {
    delay(1200);
    return digitalRead(PIN_BOOT_BTN) == LOW;
  }
  return false;
}

}  // namespace

void setup() {
  initActuatorsOff();
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_BUZZER, LOW);
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);
  pinMode(PIN_BOOT_BTN, INPUT_PULLUP);

  Serial.begin(115200);
  WiFi.mode(WIFI_STA);
  initDefaultZones();
  loadProvisionFromNvs();

  Serial.printf("[gw] GreenHub gateway fw %s, MAC %s\n", GH_FW_VERSION_STR,
                WiFi.macAddress().c_str());

  const bool force_portal = shouldForcePortalOnBoot();
  connectWifiAndPortal(force_portal);
  syncNtpWait();

  g_udp_started = (g_udp.begin(gh::UDP_PORT) != 0);
  if (g_udp_started) {
    Serial.printf("[gw] UDP JSON server listening on port %u\n", gh::UDP_PORT);
  } else {
    Serial.printf("[gw] Failed to start UDP server on port %u\n", gh::UDP_PORT);
  }

  ArduinoOTA.setHostname("gateway");
  ArduinoOTA.onStart([]() {
    initActuatorsOff();
    Serial.println("[gw] OTA Update Start");
  });
  ArduinoOTA.onEnd([]() {
    Serial.println("\n[gw] OTA Update End");
  });
  ArduinoOTA.onError([](ota_error_t error) {
    Serial.printf("[gw] OTA Error[%u]\n", error);
  });
  ArduinoOTA.begin();
  Serial.println("[gw] ArduinoOTA ready (hostname: gateway.local)");

  g_tls_client.setCACert(GH_CA_CERT_BUNDLE_PEM);
  g_mqtt.setBufferSize(MQTT_MAX_PACKET_SIZE);
  g_mqtt.setSocketTimeout(5);
  g_mqtt.setKeepAlive(15);
  g_mqtt.setServer(g_prov.mqtt_host, g_prov.mqtt_port);
  g_mqtt.setCallback(onMqttMessage);

  g_mqtt_disconnected_since_ms = millis64();
  if (!attemptMqttConnect()) {
    g_next_reconnect_ms = millis64() + g_reconnect_backoff_ms;
  }
}

void loop() {
  ArduinoOTA.handle();
  pollUdpPackets();
  tickActuatorDeadlines();
  tickMqttConnection();
  tickFailsafeAndBuzzer();
  tickStatusLed();
  delay(10);
}
