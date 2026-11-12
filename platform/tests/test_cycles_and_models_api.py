"""Unit tests cho Cycles API, Recommendations API và Global Models API (không lộ yield_samples)."""

import uuid
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from api.routers.cycles import abandon_cycle, create_zone_cycle, harvest_cycle
from api.routers.models import get_active_model, list_models, list_zone_predictions
from api.routers.recommendations import (
    get_greenhouse_recommendations,
    refresh_greenhouse_recommendations,
)
from core.crop_templates import SYSTEM_CROP_TEMPLATES
from core.models import (
    CropCycle,
    CropProfile,
    DeviceState,
    Greenhouse,
    MlModel,
    Prediction,
    User,
    Zone,
)
from core.schemas import (
    CropCycleAbandonRequest,
    CropCycleCreateRequest,
    CropCycleHarvestRequest,
)


def _run_coro(coro: Coroutine[Any, Any, Any]) -> Any:
    try:
        while True:
            coro.send(None)
    except StopIteration as stop:
        return stop.value
    finally:
        coro.close()


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


def test_cycles_create_conflict_harvest_and_abandon() -> None:
    farm_id = uuid.uuid4()
    gh_id = uuid.uuid4()
    zone_id = uuid.uuid4()
    old_prof_id = uuid.uuid4()

    lettuce_tpl = next(
        t for t in SYSTEM_CROP_TEMPLATES if t["crop_code"] == "lettuce" and t["variety"] == "demo"
    )
    profile = CropProfile(
        id=lettuce_tpl["id"],
        farm_id=None,
        crop_code="lettuce",
        crop_name="Xà lách",
        variety="demo",
        schema_version=2,
        parameters_json=lettuce_tpl["parameters_json"],
    )
    user = User(id=uuid.uuid4(), farm_id=farm_id, email="op@greenhub.vn", role="operator")
    gh = Greenhouse(id=gh_id, farm_id=farm_id, name="GH 1")
    zone = Zone(
        id=zone_id,
        greenhouse_id=gh_id,
        zone_index=1,
        name="Zone 1",
        crop_profile_id=old_prof_id,
        area_m2=1.5,
    )
    state = DeviceState(
        greenhouse_id=gh_id, reported={}, desired={}, cfg_version_desired=1, cfg_version_reported=1
    )

    added: list[Any] = []
    session = AsyncMock()
    session.add = added.append
    session.get.return_value = state
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    # 1. Tạo vụ mới thành công -> cập nhật zone.crop_profile_id & bump cfg_version
    session.execute.side_effect = [
        _FakeResult((zone, gh)),  # _get_owned_zone
        _FakeResult(None),  # không có active cycle
        _FakeResult(profile),  # crop profile
        _FakeResult(None),  # bump_cfg_version SELECT
        _FakeResult(None),  # pg_notify worker
        _FakeResult(None),  # pg_notify ws
    ]
    res = _run_coro(
        create_zone_cycle(
            zone_id=zone_id,
            body=CropCycleCreateRequest(crop_profile_id=profile.id),
            user=user,
            session=session,
        )
    )
    assert res.status == "active"
    assert res.area_m2 == pytest.approx(1.5)
    assert res.crop_code == "lettuce"
    assert zone.crop_profile_id == profile.id
    assert state.cfg_version_desired == 2

    # 2. Tạo thêm vụ khi đang có active -> 409 Conflict
    session.execute.side_effect = [
        _FakeResult((zone, gh)),
        _FakeResult(uuid.uuid4()),  # đang có active cycle
    ]
    with pytest.raises(HTTPException) as exc_conflict:
        _run_coro(
            create_zone_cycle(
                zone_id=zone_id,
                body=CropCycleCreateRequest(crop_profile_id=profile.id),
                user=user,
                session=session,
            )
        )
    assert exc_conflict.value.status_code == 409

    # 3. Thu hoạch -> yield_kg_m2 tính chuẩn và phát NOTIFY cycle_harvested
    active_cycle = CropCycle(
        id=uuid.uuid4(),
        zone_id=zone_id,
        crop_profile_id=profile.id,
        started_at=datetime.now(UTC) - timedelta(days=20),
        area_m2=1.5,
        status="active",
        created_at=datetime.now(UTC),
    )
    session.execute.side_effect = [
        _FakeResult((active_cycle, zone, gh, profile)),
        _FakeResult(None),
        _FakeResult(None),
    ]
    harvested = _run_coro(
        harvest_cycle(
            cycle_id=active_cycle.id,
            body=CropCycleHarvestRequest(yield_kg=4.2, notes="Thu lứa 1"),
            user=user,
            session=session,
        )
    )
    assert harvested.status == "harvested"
    assert harvested.yield_kg_m2 == pytest.approx(2.8, abs=1e-4)

    # 4. Huỷ vụ
    ab_cycle = CropCycle(
        id=uuid.uuid4(),
        zone_id=zone_id,
        crop_profile_id=profile.id,
        started_at=datetime.now(UTC),
        area_m2=1.5,
        status="active",
        created_at=datetime.now(UTC),
    )
    session.execute.side_effect = [
        _FakeResult((ab_cycle, zone, gh, profile)),
        _FakeResult(None),
    ]
    abandoned = _run_coro(
        abandon_cycle(
            cycle_id=ab_cycle.id,
            user=user,
            session=session,
            body=CropCycleAbandonRequest(notes="Sâu bệnh"),
        )
    )
    assert abandoned.status == "abandoned"


