"""Unit tests cho trích đặc trưng khí hậu Python thuần (`core.climate_features`)."""

from datetime import UTC, datetime, timedelta

import pytest

from core.climate_features import (
    CLIMATE_FEATURE_NAMES,
    FEATURE_VERSION,
    ClimateBucket,
    check_ood_features,
    compute_climate_features,
    merge_greenhouse_buckets,
)


def test_climate_features_day_night_split_and_all_16_features() -> None:
    # UTC 01:00 = 08:00 Asia/Ho_Chi_Minh (day) -> 28 °C
    # UTC 15:00 = 22:00 Asia/Ho_Chi_Minh (night) -> 18 °C
    # UTC 05:00 = 12:00 Asia/Ho_Chi_Minh (day) -> 32 °C (> 30 °C)
    # UTC 19:00 = 02:00 Asia/Ho_Chi_Minh (night) -> 11 °C (< 12 °C)
    start = datetime(2026, 11, 10, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=24)

    buckets = [
        ClimateBucket(
            ts=datetime(2026, 11, 10, 1, 0, tzinfo=UTC),
            air_temp=28.0,
            air_rh=60.0,
            vpd=1.5,
            soil_moisture=60.0,
            lux=20000.0,
        ),
        ClimateBucket(
            ts=datetime(2026, 11, 10, 5, 0, tzinfo=UTC),
            air_temp=32.0,
            air_rh=55.0,
            vpd=2.0,
            soil_moisture=50.0,
            lux=40000.0,
        ),
        ClimateBucket(
            ts=datetime(2026, 11, 10, 15, 0, tzinfo=UTC),
            air_temp=18.0,
            air_rh=90.0,
            vpd=0.2,
            soil_moisture=70.0,
            lux=0.0,
        ),
        ClimateBucket(
            ts=datetime(2026, 11, 10, 19, 0, tzinfo=UTC),
            air_temp=11.0,
            air_rh=92.0,
            vpd=0.1,
            soil_moisture=80.0,
            lux=0.0,
        ),
    ]

    res = compute_climate_features(buckets, start, end, bucket_seconds=3600)
    assert res.feature_version == FEATURE_VERSION
    assert set(res.features.keys()) == set(CLIMATE_FEATURE_NAMES)
    assert res.valid_buckets == 4
    assert res.expected_buckets == 24
    assert res.coverage == pytest.approx(4 / 24, abs=1e-4)

    # Tách ngày (28, 32) và đêm (18, 11) theo Asia/Ho_Chi_Minh
    assert res.features["t_mean"] == pytest.approx((28 + 32 + 18 + 11) / 4, abs=1e-4)
    assert res.features["t_day_mean"] == pytest.approx(30.0, abs=1e-4)
    assert res.features["t_night_mean"] == pytest.approx(14.5, abs=1e-4)
    assert res.features["frac_t_gt_30"] == pytest.approx(0.25, abs=1e-4)
    assert res.features["frac_t_lt_12"] == pytest.approx(0.25, abs=1e-4)
    assert res.features["frac_vpd_low"] == pytest.approx(0.5, abs=1e-4)  # 0.2 và 0.1 < 0.4
    assert res.features["frac_vpd_high"] == pytest.approx(0.25, abs=1e-4)  # 2.0 > 1.6
    # GDD = ((28-10) + (32-10) + (18-10) + (11-10)) / 4 = 49 / 4 = 12.25
    assert res.features["gdd_per_day"] == pytest.approx(12.25, abs=1e-4)
    # mean lux = 15000 -> PPFD = 277.5 -> DLI = 277.5 * 86400 / 1e6 = 23.976
    assert res.features["dli_mean"] == pytest.approx(23.976, abs=1e-3)
    assert res.features["soil_mean"] == pytest.approx(65.0, abs=1e-4)
    assert res.features["soil_std"] is not None and res.features["soil_std"] > 0.0


def test_climate_features_borrow_sibling_lux_and_null_dli() -> None:
    start = datetime(2026, 11, 10, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=2)
    t1 = start
    t2 = start + timedelta(hours=1)

    # Zone không có BH1750 (lux=None) nhưng có dữ liệu lux từ zone anh em
    buckets = [
        ClimateBucket(ts=t1, air_temp=22.0, air_rh=70.0, vpd=0.8, soil_moisture=65.0, lux=None),
        ClimateBucket(ts=t2, air_temp=23.0, air_rh=68.0, vpd=0.9, soil_moisture=66.0, lux=None),
    ]
    res_borrowed = compute_climate_features(
        buckets,
        start,
        end,
        bucket_seconds=3600,
        sibling_lux_by_ts={t1: 10000.0, t2: 20000.0},
    )
    assert res_borrowed.features["dli_mean"] is not None
    assert res_borrowed.features["dli_mean"] > 0.0

    # Nếu cả nhà kính đều không có lux -> dli_mean = None
    res_no_lux = compute_climate_features(buckets, start, end, bucket_seconds=3600)
    assert res_no_lux.features["dli_mean"] is None


def test_merge_greenhouse_buckets_and_ood_check() -> None:
    t0 = datetime(2026, 11, 10, 6, 0, tzinfo=UTC)
    merged = merge_greenhouse_buckets(
        [
            ClimateBucket(
                ts=t0, air_temp=24.0, air_rh=70.0, vpd=0.9, soil_moisture=60.0, lux=None
            ),
            ClimateBucket(
                ts=t0, air_temp=26.0, air_rh=74.0, vpd=0.8, soil_moisture=70.0, lux=25000.0
            ),
        ]
    )
    assert len(merged) == 1
    assert merged[0].air_temp == pytest.approx(25.0)
    assert merged[0].soil_moisture == pytest.approx(65.0)
    assert merged[0].lux == pytest.approx(25000.0)

    bounds = {
        "t_mean": {"min": 14.0, "max": 30.0, "median": 22.0},
        "soil_mean": {"min": 40.0, "max": 80.0, "median": 65.0},
    }
    ood = check_ood_features({"t_mean": 34.5, "soil_mean": 20.0}, bounds)
    assert ood == ["t_mean", "soil_mean"]

    ood_ignore_soil = check_ood_features(
        {"t_mean": 25.0, "soil_mean": 20.0}, bounds, ignore_keys={"soil_mean", "soil_std"}
    )
    assert ood_ignore_soil == []
