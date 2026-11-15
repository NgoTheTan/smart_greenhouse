"""CLI Huấn luyện Mô hình Dự đoán Năng suất & Gợi ý Cây trồng (`task = 'yield'`, spec §8.2–8.3).

Cú pháp:
    $env:PYTHONPATH = "platform;."
    python -m ml.train --task yield [--sources synthetic,sim,real,public] [--feature-version 1]
    python -m ml.train --task yield --csv data/synthetic_yield.csv
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Bảo đảm `platform/` nằm trên sys.path khi chạy CLI trực tiếp từ gốc repo
_REPO_ROOT = Path(__file__).resolve().parents[1]
_PLATFORM_DIR = str(_REPO_ROOT / "platform")
if _PLATFORM_DIR not in sys.path:
    sys.path.insert(0, _PLATFORM_DIR)

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from lightgbm import LGBMRegressor  # noqa: E402
from sklearn.compose import ColumnTransformer  # noqa: E402
from sklearn.impute import SimpleImputer  # noqa: E402
from sklearn.linear_model import Ridge  # noqa: E402
from sklearn.model_selection import GroupShuffleSplit  # noqa: E402
from sklearn.pipeline import Pipeline  # noqa: E402
from sklearn.preprocessing import OneHotEncoder, StandardScaler  # noqa: E402

from core.climate_features import CLIMATE_FEATURE_NAMES, FEATURE_VERSION  # noqa: E402
from core.crop_templates import get_system_crop_catalog  # noqa: E402
from ml.dataset import load_samples_from_csv  # noqa: E402
from ml.evaluate import (  # noqa: E402
    check_activation_gate,
    evaluate_recommendations,
    evaluate_yield_predictions,
)
from ml.features import (  # noqa: E402
    FEATURE_COLUMNS,
    compute_train_feature_bounds_and_stats,
    get_reference_kg_m2_map,
    records_to_dataframe,
)

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
log = logging.getLogger("ml.train")


class CropMedianBaseline:
    """Baseline B0: dự đoán trung vị `relative_yield` theo từng `crop_code` trên tập train."""

    def __init__(self) -> None:
        self.medians_by_crop: dict[str, float] = {}
        self.global_median: float = 1.0

    def fit(self, df: pd.DataFrame, y_rel: pd.Series) -> CropMedianBaseline:
        tmp = pd.DataFrame({"crop_code": df["crop_code"].astype(str), "y": y_rel.astype(float)})
        self.global_median = float(tmp["y"].median()) if not tmp.empty else 1.0
        self.medians_by_crop = {
            str(crop): float(grp["y"].median()) for crop, grp in tmp.groupby("crop_code")
        }
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        preds = [
            self.medians_by_crop.get(str(c), self.global_median)
            for c in df["crop_code"].astype(str)
        ]
        return np.asarray(preds, dtype=float)


class RidgeYieldBaseline:
    """Baseline B1: SimpleImputer + StandardScaler + OneHot(crop_code) + Ridge(alpha=1.0)."""

    def __init__(self, alpha: float = 1.0) -> None:
        num_pipe = Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
            ]
        )
        pre = ColumnTransformer(
            transformers=[
                ("num", num_pipe, list(CLIMATE_FEATURE_NAMES)),
                ("cat", OneHotEncoder(handle_unknown="ignore"), ["crop_code"]),
            ]
        )
        self.pipeline = Pipeline(steps=[("prep", pre), ("ridge", Ridge(alpha=alpha))])

    def fit(self, df: pd.DataFrame, y_rel: pd.Series) -> RidgeYieldBaseline:
        self.pipeline.fit(df[FEATURE_COLUMNS], y_rel.astype(float))
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        preds = self.pipeline.predict(df[FEATURE_COLUMNS])
        return np.clip(np.asarray(preds, dtype=float), 0.0, None)


def split_by_greenhouse(
    df: pd.DataFrame,
    *,
    random_state: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Chia 70% train / 15% val / 15% test theo `greenhouse_key` (không rò rỉ nhà kính)."""
    unique_ghs = df["greenhouse_key"].nunique()
    if unique_ghs < 3:
        raise ValueError(
            f"Cần ít nhất 3 nhà kính khác nhau để chia train/val/test, hiện có {unique_ghs}"
        )

    gss_test = GroupShuffleSplit(n_splits=1, test_size=0.15, random_state=random_state)
    train_val_idx, test_idx = next(gss_test.split(df, groups=df["greenhouse_key"]))
    df_train_val = df.iloc[train_val_idx].reset_index(drop=True)
    df_test = df.iloc[test_idx].reset_index(drop=True)

    val_ratio_in_tv = 0.15 / 0.85
    gss_val = GroupShuffleSplit(n_splits=1, test_size=val_ratio_in_tv, random_state=random_state)
    train_idx, val_idx = next(
        gss_val.split(df_train_val, groups=df_train_val["greenhouse_key"])
    )
    df_train = df_train_val.iloc[train_idx].reset_index(drop=True)
    df_val = df_train_val.iloc[val_idx].reset_index(drop=True)
    return df_train, df_val, df_test


