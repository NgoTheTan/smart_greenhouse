"""Cơ sở dữ liệu Dev SQLite & Tự động Seed khi chạy không có Docker/PostgreSQL."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlalchemy.ext.compiler import compiles


@compiles(UUID, "sqlite")
def _compile_uuid_for_sqlite(type_, compiler, **kw):
    return "TEXT"


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(type_, compiler, **kw):
    return "JSON"

from core.crop_templates import (
    SYSTEM_CROP_TEMPLATES,
    TEMPLATE_STRAWBERRY_DEMO_ID,
    TEMPLATE_TOMATO_DEMO_ID,
)
from core.db import Base
from core.security import hash_password
from core.vpd import calc_vpd

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEV_DB_FILE = _REPO_ROOT / "greenhub_dev.sqlite3"
DEV_SQLITE_URL = f"sqlite+aiosqlite:///{DEV_DB_FILE.as_posix()}"

log = logging.getLogger("core.dev_db")

FARM_ID = uuid.UUID("11111111-fa7a-4111-8111-111111111111")
USER_ID = uuid.UUID("22222222-05e7-4222-8222-222222222222")
GREENHOUSE_ID = uuid.UUID("33333333-6800-4333-8333-333333333333")
GATEWAY_ID = uuid.UUID("44444444-9a7e-4444-8444-444444444444")
ZONE_1_ID = uuid.UUID("55555555-2001-4555-8555-55555555555a")
ZONE_2_ID = uuid.UUID("55555555-2002-4555-8555-55555555555b")
CYCLE_1_ID = uuid.UUID("66666666-c7c1-4666-8666-66666666666a")
CYCLE_2_ID = uuid.UUID("66666666-c7c2-4666-8666-66666666666b")
MODEL_ID = uuid.UUID("77777777-a100-4777-8777-777777777777")


async def init_dev_database(engine: AsyncEngine) -> None:
    """Tạo bảng và seed dữ liệu mẫu vào SQLite để test frontend không cần Docker."""
    from core.models import (
        CropCycle,
        CropProfile,
        DeviceNode,
        DeviceState,
        Farm,
        Gateway,
        Greenhouse,
        MlModel,
        Reading,
        User,
        Zone,
    )
    # Bỏ các cú pháp riêng của PostgreSQL trong server_default (::jsonb, gen_random_uuid)
    for t in Base.metadata.tables.values():
        for col in t.columns:
            if col.server_default is not None:
                arg_str = str(col.server_default.arg)
                if "::" in arg_str or "gen_random_uuid" in arg_str:
                    col.server_default = None

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Tạo bảng liên tục readings_1m và readings_1h cho SQLite
        await conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS readings_1m (
                bucket TIMESTAMP NOT NULL,
                zone_id UUID NOT NULL,
                air_temp FLOAT,
                air_rh FLOAT,
                vpd FLOAT,
                soil_moisture FLOAT,
                lux FLOAT,
                n INTEGER
            );
            """
            )
        )
        await conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS readings_1h (
                bucket TIMESTAMP NOT NULL,
                zone_id UUID NOT NULL,
                air_temp FLOAT,
                air_rh FLOAT,
                vpd FLOAT,
                soil_moisture FLOAT,
                lux FLOAT,
                n INTEGER
            );
            """
            )
        )

    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as session:
        existing = (await session.execute(select(Farm).where(Farm.id == FARM_ID))).scalar_one_or_none()
        if existing is not None:
            log.info("Dev SQLite DB đã có dữ liệu Farm, bỏ qua seed.")
            return

        log.info("Đang khởi tạo dữ liệu mẫu cho Dev SQLite DB...")
        now = datetime.now(UTC)

        # 1. Farm & User (Chủ farm duy nhất)
        farm = Farm(id=FARM_ID, name="Nông trại Thông minh GreenHub", created_at=now - timedelta(days=90))
        session.add(farm)

        owner = User(
            id=USER_ID,
            farm_id=FARM_ID,
            email="owner@greenhub.vn",
            password_hash=hash_password("greenhub123"),
            role="owner",
            created_at=now - timedelta(days=90),
        )
        session.add(owner)

        # 2. Greenhouse & Gateway
        gh = Greenhouse(
            id=GREENHOUSE_ID,
            farm_id=FARM_ID,
            name="Nhà kính Mini Đà Lạt",
            location="Khu Nông Nghiệp Công Nghệ Cao Đà Lạt",
            created_at=now - timedelta(days=90),
        )
        session.add(gh)

        gw = Gateway(
            id=GATEWAY_ID,
            greenhouse_id=GREENHOUSE_ID,
            mqtt_username="gw-dalat-01",
            is_simulated=False,
            online=True,
            fw_version="1.2.0",
            rssi=-58,
            last_seen=now,
        )
        session.add(gw)

        dev_state = DeviceState(
            greenhouse_id=GREENHOUSE_ID,
            reported={
                "pump_1": "auto",
                "pump_2": "auto",
                "fan": "auto",
                "mist": "auto",
            },
            desired={
                "pump_1": "auto",
                "pump_2": "auto",
                "fan": "auto",
                "mist": "auto",
            },
            cfg_version_desired=1,
            cfg_version_reported=1,
            updated_at=now,
        )
        session.add(dev_state)

        # 3. Crop Profiles hệ thống (10 bộ template)
        for tpl in SYSTEM_CROP_TEMPLATES:
            cp = CropProfile(
                id=tpl["id"],
                farm_id=None,
                crop_code=tpl["crop_code"],
                crop_name=tpl["crop_name"],
                variety=tpl.get("variety", tpl["crop_name"]),
                schema_version=tpl.get("schema_version", 2),
                parameters_json=tpl["parameters_json"],
            )
            session.add(cp)

        # 4. Zones
        # Zone 1: Cà chua bi, diện tích 25m², gieo từ 60 ngày trước (quá cycle 55 ngày -> Đến vụ thu hoạch!)
        zone1 = Zone(
            id=ZONE_1_ID,
            greenhouse_id=GREENHOUSE_ID,
            zone_index=1,
            name="Khu 1 - Cà chua bi",
            crop_profile_id=TEMPLATE_TOMATO_DEMO_ID,
            area_m2=25.0,
            pump_channel=1,
            soil_dry_raw=2900,
            soil_wet_raw=1300,
            planting_date=(now - timedelta(days=60)).date(),
        )
        session.add(zone1)

        # Zone 2: Dâu tây Nhật, diện tích 20m², gieo từ 15 ngày trước
        zone2 = Zone(
            id=ZONE_2_ID,
            greenhouse_id=GREENHOUSE_ID,
            zone_index=2,
            name="Khu 2 - Dâu tây Nhật",
            crop_profile_id=TEMPLATE_STRAWBERRY_DEMO_ID,
            area_m2=20.0,
            pump_channel=2,
            soil_dry_raw=2900,
            soil_wet_raw=1300,
            planting_date=(now - timedelta(days=15)).date(),
        )
        session.add(zone2)

        # 5. Crop Cycles
        # Cycle 1: Cà chua bi đến vụ thu hoạch (đã trồng 60 ngày, chu kỳ chuẩn 55 ngày) -> nhảy thông báo
        cycle1 = CropCycle(
            id=CYCLE_1_ID,
            zone_id=ZONE_1_ID,
            crop_profile_id=TEMPLATE_TOMATO_DEMO_ID,
            started_at=now - timedelta(days=60),
            area_m2=25.0,
            status="active",
            notes="Vụ gieo mẫu tự động: Cây phát triển rất tốt, quả đã chín đỏ đồng loạt.",
            created_by=USER_ID,
            created_at=now - timedelta(days=60),
        )
        session.add(cycle1)

        # Cycle 2: Dâu tây đang trong thời kỳ sinh trưởng (15 ngày)
        cycle2 = CropCycle(
            id=CYCLE_2_ID,
            zone_id=ZONE_2_ID,
            crop_profile_id=TEMPLATE_STRAWBERRY_DEMO_ID,
            started_at=now - timedelta(days=15),
            area_m2=20.0,
            status="active",
            notes="Vụ dâu tây Nhật New Zealand F1, bắt đầu nở hoa lứa đầu.",
            created_by=USER_ID,
            created_at=now - timedelta(days=15),
        )
        session.add(cycle2)

        # 6. Sensor Nodes
        node1 = DeviceNode(
            mac_address="AA:BB:CC:11:22:33",
            greenhouse_id=GREENHOUSE_ID,
            zone_id=ZONE_1_ID,
            status="paired",
            firmware_version="1.0.4",
            battery_mv=3250,
            rssi=-62,
            first_seen=now - timedelta(days=90),
            last_seen=now,
        )
        session.add(node1)

        node2 = DeviceNode(
            mac_address="AA:BB:CC:11:22:44",
            greenhouse_id=GREENHOUSE_ID,
            zone_id=ZONE_2_ID,
            status="paired",
            firmware_version="1.0.4",
            battery_mv=3180,
            rssi=-68,
            first_seen=now - timedelta(days=90),
            last_seen=now,
        )
        session.add(node2)

        # 7. Model AI năng suất Active
        model = MlModel(
            id=MODEL_ID,
            task="yield",
            version=1,
            feature_version=1,
            artifact_path="models/yield/lgbm_v1.joblib",
            trained_at=now - timedelta(days=7),
            n_samples=204,
            n_greenhouses=8,
            source_mix={"real": 24, "sim": 180},
            crops=[
                {"crop_code": "tomato_cherry", "name": "Cà chua bi"},
                {"crop_code": "strawberry", "name": "Dâu tây"},
                {"crop_code": "lettuce", "name": "Xà lách"},
                {"crop_code": "cucumber", "name": "Dưa leo"},
                {"crop_code": "bell_pepper", "name": "Ớt chuông"},
            ],
            metrics={
                "b0_test_mae": 0.178,
                "b1_test_mae": 0.142,
                "model_test_mae": 0.089,
                "r2_test": 0.835,
                "top1_acc": 0.91,
                "ndcg_at_3": 0.94,
                "by_crop_mae": {
                    "tomato_cherry": 0.076,
                    "strawberry": 0.082,
                    "lettuce": 0.091,
                    "cucumber": 0.088,
                    "bell_pepper": 0.098,
                },
                "by_source": {
                    "real": {"n": 24, "mae": 0.082},
                    "sim": {"n": 180, "mae": 0.090},
                },
                "drift_signal": "stable",
            },
            baseline_metrics={
                "b0_test_mae": 0.178,
                "b1_test_mae": 0.142,
            },
            is_active=True,
            notes="Mô hình chính thức v1.2.0: vượt baseline B0 và B1 trên cả 5 cây trồng.",
        )
        session.add(model)
        await session.commit()

        # 8. Sinh 24 giờ dữ liệu readings để biểu đồ hiển thị đẹp mắt
        for hour_idx in range(24, 0, -1):
            ts = now - timedelta(hours=hour_idx)
            hour_val = ts.hour
            is_day = 6 <= hour_val <= 18
            base_temp = 24.5 + (4.0 if is_day else -3.0)
            base_rh = 68.0 + (-12.0 if is_day else 15.0)
            base_soil = 64.0 + (hour_idx % 3)
            base_lux = 32000.0 if (8 <= hour_val <= 16) else (5000.0 if is_day else 0.0)
            vpd = calc_vpd(base_temp, base_rh, leaf_offset_c=1.0)

            for z_id in (ZONE_1_ID, ZONE_2_ID):
                r = Reading(
                    zone_id=z_id,
                    ts=ts,
                    air_temp=round(base_temp + (0.5 if z_id == ZONE_1_ID else -0.5), 2),
                    air_rh=round(base_rh, 1),
                    vpd=round(vpd, 3),
                    soil_moisture=round(base_soil, 1),
                    soil_raw=1850,
                    lux=base_lux,
                    rssi=-65,
                    seq=hour_idx,
                    quality="ok",
                    source="real",
                )
                session.add(r)

                # Chèn luôn vào continuous table
                await session.execute(
                    text(
                        """
                    INSERT INTO readings_1h (bucket, zone_id, air_temp, air_rh, vpd, soil_moisture, lux, n)
                    VALUES (:b, :zid, :t, :rh, :vpd, :soil, :lux, 60)
                    """
                    ),
                    {
                        "b": ts,
                        "zid": str(z_id),
                        "t": r.air_temp,
                        "rh": r.air_rh,
                        "vpd": r.vpd,
                        "soil": r.soil_moisture,
                        "lux": r.lux,
                    },
                )
                await session.execute(
                    text(
                        """
                    INSERT INTO readings_1m (bucket, zone_id, air_temp, air_rh, vpd, soil_moisture, lux, n)
                    VALUES (:b, :zid, :t, :rh, :vpd, :soil, :lux, 1)
                    """
                    ),
                    {
                        "b": ts,
                        "zid": str(z_id),
                        "t": r.air_temp,
                        "rh": r.air_rh,
                        "vpd": r.vpd,
                        "soil": r.soil_moisture,
                        "lux": r.lux,
                    },
                )

        await session.commit()
        log.info("Khởi tạo dữ liệu mẫu Dev SQLite thành công! Chủ farm: owner@greenhub.vn / greenhub123")
