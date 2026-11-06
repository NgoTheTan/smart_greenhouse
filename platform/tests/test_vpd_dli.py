"""Unit tests cho công thức vi khí hậu VPD, PPFD, DLI và rủi ro chuẩn hoá (spec 6.4, 15)."""

from datetime import UTC, datetime, timedelta

import pytest

from core.vpd import (
    calc_risk_heat,
    calc_risk_vpd_low,
    calc_vpd,
    calc_vpsat,
    integrate_dli,
    lux_to_ppfd,
)


def test_vpd_spec_reference_case() -> None:
    """Test T1 bắt buộc (spec 6.4 & 15): T=20 °C, RH=94%, T_lá=T_khí -> VPD ≈ 0.14 kPa."""
    vpd = calc_vpd(20.0, 94.0, leaf_offset_c=0.0)
    assert vpd == pytest.approx(0.1403, abs=0.005)


def test_vpd_leaf_offset_and_condensation_clamp() -> None:
    vpd_no_offset = calc_vpd(26.0, 70.0, leaf_offset_c=0.0)
    vpd_with_offset = calc_vpd(26.0, 70.0, leaf_offset_c=1.0)
    assert vpd_with_offset < vpd_no_offset

    # Khi RH=100% và lá mát hơn không khí 1 °C -> điểm sương/ngưng tụ, VPD không âm
    assert calc_vpd(20.0, 100.0, leaf_offset_c=1.0) == 0.0
    assert calc_vpsat(0.0) == pytest.approx(0.61078, rel=1e-4)


def test_lux_to_ppfd() -> None:
    assert lux_to_ppfd(None) is None
    assert lux_to_ppfd(-10.0) is None
    assert lux_to_ppfd(10_000.0) == pytest.approx(185.0)


def test_integrate_dli_constant_and_gap_cap() -> None:
    t0 = datetime(2026, 11, 5, 8, 0, 0, tzinfo=UTC)
    # 20.000 lux -> PPFD = 370 µmol/m²/s; trong 3600s (61 điểm cách nhau 60s) -> 1.332 mol/m²
    samples = [(t0 + timedelta(seconds=60 * i), 20_000.0) for i in range(61)]
    assert integrate_dli(samples, max_gap_s=180.0) == pytest.approx(1.332, rel=1e-4)

    # Nếu đứt kết nối 2 giờ giữa 2 mẫu thì chỉ tích luỹ tối đa max_gap_s = 180s
    gapped = [(t0, 20_000.0), (t0 + timedelta(hours=2), 20_000.0)]
    expected_capped = (370.0 * 180.0) / 1_000_000.0
    assert integrate_dli(gapped, max_gap_s=180.0) == pytest.approx(expected_capped, rel=1e-4)


def test_normalized_risk_helpers() -> None:
    # VPD optimal [0.8, 1.2], low_crit 0.4
    assert calc_risk_vpd_low(0.9, 0.8, 0.4) == 0.0
    assert calc_risk_vpd_low(0.6, 0.8, 0.4) == pytest.approx(0.5)
    assert calc_risk_vpd_low(0.3, 0.8, 0.4) == 1.0

    # Temp optimal high 28, critical 35
    assert calc_risk_heat(26.0, 28.0, 35.0) == 0.0
    assert calc_risk_heat(31.5, 28.0, 35.0) == pytest.approx(0.5)
    assert calc_risk_heat(36.0, 28.0, 35.0) == 1.0

