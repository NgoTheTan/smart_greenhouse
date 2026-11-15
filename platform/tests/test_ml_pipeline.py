"""Unit tests cho `tools/simulator/growth.py` và pipeline `ml/` (`task = 'yield'`)."""

from __future__ import annotations

import csv
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import joblib
import pytest

from core.climate_features import CLIMATE_FEATURE_NAMES
from core.models import MlModel
from ml.dataset import deterministic_sample_id, load_samples_from_csv
from ml.evaluate import check_activation_gate
from ml.features import get_reference_kg_m2_map, records_to_dataframe
from ml.train import split_by_greenhouse, train_yield_pipeline
from ml.wur_adapter import (
    align_wur_yield_to_greenhub,
    build_wur_benchmark_records,
    excel_serial_to_utc,
    humdef_to_rh,
    par_or_iglob_to_lux,
    parse_raw_4tu_wur_folder,
)
from tools.simulator.growth import generate_synthetic_yield_dataset, write_synthetic_yield_csv
from worker.inference import InferenceService, _predict_rows_sync


def test_growth_model_deterministic_and_region_differentiation() -> None:
    rec1 = generate_synthetic_yield_dataset(greenhouses=12, cycles_per_gh=3, seed=42)
    rec2 = generate_synthetic_yield_dataset(greenhouses=12, cycles_per_gh=3, seed=42)
    assert rec1 == rec2
    assert len(rec1) >= 30

    dalat_oracles = [
        r["meta"]["oracle_relative_yields"] for r in rec1 if r["meta"]["region"] == "dalat"
    ]
    hcm_oracles = [
        r["meta"]["oracle_relative_yields"] for r in rec1 if r["meta"]["region"] == "hcm"
    ]
    assert dalat_oracles and hcm_oracles

    dalat_straw = sum(o["strawberry"] for o in dalat_oracles) / len(dalat_oracles)
    hcm_straw = sum(o["strawberry"] for o in hcm_oracles) / len(hcm_oracles)
    hcm_cuc = sum(o["cucumber"] for o in hcm_oracles) / len(hcm_oracles)

    assert dalat_straw > hcm_straw
    assert hcm_cuc > hcm_straw


def test_dataset_csv_loader_filters_and_public_timeseries_adapter(tmp_path: Path) -> None:
    records = generate_synthetic_yield_dataset(greenhouses=3, cycles_per_gh=2, seed=7)
    csv_path = tmp_path / "syn.csv"
    write_synthetic_yield_csv(records, csv_path)

    # Thêm 1 dòng coverage thấp (< 0.7) và 1 dòng yield âm để kiểm tra bộ lọc
    with csv_path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        bad = records[0]
        writer.writerow(
            [
                "synthetic",
                "syn-bad-cov",
                "lettuce",
                bad["started_at"],
                bad["ended_at"],
                40,
                1,
                json.dumps(bad["features"]),
                0.5,
                2.0,
                "{}",
            ]
        )
        writer.writerow(
            [
                "synthetic",
                "syn-bad-yield",
                "lettuce",
                bad["started_at"],
                bad["ended_at"],
                40,
                1,
                json.dumps(bad["features"]),
                0.95,
                -1.2,
                "{}",
            ]
        )

    loaded, rejected = load_samples_from_csv(csv_path, source="synthetic")
    assert len(loaded) == len(records)
    assert rejected == 2
    assert deterministic_sample_id(loaded[0]) == deterministic_sample_id(loaded[0])

    # Kiểm tra adapter public chuỗi thời gian theo giờ
    pub_csv = tmp_path / "public_wur.csv"
    t0 = datetime(2026, 2, 1, 0, 0, tzinfo=UTC)
    with pub_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "greenhouse_key",
                "crop_code",
                "cycle_id",
                "ts",
                "air_temp",
                "air_rh",
                "soil_moisture",
                "lux",
                "yield_kg_m2",
            ]
        )
        for h in range(24):
            writer.writerow(
                [
                    "wur-gh-01",
                    "tomato_cherry",
                    "c1",
                    (t0 + timedelta(hours=h)).isoformat(),
                    23.0 + (h % 5),
                    72.0,
                    66.0,
                    20000.0 if 6 <= h < 18 else 0.0,
                    9.5,
                ]
            )

    pub_loaded, pub_rejected = load_samples_from_csv(pub_csv, source="public")
    assert pub_rejected == 0
    assert len(pub_loaded) == 1
    assert set(pub_loaded[0]["features"].keys()) == set(CLIMATE_FEATURE_NAMES)
    assert pub_loaded[0]["yield_kg_m2"] == pytest.approx(9.5)


