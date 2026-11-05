#!/usr/bin/env bash
# Tạo CA tự ký + chứng chỉ server cho Mosquitto TLS khi phát triển trên laptop.
# Dùng: bash deploy/scripts/gen-dev-certs.sh [LAN_IP]
#   LAN_IP: IP cố định của laptop trong LAN (để gateway ESP32 thật kết nối). Mặc định bỏ qua.
# Không có openssl (Windows)? Chạy qua Docker:
#   docker run --rm -v "${PWD}:/w" -w /w alpine/openssl sh deploy/scripts/gen-dev-certs.sh 192.168.1.10
# Kết quả: deploy/certs/{ca.crt, ca.key, server.crt, server.key}
#   ca.crt -> nhúng vào firmware gateway / simulator để kiểm tra chứng chỉ.
set -eu
export MSYS_NO_PATHCONV=1

LAN_IP="${1:-}"
DIR="$(cd "$(dirname "$0")/.." && pwd)/certs"
mkdir -p "$DIR"
cd "$DIR"

SAN="DNS:localhost,DNS:mosquitto,IP:127.0.0.1"
[ -n "$LAN_IP" ] && SAN="$SAN,IP:$LAN_IP"

if [ ! -f ca.key ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
    -keyout ca.key -out ca.crt -subj "/CN=GreenHub Dev CA"
fi

openssl req -newkey rsa:2048 -nodes -keyout server.key -out server.csr -subj "/CN=localhost"
printf "subjectAltName=%s\nextendedKeyUsage=serverAuth\n" "$SAN" > server.ext
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days 825 -sha256 -extfile server.ext
rm -f server.csr server.ext ca.srl
chmod 644 server.key   # container mosquitto sao chép rồi tự chmod 600

echo "Đã tạo chứng chỉ trong $DIR (SAN: $SAN)"

