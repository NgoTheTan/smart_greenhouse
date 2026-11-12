"""Unit tests cho AI Runtime Inference, `yield_samples`, `yield_forecast` và gợi ý cây."""

import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from core.climate_features import CLIMATE_FEATURE_NAMES, ClimateBucket
from core.crop_templates import SYSTEM_CROP_TEMPLATES
from core.models import (
    Alert,
    Command,
    CropCycle,
    CropProfile,
    Gateway,
    Greenhouse,
    MlModel,
    Prediction,
    YieldSample,
    Zone,
)
from worker.inference import InferenceService, build_recommendation_reasons


def _run_coro(coro: Coroutine[Any, Any, Any]) -> Any:
    try:
        while True:
            coro.send(None)
    except StopIteration as stop:
        return stop.value
    finally:
        coro.close()


async def _sync_to_thread(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return fn(*args, **kwargs)


class _FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def first(self) -> Any:
        if isinstance(self._value, list):
            return self._value[0] if self._value else None
        return self._value

    def scalar_one_or_none(self) -> Any:
        if isinstance(self._value, list):
            return self._value[0] if self._value else None
        return self._value

    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[Any]:
        if self._value is None:
            return []
        return self._value if isinstance(self._value, list) else [self._value]


class _FakeEstimator:
    """Estimator giả lập không phụ thuộc file model ngoài."""

    def __init__(self, rel_by_crop: dict[str, float] | None = None, default: float = 0.85) -> None:
        self.rel_by_crop = rel_by_crop or {}
        self.default = default
        self.params: dict[str, Any] = {}
        self.seen_soil_means: dict[str, float] = {}

    def set_params(self, **kwargs: Any) -> "_FakeEstimator":
        self.params.update(kwargs)
        return self

    def predict(self, df: Any) -> list[float]:
        out: list[float] = []
        for idx in range(len(df)):
            crop = str(df.iloc[idx]["crop_code"]) if "crop_code" in df.columns else ""
            if "soil_mean" in df.columns:
                self.seen_soil_means[crop] = float(df.iloc[idx]["soil_mean"])
            out.append(self.rel_by_crop.get(crop, self.default))
        return out


def _make_bundle(
    rel_by_crop: dict[str, float] | None = None,
    default: float = 0.85,
) -> dict[str, Any]:
    bounds = {
        feat: {"min": -10.0, "max": 100.0, "median": 5.0} for feat in CLIMATE_FEATURE_NAMES
    }
    bounds["t_mean"] = {"min": 14.0, "max": 32.0, "median": 23.0}
    return {
        "task": "yield",
        "version": 1,
        "feature_version": 1,
        "model": _FakeEstimator(rel_by_crop=rel_by_crop, default=default),
        "feature_names": [*CLIMATE_FEATURE_NAMES, "crop_code"],
        "crop_categories": ["lettuce", "strawberry", "tomato_cherry"],
        "crops": [
            {"crop_code": "lettuce", "n": 40, "reference_kg_m2": 3.0},
            {"crop_code": "strawberry", "n": 40, "reference_kg_m2": 4.0},
            {"crop_code": "tomato_cherry", "n": 40, "reference_kg_m2": 10.0},
        ],
        "residual_quantiles": {"p10": -0.1, "p90": 0.1},
        "train_feature_bounds": bounds,
        "train_stats": {feat: {"mean": 1.0, "std": 1.0} for feat in CLIMATE_FEATURE_NAMES},
    }


def _lettuce_demo_profile() -> CropProfile:
    tpl = next(
        t for t in SYSTEM_CROP_TEMPLATES if t["crop_code"] == "lettuce" and t["variety"] == "demo"
    )
    return CropProfile(
        id=tpl["id"],
        farm_id=None,
        crop_code=tpl["crop_code"],
        crop_name=tpl["crop_name"],
        variety=tpl["variety"],
        schema_version=2,
        parameters_json=tpl["parameters_json"],
    )


def test_load_active_model_and_hot_reload(tmp_path: Path) -> None:
    model_file = tmp_path / "yield_v2.joblib"
    model_file.write_bytes(b"placeholder")

    meta = MlModel(
        id=uuid.uuid4(),
        task="yield",
        version=2,
        feature_version=1,
        artifact_path=str(model_file),
        trained_at=datetime.now(UTC),
        n_samples=120,
        n_greenhouses=30,
        crops=[{"crop_code": "lettuce", "n": 40, "reference_kg_m2": 3.0}],
        is_active=True,
    )

    session = AsyncMock()
    session.execute.return_value = _FakeResult(meta)

    service = InferenceService()
    bundle = _make_bundle()

    with (
        patch("asyncio.to_thread", side_effect=_sync_to_thread),
        patch("joblib.load", return_value=bundle) as mock_load,
    ):
        ok = _run_coro(service.load_active_model(session))
        assert ok is True
        assert service.has_active_model is True
        assert service.active_model_meta is not None
        assert service.active_model_meta.id == meta.id
        assert bundle["model"].params.get("n_jobs") == 1
        assert mock_load.call_count == 1

        # Gọi lại với cùng model id -> dùng cache RAM, không load lại file
        ok2 = _run_coro(service.load_active_model(session))
        assert ok2 is True
        assert mock_load.call_count == 1


def test_handle_cycle_harvested_creates_sample_or_records_low_coverage() -> None:
    farm_id = uuid.uuid4()
    gh_id = uuid.uuid4()
    zone_id = uuid.uuid4()
    prof = _lettuce_demo_profile()

    gh = Greenhouse(id=gh_id, farm_id=farm_id, name="GH Sim")
    gw = Gateway(id=uuid.uuid4(), greenhouse_id=gh_id, mqtt_username="gw", is_simulated=True)
    zone = Zone(id=zone_id, greenhouse_id=gh_id, zone_index=1, name="Zone 1", area_m2=2.0)

    started = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
    harvested = started + timedelta(hours=2)
    cycle = CropCycle(
        id=uuid.uuid4(),
        zone_id=zone_id,
        crop_profile_id=prof.id,
        started_at=started,
        harvested_at=harvested,
        area_m2=2.0,
        yield_kg=5.4,
        status="harvested",
    )

    added: list[Any] = []
    session = AsyncMock()
    session.add = added.append
    session.flush = AsyncMock()

    def _exec(stmt: Any, *args: Any, **kwargs: Any) -> _FakeResult:
        sql = str(stmt)
        if "FROM crop_cycles" in sql:
            return _FakeResult((cycle, zone, gh, gw, prof))
        return _FakeResult(None)

    session.execute.side_effect = _exec

    service = InferenceService()

    # 1. Đủ 120 bucket 1-phút (coverage = 1.0 >= 0.7) -> tạo YieldSample source='sim'
    full_buckets = [
        ClimateBucket(
            ts=started + timedelta(minutes=i),
            air_temp=21.0,
            air_rh=72.0,
            vpd=0.7,
            soil_moisture=68.0,
            lux=18000.0,
        )
        for i in range(120)
    ]
    with patch.object(
        service, "_fetch_zone_buckets", new=AsyncMock(return_value=(full_buckets, {}))
    ):
        sample = _run_coro(service.handle_cycle_harvested(session, cycle.id))

    assert isinstance(sample, YieldSample)
    assert sample.source == "sim"
    assert sample.yield_kg_m2 == pytest.approx(2.7, abs=1e-4)
    assert sample.coverage == pytest.approx(1.0)
    assert sample.feature_version == 1

    # 2. Thiếu dữ liệu (coverage < 0.7) -> không tạo sample, ghi notes vào cycle
    cycle2 = CropCycle(
        id=uuid.uuid4(),
        zone_id=zone_id,
        crop_profile_id=prof.id,
        started_at=started,
        harvested_at=harvested,
        area_m2=2.0,
        yield_kg=4.0,
        status="harvested",
    )

    def _exec2(stmt: Any, *args: Any, **kwargs: Any) -> _FakeResult:
        if "FROM crop_cycles" in str(stmt):
            return _FakeResult((cycle2, zone, gh, gw, prof))
        return _FakeResult(None)

    session.execute.side_effect = _exec2
    sparse_buckets = full_buckets[:10]
    with patch.object(
        service, "_fetch_zone_buckets", new=AsyncMock(return_value=(sparse_buckets, {}))
    ):
        sample2 = _run_coro(service.handle_cycle_harvested(session, cycle2.id))

    assert sample2 is None
    assert cycle2.notes is not None
    assert "Không tạo mẫu yield_samples" in cycle2.notes


def test_yield_forecast_low_confidence_alert_and_no_commands() -> None:
    farm_id = uuid.uuid4()
    gh_id = uuid.uuid4()
    zone_id = uuid.uuid4()
    prof = _lettuce_demo_profile()

    gh = Greenhouse(id=gh_id, farm_id=farm_id, name="GH Real")
    zone = Zone(id=zone_id, greenhouse_id=gh_id, zone_index=1, name="Zone 1", area_m2=1.5)
    now = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)

    service = InferenceService()
    meta = MlModel(
        id=uuid.uuid4(),
        task="yield",
        version=1,
        feature_version=1,
        artifact_path="/models/yield/v1.joblib",
        trained_at=now,
        is_active=True,
    )
    bundle = _make_bundle(rel_by_crop={"lettuce": 0.45})
    service._meta = meta
    service._bundle = service._parse_bundle_dict(bundle, meta)

    added: list[Any] = []
    session = AsyncMock()
    session.add = added.append
    session.flush = AsyncMock()
    session.get.return_value = gh
    session.execute.return_value = _FakeResult(None)

    # Case A: Vụ chạy 2h (< 24h) -> gắn low_confidence=True, KHÔNG raise YIELD_FORECAST_LOW
    cycle_short = CropCycle(
        id=uuid.uuid4(),
        zone_id=zone_id,
        crop_profile_id=prof.id,
        started_at=now - timedelta(hours=2),
        area_m2=1.5,
        status="active",
    )
    short_buckets = [
        ClimateBucket(
            ts=(now - timedelta(hours=2)) + timedelta(minutes=i),
            air_temp=22.0,
            air_rh=70.0,
            vpd=0.8,
            soil_moisture=65.0,
            lux=15000.0,
        )
        for i in range(110)
    ]
    with (
        patch("asyncio.to_thread", side_effect=_sync_to_thread),
        patch.object(
            service, "_fetch_zone_buckets", new=AsyncMock(return_value=(short_buckets, {}))
        ),
    ):
        pred_short = _run_coro(
            service.run_yield_forecast_for_cycle(session, cycle_short, zone, gh, prof, now=now)
        )

    assert pred_short is not None
    assert pred_short.task == "yield_forecast"
    assert pred_short.score == pytest.approx(0.45, abs=1e-4)
    assert pred_short.value == pytest.approx(0.45 * 3.0, abs=1e-4)
    assert pred_short.details["low_confidence"] is True
    assert not [o for o in added if isinstance(o, Alert)]
    assert not [o for o in added if isinstance(o, Command)]

    # Case B: Vụ chạy 30h (>= 24h) với năng suất 0.45 < 0.6 -> mở alert info YIELD_FORECAST_LOW
    added.clear()
    cycle_long = CropCycle(
        id=uuid.uuid4(),
        zone_id=zone_id,
        crop_profile_id=prof.id,
        started_at=now - timedelta(hours=30),
        area_m2=1.5,
        status="active",
    )
    long_buckets = [
        ClimateBucket(
            ts=(now - timedelta(hours=30)) + timedelta(hours=i),
            air_temp=22.0,
            air_rh=70.0,
            vpd=0.8,
            soil_moisture=65.0,
            lux=15000.0,
        )
        for i in range(28)
    ]
    with (
        patch("asyncio.to_thread", side_effect=_sync_to_thread),
        patch.object(
            service, "_fetch_zone_buckets", new=AsyncMock(return_value=(long_buckets, {}))
        ),
        patch("worker.alerts.send_alert_notifications", new=AsyncMock(return_value=1)),
    ):
        pred_long = _run_coro(
            service.run_yield_forecast_for_cycle(session, cycle_long, zone, gh, prof, now=now)
        )

    assert pred_long is not None
    assert pred_long.details["low_confidence"] is False
    alerts = [o for o in added if isinstance(o, Alert)]
    assert len(alerts) == 1
    assert alerts[0].alert_type == "YIELD_FORECAST_LOW"
    assert alerts[0].severity == "info"
    assert not [o for o in added if isinstance(o, Command)]


