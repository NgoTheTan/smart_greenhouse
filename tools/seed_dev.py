"""Khởi tạo dữ liệu mẫu idempotent cho môi trường phát triển cục bộ (M2–M4).

Chạy từ gốc repo (sau khi stack Docker dev đang chạy):
    .venv\\Scripts\\python.exe -m tools.seed_dev

Tạo:
- Farm: "Nông trại Demo GreenHub"
- Users: owner / operator / viewer @greenhub.vn (mật khẩu: greenhub123)
- Greenhouse: "Nhà kính Fomex 01" với Zone 1 (Cà chua bi demo) và Zone 2 (Dâu tây demo)
- Gateway + cấp phát tài khoản MQTT Dynamic Security + 2 Node mẫu ghép sẵn (lưu `.dev-gateway.json`)
"""

import asyncio
import json
import os
import secrets
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLATFORM_DIR = REPO_ROOT / "platform"
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))


def _patch_host_env_if_outside_docker() -> None:
    """Khi chạy từ laptop (ngoài container), tự chuyển hostname nội bộ Docker về 127.0.0.1."""
    if Path("/.dockerenv").exists():
        return
    from core.config import get_settings

    s = get_settings()
    if "@timescaledb:5432" in s.database_url:
        os.environ["DATABASE_URL"] = s.database_url.replace(
            "@timescaledb:5432", "@127.0.0.1:15432"
        )
    if s.mqtt_host == "mosquitto":
        os.environ["MQTT_HOST"] = "127.0.0.1"
    get_settings.cache_clear()


async def seed() -> dict:
    _patch_host_env_if_outside_docker()

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from api.provisioning import provision_gateway_mqtt
    from core.config import get_settings
    from core.crop_templates import TEMPLATE_STRAWBERRY_DEMO_ID, TEMPLATE_TOMATO_DEMO_ID
    from core.models import (
        DeviceNode,
        DeviceState,
        Farm,
        Gateway,
        Greenhouse,
        NotificationPref,
        User,
        Zone,
    )
    from core.pubsub import CHANNEL_WORKER, pg_notify
    from core.security import hash_password

    s = get_settings()
    eng = create_async_engine(s.database_url, pool_pre_ping=True)
    maker = async_sessionmaker(eng, expire_on_commit=False)

    dev_gw_file = REPO_ROOT / ".dev-gateway.json"

    try:
        async with maker() as session:
            owner = (
                await session.execute(
                    select(User).where(User.email == "owner@greenhub.vn")
                )
            ).scalar_one_or_none()

            if owner is None:
                farm = Farm(name="Nông trại Demo GreenHub")
                session.add(farm)
                await session.flush()

                pw_hash = hash_password("greenhub123")
                for email, role in (
                    ("owner@greenhub.vn", "owner"),
                    ("operator@greenhub.vn", "operator"),
                    ("viewer@greenhub.vn", "viewer"),
                ):
                    u = User(
                        farm_id=farm.id, email=email, password_hash=pw_hash, role=role
                    )
                    session.add(u)
                    await session.flush()
                    session.add(NotificationPref(user_id=u.id))
                    if role == "owner":
                        owner = u
            else:
                farm = await session.get(Farm, owner.farm_id)
                assert farm is not None

            gh = (
                await session.execute(
                    select(Greenhouse).where(
                        Greenhouse.farm_id == farm.id,
                        Greenhouse.name == "Nhà kính Fomex 01",
                    )
                )
            ).scalar_one_or_none()

            if gh is None:
                gh = Greenhouse(
                    farm_id=farm.id,
                    name="Nhà kính Fomex 01",
                    location="Phòng thí nghiệm IoT",
                )
                session.add(gh)
                await session.flush()

                z1 = Zone(
                    greenhouse_id=gh.id,
                    zone_index=1,
                    name="Zone 1 – Cà chua bi",
                    crop_profile_id=TEMPLATE_TOMATO_DEMO_ID,
                    pump_channel=1,
                    soil_dry_raw=2900,
                    soil_wet_raw=1300,
                )
                z2 = Zone(
                    greenhouse_id=gh.id,
                    zone_index=2,
                    name="Zone 2 – Dâu tây",
                    crop_profile_id=TEMPLATE_STRAWBERRY_DEMO_ID,
                    pump_channel=2,
                    soil_dry_raw=2900,
                    soil_wet_raw=1300,
                )
                session.add_all([z1, z2])
                await session.flush()

                for mac, zone_obj in (
                    ("AA:BB:CC:DD:EE:01", z1),
                    ("AA:BB:CC:DD:EE:02", z2),
                ):
                    existing_node = (
                        await session.execute(
                            select(DeviceNode).where(DeviceNode.mac_address == mac)
                        )
                    ).scalar_one_or_none()
                    if existing_node is None:
                        session.add(
                            DeviceNode(
                                mac_address=mac,
                                greenhouse_id=gh.id,
                                zone_id=zone_obj.id,
                                status="paired",
                            )
                        )
                    else:
                        existing_node.greenhouse_id = gh.id
                        existing_node.zone_id = zone_obj.id
                        existing_node.status = "paired"
                session.add(
                    DeviceState(
                        greenhouse_id=gh.id,
                        reported={},
                        desired={},
                        cfg_version_desired=1,
                        cfg_version_reported=0,
                    )
                )

            gw = (
                await session.execute(select(Gateway).where(Gateway.greenhouse_id == gh.id))
            ).scalar_one_or_none()

            mqtt_username = gw.mqtt_username if gw else f"gw_{gh.id.hex[:12]}"
            mqtt_password = secrets.token_urlsafe(20)
            if dev_gw_file.exists():
                saved = json.loads(dev_gw_file.read_text(encoding="utf-8"))
                if saved.get("greenhouse_id") == str(gh.id) and saved.get("mqtt_password"):
                    mqtt_password = str(saved["mqtt_password"])

            await provision_gateway_mqtt(farm.id, gh.id, mqtt_username, mqtt_password)

            if gw is None:
                gw = Gateway(
                    greenhouse_id=gh.id,
                    mqtt_username=mqtt_username,
                    is_simulated=True,
                    online=False,
                )
                session.add(gw)
                await session.flush()

            await pg_notify(
                session, CHANNEL_WORKER, {"type": "cfg_updated", "greenhouse_id": str(gh.id)}
            )
            await session.commit()

            result = {
                "gateway_id": str(gw.id),
                "farm_id": str(farm.id),
                "greenhouse_id": str(gh.id),
                "mqtt_username": mqtt_username,
                "mqtt_password": mqtt_password,
                "host": s.mqtt_public_host,
                "port": s.mqtt_public_port,
                "is_simulated": gw.is_simulated,
            }
            dev_gw_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
            return result
    finally:
        await eng.dispose()


def main() -> None:
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    info = asyncio.run(seed(), loop_factory=loop_factory)
    print("Seed hoàn tất! Thông tin gateway đã lưu vào .dev-gateway.json:")
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
