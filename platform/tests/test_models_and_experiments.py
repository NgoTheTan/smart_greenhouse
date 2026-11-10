"""Unit tests cho REST Routers Models, Predictions & Experiments (spec 8.3, 8.4, 9)."""

import uuid
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

from api.routers.experiments import (
    get_experiment_kpis,
    list_experiments,
    start_experiment,
    stop_experiment,
)
from api.routers.models import activate_model, list_models, list_zone_predictions
from core.models import (
    ExperimentRun,
    Greenhouse,
    MlModel,
    Prediction,
    Reading,
    User,
    Zone,
)
from core.schemas import ExperimentCreateRequest


def _run_coro(coro: Coroutine[Any, Any, Any]) -> Any:
    """Chạy coroutine thuần bộ nhớ không cần khởi tạo socket loopback của ProactorEventLoop."""
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

    def scalar_one(self) -> Any:
        if isinstance(self._value, list):
            return self._value[0] if self._value else 0
        return self._value

    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[Any]:
        if self._value is None:
            return []
        return self._value if isinstance(self._value, list) else [self._value]


def test_models_router_list_predictions_and_activate() -> None:
    """Kiểm tra API quản lý mô hình: xem dự báo zone, xem danh sách và kích hoạt model."""
    farm_id = uuid.uuid4()
    gh_id = uuid.uuid4()
    zone_id = uuid.uuid4()
    user = User(
        id=uuid.uuid4(), farm_id=farm_id, email="op@greenhub.vn", password_hash="x", role="operator"
    )

    zone = Zone(id=zone_id, greenhouse_id=gh_id, zone_index=1)
    model = MlModel(
        id=uuid.uuid4(),
        zone_id=zone_id,
        task="pump_response",
        version=1,
        artifact_path="pump_model_v1.joblib",
        is_active=False,
        metrics={"pump_gain_pct_per_s": 0.42},
    )
    pred = Prediction(
        zone_id=zone_id,
        task="risk_forecast",
        ts=datetime.now(UTC),
        model_id=None,
        horizon_min=15,
        score=0.78,
        value=None,
        details={"baseline": True},
    )

    session = AsyncMock()

    def _mock_execute(stmt: Any, *args: Any, **kwargs: Any) -> _FakeResult:
        sql = str(stmt)
        if "FROM zones" in sql:
            if "zones.id" in sql or "zones_1.id" in sql:
                return _FakeResult([zone_id])
            return _FakeResult([zone])
        if "FROM predictions" in sql:
            return _FakeResult([pred])
        if "FROM ml_models" in sql:
            return _FakeResult([model])
        return _FakeResult([])

    session.execute.side_effect = _mock_execute
    session.add = lambda obj: None
    session.flush = AsyncMock()

    # 1. Xem dự báo của zone
    preds_res = _run_coro(
        list_zone_predictions(zone_id=zone_id, user=user, session=session, task="risk_forecast")
    )
    assert len(preds_res) == 1
    assert preds_res[0].score == 0.78

    # 2. Xem danh sách model
    models_res = _run_coro(list_models(user=user, session=session, zone_id=zone_id))
    assert len(models_res) == 1
    assert models_res[0].id == model.id

    # 3. Kích hoạt model
    act_res = _run_coro(activate_model(model_id=model.id, user=user, session=session))
    assert act_res.is_active is True


def test_experiments_router_lifecycle_and_kpis() -> None:
    """Kiểm tra vòng đời thí nghiệm Fixed vs Adaptive và tính toán 5 KPI qua SQL thuần."""
    farm_id = uuid.uuid4()
    gh_id = uuid.uuid4()
    zone_id = uuid.uuid4()
    user = User(
        id=uuid.uuid4(), farm_id=farm_id, email="op@greenhub.vn", password_hash="x", role="operator"
    )
    gh = Greenhouse(id=gh_id, farm_id=farm_id, name="Nhà kính A")
    zone = Zone(id=zone_id, greenhouse_id=gh_id, zone_index=1, name="Z1", control_strategy="fixed")

    added_objects: list[Any] = []
    exp_run = ExperimentRun(
        id=uuid.uuid4(),
        greenhouse_id=gh_id,
        strategy="adaptive",
        started_at=datetime.now(UTC) - timedelta(hours=2),
        ended_at=None,
    )

    session = AsyncMock()

    def _mock_execute(stmt: Any, *args: Any, **kwargs: Any) -> _FakeResult:
        sql = str(stmt)
        if "FROM greenhouses" in sql:
            return _FakeResult(gh)
        if "FROM experiment_runs" in sql:
            return _FakeResult([exp_run])
        if "FROM actuator_logs" in sql and "count" in sql:
            # 2 chu kỳ quạt, 4 chu kỳ bơm
            return _FakeResult([("fan", 2), ("pump_1", 4)])
        if "FROM actuator_logs" in sql and "sum" in sql:
            # Bơm chạy 120s
            return _FakeResult([("pump_1", 120)])
        if "FROM zones" in sql:
            return _FakeResult([zone])
        if "FROM readings" in sql:
            # 10 mẫu readings với VPD trong ngưỡng optimal
            r_list = [
                Reading(
                    zone_id=zone_id,
                    ts=datetime.now(UTC),
                    air_temp=24.0,
                    air_rh=70.0,
                    vpd=0.8,
                    soil_moisture=65.0,
                    quality="ok",
                )
                for _ in range(10)
            ]
            return _FakeResult(r_list)
        if "FROM alerts" in sql and "count" in sql:
            return _FakeResult(1)  # 1 cảnh báo sai
        return _FakeResult([])

    session.execute.side_effect = _mock_execute
    session.add = lambda obj: added_objects.append(obj)
    session.flush = AsyncMock()
    session.get.return_value = None

    # 1. Xem danh sách thí nghiệm
    exps_list = _run_coro(list_experiments(user=user, session=session, greenhouse_id=gh_id))
    assert len(exps_list) == 1

    # 2. Bắt đầu thí nghiệm mới
    req = ExperimentCreateRequest(
        greenhouse_id=gh_id, strategy="adaptive", notes="Thử nghiệm adaptive"
    )
    new_exp = _run_coro(start_experiment(body=req, user=user, session=session))
    assert new_exp.strategy == "adaptive"
    assert new_exp.greenhouse_id == gh_id

    # 3. Dừng thí nghiệm
    stopped_exp = _run_coro(stop_experiment(exp_id=exp_run.id, user=user, session=session))
    assert stopped_exp.ended_at is not None

    # 4. Tính toán 5 KPIs
    kpi_res = _run_coro(get_experiment_kpis(exp_id=exp_run.id, user=user, session=session))
    assert kpi_res.experiment_id == exp_run.id
    assert kpi_res.duration_hours >= 1.9
    assert kpi_res.actuator_cycles_per_hour["fan"] == 1.0  # 2 lần / 2 giờ = 1.0 lần/h
    assert kpi_res.actuator_cycles_per_hour["pump_1"] == 2.0  # 4 lần / 2 giờ = 2.0 lần/h
    assert kpi_res.total_pump_duration_s["pump_1"] == 120
    assert kpi_res.vpd_in_range_pct["Z1"] == 100.0
    assert kpi_res.false_positive_alerts == 1
