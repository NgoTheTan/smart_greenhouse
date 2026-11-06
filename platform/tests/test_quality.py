"""Unit tests cho bộ luật chất lượng dữ liệu tầng 1 (A1 – spec mục 8.2, Test T7)."""

from core.quality import (
    FLAG_AHT_ERR,
    FLAG_BH_ERR,
    FLAG_SOIL_ERR,
    ReadingSample,
    ZoneQualityTracker,
    is_neighbor_divergent,
)


def _sample(
    ts: float,
    *,
    air_t: float | None = 25.0,
    air_rh: float | None = 70.0,
    soil_m: float | None = 62.0,
    soil_raw: int | None = 1900,
    lux: float | None = 15000.0,
    flags: int = 0,
) -> ReadingSample:
    return ReadingSample(
        ts_epoch=ts,
        air_t=air_t,
        air_rh=air_rh,
        soil_m=soil_m,
        soil_raw=soil_raw,
        lux=lux,
        flags=flags,
    )


def test_quality_ok_and_dropout_flags() -> None:
    tracker = ZoneQualityTracker()
    assert tracker.evaluate(_sample(100.0), sample_interval_s=10.0) == "ok"
    assert tracker.evaluate(_sample(110.0, flags=FLAG_AHT_ERR), sample_interval_s=10.0) == "dropout"
    assert (
        tracker.evaluate(_sample(120.0, flags=FLAG_SOIL_ERR), sample_interval_s=10.0) == "dropout"
    )
    assert tracker.evaluate(_sample(130.0, air_t=None), sample_interval_s=10.0) == "dropout"
    # Lỗi riêng cảm biến ánh sáng phụ không làm hỏng dữ liệu nhiệt-ẩm/đất
    assert tracker.evaluate(_sample(140.0, flags=FLAG_BH_ERR), sample_interval_s=10.0) == "ok"


def test_quality_out_of_range_and_unplugged_soil_wire() -> None:
    tracker = ZoneQualityTracker()
    # Test T7: rút dây cảm biến ẩm đất đọc ~0 ADC -> out_of_range
    assert tracker.evaluate(_sample(100.0, soil_raw=0, soil_m=100.0)) == "out_of_range"
    assert tracker.evaluate(_sample(110.0, soil_raw=4095, soil_m=0.0)) == "out_of_range"
    assert tracker.evaluate(_sample(120.0, air_t=65.0)) == "out_of_range"
    assert tracker.evaluate(_sample(130.0, air_rh=105.0)) == "out_of_range"
    assert tracker.evaluate(_sample(140.0, lux=70000.0)) == "out_of_range"


def test_quality_spike_and_long_gap_exemption() -> None:
    tracker = ZoneQualityTracker()
    assert tracker.evaluate(_sample(100.0, air_t=25.0, air_rh=70.0, soil_m=60.0), 10.0) == "ok"
    # Nhảy 6.5 °C sau 10s -> spike
    assert tracker.evaluate(_sample(110.0, air_t=31.5, air_rh=70.0, soil_m=60.0), 10.0) == "spike"

    # Nhưng nếu cách nhau 120s (> 3 * 10s) thì môi trường đổi thật -> không gắn nhầm spike
    assert tracker.evaluate(_sample(230.0, air_t=24.0, air_rh=70.0, soil_m=60.0), 10.0) == "ok"


def test_quality_stuck_air_and_soil() -> None:
    tracker = ZoneQualityTracker()
    # 29 mẫu khí y hệt (đổi nhẹ soil_raw) -> ok; mẫu thứ 30 -> stuck
    for i in range(29):
        lbl = tracker.evaluate(_sample(i * 10.0, air_t=24.5, air_rh=75.0, soil_raw=1800 + i), 10.0)
        assert lbl == "ok"
    assert (
        tracker.evaluate(_sample(290.0, air_t=24.5, air_rh=75.0, soil_raw=1850), 10.0) == "stuck"
    )

    # Kiểm tra kẹt soil_raw qua 60 mẫu liên tiếp khi air vẫn dao động bình thường
    soil_tracker = ZoneQualityTracker()
    for i in range(59):
        lbl = soil_tracker.evaluate(
            _sample(i * 10.0, air_t=24.0 + (i % 3) * 0.2, air_rh=70.0 + (i % 2), soil_raw=2000),
            10.0,
        )
        assert lbl == "ok"
    assert (
        soil_tracker.evaluate(_sample(590.0, air_t=24.1, air_rh=70.5, soil_raw=2000), 10.0)
        == "stuck"
    )


def test_neighbor_divergence() -> None:
    z1 = _sample(100.0, air_t=25.0, air_rh=70.0)
    z2_close = _sample(105.0, air_t=26.5, air_rh=74.0)
    z2_far = _sample(105.0, air_t=35.0, air_rh=74.0)
    assert not is_neighbor_divergent(z1, z2_close, sample_interval_s=10.0)
    assert is_neighbor_divergent(z1, z2_far, sample_interval_s=10.0)