def test_recommendations_and_global_models_endpoints() -> None:
    farm_id = uuid.uuid4()
    gh_id = uuid.uuid4()
    zone_id = uuid.uuid4()
    viewer = User(id=uuid.uuid4(), farm_id=farm_id, email="v@greenhub.vn", role="viewer")
    operator = User(id=uuid.uuid4(), farm_id=farm_id, email="op@greenhub.vn", role="operator")
    gh = Greenhouse(id=gh_id, farm_id=farm_id, name="GH Dalat")
    zone = Zone(id=zone_id, greenhouse_id=gh_id, zone_index=1, name="Zone 1")

    model_v1 = MlModel(
        id=uuid.uuid4(),
        task="yield",
        version=1,
        feature_version=1,
        artifact_path="/models/yield/v1.joblib",
        trained_at=datetime.now(UTC),
        n_samples=500,
        n_greenhouses=120,
        crops=[{"crop_code": "lettuce", "n": 100, "reference_kg_m2": 3.0}],
        metrics={
            "mae_kg_m2": 0.45,
            "train_stats": {"t_mean": {"mean": 22.0, "std": 1.0}},
        },
        baseline_metrics={"B0": {"mae_kg_m2": 0.8}, "B1": {"mae_kg_m2": 0.6}},
        is_active=True,
    )

    session = AsyncMock()
    session.commit = AsyncMock()

    # 1. GET /recommendations khi chưa có -> None
    session.execute.side_effect = [_FakeResult(gh), _FakeResult(None)]
    rec_empty = _run_coro(get_greenhouse_recommendations(gh_id, viewer, session))
    assert rec_empty is None

    # 2. POST /recommendations/refresh -> 202 accepted + NOTIFY
    session.execute.side_effect = [_FakeResult(gh), _FakeResult(None)]
    ref_res = _run_coro(refresh_greenhouse_recommendations(gh_id, operator, session))
    assert ref_res.status == "accepted"
    assert ref_res.greenhouse_id == gh_id

    # 3. GET /models & GET /models/active kèm feature_drift thuần Python
    session.execute.side_effect = None
    session.execute.return_value = _FakeResult([model_v1])
    models = _run_coro(list_models(viewer, session))
    assert len(models) == 1
    assert models[0].version == 1

    # 6 predictions gần đây có t_mean = 26.0 (lệch 4 std so với train_mean=22.0) -> drifted=True
    recent_details = [{"features": {"t_mean": 26.0, "rh_mean": 70.0}} for _ in range(6)]
    session.execute.side_effect = [
        _FakeResult(model_v1),
        _FakeResult(recent_details),
    ]
    active = _run_coro(get_active_model(viewer, session))
    assert active is not None
    assert active.feature_drift is not None
    assert active.feature_drift["n_predictions"] == 6
    assert active.feature_drift["features"]["t_mean"]["drifted"] is True
    assert active.feature_drift["features"]["t_mean"]["z_score"] == pytest.approx(4.0)

    # 4. GET /zones/{id}/predictions: reject task != yield_forecast -> 422
    with pytest.raises(HTTPException) as exc_task:
        _run_coro(list_zone_predictions(zone_id, viewer, session, task="risk_forecast"))
    assert exc_task.value.status_code == 422

    pred_row = Prediction(
        id=uuid.uuid4(),
        ts=datetime.now(UTC),
        task="yield_forecast",
        greenhouse_id=gh_id,
        zone_id=zone_id,
        model_id=model_v1.id,
        value=2.7,
        score=0.9,
        details={"crop_code": "lettuce"},
    )
    session.execute.side_effect = [_FakeResult(zone), _FakeResult([pred_row])]
    preds = _run_coro(list_zone_predictions(zone_id, viewer, session, task="yield_forecast"))
    assert len(preds) == 1
    assert preds[0].value == pytest.approx(2.7)
