# GreenHub – Nền tảng IoT nhà kính thông minh

Giám sát và điều khiển nhà kính đa vùng, đa loại cây: Node ESP32 → (ESP-NOW) → Gateway ESP32 → (MQTT TLS) → Cloud tự xây (FastAPI + TimescaleDB + Mosquitto) → Web console PWA.

- Đặc tả: [docs/greenhub-spec.md](docs/greenhub-spec.md)
- Kế hoạch nhóm: [docs/greenhub-team-plan.md](docs/greenhub-team-plan.md)
- Quyết định kỹ thuật: [docs/DECISIONS.md](docs/DECISIONS.md)

## Cấu trúc repo

```
firmware/
  common/gh_common/   # struct gói tin ESP-NOW, hằng số dùng chung (lib PlatformIO)
  node/               # PlatformIO project – sensor node
  gateway/            # PlatformIO project – gateway + relay
platform/             # Backend Python 3.12 (gốc import: api, worker, core)
  api/                # FastAPI: REST, WebSocket, auth, provisioning
  worker/             # MQTT ingest, rules, commands, alerts, notify, inference, scheduler
  core/               # config, db, models, schemas, vpd/dli
  migrations/         # Alembic
  tests/
web/                  # React 18 + Vite + TS, PWA (public/manifest.json, sw.js)
ml/                   # train.py, features.py, evaluate.py, notebooks/
tools/simulator/      # Simulator gateway/node
tools/gen_vapid.py    # Sinh khoá VAPID cho Web Push
tools/gen_dev_certs.py # Sinh chứng chỉ TLS tự ký cho dev (đa nền tảng)
deploy/               # docker-compose*.yml, mosquitto/, caddy/, scripts/, backup.sh
docs/
```

## Yêu cầu

| Công cụ | Phiên bản | Dùng cho |
|---|---|---|
| Docker Desktop | 24+ (Compose v2) | Chạy toàn bộ stack |
| Python | 3.12 | Backend, ML, simulator, PlatformIO CLI |
| Node.js | 20+ | Web console |
| PlatformIO | VS Code extension hoặc `pio` (đã có trong `.venv`) | Firmware ESP32 |
| Git Bash / openssl | – | Tạo chứng chỉ dev |

## Bắt đầu nhanh (laptop)

```powershell
# 1. Biến môi trường
Copy-Item .env.example .env        # rồi sửa mật khẩu, JWT_SECRET...

# 2. Python venv (backend + ml + simulator + pio)
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r platform/requirements-dev.txt
python -m tools.gen_vapid           # chép 2 dòng VAPID_* vào .env

# 3. Chứng chỉ TLS dev cho Mosquitto (thêm IP LAN của laptop nếu dùng gateway thật)
python -m tools.gen_dev_certs 192.168.1.10   # hoặc: bash deploy/scripts/gen-dev-certs.sh 192.168.1.10

# 4. Chạy stack
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up -d --build
#    https://localhost          -> web console (Caddy, chứng chỉ nội bộ)
#    https://localhost/api/docs -> OpenAPI
#    mqtts://localhost:8883     -> broker cho gateway/simulator

# 5. Phát triển web với hot reload (proxy /api -> 127.0.0.1:8000)
cd web; npm install; npm run dev    # http://localhost:5173
```

### Kiểm thử và lint

```powershell
pytest                 # đọc cấu hình từ pyproject.toml (PYTHONPATH = platform;.)
ruff check .
npm run build --prefix web
```

### Firmware

```powershell
cd firmware/node;    pio run -e node_demo -t upload; pio device monitor
cd firmware/gateway; pio run -t upload
```

### ML và simulator (chạy từ gốc repo)

```powershell
$env:PYTHONPATH = "platform;."
python -m ml.train --task risk_forecast --zone all
python -m tools.simulator --farms 2 --gateways 5 --nodes-per-gw 2 --interval 10 --scenario normal
```

Khi chạy Python ngoài Docker, đổi host trong `.env`: `DATABASE_URL=...@localhost:5432/...`, `MQTT_HOST=localhost`.

## Triển khai AWS (prod)

```bash
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build
```

Xem spec mục 13: EC2 t3.small (ap-southeast-1), Elastic IP + DuckDNS, Security Group chỉ mở 22 (IP quản trị), 80/443, 8883. Trong `.env` đặt `DOMAIN`, `MQTT_PUBLIC_HOST` là tên miền, và `MQTT_TLS_*` trỏ tới chứng chỉ Caddy. Cron: `deploy/backup.sh` hằng ngày, `restart mosquitto` hằng tháng.

## Milestone

M1 phần cứng + ESP-NOW + MQTT → M2 ingestion/DB/cmd-ack → M3 web + rule engine + alert → M4 provisioning + EC2 + simulator → M5 AI/ML → M6 demo. Chi tiết ở spec mục 16.