def _crop_soil_midpoints() -> dict[str, float]:
    catalog = get_system_crop_catalog()
    out: dict[str, float] = {}
    for code, tpl in catalog.items():
        sm = (tpl.get("parameters_json") or {}).get("soil_moisture_pct") or {}
        if "min" in sm and "max" in sm:
            out[code] = round((float(sm["min"]) + float(sm["max"])) / 2.0, 2)
    return out


def _evaluate_model_recommendation_ranking(
    estimator: Any,
    df_test: pd.DataFrame,
    *,
    candidate_crops: list[str],
    soil_midpoints: dict[str, float],
    default_soil_std: float,
) -> dict[str, float | int]:
    """Xếp hạng ứng viên bằng mô hình và đối chiếu với `meta.oracle_relative_yields`."""
    eval_rows: list[tuple[dict[str, Any], dict[str, float]]] = []
    for _, row in df_test.iterrows():
        meta = row.get("meta")
        if isinstance(meta, dict) and isinstance(meta.get("oracle_relative_yields"), dict):
            oracle = {
                str(k): float(v)
                for k, v in meta["oracle_relative_yields"].items()
                if str(k) in candidate_crops
            }
            if oracle:
                eval_rows.append((row.to_dict(), oracle))

    if not eval_rows:
        return {"n_eval": 0, "top1_accuracy": 0.0, "ndcg_at_3": 0.0}

    batch_rows: list[dict[str, Any]] = []
    for base_row, _oracle in eval_rows:
        for crop in candidate_crops:
            cand = {feat: base_row[feat] for feat in CLIMATE_FEATURE_NAMES}
            cand["soil_mean"] = soil_midpoints.get(crop, 65.0)
            cand["soil_std"] = default_soil_std
            cand["crop_code"] = crop
            batch_rows.append(cand)

    cand_df = pd.DataFrame(batch_rows, columns=FEATURE_COLUMNS)
    cand_df["crop_code"] = pd.Categorical(cand_df["crop_code"], categories=candidate_crops)
    preds = np.clip(np.asarray(estimator.predict(cand_df), dtype=float), 0.0, None)

    n_cand = len(candidate_crops)
    predicted_rankings: list[list[str]] = []
    oracle_dicts: list[dict[str, float]] = []
    for idx, (_base_row, oracle) in enumerate(eval_rows):
        chunk = preds[idx * n_cand : (idx + 1) * n_cand]
        scored = sorted(
            zip(candidate_crops, chunk, strict=True),
            key=lambda item: float(item[1]),
            reverse=True,
        )
        predicted_rankings.append([c for c, _ in scored])
        oracle_dicts.append(oracle)

    return evaluate_recommendations(predicted_rankings, oracle_dicts)