def test_crop_recommendation_overrides_soil_mean_and_ranks_crops() -> None:
    farm_id = uuid.uuid4()
    gh_id = uuid.uuid4()
    zone = Zone(id=uuid.uuid4(), greenhouse_id=gh_id, zone_index=1, name="Zone 1")
    gh = Greenhouse(id=gh_id, farm_id=farm_id, name="GH Dalat")
    prof = _lettuce_demo_profile()
    now = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)

    bundle = _make_bundle(
        rel_by_crop={"strawberry": 0.94, "lettuce": 0.89, "tomato_cherry": 0.72}
    )
    estimator = bundle["model"]
    meta = MlModel(
        id=uuid.uuid4(),
        task="yield",
        version=1,
        feature_version=1,
        artifact_path="/models/yield/v1.joblib",
        trained_at=now,
        is_active=True,
    )
    service = InferenceService()
    service._meta = meta
    service._bundle = service._parse_bundle_dict(bundle, meta)

    added: list[Any] = []
    session = AsyncMock()
    session.get.return_value = gh
    session.add = added.append
    session.flush = AsyncMock()
    session.execute.side_effect = [
        _FakeResult([(zone, prof)]),  # zone_rows
        _FakeResult([]),  # system crop profiles in DB (fallback catalog)
        _FakeResult(None),  # pg_notify CHANNEL_WS
    ]

    # recommend_window_h = 1 (demo) -> 60 buckets of 1 minute; thay soil_mean bằng midpoint
    start = now - timedelta(hours=1)
    buckets = [
        ClimateBucket(
            ts=start + timedelta(minutes=i),
            air_temp=19.8,
            air_rh=74.5,
            vpd=0.72,
            soil_moisture=25.0,
            lux=14000.0,
        )
        for i in range(55)
    ]

    with (
        patch("asyncio.to_thread", side_effect=_sync_to_thread),
        patch.object(service, "_fetch_greenhouse_buckets", new=AsyncMock(return_value=buckets)),
    ):
        pred = _run_coro(service.run_recommendation_for_greenhouse(session, gh_id, now=now))

    assert isinstance(pred, Prediction)
    assert pred.task == "crop_recommendation"
    assert pred.score == pytest.approx(0.94, abs=1e-4)

    ranking = pred.details["ranking"]
    assert [r["crop_code"] for r in ranking] == ["strawberry", "lettuce", "tomato_cherry"]
    assert ranking[0]["expected_kg_m2"] == pytest.approx(0.94 * 4.0, abs=1e-3)
    assert len(ranking[0]["reasons"]) >= 1

    # Kiểm tra đã thay soil_mean bằng trung điểm từng cây (không dùng 25.0%)
    # Lettuce: 70.0; Strawberry: (50+65)/2 = 57.5; Tomato: (60+75)/2 = 67.5
    assert estimator.seen_soil_means["lettuce"] == pytest.approx(70.0)
    assert estimator.seen_soil_means["strawberry"] == pytest.approx(57.5)
    assert estimator.seen_soil_means["tomato_cherry"] == pytest.approx(67.5)
    assert pred.details["features"]["soil_mean"] is None
    assert not [o for o in added if isinstance(o, Command)]


