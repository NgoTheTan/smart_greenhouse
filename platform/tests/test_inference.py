"""Unit tests cho AI Runtime Inference trong worker (spec 8.3)."""

import uuid
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

from core.models import Alert, Greenhouse, Prediction, Reading, Zone
from worker.inference import InferenceService


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


def test_inference_service_baseline_risk_forecast_and_alert() -> None:
    """Kiểm tra chu kỳ inference tính toán risk_forecast và kích hoạt cảnh báo sớm."""
    service = InferenceService()

    farm_id = uuid.uuid4()
    gh_id = uuid.uuid4()
    zone_id = uuid.uuid4()

    gh = Greenhouse(id=gh_id, farm_id=farm_id, name="Nhà kính 1")
    zone = Zone(
        id=zone_id, greenhouse_id=gh_id, zone_index=1, name="Zone 1", control_strategy="fixed"
    )

    now = datetime.now(UTC)
    # Dữ liệu bất lợi: RH cao 93.5%, VPD rất thấp 0.22 kPa (rủi ro nấm cao)
    readings = [
        Reading(
            zone_id=zone_id,
            ts=now - timedelta(minutes=10),
            air_temp=22.0,
            air_rh=90.0,
            vpd=0.35,
            soil_moisture=65.0,
            quality="ok",
        ),
        Reading(
            zone_id=zone_id,
            ts=now - timedelta(minutes=1),
            air_temp=21.5,
            air_rh=93.5,
            vpd=0.22,
            soil_moisture=65.0,
            quality="ok",
        ),
    ]

    added_objects: list[Any] = []
    mock_session = AsyncMock()

    def _mock_execute(stmt: Any, *args: Any, **kwargs: Any) -> _FakeResult:
        sql = str(stmt)
        if "FROM zones" in sql:
            return _FakeResult([(zone, gh)])
        if "FROM readings" in sql:
            return _FakeResult(readings)
        if "FROM alerts" in sql:
            return _FakeResult([])
        if "FROM ml_models" in sql:
            return _FakeResult([])
        return _FakeResult([])

    mock_session.execute.side_effect = _mock_execute
    mock_session.get.return_value = None
    mock_session.add = lambda obj: added_objects.append(obj)
    mock_session.flush = AsyncMock()

    # Chạy 1 chu kỳ suy luận
    _run_coro(service.run_cycle(mock_session, now=now))

    # Kiểm tra bản ghi Prediction được tạo ra
    predictions = [o for o in added_objects if isinstance(o, Prediction)]
    assert len(predictions) >= 1

    rf_pred = next(p for p in predictions if p.task == "risk_forecast")
    assert rf_pred.score is not None
    assert rf_pred.score >= 0.7  # RH 93.5% và VPD 0.22 kPa vượt ngưỡng rủi ro 0.7

    # Kiểm tra cảnh báo sớm DISEASE_RISK_FORECAST được sinh ra (Kịch bản A)
    alert = next((o for o in added_objects if isinstance(o, Alert)), None)
    assert alert is not None
    assert alert.alert_type == "DISEASE_RISK_FORECAST"
    assert alert.severity == "warning"
    assert alert.zone_id == zone_id


def test_inference_service_baseline_irrigation_eta() -> None:
    """Kiểm tra chu kỳ inference tính toán thời gian cần tưới tiếp theo (irrigation_eta)."""
    service = InferenceService()

    farm_id = uuid.uuid4()
    gh_id = uuid.uuid4()
    zone_id = uuid.uuid4()

    gh = Greenhouse(id=gh_id, farm_id=farm_id, name="Nhà kính 1")
    zone = Zone(
        id=zone_id, greenhouse_id=gh_id, zone_index=1, name="Zone 1", control_strategy="fixed"
    )

    now = datetime.now(UTC)
    # Đất đang khô dần: từ 75% xuống 65% trong 19 phút (ngưỡng tối thiểu 60%)
    # Còn lại 5% => cần tưới sau ~9.5 phút
    readings = [
        Reading(
            zone_id=zone_id,
            ts=now - timedelta(minutes=20),
            air_temp=25.0,
            air_rh=65.0,
            vpd=0.9,
            soil_moisture=75.0,
            quality="ok",
        ),
        Reading(
            zone_id=zone_id,
            ts=now - timedelta(minutes=1),
            air_temp=25.5,
            air_rh=64.0,
            vpd=0.95,
            soil_moisture=65.0,
            quality="ok",
        ),
    ]

    added_objects: list[Any] = []
    mock_session = AsyncMock()

    def _mock_execute(stmt: Any, *args: Any, **kwargs: Any) -> _FakeResult:
        sql = str(stmt)
        if "FROM zones" in sql:
            return _FakeResult([(zone, gh)])
        if "FROM readings" in sql:
            return _FakeResult(readings)
        if "FROM alerts" in sql:
            return _FakeResult([])
        if "FROM ml_models" in sql:
            return _FakeResult([])
        return _FakeResult([])

    mock_session.execute.side_effect = _mock_execute
    mock_session.get.return_value = None
    mock_session.add = lambda obj: added_objects.append(obj)
    mock_session.flush = AsyncMock()

    _run_coro(service.run_cycle(mock_session, now=now))

    predictions = [o for o in added_objects if isinstance(o, Prediction)]
    eta_pred = next(p for p in predictions if p.task == "irrigation_eta")
    assert eta_pred.value is not None
    # Giá trị ETA nằm trong khoảng ~9.5 - 10.5 phút
    assert 8.0 <= eta_pred.value <= 12.0