def train_yield_pipeline(
    records: list[dict[str, Any]],
    *,
    reference_map: dict[str, float],
    version: int = 1,
    feature_version: int = FEATURE_VERSION,
    min_samples_per_crop: int = 30,
    random_state: int = 42,
    models_dir: Path | None = None,
) -> dict[str, Any]:
    """Chạy trọn vòng train/val/test cho `task='yield'` và xuất artifact bundle `.joblib`."""
    df_all = records_to_dataframe(records, reference_map)
    if df_all.empty:
        raise ValueError("Không có mẫu hợp lệ nào để huấn luyện")

    df_train_raw, df_val_raw, df_test_raw = split_by_greenhouse(df_all, random_state=random_state)

    train_counts = df_train_raw["crop_code"].astype(str).value_counts()
    valid_crops = sorted(
        str(crop) for crop, cnt in train_counts.items() if int(cnt) >= min_samples_per_crop
    )
    if not valid_crops:
        raise ValueError(
            f"Không có loại cây nào đạt tối thiểu {min_samples_per_crop} mẫu trên tập train"
        )

    def _filter_crops(part: pd.DataFrame) -> pd.DataFrame:
        filtered = part[part["crop_code"].astype(str).isin(valid_crops)].copy()
        filtered["crop_code"] = pd.Categorical(
            filtered["crop_code"].astype(str), categories=valid_crops
        )
        return filtered.reset_index(drop=True)

    df_train = _filter_crops(df_train_raw)
    df_val = _filter_crops(df_val_raw)
    df_test = _filter_crops(df_test_raw)

    if df_val.empty or df_test.empty:
        raise ValueError("Tập validation hoặc test bị rỗng sau khi lọc cây đủ mẫu")

    # Kiểm tra tuyệt đối không rò rỉ greenhouse_key
    train_gh = set(df_train["greenhouse_key"])
    val_gh = set(df_val["greenhouse_key"])
    test_gh = set(df_test["greenhouse_key"])
    if (train_gh & val_gh) or (train_gh & test_gh) or (val_gh & test_gh):
        raise AssertionError("Phát hiện rò rỉ greenhouse_key giữa train/val/test")

    x_train, y_train_rel = df_train[FEATURE_COLUMNS], df_train["relative_yield"]
    x_val, y_val_rel = df_val[FEATURE_COLUMNS], df_val["relative_yield"]
    x_test = df_test[FEATURE_COLUMNS]

    b0 = CropMedianBaseline().fit(x_train, y_train_rel)
    b1 = RidgeYieldBaseline(alpha=1.0).fit(x_train, y_train_rel)

    lgbm = LGBMRegressor(
        n_estimators=180,
        learning_rate=0.05,
        num_leaves=15,
        max_depth=5,
        min_child_samples=15,
        subsample=1.0,
        colsample_bytree=1.0,
        reg_alpha=0.0,
        reg_lambda=0.2,
        random_state=random_state,
        n_jobs=1,
        verbosity=-1,
    )
    lgbm.fit(x_train, y_train_rel, categorical_feature=["crop_code"])

    # Khoảng tin cậy từ residuals trên validation
    val_pred_rel = np.clip(np.asarray(lgbm.predict(x_val), dtype=float), 0.0, None)
    residuals = y_val_rel.to_numpy(dtype=float) - val_pred_rel
    q10 = round(float(np.percentile(residuals, 10)), 4)
    q90 = round(float(np.percentile(residuals, 90)), 4)

    train_bounds, train_stats = compute_train_feature_bounds_and_stats(df_train)
    default_soil_std = float((train_bounds.get("soil_std") or {}).get("median", 4.0))
    soil_midpoints = _crop_soil_midpoints()

    # Đánh giá trên tập test (quy đổi về kg/m²)
    y_test_kg = df_test["yield_kg_m2"].astype(float).tolist()
    refs_test = df_test["reference_kg_m2"].to_numpy(dtype=float)
    crops_test = df_test["crop_code"].astype(str).tolist()
    sources_test = df_test["source"].astype(str).tolist()

    lgbm_rel_pred = np.clip(np.asarray(lgbm.predict(x_test), dtype=float), 0.0, None)
    lgbm_test_kg = (lgbm_rel_pred * refs_test).tolist()
    b0_test_kg = (np.clip(b0.predict(x_test), 0.0, None) * refs_test).tolist()
    b1_test_kg = (np.clip(b1.predict(x_test), 0.0, None) * refs_test).tolist()

    rec_lgbm = _evaluate_model_recommendation_ranking(
        lgbm,
        df_test,
        candidate_crops=valid_crops,
        soil_midpoints=soil_midpoints,
        default_soil_std=default_soil_std,
    )
    rec_b0 = _evaluate_model_recommendation_ranking(
        b0,
        df_test,
        candidate_crops=valid_crops,
        soil_midpoints=soil_midpoints,
        default_soil_std=default_soil_std,
    )
    rec_b1 = _evaluate_model_recommendation_ranking(
        b1,
        df_test,
        candidate_crops=valid_crops,
        soil_midpoints=soil_midpoints,
        default_soil_std=default_soil_std,
    )

    metrics = evaluate_yield_predictions(
        y_true_kg=y_test_kg,
        y_pred_kg=lgbm_test_kg,
        crops=crops_test,
        sources=sources_test,
        recommendation_metrics=rec_lgbm,
    )
    baseline_metrics = {
        "B0": evaluate_yield_predictions(
            y_true_kg=y_test_kg,
            y_pred_kg=b0_test_kg,
            crops=crops_test,
            sources=sources_test,
            recommendation_metrics=rec_b0,
        ),
        "B1": evaluate_yield_predictions(
            y_true_kg=y_test_kg,
            y_pred_kg=b1_test_kg,
            crops=crops_test,
            sources=sources_test,
            recommendation_metrics=rec_b1,
        ),
    }

    trained_at = datetime.now(UTC).isoformat()
    crops_meta = [
        {
            "crop_code": code,
            "n": int(train_counts[code]),
            "reference_kg_m2": float(reference_map[code]),
        }
        for code in valid_crops
    ]

    bundle: dict[str, Any] = {
        "task": "yield",
        "version": version,
        "feature_version": feature_version,
        "trained_at": trained_at,
        "model": lgbm,
        "feature_names": FEATURE_COLUMNS,
        "categorical_features": ["crop_code"],
        "crop_categories": valid_crops,
        "crops": crops_meta,
        "residual_quantiles": {"p10": q10, "p90": q90},
        "train_feature_bounds": train_bounds,
        "train_stats": train_stats,
    }

    artifact_path: Path | None = None
    if models_dir is not None:
        out_dir = models_dir / "yield"
        out_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = out_dir / f"v{version}.joblib"
        joblib.dump(bundle, artifact_path)

    source_mix: dict[str, int] = {}
    for src in df_all["source"].astype(str):
        source_mix[src] = source_mix.get(src, 0) + 1

    return {
        "version": version,
        "feature_version": feature_version,
        "trained_at": trained_at,
        "artifact_path": artifact_path,
        "n_samples": int(len(df_all)),
        "n_greenhouses": int(df_all["greenhouse_key"].nunique()),
        "source_mix": source_mix,
        "crops": crops_meta,
        "metrics": metrics,
        "baseline_metrics": baseline_metrics,
        "train_stats": train_stats,
        "bundle": bundle,
    }