def test_build_recommendation_reasons_vietnamese() -> None:
    tpl = next(
        t
        for t in SYSTEM_CROP_TEMPLATES
        if t["crop_code"] == "strawberry" and t["variety"] == "real"
    )
    reasons = build_recommendation_reasons(
        {"t_mean": 31.2, "vpd_mean": 0.35, "dli_mean": 18.0},
        tpl,
    )
    assert len(reasons) == 3
    assert any("cao hơn khoảng tối ưu" in r for r in reasons)
    assert any("thấp hơn khoảng tối ưu" in r for r in reasons)


def test_worker_runtime_handles_ai_events_when_mqtt_disconnected() -> None:
    """Các sự kiện AI qua NOTIFY vẫn chạy kể cả khi MQTT đang tạm mất kết nối."""
    from worker.main import WorkerRuntime

    rt = WorkerRuntime()
    rt._mqtt_client = None
    rt.inference.load_active_model = AsyncMock(return_value=True)
    rt.inference.handle_cycle_harvested = AsyncMock(return_value=None)
    rt.inference.run_recommendation_for_greenhouse = AsyncMock(return_value=None)

    fake_session = AsyncMock()
    fake_cm = AsyncMock()
    fake_cm.__aenter__.return_value = fake_session
    fake_cm.__aexit__.return_value = None

    cid = uuid.uuid4()
    gid = uuid.uuid4()

    with patch("worker.main.SessionLocal", return_value=fake_cm):
        _run_coro(rt.on_worker_event({"type": "model_activated"}))
        _run_coro(rt.on_worker_event({"type": "cycle_harvested", "cycle_id": str(cid)}))
        _run_coro(rt.on_worker_event({"type": "recommend", "greenhouse_id": str(gid)}))

    assert rt.inference.load_active_model.await_count == 1
    assert rt.inference.handle_cycle_harvested.await_args[0][1] == cid
    assert rt.inference.run_recommendation_for_greenhouse.await_args[0][1] == gid
