# Feature: Triển khai Docker Compose, Caddy HTTPS, VPS Linux & Bảo mật (`deploy/`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 1, 2.2, 3.1, 3.2, 12, 13, 15, 16 (M4, M6); `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Đóng gói và vận hành toàn bộ GreenHub stack trên cùng một bộ định nghĩa Docker Compose cho cả **Laptop phát triển (`dev`)** và **một VPS Linux (`prod`)** của nhà cung cấp bất kỳ (trong nước hoặc quốc tế):
1. Tự động khởi động 5 container (`timescaledb`, `mosquitto`, `api`, `worker`, `caddy`) chỉ với `.env` hợp lệ, không thao tác thủ công ngoài `alembic upgrade head` tự chạy trong `api`.
2. Đảm bảo vừa khít ngân sách RAM **2 GB** (cấu hình VPS tối thiểu) thông qua memory limit từng service và 2 GB swap trên host; VPS 4 GB (khuyến nghị) giữ nguyên các limit này để có dư địa.
3. Dùng **Caddy** làm Reverse Proxy HTTPS (tự động xin/gia hạn chứng chỉ Let's Encrypt cho tên miền riêng hoặc DuckDNS) và chia sẻ chính chứng chỉ đó sang Mosquitto `:8883`.
4. Hardening VPS (`ufw`, SSH chỉ key, `unattended-upgrades`, `fail2ban`), áp dụng checklist bảo mật mạng/dữ liệu/điện áp và quy trình sao lưu tự động hằng ngày (`backup.sh`) kèm kéo bản sao về laptop bằng `rsync`/`scp`.

- **Ngoài phạm vi (TUYỆT ĐỐI KHÔNG dùng):** Dịch vụ cloud managed (AWS IoT Core, RDS, Lambda… và các dịch vụ tương đương ở nhà cung cấp khác như managed PostgreSQL/MQTT/serverless), Grafana, Redis, Kubernetes/microservice tách rời, hoặc đấu tải điện 220 V AC trong demo.

## 2. Trạng thái hiện thực trong repo

- **Đã hoàn thiện (M1–M2 nền):**
  - `deploy/docker-compose.yml`: định nghĩa 5 service chính, healthcheck, `restart: unless-stopped`, memory limits và 5 named volumes.
  - `deploy/docker-compose.dev.yml` & `deploy/docker-compose.prod.yml`: override tách biệt môi trường `dev` vs `prod` (VPS).
  - `platform/Dockerfile` & `platform/docker-entrypoint.sh`: single image Python 3.12 cho `api` và `worker` (chứa cả `ml/` và `libgomp1` cho LightGBM), user non-root `greenhub` (UID 1000).
  - `deploy/caddy/Dockerfile` & `deploy/caddy/Caddyfile`: multi-stage build `web/` (`node:22-alpine` -> `caddy:2.8-alpine`), proxy `/api/*` & `/ws*`, SPA fallback + `no-cache` cho `sw.js`/`manifest.json`, HSTS/security headers.
  - `deploy/scripts/gen-dev-certs.sh` (và `tools/gen_dev_certs.py`): tạo CA + server cert dev có SAN cho `localhost`, `mosquitto`, `127.0.0.1` và `LAN_IP`.
  - `deploy/backup.sh` & `.env.example`.
- **Cần thực hiện & kiểm chứng tại M4 & M6:**
  - Thuê VPS (mục 5.2), cài Ubuntu 24.04 LTS, tạo 2 GB swap, hardening SSH, `ufw`, cài Docker Engine + Compose plugin, trỏ bản ghi A của tên miền về IP VPS.
  - Kiểm tra `deploy/docker-compose.prod.yml` **chỉ publish `80`, `443` (TCP + UDP) và `8883`**; không publish `5432`, `1883`, `8000` (Docker bỏ qua `ufw`, xem mục 5.2.3).
  - Deploy bằng `docker-compose.prod.yml`, kiểm chứng Let's Encrypt HTTPS, `openssl s_client` trên `:8883` với tên miền, Web Push trên Android/iOS, thử tải 50–100 gateway giả lập từ laptop (M5).
  - Cập nhật `deploy/backup.sh` theo mục 7: giữ **7** bản (hiện mã đang `KEEP=14`) và sao lưu thêm thư mục/volume `/models`.
  - Cài đặt 2 cronjob trên VPS (`backup.sh` 03:00 UTC hằng ngày + `restart mosquitto` ngày 1 hằng tháng) và kéo toàn bộ DB/models/video về laptop định kỳ, đặc biệt trước khi kết thúc hợp đồng thuê VPS (M6).

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
| `api` | `platform/Dockerfile` (`context: ..`), `cmd: ["api"]` | *Nội bộ* (dev: `127.0.0.1:8000`) | `384m` | Chờ `timescaledb` healthy; `curl /api/health` (15s × 10, start 20s) | Chạy `alembic upgrade head` trước khi bật `uvicorn --proxy-headers --forwarded-allow-ips='*'`. Volume `models`. **Không** import `pandas`/`scikit-learn`/`lightgbm`. |
| `worker` | `platform/Dockerfile` (`context: ..`), `cmd: ["worker"]` | *Không* | `512m` | Chờ `timescaledb`, `mosquitto`, `api` healthy | Chạy `python -m worker.main` (`aiomqtt` + APScheduler + suy luận mô hình năng suất/gợi ý cây trồng LightGBM từ `/models/yield/v{n}.joblib`, chạy trong `asyncio.to_thread`). Volume `models`. |
| `caddy` | `deploy/caddy/Dockerfile` (`context: ..`) | `80`, `443`, `443/udp` | `128m` | `depends_on: api` | Multi-stage Node 22 build `web/dist` vào `/srv`; Volumes `caddy_data`, `caddy_config`. |

- **Image dùng chung `greenhub-platform:latest`:** `platform/Dockerfile` cài `libgomp1` (runtime cho LightGBM), `curl` (healthcheck), copy cả `platform/` và `ml/` vào `/app` (để có thể chạy `python -m ml.train --task yield` trong container `worker` hoặc nạp artifact từ `/models`), chạy dưới user `greenhub` (UID `1000`). **Không** chứa `pytest`/`ruff` (chỉ có ở `requirements-dev.txt`).
- **Huấn luyện trên VPS 2 GB:** `ml.train` SHOULD chạy trên laptop (kết nối DB dev hoặc bản dump kéo về) rồi chép artifact lên `/models`; nếu chạy trên VPS thì dùng `docker compose ... exec worker python -m ml.train --task yield` ngoài giờ thử tải (tận dụng swap 2 GB). Sau khi kích hoạt mô hình, `ml/train.py` gửi `NOTIFY worker_events {type:"model_activated"}` để worker nạp lại.

## 4. Reverse Proxy & TLS với Caddy (`deploy/caddy/`)

1. **Multi-stage build (`deploy/caddy/Dockerfile`):**
   - Stage 1 (`node:22-alpine`): `npm ci` từ `web/package-lock.json` rồi `npm run build` sinh `web/dist/`.
   - Stage 2 (`caddy:2.8-alpine`): copy `/web/dist` vào `/srv` và `deploy/caddy/Caddyfile` vào `/etc/caddy/Caddyfile`.
2. **Định tuyến & Bảo mật (`deploy/caddy/Caddyfile`):**
   - Site block `{$DOMAIN:localhost}`: tự động dùng internal CA trên `localhost` (`dev`), hoặc tự xin chứng chỉ **Let's Encrypt** (ACME HTTP-01/TLS-ALPN-01 qua cổng 80/443) trên tên miền công cộng (`prod`). Điều kiện: bản ghi A đã trỏ đúng IP VPS và cổng 80/443 mở ở cả `ufw` lẫn firewall mạng của nhà cung cấp.
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
  - `127.0.0.1:15432:5432` → cho `ml/train.py`, `ml/dataset.py`, `tools/seed_dev.py`, công cụ DB chạy trên Windows không đụng Postgres local 5432.
  - `127.0.0.1:1883:1883` → cho `mosquitto_sub`/`mosquitto_pub` debug trên laptop.
  - `127.0.0.1:8000:8000` → cho `npm run dev` (Vite proxy port 5173) gọi API/WS trực tiếp.
- Chứng chỉ TLS dev cho Mosquitto (`deploy/certs:/certs:ro`):
  - Sinh bằng `python -m tools.gen_dev_certs [LAN_IP]` hoặc `bash deploy/scripts/gen-dev-certs.sh [LAN_IP]` (khi thử Gateway ESP32 thật trong mạng Wi-Fi LAN, truyền **IP cố định** của laptop làm `[LAN_IP]` để SAN hợp lệ và nhúng `deploy/certs/ca.crt` vào firmware/simulator).

### 5.2 Production trên VPS Linux (`deploy/docker-compose.prod.yml` & Spec §13.3)

#### 5.2.1 Chọn VPS & thông số hạ tầng bắt buộc

| Hạng mục | Cấu hình chuẩn | Lưu ý vận hành |
|---|---|---|
| Nhà cung cấp | VPS bất kỳ (trong nước hoặc quốc tế) có **IPv4 công khai tĩnh** | MUST cho phép mở cổng `80`/`443`/`8883` từ Internet (không chặn cổng tuỳ ý, không CGNAT). Ưu tiên datacenter tại Việt Nam/Singapore để giảm độ trễ cho Gateway ESP32 & WebSocket. |
| CPU & RAM | **2 vCPU, 2 GB RAM** tối thiểu (khuyến nghị **4 GB**), x86_64 | VPS giá rẻ thường dùng **vCPU chia sẻ**: chạy thử tải theo đợt ngắn, ghi rõ cấu hình VPS trong báo cáo. |
| OS & Ổ đĩa | Ubuntu 24.04 LTS, SSD ≥ 40 GB + **Swap 2 GB** | Swap 2 GB giúp tránh OOM khi `docker build` Caddy/Node hoặc worker nạp/huấn luyện mô hình ML. |
| Tên miền | Tên miền riêng hoặc DuckDNS, bản ghi **A** trỏ về IP VPS | Gateway firmware **bắt buộc dùng tên miền** (không dùng IP) để verify TLS cert Let's Encrypt. |
| Không dùng | Dịch vụ managed của nhà cung cấp (DB, MQTT, serverless, object storage bắt buộc) | Toàn bộ stack chạy trong Docker Compose trên một VPS. |

#### 5.2.2 Hardening SSH & hệ điều hành

| Hạng mục | Yêu cầu | Mức |
|---|---|---|
| Tài khoản | Tạo user thường (ví dụ `deploy`) + quyền `sudo` + nhóm `docker`; không vận hành bằng `root` | MUST |
| SSH | Chỉ đăng nhập bằng key: `PasswordAuthentication no`, `PermitRootLogin no`, `KbdInteractiveAuthentication no` | MUST |
| Cập nhật | `unattended-upgrades` bật cập nhật bảo mật tự động | MUST |
| Chống dò mật khẩu | `fail2ban` jail `sshd` | SHOULD |
| Giờ hệ thống | Host giữ múi giờ **UTC** (cron trong mục 7 tính theo UTC); container dùng `TZ=Asia/Ho_Chi_Minh` từ `.env` | SHOULD |

#### 5.2.3 Firewall `ufw` & lưu ý Docker bỏ qua `ufw`

| Cổng | Nguồn | Mục đích |
|---|---|---|
| `22/TCP` | **Nên giới hạn IP quản trị**, chỉ SSH key | SSH quản trị server. |
| `80/TCP`, `443/TCP`, `443/UDP` | Mọi nơi | Web Console HTTPS, ACME HTTP-01, HTTP/3 (QUIC). |
| `8883/TCP` | Mọi nơi | MQTT over TLS cho Gateway ESP32 & Simulator. |
| `1883`, `5432`, `8000` và mọi cổng khác | **ĐÓNG HOÀN TOÀN** (`default deny incoming`) | Chỉ giao tiếp nội bộ trong Docker bridge network. |

> [!WARNING]
> Docker ghi trực tiếp rule `iptables` (chain `DOCKER`) cho các cổng được publish (`ports:`), nên **cổng publish của container bỏ qua `ufw`**. Vì vậy `deploy/docker-compose.prod.yml` **MUST chỉ publish `80`, `443`, `443/udp` và `8883`**; tuyệt đối không publish `5432`, `1883`, `8000` (kể cả "tạm thời để debug"). Khi cần truy cập DB từ laptop, dùng SSH tunnel: `ssh -L 15432:127.0.0.1:5432 ...` kết hợp `docker compose exec`, hoặc publish dạng `127.0.0.1:...` (chỉ loopback). Nếu nhà cung cấp có firewall mạng (cloud firewall/security panel), cấu hình cùng tập luật như bảng trên.

#### 5.2.4 Chứng chỉ TLS dùng chung Caddy → Mosquitto

- `mosquitto` mount `caddy_data:/caddy-data:ro` và `depends_on: caddy`. Trong `.env` phải đặt đúng đường dẫn cert Let's Encrypt do Caddy cấp:
  ```dotenv
  DOMAIN=<ten-mien>            # vd greenhub.example.vn hoặc <sub>.duckdns.org
  MQTT_PUBLIC_HOST=<ten-mien>
  MQTT_PUBLIC_PORT=8883
  MQTT_TLS_CERTFILE=/caddy-data/caddy/certificates/acme-v02.api.letsencrypt.org-directory/<DOMAIN>/<DOMAIN>.crt
  MQTT_TLS_KEYFILE=/caddy-data/caddy/certificates/acme-v02.api.letsencrypt.org-directory/<DOMAIN>/<DOMAIN>.key
  TZ=Asia/Ho_Chi_Minh
  ```
- Lần khởi động đầu tiên Caddy cần vài chục giây để xin cert; nếu `mosquitto` báo thiếu file cert thì chờ Caddy xong rồi `docker compose ... restart mosquitto`.
- Entrypoint Mosquitto **sao chép** cert khi khởi động → cron `restart mosquitto` hằng tháng (mục 7) để nạp cert sau gia hạn.

#### 5.2.5 Các bước triển khai từng lệnh (Ubuntu 24.04)

```bash
# --- 0. Trên laptop: kiểm tra DNS đã trỏ đúng IP VPS ---
nslookup <DOMAIN>

# --- 1. Đăng nhập root lần đầu, tạo user quản trị ---
ssh root@<VPS_IP>
adduser deploy && usermod -aG sudo deploy
mkdir -p /home/deploy/.ssh && cp ~/.ssh/authorized_keys /home/deploy/.ssh/
chown -R deploy:deploy /home/deploy/.ssh && chmod 700 /home/deploy/.ssh && chmod 600 /home/deploy/.ssh/authorized_keys

# --- 2. Hardening SSH (mở phiên SSH mới bằng user deploy để thử trước khi đóng phiên root) ---
sudo tee /etc/ssh/sshd_config.d/99-greenhub.conf >/dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
sudo systemctl restart ssh

# --- 3. Cập nhật hệ thống, cập nhật bảo mật tự động, fail2ban ---
sudo apt update && sudo apt -y upgrade
sudo apt -y install unattended-upgrades fail2ban git rsync
sudo dpkg-reconfigure -plow unattended-upgrades
sudo systemctl enable --now fail2ban

# --- 4. Swap 2 GB ---
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# --- 5. Firewall ufw (giới hạn SSH theo IP quản trị nếu có IP tĩnh) ---
sudo ufw default deny incoming && sudo ufw default allow outgoing
sudo ufw allow from <ADMIN_IP> to any port 22 proto tcp   # hoặc: sudo ufw allow 22/tcp
sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw allow 443/udp && sudo ufw allow 8883/tcp
sudo ufw enable && sudo ufw status verbose

# --- 6. Cài Docker Engine + Compose plugin (repo chính thức Docker) ---
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker deploy && newgrp docker
docker version && docker compose version

# --- 7. Lấy mã nguồn & cấu hình .env ---
git clone <REPO_URL> ~/greenhub && cd ~/greenhub
cp .env.example .env && chmod 600 .env
nano .env   # DOMAIN, MQTT_PUBLIC_HOST, MQTT_TLS_*, mật khẩu DB/MQTT, JWT_SECRET, VAPID_*, SMTP_*, TZ

# --- 8. Kiểm tra compose ghép nối & chỉ publish 80/443/8883 ---
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml config | grep -A3 'ports:'

# --- 9. Khởi chạy stack prod ---
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml ps

# --- 10. Xác nhận từ bên ngoài (chạy trên laptop) ---
curl -fsS https://<DOMAIN>/api/health
openssl s_client -connect <DOMAIN>:8883 -servername <DOMAIN> </dev/null
nmap -Pn -p 22,80,443,1883,5432,8000,8883 <DOMAIN>   # 1883/5432/8000 phải filtered/closed
```

- **Cập nhật phiên bản mới:** `cd ~/greenhub && git pull && docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build` (migration tự chạy trong `api`).
- **Theo dõi tài nguyên:** `docker stats --no-stream`, `free -h`; tổng memory limit 1.792 MB, phần còn lại + swap dành cho OS và `docker build`.

## 6. Bảng Biến Môi trường (`.env.example` → `.env`)

File `.env` nằm trong `.gitignore`, tuyệt đối không commit. Khi chạy script Python trên laptop (`ml/train.py`, `ml/dataset.py`, `tools/seed_dev.py`) nhớ sự khác biệt host (`timescaledb:5432` vs `127.0.0.1:15432`, `mosquitto` vs `127.0.0.1`). Không có biến riêng của nhà cung cấp cloud nào:

| Nhóm | Biến môi trường | Giá trị mẫu / Ghi chú |
|---|---|---|
| **DB** | `POSTGRES_USER`, `POSTGRES_DB`, `POSTGRES_PASSWORD` | Tài khoản khởi tạo container `timescaledb`. |
| **DB URL** | `DATABASE_URL` | `postgresql+asyncpg://greenhub:<pw>@timescaledb:5432/greenhub` (ngoài Docker dùng `@127.0.0.1:15432`). |
| **Auth** | `JWT_SECRET`, `JWT_EXPIRE_MIN` | Chuỗi random dài tối thiểu 32+ bytes; mặc định `720` phút (12 h). |
| **MQTT Nội bộ** | `MQTT_HOST`, `MQTT_PORT`, `MQTT_WORKER_USER`, `MQTT_WORKER_PASSWORD`, `MQTT_ADMIN_USER`, `MQTT_ADMIN_PASSWORD` | `mosquitto` / `1883` trong Docker (`127.0.0.1` ngoài Docker). |
| **MQTT Public & TLS** | `MQTT_PUBLIC_HOST`, `MQTT_PUBLIC_PORT`, `MQTT_TLS_CERTFILE`, `MQTT_TLS_KEYFILE` | Trả về từ `POST /api/gateways`; prod là `<DOMAIN>:8883` + path cert Caddy. |
| **Web Push** | `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | Sinh từ `python -m tools.gen_vapid`; subject dạng `mailto:admin@example.com`. |
| **Email SMTP** | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL_FROM` | Leo thang cảnh báo `critical` chưa ack; TLS `587`. Một số VPS chặn cổng SMTP 25 — dùng 587 của dịch vụ email. |
| **Triển khai** | `DOMAIN`, `MODELS_DIR`, `LOG_LEVEL`, `TZ` | `localhost` (dev) hoặc tên miền VPS (prod); `/models`; `INFO`; `Asia/Ho_Chi_Minh` (dùng cho đặc trưng khí hậu ngày/đêm, dữ liệu vẫn lưu ts UTC). |

## 7. Sao lưu, Cronjob & Vòng đời Dữ liệu (`deploy/backup.sh`)

- **Cơ chế `deploy/backup.sh`:**
  1. Nạp biến từ `.env` gốc repo (`POSTGRES_USER`, `POSTGRES_DB`).
  2. Chạy `docker compose -f deploy/docker-compose.yml exec -T timescaledb pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > backups/greenhub_<UTC_STAMP>.dump` (định dạng PostgreSQL custom nén sẵn, phục hồi nhanh bằng `pg_restore`).
  3. MUST sao lưu thêm thư mục mô hình `/models` (volume `models`), ví dụ `docker compose -f deploy/docker-compose.yml exec -T worker tar -C /models -czf - . > backups/models_<UTC_STAMP>.tar.gz`.
  4. Xoay vòng giữ lại đúng **7** bản sao lưu gần nhất cho mỗi loại (`ls -1t ... | tail -n +8 | xargs -r rm -f`). *(Mã hiện tại đang `KEEP=14`, cần chỉnh theo spec.)*
- **2 Cronjob bắt buộc trên VPS (`crontab -e` của user `deploy`, giờ UTC):**
  ```cron
  # 1. Sao lưu DB + models mỗi ngày lúc 03:00 UTC
  0 3 * * * /home/deploy/greenhub/deploy/backup.sh >> /home/deploy/greenhub/backups/backup.log 2>&1

  # 2. Restart Mosquitto mỗi tháng (04:00 UTC ngày 1) để nạp cert Let's Encrypt mới từ Caddy
  0 4 1 * * cd /home/deploy/greenhub && docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml restart mosquitto
  ```
- **Kéo bản sao về laptop (SHOULD hằng tuần, MUST trước M6/kết thúc thuê VPS):**
  ```bash
  rsync -avz deploy@<DOMAIN>:~/greenhub/backups/ ./backups/
  # hoặc: scp deploy@<DOMAIN>:~/greenhub/backups/greenhub_*.dump ./backups/
  ```
- **Phục hồi:** `docker compose ... exec -T timescaledb pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean < backups/greenhub_<STAMP>.dump`; giải nén `models_<STAMP>.tar.gz` vào volume `models` rồi restart `worker`.

## 8. Checklist Bảo mật Toàn hệ thống (Spec §12, MUST)

- [ ] **Mật khẩu & Secret:** Băm Argon2/bcrypt; JWT có `exp`; `.env`, `.dev-gateway.json`, `deploy/certs/`, `*.key`, `*.pem`, `backups/` nằm trong `.gitignore`; `.env` trên VPS `chmod 600`.
- [ ] **VPS:** SSH chỉ key, `PermitRootLogin no`, `ufw` default deny + chỉ mở 22/80/443/8883, `unattended-upgrades` bật, SHOULD `fail2ban`; compose prod không publish `5432`/`1883`/`8000`.
- [ ] **MQTT Broker:** Cấm anonymous, chỉ mở `:8883` TLS ra ngoài, mỗi gateway có user + Dynamic Security ACL khóa chặt theo `farm_id`/`greenhouse_id`.
- [ ] **CSDL & API:** TimescaleDB không mở ra ngoài (không có Redis); API kiểm tra JWT + RBAC (`viewer` / `operator` / `owner`) + lọc `farm_id` trên mọi truy vấn và WebSocket; bảng `yield_samples` **không bao giờ** trả qua API, `GET /models` chỉ trả số liệu tổng hợp.
- [ ] **An toàn AI:** Tuyệt đối không dùng LLM; AI chỉ dự báo năng suất (`yield_forecast`) và gợi ý cây trồng (`crop_recommendation`), **không** gửi lệnh tới thiết bị. Điều khiển chỉ do Rule Engine (hysteresis cố định) và `GatewaySafetyEngine` đảm nhiệm.
- [ ] **An toàn điện vật lý (Demo):** Toàn bộ bơm mini (3–6 V), quạt, máy tạo ẩm chỉ dùng nguồn **5 V DC** có diode `1N4007` chống EMF ngược và tụ lọc `1000 µF`; **TUYỆT ĐỐI KHÔNG** đấu tải AC 220 V.

## 9. Kiểm tra & Xác nhận Khởi động sạch

```bash
# 1. Kiểm tra file Compose ghép nối hợp lệ (không warning thiếu biến)
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml config >/dev/null
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml config >/dev/null

# 2. Khởi động sạch stack dev (bắt buộc cả 5 service đều healthy/up, tự migrate DB)
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up -d --build
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml ps

# 3. Kiểm tra health HTTPS API & TLS MQTT trên Prod (sau khi deploy VPS)
curl -fsS https://<DOMAIN>/api/health
openssl s_client -connect <DOMAIN>:8883 -servername <DOMAIN> </dev/null

# 4. Xác nhận cổng nội bộ không lộ ra Internet (chạy từ laptop)
nmap -Pn -p 1883,5432,8000 <DOMAIN>
```