def _resolve_models_dir(configured: Path, override: str | None = None) -> Path:
    """Chuẩn hoá thư mục lưu model giữa Docker (`/models`) và Windows laptop."""
    if override:
        p = Path(override)
        return p if p.is_absolute() else (_REPO_ROOT / p)
    posix_str = configured.as_posix()
    if sys.platform == "win32" and posix_str.startswith("/"):
        return _REPO_ROOT / posix_str.lstrip("/")
    return configured if configured.is_absolute() else (_REPO_ROOT / configured)


def _next_local_version(models_dir: Path) -> int:
    yield_dir = models_dir / "yield"
    if not yield_dir.exists():
        return 1
    versions: list[int] = []
    for p in yield_dir.glob("v*.joblib"):
        stem = p.stem.lstrip("v")
        if stem.isdigit():
            versions.append(int(stem))
    return (max(versions) + 1) if versions else 1


async def _load_reference_map_from_db() -> dict[str, float]:
    from sqlalchemy import select

    from core.db import SessionLocal
    from core.models import CropProfile

    ref_map = get_reference_kg_m2_map()
    async with SessionLocal() as session:
        stmt = select(CropProfile).where(CropProfile.farm_id.is_(None))
        rows = (await session.execute(stmt)).scalars().all()
        for cp in rows:
            params = cp.parameters_json or {}
            y = params.get("yield") or {}
            if y.get("reference_kg_m2") and (cp.variety == "real" or cp.crop_code not in ref_map):
                ref_map[cp.crop_code] = float(y["reference_kg_m2"])
    return ref_map


