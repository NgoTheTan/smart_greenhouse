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
  if [ "${MQTT_TLS_AUTO_SELFSIGNED:-0}" = "1" ]; then
    echo "[mosquitto] Tự sinh chứng chỉ TLS self-signed tại $MQTT_TLS_CERTFILE"
    command -v openssl >/dev/null 2>&1 || apk add --no-cache openssl >/dev/null
    mkdir -p "$(dirname "$MQTT_TLS_CERTFILE")" "$(dirname "$MQTT_TLS_KEYFILE")"
    SAN="DNS:localhost,DNS:mosquitto,IP:127.0.0.1,DNS:127.0.0.1"
    PUB_HOST="${MQTT_PUBLIC_HOST:-}"
    CN="localhost"
    if [ -n "$PUB_HOST" ] && [ "$PUB_HOST" != "localhost" ] && [ "$PUB_HOST" != "127.0.0.1" ]; then
      CN="$PUB_HOST"
      SAN="$SAN,DNS:$PUB_HOST"
      case "$PUB_HOST" in
        *[!0-9.]*) ;;
        *.*.*.*) SAN="$SAN,IP:$PUB_HOST" ;;
      esac
    fi
    openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
      -keyout "$MQTT_TLS_KEYFILE" -out "$MQTT_TLS_CERTFILE" \
      -subj "/CN=$CN" \
      -addext "subjectAltName=$SAN" \
      -addext "extendedKeyUsage=serverAuth"
  else
    echo "[mosquitto] Không tìm thấy chứng chỉ: $MQTT_TLS_CERTFILE / $MQTT_TLS_KEYFILE" >&2
    echo "[mosquitto] Dev: chạy deploy/scripts/gen-dev-certs.sh trước." >&2
    exit 1
  fi
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

