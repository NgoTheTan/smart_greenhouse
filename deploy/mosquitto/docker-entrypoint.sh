#!/bin/sh
# Entrypoint Mosquitto cho GreenHub:
#  1) Sao chép chứng chỉ TLS (dev: tự ký; prod: của Caddy) và chown cho user mosquitto
#  2) Lần đầu: khởi tạo Dynamic Security với user api-admin, tạo user worker + role toàn quyền gh/#
#  3) Chạy mosquitto (tự hạ quyền xuống user mosquitto)
set -e

: "${MQTT_TLS_CERTFILE:?MQTT_TLS_CERTFILE chưa đặt}"
: "${MQTT_TLS_KEYFILE:?MQTT_TLS_KEYFILE chưa đặt}"
: "${MQTT_ADMIN_USER:?}" "${MQTT_ADMIN_PASSWORD:?}" "${MQTT_WORKER_USER:?}" "${MQTT_WORKER_PASSWORD:?}"

if [ ! -f "$MQTT_TLS_CERTFILE" ] || [ ! -f "$MQTT_TLS_KEYFILE" ]; then
  echo "[mosquitto] Không tìm thấy chứng chỉ: $MQTT_TLS_CERTFILE / $MQTT_TLS_KEYFILE" >&2
  echo "[mosquitto] Dev: chạy deploy/scripts/gen-dev-certs.sh trước." >&2
  exit 1
fi

mkdir -p /mosquitto/certs
cp "$MQTT_TLS_CERTFILE" /mosquitto/certs/server.crt
cp "$MQTT_TLS_KEYFILE" /mosquitto/certs/server.key
chmod 644 /mosquitto/certs/server.crt
chmod 600 /mosquitto/certs/server.key
chown -R mosquitto:mosquitto /mosquitto/certs /mosquitto/data

DYNSEC=/mosquitto/data/dynamic-security.json
FIRST_RUN=0
if [ ! -f "$DYNSEC" ]; then
  echo "[mosquitto] Khởi tạo Dynamic Security ($MQTT_ADMIN_USER)"
  mosquitto_ctrl dynsec init "$DYNSEC" "$MQTT_ADMIN_USER" "$MQTT_ADMIN_PASSWORD"
  chown mosquitto:mosquitto "$DYNSEC"
  FIRST_RUN=1
fi

mosquitto -c /mosquitto/config/mosquitto.conf &
PID=$!
trap 'kill -TERM $PID 2>/dev/null' TERM INT

if [ "$FIRST_RUN" = "1" ]; then
  ctrl() { mosquitto_ctrl -h 127.0.0.1 -p 1883 -u "$MQTT_ADMIN_USER" -P "$MQTT_ADMIN_PASSWORD" dynsec "$@"; }
  i=0
  until ctrl getDefaultACLAccess >/dev/null 2>&1; do
    i=$((i + 1)); [ "$i" -gt 30 ] && { echo "[mosquitto] broker không sẵn sàng" >&2; break; }
    sleep 1
  done
  echo "[mosquitto] Tạo user worker + role worker-role (gh/#)"
  ctrl createRole worker-role || true
  ctrl addRoleACL worker-role publishClientSend 'gh/#' allow || true
  ctrl addRoleACL worker-role publishClientReceive 'gh/#' allow || true
  ctrl addRoleACL worker-role subscribePattern 'gh/#' allow || true
  ctrl createClient "$MQTT_WORKER_USER" -p "$MQTT_WORKER_PASSWORD" || true
  ctrl addClientRole "$MQTT_WORKER_USER" worker-role || true
fi

wait "$PID"