async def _train_and_register_db(args: argparse.Namespace) -> None:
    from sqlalchemy import desc, func, select, update

    from core.config import get_settings
    from core.db import SessionLocal
    from core.models import MlModel, YieldSample
    from core.pubsub import CHANNEL_WORKER, pg_notify

    settings = get_settings()
    models_dir = _resolve_models_dir(settings.models_dir, args.models_dir)
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]

    async with SessionLocal() as session:
        stmt = select(YieldSample).where(YieldSample.feature_version == args.feature_version)
        if sources:
            stmt = stmt.where(YieldSample.source.in_(sources))
        rows = list((await session.execute(stmt)).scalars().all())

        max_ver_stmt = select(func.max(MlModel.version)).where(MlModel.task == "yield")
        max_ver = (await session.execute(max_ver_stmt)).scalar_one_or_none() or 0
        next_version = int(max_ver) + 1

        active_stmt = (
            select(MlModel)
            .where(MlModel.task == "yield", MlModel.is_active.is_(True))
            .order_by(desc(MlModel.version))
            .limit(1)
        )
        current_active = (await session.execute(active_stmt)).scalar_one_or_none()

    if not rows:
        log.warning("Không có mẫu yield_samples nào khớp điều kiện — thoát sạch.")
        return

    records = [
        {
            "source": r.source,
            "greenhouse_key": r.greenhouse_key,
            "crop_code": r.crop_code,
            "features": r.features,
            "coverage": r.coverage,
            "yield_kg_m2": r.yield_kg_m2,
            "meta": r.meta or {},
        }
        for r in rows
    ]
    ref_map = await _load_reference_map_from_db()

    try:
        result = train_yield_pipeline(
            records,
            reference_map=ref_map,
            version=next_version,
            feature_version=args.feature_version,
            min_samples_per_crop=args.min_samples_per_crop,
            random_state=args.seed,
            models_dir=models_dir,
        )
    except ValueError as exc:
        log.warning("Không thể huấn luyện mô hình: %s", exc)
        return

    active_metrics = current_active.metrics if current_active is not None else None
    should_activate, gate_notes = check_activation_gate(
        result["metrics"],
        result["baseline_metrics"],
        active_metrics,
    )

    metrics_with_stats = {
        **result["metrics"],
        "train_stats": result["train_stats"],
    }

    async with SessionLocal() as session:
        async with session.begin():
            if should_activate:
                await session.execute(
                    update(MlModel)
                    .where(MlModel.task == "yield", MlModel.is_active.is_(True))
                    .values(is_active=False)
                )
            rel_artifact = f"yield/v{next_version}.joblib"
            model_row = MlModel(
                task="yield",
                version=next_version,
                feature_version=args.feature_version,
                artifact_path=rel_artifact,
                n_samples=result["n_samples"],
                n_greenhouses=result["n_greenhouses"],
                source_mix=result["source_mix"],
                crops=result["crops"],
                metrics=metrics_with_stats,
                baseline_metrics=result["baseline_metrics"],
                is_active=should_activate,
                notes=gate_notes,
            )
            session.add(model_row)
            await session.flush()
            if should_activate:
                await pg_notify(
                    session,
                    CHANNEL_WORKER,
                    {"type": "model_activated", "task": "yield", "version": next_version},
                )

    _log_training_summary(result, is_active=should_activate, notes=gate_notes)


