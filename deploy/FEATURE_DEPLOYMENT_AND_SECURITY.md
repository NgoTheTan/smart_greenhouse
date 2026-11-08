# Feature: Triển khai Docker Compose, Caddy HTTPS, AWS EC2 & Bảo mật (`deploy/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 1, 2.2, 3.1, 3.2, 12, 13, 15, 16 (M4, M6); `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Đóng gói và vận hành toàn bộ GreenHub stack trên cùng một bộ định nghĩa Docker Compose cho cả **Laptop phát triển (`dev`)** và **AWS EC2 `t3.small` (`prod`)**:
1. Tự động khởi động 5 container (`timescaledb`, `mosquitto`, `api`, `worker`, `caddy`) chỉ với `.env` hợp lệ, không thao tác thủ công ngoài `alembic upgrade head` tự chạy trong `api`.
2. Đảm bảo vừa khít ngân sách RAM **2 GB** của EC2 `t3.small` thông qua memory limit từng service và 2 GB swap trên host.
3. Dùng **Caddy** làm Reverse Proxy HTTPS (tự động xin/gia hạn chứng chỉ Let's Encrypt bằng tên miền DuckDNS) và chia sẻ chính chứng chỉ đó sang Mosquitto `:8883`.
4. Áp dụng checklist bảo mật mạng/dữ liệu/điện áp và quy trình sao lưu tự động hằng ngày (`backup.sh`) trước khi Free plan hết hạn.

- **Ngoài phạm vi (TUYỆT ĐỐI KHÔNG dùng):** AWS IoT Core, AWS RDS (không hỗ trợ TimescaleDB), AWS Lambda, Grafana, Redis, Kubernetes/microservice tách rời, hoặc đấu tải điện 220 V AC trong demo.

## 2. Trạng thái hiện thực trong repo

- **Đã hoàn thiện (M1–M2 nền):**
  - `deploy/docker-compose.yml`: định nghĩa 5 service chính, healthcheck, `restart: unless-stopped`, memory limits và 5 named volumes.
  - `deploy/docker-compose.dev.yml` & `deploy/docker-compose.prod.yml`: override tách biệt môi trường `dev` vs `prod`.
  - `platform/Dockerfile` & `platform/docker-entrypoint.sh`: single image Python 3.12 cho `api` và `worker` (chứa cả `ml/` và `libgomp1` cho LightGBM), user non-root `greenhub` (UID 1000).
  - `deploy/caddy/Dockerfile` & `deploy/caddy/Caddyfile`: multi-stage build `web/` (`node:22-alpine` -> `caddy:2.8-alpine`), proxy `/api/*` & `/ws*`, SPA fallback + `no-cache` cho `sw.js`/`manifest.json`, HSTS/security headers.
  - `deploy/scripts/gen-dev-certs.sh` (và `tools/gen_dev_certs.py`): tạo CA + server cert dev có SAN cho `localhost`, `mosquitto`, `127.0.0.1` và `LAN_IP`.
  - `deploy/backup.sh` & `.env.example`.
- **Cần thực hiện & kiểm chứng tại M4 & M6:**
  - Khởi tạo EC2 `t3.small` (Ubuntu 24.04 LTS, `ap-southeast-1`), cấu hình 2 GB swap, Elastic IP, DuckDNS, Security Group.
  - Deploy bằng `docker-compose.prod.yml`, kiểm chứng Let's Encrypt HTTPS, `openssl s_client` trên `:8883` với tên miền DuckDNS, Web Push trên Android/iOS, thử tải từ laptop.
  - Cài đặt 2 cronjob trên EC2 (`backup.sh` 03:00 UTC hằng ngày + `restart mosquitto` ngày 1 hằng tháng) và sao lưu toàn bộ DB/models/video về laptop trước hạn AWS Free plan (M6).

## 3. Kiến trúc Docker Compose & Ngân sách Tài nguyên

### 3.1 Quy ước biến môi trường trong Compose (`docs/DECISIONS.md`)

- File `deploy/docker-compose.yml` **KHÔNG dùng interpolation `${VAR}`**; tất cả biến được truyền vào container qua `env_file: ../.env`.
- Ngoại lệ duy nhất là escape `$$` cho shell inside-container trong `healthcheck` (`$${POSTGRES_USER}`, `$${MQTT_ADMIN_USER}`) và `{$DOMAIN:localhost}` đọc từ environment của container Caddy.
- Nhờ vậy chỉ cần duy nhất 1 file `.env` ở gốc repo (không cần giữ `.env` trùng trong `deploy/`).

### 3.2 Chi tiết 5 Service & Giới hạn RAM (Tổng = 1.792 MB / 2.048 MB)

| Service | Image / Build | Port ngoài | Memory Limit | Phụ thuộc & Healthcheck | Cấu hình đặc biệt |
|---|---|---|---|---|---|
| `timescaledb` | `timescale/timescaledb:2.17.2-pg16` | *Đóng* (dev: `127.0.0.1:15432`) | `640m` | `pg_isready` (10s × 10) | `shared_buffers=256MB`, `max_connections=50`. Volume `pgdata`. |
| `mosquitto` | `eclipse-mosquitto:2.0.20` | `8883` (dev: `127.0.0.1:1883`) | `128m` | `mosquitto_ctrl ... getDefaultACLAccess` (15s × 10, start 10s) | Custom entrypoint `/greenhub-entrypoint.sh`; Volume `mosquitto_data`. |
| `api` | `platform/Dockerfile` (`context: ..`), `cmd: ["api"]` | *Nội bộ* (dev: `127.0.0.1:8000`) | `384m` | Chờ `timescaledb` healthy; `curl /api/health` (15s × 10, start 20s) | Chạy `alembic upgrade head` trước khi bật `uvicorn --proxy-headers --forwarded-allow-ips='*'`. Volume `models`. |
| `worker` | `platform/Dockerfile` (`context: ..`), `cmd: ["worker"]` | *Không* | `512m` | Chờ `timescaledb`, `mosquitto`, `api` healthy | Chạy `python -m worker.main` (`aiomqtt` + APScheduler + LightGBM joblib). Volume `models`. |
| `caddy` | `deploy/caddy/Dockerfile` (`context: ..`) | `80`, `443`, `443/udp` | `128m` | `depends_on: api` | Multi-stage Node 22 build `web/dist` vào `/srv`; Volumes `caddy_data`, `caddy_config`. |

- **Image dùng chung `greenhub-platform:latest`:** `platform/Dockerfile` cài `libgomp1` (runtime cho LightGBM), `curl` (healthcheck), copy cả `platform/` và `ml/` vào `/app` (để `worker` có thể chạy `ml.train` hoặc nạp artifact từ `/models`), chạy dưới user `greenhub` (UID `1000`). **Không** chứa `pytest`/`ruff` (chỉ có ở `requirements-dev.txt`).

## 4. Reverse Proxy & TLS với Caddy (`deploy/caddy/`)

1. **Multi-stage build (`deploy/caddy/Dockerfile`):**
   - Stage 1 (`node:22-alpine`): `npm ci` từ `web/package-lock.json` rồi `npm run build` sinh `web/dist/`.
   - Stage 2 (`caddy:2.8-alpine`): copy `/web/dist` vào `/srv` và `deploy/caddy/Caddyfile` vào `/etc/caddy/Caddyfile`.
2. **Định tuyến & Bảo mật (`deploy/caddy/Caddyfile`):**
   - Site block `{$DOMAIN:localhost}`: tự động dùng internal CA trên `localhost` (`dev`), hoặc tự xin chứng chỉ **Let's Encrypt** trên tên miền công cộng (`prod`).
   - Nén `encode zstd gzip`.
   - `handle /api/*` & `handle /ws*` → `reverse_proxy api:8000` (chuyển tiếp cả HTTP REST và WebSocket Upgrade kèm header gốc).
   - `handle` (tất cả đường dẫn còn lại): `root * /srv`, `try_files {path} /index.html` phục vụ React Router SPA.
   - `@sw path /sw.js /manifest.json` → `header @sw Cache-Control "no-cache"` để trình duyệt luôn kiểm tra bản Service Worker & manifest mới nhất.
   - Security headers toàn cục: `Strict-Transport-Security "max-age=31536000"`, `X-Content-Type-Options nosniff`, `Referrer-Policy strict-origin-when-cross-origin`.

## 5. Hai Môi trường Vận hành (`dev` vs `prod`)

### 5.1 Laptop Phát triển (`deploy/docker-compose.dev.yml`)

- Lệnh khởi chạy:
  ```powershell
  docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up -d --build
  ```
- Bind cổng loopback an toàn trên `127.0.0.1`:
  - `127.0.0.1:15432:5432` → cho `ml/train.py`, `tools/seed_dev.py`, công cụ DB chạy trên Windows không đụng Postgres local 5432.
  - `127.0.0.1:1883:1883` → cho `mosquitto_sub`/`mosquitto_pub` debug trên laptop.
  - `127.0.0.1:8000:8000` → cho `npm run dev` (Vite proxy port 5173) gọi API/WS trực tiếp.
- Chứng chỉ TLS dev cho Mosquitto (`deploy/certs:/certs:ro`):
  - Sinh bằng `python -m tools.gen_dev_certs [LAN_IP]` hoặc `bash deploy/scripts/gen-dev-certs.sh [LAN_IP]` (khi thử Gateway ESP32 thật trong mạng Wi-Fi LAN, truyền **IP cố định** của laptop làm `[LAN_IP]` để SAN hợp lệ và nhúng `deploy/certs/ca.crt` vào firmware/simulator).

### 5.2 Production trên AWS EC2 (`deploy/docker-compose.prod.yml` & Spec §13.3)

- Lệnh khởi chạy:
  ```bash
  docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build
  ```
- Cơ chế dùng chung chứng chỉ TLS: `mosquitto` mount `caddy_data:/caddy-data:ro` và `depends_on: caddy`. Trong `.env` phải đặt đúng đường dẫn cert Let's Encrypt do Caddy cấp:
  ```dotenv
  DOMAIN=<ten-mien>.duckdns.org
  MQTT_PUBLIC_HOST=<ten-mien>.duckdns.org
  MQTT_PUBLIC_PORT=8883
  MQTT_TLS_CERTFILE=/caddy-data/caddy/certificates/acme-v02.api.letsencrypt.org-directory/<DOMAIN>/<DOMAIN>.crt
  MQTT_TLS_KEYFILE=/caddy-data/caddy/certificates/acme-v02.api.letsencrypt.org-directory/<DOMAIN>/<DOMAIN>.key
  ```
- **Thông số hạ tầng AWS EC2 bắt buộc (spec §13.3):**

| Hạng mục | Cấu hình chuẩn | Lưu ý vận hành |
|---|---|---|
| Tài khoản | AWS Free plan (tài khoản mới) | Tự đóng sau 6 tháng hoặc khi hết credit → xuất dữ liệu, model, video trước hạn! |
| Region | `ap-southeast-1` (Singapore) | Giảm độ trễ từ Việt Nam cho Gateway ESP32 & WebSocket. |
| Instance | `t3.small` (2 vCPU, 2 GB RAM, x86) | Instance burstable: tránh chạy thử tải liên tục kéo dài làm cạn `CPUCreditBalance`. |
| OS & Ổ đĩa | Ubuntu 24.04 LTS, EBS `gp3` 20–30 GB + **Swap 2 GB** | Swap 2 GB giúp tránh OOM khi `docker build` Caddy/Node hoặc worker nạp/train ML. |
| IP & Tên miền | Elastic IP + tên miền DuckDNS | Gateway firmware **bắt buộc dùng tên miền** (không dùng IP) để verify TLS cert Let's Encrypt. |

- **AWS Security Group (Inbound Rules):**

| Cổng | Nguồn | Mục đích |
|---|---|---|
| `22/TCP` | **Chỉ IP quản trị**, chỉ SSH key | SSH quản trị server (`PasswordAuthentication no`). |
| `80/TCP`, `443/TCP`, `443/UDP` | `0.0.0.0/0` (Mọi nơi) | Web Console HTTPS, ACME HTTP-01, HTTP/3 (QUIC). |
| `8883/TCP` | `0.0.0.0/0` (Mọi nơi) | MQTT over TLS cho Gateway ESP32 & Simulator. |
| `1883`, `5432`, `8000` | **ĐÓNG HOÀN TOÀN** | Chỉ giao tiếp nội bộ trong Docker bridge network. |

## 6. Bảng Biến Môi trường (`.env.example` → `.env`)

File `.env` nằm trong `.gitignore`, tuyệt đối không commit. Khi chạy script Python trên laptop (`ml/train.py`, `tools/seed_dev.py`) nhớ sự khác biệt host (`timescaledb:5432` vs `127.0.0.1:15432`, `mosquitto` vs `127.0.0.1`):

| Nhóm | Biến môi trường | Giá trị mẫu / Ghi chú |
|---|---|---|
| **DB** | `POSTGRES_USER`, `POSTGRES_DB`, `POSTGRES_PASSWORD` | Tài khoản khởi tạo container `timescaledb`. |
| **DB URL** | `DATABASE_URL` | `postgresql+asyncpg://greenhub:<pw>@timescaledb:5432/greenhub` (ngoài Docker dùng `@127.0.0.1:15432`). |
| **Auth** | `JWT_SECRET`, `JWT_EXPIRE_MIN` | Chuỗi random dài tối thiểu 32+ bytes; mặc định `720` phút (12 h). |
| **MQTT Nội bộ** | `MQTT_HOST`, `MQTT_PORT`, `MQTT_WORKER_USER`, `MQTT_WORKER_PASSWORD`, `MQTT_ADMIN_USER`, `MQTT_ADMIN_PASSWORD` | `mosquitto` / `1883` trong Docker (`127.0.0.1` ngoài Docker). |
| **MQTT Public & TLS** | `MQTT_PUBLIC_HOST`, `MQTT_PUBLIC_PORT`, `MQTT_TLS_CERTFILE`, `MQTT_TLS_KEYFILE` | Trả về từ `POST /api/gateways`; prod là `<DOMAIN>:8883` + path cert Caddy. |
| **Web Push** | `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | Sinh từ `python -m tools.gen_vapid`; subject dạng `mailto:admin@example.com`. |
| **Email SMTP** | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL_FROM` | Leo thang cảnh báo `critical` chưa ack; TLS `587`. |
| **Triển khai** | `DOMAIN`, `MODELS_DIR`, `LOG_LEVEL` | `localhost` (dev) hoặc `<sub >.duckdns.org` (prod); `/models`; `INFO`. |

## 7. Sao lưu, Cronjob & Vòng đời Dữ liệu (`deploy/backup.sh`)

- **Cơ chế `deploy/backup.sh`:**
  1. Nạp biến từ `.env` gốc repo (`POSTGRES_USER`, `POSTGRES_DB`).
  2. Chạy `docker compose -f deploy/docker-compose.yml exec -T timescaledb pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > backups/greenhub_<UTC_STAMP>.dump` (định dạng PostgreSQL custom nén sẵn, phục hồi nhanh bằng `pg_restore`).
  3. Xoay vòng giữ lại đúng **`KEEP=14`** bản sao lưu gần nhất (`ls -1t ... | tail -n +15 | xargs -r rm -f`).
- **2 Cronjob bắt buộc trên EC2 (`crontab -e`):**
  ```cron
  # 1. Sao lưu DB mỗi ngày lúc 03:00 UTC
  0 3 * * * /home/ubuntu/greenhub/deploy/backup.sh >> /home/ubuntu/greenhub/backups/backup.log 2>&1

  # 2. Restart Mosquitto mỗi tháng (04:00 UTC ngày 1) để nạp cert Let's Encrypt mới từ Caddy
  0 4 1 * * cd /home/ubuntu/greenhub && docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml restart mosquitto
  ```
- **Xuất dữ liệu trước hạn Free plan (M6):** Định kỳ kéo `backups/*.dump` và sao chép volume `models` về laptop bằng `scp` / `docker compose cp`.

## 8. Checklist Bảo mật Toàn hệ thống (Spec §12, MUST)

- [ ] **Mật khẩu & Secret:** Băm Argon2/bcrypt; JWT có `exp`; `.env`, `.dev-gateway.json`, `deploy/certs/`, `*.key`, `*.pem`, `backups/` nằm trong `.gitignore`.
- [ ] **MQTT Broker:** Cấm anonymous, chỉ mở `:8883` TLS ra ngoài, mỗi gateway có user + Dynamic Security ACL khóa chặt theo `farm_id`/`greenhouse_id`.
- [ ] **CSDL & API:** TimescaleDB & Redis (không có) không mở ra ngoài; API kiểm tra JWT + RBAC (`viewer` / `operator` / `owner`) + lọc `farm_id` trên mọi truy vấn và WebSocket.
- [ ] **An toàn AI trong vòng điều khiển:** Tuyệt đối không dùng LLM; AI chỉ sinh dự báo (`DISEASE_RISK_FORECAST`) hoặc tham số độ lợi (`adaptive`) bị chặn trong biên an toàn `GatewaySafetyEngine`.
- [ ] **An toàn điện vật lý (Demo):** Toàn bộ bơm mini (3–6 V), quạt, máy tạo ẩm chỉ dùng nguồn **5 V DC** có diode `1N4007` chống EMF ngược và tụ lọc `1000 µF`; **TUYỆT ĐỐI KHÔNG** đấu tải AC 220 V.

## 9. Kiểm tra & Xác nhận Khởi động sạch

```bash
# 1. Kiểm tra file Compose ghép nối hợp lệ (không warning thiếu biến)
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml config >/dev/null

# 2. Khởi động sạch stack dev (bắt buộc cả 5 service đều healthy/up, tự migrate DB)
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up -d --build
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml ps

# 3. Kiểm tra health HTTPS API & TLS MQTT trên Prod (sau khi deploy EC2)
curl -fsS https://<DOMAIN>/api/health
openssl s_client -connect <DOMAIN>:8883 -servername <DOMAIN> </dev/null
```