def test_train_pipeline_zero_leakage_beats_baselines_and_worker_compatible(tmp_path: Path) -> None:
    records = generate_synthetic_yield_dataset(greenhouses=80, cycles_per_gh=5, seed=42)
    ref_map = get_reference_kg_m2_map()

    df_all = records_to_dataframe(records, ref_map)
    df_train, df_val, df_test = split_by_greenhouse(df_all, random_state=42)
    train_gh = set(df_train["greenhouse_key"])
    val_gh = set(df_val["greenhouse_key"])
    test_gh = set(df_test["greenhouse_key"])
    assert not (train_gh & val_gh)
    assert not (train_gh & test_gh)
    assert not (val_gh & test_gh)

    res = train_yield_pipeline(
        records,
        reference_map=ref_map,
        version=1,
        min_samples_per_crop=20,
        random_state=42,
        models_dir=tmp_path,
    )

    metrics = res["metrics"]
    b0 = res["baseline_metrics"]["B0"]
    b1 = res["baseline_metrics"]["B1"]

    assert metrics["mae_kg_m2"] < b0["mae_kg_m2"]
    assert metrics["mae_kg_m2"] < b1["mae_kg_m2"]
    assert metrics["top1_accuracy"] > 0.5
    assert metrics["ndcg_at_3"] > 0.7
    assert "synthetic" in metrics["by_source"]
    assert len(metrics["by_crop"]) == 5

    # Xác nhận artifact bundle tương thích trực tiếp với worker InferenceService
    art_path = res["artifact_path"]
    assert art_path is not None and art_path.exists()
    raw_bundle = joblib.load(art_path)

    meta = MlModel(
        id=uuid.uuid4(),
        task="yield",
        version=1,
        feature_version=1,
        artifact_path=str(art_path),
        trained_at=datetime.now(UTC),
        crops=res["crops"],
        is_active=True,
    )
    parsed = InferenceService._parse_bundle_dict(raw_bundle, meta)
    assert parsed is not None

    sample_row = {**records[0]["features"], "crop_code": records[0]["crop_code"]}
    preds = _predict_rows_sync(parsed, [sample_row])
    assert len(preds) == 1
    assert preds[0] > 0.0


def test_activation_gate_rules() -> None:
    new_m = {"mae_kg_m2": 0.72}
    baselines = {"B0": {"mae_kg_m2": 1.40}, "B1": {"mae_kg_m2": 0.95}}

    passed, _ = check_activation_gate(new_m, baselines, None)
    assert passed is True

    passed_active, _ = check_activation_gate(new_m, baselines, {"mae_kg_m2": 0.80})
    assert passed_active is True

    fail_active, reason_active = check_activation_gate(new_m, baselines, {"mae_kg_m2": 0.65})
    assert fail_active is False
    assert "active" in reason_active

    fail_b1, reason_b1 = check_activation_gate({"mae_kg_m2": 0.96}, baselines, None)
    assert fail_b1 is False
    assert "B1" in reason_b1


def test_wur_adapter_physics_raw_4tu_parser_and_combined_training(tmp_path: Path) -> None:
    # 1. Quy đổi vật lý
    dt = excel_serial_to_utc("43800.5")
    assert dt.year == 2019 and dt.hour == 12
    rh = humdef_to_rh(22.0, 4.86)
    assert 70.0 < rh < 80.0
    lux = par_or_iglob_to_lux(par_in=370.0)
    assert lux == pytest.approx(20000.0, abs=10.0)
    aligned = align_wur_yield_to_greenhub(41.1, 34.5, "cucumber")
    assert aligned == pytest.approx((41.1 / 34.5) * 15.0, abs=1e-3)

    # 2. Parser thư mục thô 4TU.ResearchData (GreenhouseClimate.csv + Production.csv)
    comp_dir = tmp_path / "wur_raw" / "Sonoma"
    comp_dir.mkdir(parents=True)
    with (comp_dir / "GreenhouseClimate.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["%time", "Tair", "Rhair", "Tot_PAR", "WC"])
        base_serial = 43332.0  # 2018-08-20 00:00 UTC
        for h in range(24):
            for step in (0, 30):
                s = base_serial + (h + step / 60.0) / 24.0
                par = 350.0 if 6 <= h < 18 else 0.0
                w.writerow([f"{s:.6f}", 22.5, 78.0, par, 71.5])
    with (comp_dir / "Production.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["%time", "ProdA"])
        w.writerow(["43444.0", 41.1])

    parsed = parse_raw_4tu_wur_folder(
        tmp_path / "wur_raw", crop_code="cucumber", edition="1st_2018", wur_ref_kg_m2=34.5
    )
    assert len(parsed) == 1
    assert parsed[0]["source"] == "public"
    assert parsed[0]["greenhouse_key"] == "wur-1st_2018-sonoma"
    assert parsed[0]["yield_kg_m2"] == pytest.approx(aligned, abs=1e-3)

    # 3. Huấn luyện kết hợp synthetic + WUR public
    syn_recs = generate_synthetic_yield_dataset(greenhouses=50, cycles_per_gh=5, seed=42)
    wur_recs = build_wur_benchmark_records(windows_per_compartment=4, seed=42)
    assert len(wur_recs) == 22 * 4

    res = train_yield_pipeline(
        syn_recs + wur_recs,
        reference_map=get_reference_kg_m2_map(),
        version=2,
        min_samples_per_crop=20,
        random_state=42,
        models_dir=tmp_path / "models",
    )
    assert "synthetic" in res["source_mix"]
    assert "public" in res["source_mix"]
    assert res["metrics"]["mae_kg_m2"] < res["baseline_metrics"]["B0"]["mae_kg_m2"]
    assert res["metrics"]["mae_kg_m2"] < res["baseline_metrics"]["B1"]["mae_kg_m2"]
    assert "public" in res["metrics"]["by_source"]