def _log_training_summary(result: dict[str, Any], *, is_active: bool, notes: str) -> None:
    m = result["metrics"]
    b0 = result["baseline_metrics"]["B0"]
    b1 = result["baseline_metrics"]["B1"]
    log.info(
        "=== KẾT QUẢ HUẤN LUYỆN yield v%d (n=%d, greenhouses=%d) ===",
        result["version"],
        result["n_samples"],
        result["n_greenhouses"],
    )
    log.info(
        "LightGBM Test: MAE=%.4f kg/m², RMSE=%.4f, R²=%.4f, MAPE=%.2f%%, Top-1=%.4f, NDCG@3=%.4f",
        m["mae_kg_m2"],
        m["rmse_kg_m2"],
        m["r2"],
        m.get("mape", 0.0),
        m.get("top1_accuracy", 0.0),
        m.get("ndcg_at_3", 0.0),
    )
    log.info("Baseline B0   : MAE=%.4f kg/m², RMSE=%.4f", b0["mae_kg_m2"], b0["rmse_kg_m2"])
    log.info("Baseline B1   : MAE=%.4f kg/m², RMSE=%.4f", b1["mae_kg_m2"], b1["rmse_kg_m2"])
    by_src = m.get("by_source") or {}
    if by_src:
        src_str = " | ".join(
            f"{k}(n={v['n']}, MAE={v['mae_kg_m2']:.4f})" for k, v in sorted(by_src.items())
        )
        log.info("Theo nguồn    : %s", src_str)
    log.info("Activation    : is_active=%s | %s", is_active, notes)
    log.info("Artifact      : %s", result["artifact_path"])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="ml.train", description="GreenHub yield model training")
    p.add_argument("--task", default="yield", choices=["yield"], help="Tác vụ AI duy nhất: yield")
    p.add_argument(
        "--sources",
        default="synthetic,sim,real,public",
        help="Các nguồn yield_samples cách nhau bằng dấu phẩy",
    )
    p.add_argument("--feature-version", type=int, default=FEATURE_VERSION)
    p.add_argument("--min-samples-per-crop", type=int, default=30)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--csv",
        default=None,
        help="Huấn luyện offline trực tiếp từ file CSV (không cần kết nối PostgreSQL)",
    )
    p.add_argument(
        "--models-dir",
        default=None,
        help="Thư mục lưu artifact bundle (mặc định đọc MODELS_DIR hoặc ./models)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.csv:
        from core.config import get_settings

        settings = get_settings()
        models_dir = _resolve_models_dir(settings.models_dir, args.models_dir)
        records: list[dict[str, Any]] = []
        total_rejected = 0
        for raw_p in [item.strip() for item in args.csv.split(",") if item.strip()]:
            csv_path = Path(raw_p)
            if not csv_path.is_absolute():
                csv_path = _REPO_ROOT / csv_path
            part_recs, rejected = load_samples_from_csv(csv_path, source="auto")
            log.info("Đọc %s: %d mẫu hợp lệ (%d bị loại)", csv_path, len(part_recs), rejected)
            records.extend(part_recs)
            total_rejected += rejected
        log.info("Tổng hợp %d mẫu từ CSV (%d bị loại)", len(records), total_rejected)
        next_ver = _next_local_version(models_dir)
        result = train_yield_pipeline(
            records,
            reference_map=get_reference_kg_m2_map(),
            version=next_ver,
            feature_version=args.feature_version,
            min_samples_per_crop=args.min_samples_per_crop,
            random_state=args.seed,
            models_dir=models_dir,
        )
        passed, notes = check_activation_gate(result["metrics"], result["baseline_metrics"])
        _log_training_summary(result, is_active=passed, notes=notes)
        return

    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(_train_and_register_db(args), loop_factory=loop_factory)


if __name__ == "__main__":
    main()
