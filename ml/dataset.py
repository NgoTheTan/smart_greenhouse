"""CLI quản lý tập dữ liệu `yield_samples` (spec §8.3): import CSV và export phân tích."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Bảo đảm `platform/` nằm trên sys.path khi chạy trực tiếp từ gốc repo
_REPO_ROOT = Path(__file__).resolve().parents[1]
_PLATFORM_DIR = str(_REPO_ROOT / "platform")
if _PLATFORM_DIR not in sys.path:
    sys.path.insert(0, _PLATFORM_DIR)

from ml.features import (  # noqa: E402
    CLIMATE_FEATURE_NAMES,
    CORE_REQUIRED_FEATURES,
    FEATURE_VERSION,
    ClimateBucket,
    compute_climate_features,
)

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
log = logging.getLogger("ml.dataset")

VALID_SOURCES = ("synthetic", "sim", "real", "public")


def _parse_dt(val: Any) -> datetime | None:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo is not None else val.replace(tzinfo=UTC)
    dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _parse_float(val: Any) -> float | None:
    if val is None or val == "" or str(val).lower() in {"null", "none", "nan"}:
        return None
    return float(val)


def _extract_row_features(row: dict[str, Any]) -> dict[str, float | None]:
    raw_feat = row.get("features")
    if isinstance(raw_feat, dict):
        parsed = raw_feat
    elif isinstance(raw_feat, str) and raw_feat.strip():
        parsed = json.loads(raw_feat)
    else:
        parsed = {name: row.get(name) for name in CLIMATE_FEATURE_NAMES if name in row}

    out: dict[str, float | None] = {}
    for name in CLIMATE_FEATURE_NAMES:
        out[name] = _parse_float(parsed.get(name))
    return out


def _is_valid_sample(sample: dict[str, Any]) -> tuple[bool, str | None]:
    cov = sample.get("coverage")
    if cov is not None and float(cov) < 0.7:
        return False, "coverage < 0.7"
    if float(sample.get("yield_kg_m2", -1.0)) < 0.0:
        return False, "yield_kg_m2 < 0"
    feats = sample.get("features") or {}
    for req in CORE_REQUIRED_FEATURES:
        if feats.get(req) is None:
            return False, f"thiếu đặc trưng {req}"
    return True, None


def _load_aggregated_rows(
    rows: list[dict[str, str]], source: str
) -> tuple[list[dict[str, Any]], int]:
    accepted: list[dict[str, Any]] = []
    rejected = 0
    for row in rows:
        try:
            feats = _extract_row_features(row)
            meta_raw = row.get("meta")
            meta = (
                json.loads(meta_raw)
                if isinstance(meta_raw, str) and meta_raw.strip()
                else (meta_raw if isinstance(meta_raw, dict) else None)
            )
            cov = _parse_float(row.get("coverage"))
            row_source = str(row.get("source") or "").strip()
            resolved_source = (
                row_source if (source == "auto" and row_source in VALID_SOURCES) else source
            )
            sample: dict[str, Any] = {
                "source": resolved_source,
                "greenhouse_key": str(row["greenhouse_key"]).strip(),
                "crop_code": str(row["crop_code"]).strip(),
                "started_at": _parse_dt(row.get("started_at")),
                "ended_at": _parse_dt(row.get("ended_at")),
                "cycle_days": _parse_float(row.get("cycle_days")),
                "feature_version": int(row.get("feature_version") or FEATURE_VERSION),
                "features": feats,
                "coverage": cov if cov is not None else 1.0,
                "yield_kg_m2": float(row["yield_kg_m2"]),
                "meta": meta,
            }
        except (KeyError, TypeError, ValueError):
            rejected += 1
            continue

        ok, _reason = _is_valid_sample(sample)
        if not ok or not sample["greenhouse_key"] or not sample["crop_code"]:
            rejected += 1
            continue
        accepted.append(sample)
    return accepted, rejected


def _load_public_timeseries_rows(
    rows: list[dict[str, str]], source: str
) -> tuple[list[dict[str, Any]], int]:
    """Adapter cho CSV công khai dạng chuỗi thời gian theo giờ (vd WUR)."""
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    rejected = 0
    for row in rows:
        try:
            gh_key = str(row["greenhouse_key"]).strip()
            crop_code = str(row["crop_code"]).strip()
            cycle_key = str(row.get("cycle_id") or "default").strip()
            ts = _parse_dt(row["ts"])
            if ts is None:
                raise ValueError("ts trống")
            grouped.setdefault((gh_key, crop_code, cycle_key), []).append(
                {
                    "ts": ts,
                    "air_temp": _parse_float(row.get("air_temp")),
                    "air_rh": _parse_float(row.get("air_rh")),
                    "vpd": _parse_float(row.get("vpd")),
                    "soil_moisture": _parse_float(row.get("soil_moisture")),
                    "lux": _parse_float(row.get("lux")),
                    "yield_kg_m2": float(row["yield_kg_m2"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            rejected += 1

    accepted: list[dict[str, Any]] = []
    for (gh_key, crop_code, cycle_key), items in grouped.items():
        items.sort(key=lambda x: x["ts"])
        started_at = items[0]["ts"]
        ended_at = items[-1]["ts"]
        buckets = [
            ClimateBucket(
                ts=it["ts"],
                air_temp=it["air_temp"],
                air_rh=it["air_rh"],
                vpd=it["vpd"],
                soil_moisture=it["soil_moisture"],
                lux=it["lux"],
            )
            for it in items
        ]
        feat_res = compute_climate_features(
            buckets,
            started_at,
            ended_at,
            bucket_seconds=3600,
            tz_name="Asia/Ho_Chi_Minh",
        )
        duration_days = max(0.0, (ended_at - started_at).total_seconds() / 86400.0)
        sample: dict[str, Any] = {
            "source": source,
            "greenhouse_key": gh_key,
            "crop_code": crop_code,
            "started_at": started_at,
            "ended_at": ended_at,
            "cycle_days": round(duration_days, 2),
            "feature_version": feat_res.feature_version,
            "features": feat_res.features,
            "coverage": feat_res.coverage,
            "yield_kg_m2": float(items[-1]["yield_kg_m2"]),
            "meta": {"cycle_key": cycle_key, "adapter": "public_timeseries"},
        }
        ok, _reason = _is_valid_sample(sample)
        if not ok:
            rejected += 1
            continue
        accepted.append(sample)
    return accepted, rejected


def load_samples_from_csv(file_path: Path, source: str) -> tuple[list[dict[str, Any]], int]:
    """Đọc CSV mẫu `yield_samples` (hỗ trợ tổng hợp, `auto` theo cột, và chuỗi giờ `public`)."""
    if source not in ("synthetic", "public", "auto"):
        raise ValueError(
            f"Chỉ hỗ trợ source 'synthetic', 'public' hoặc 'auto', nhận '{source}'"
        )
    if not file_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file CSV: {file_path}")

    with file_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        rows = list(reader)

    if not rows:
        return [], 0

    if "features" not in fieldnames and "t_mean" not in fieldnames and "ts" in fieldnames:
        ts_source = "public" if source == "auto" else source
        return _load_public_timeseries_rows(rows, ts_source)
    return _load_aggregated_rows(rows, source)


def deterministic_sample_id(sample: dict[str, Any]) -> uuid.UUID:
    """Sinh UUID5 tất định theo khoá tự nhiên của mẫu để chèn idempotent."""
    s_dt = sample.get("started_at")
    e_dt = sample.get("ended_at")
    s_ts = s_dt.isoformat() if isinstance(s_dt, datetime) else ""
    e_ts = e_dt.isoformat() if isinstance(e_dt, datetime) else ""
    key = "|".join(
        [
            str(sample["source"]),
            str(sample["greenhouse_key"]),
            str(sample["crop_code"]),
            s_ts,
            e_ts,
            f"{float(sample['yield_kg_m2']):.4f}",
        ]
    )
    return uuid.uuid5(uuid.NAMESPACE_URL, f"greenhub:yield_sample:{key}")


async def import_samples_to_db(samples: list[dict[str, Any]]) -> tuple[int, int]:
    """Chèn idempotent danh sách mẫu vào bảng `yield_samples`."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from core.db import SessionLocal
    from core.models import YieldSample

    if not samples:
        return 0, 0

    payloads = [
        {
            "id": deterministic_sample_id(s),
            "source": s["source"],
            "greenhouse_key": s["greenhouse_key"],
            "farm_id": None,
            "crop_cycle_id": None,
            "crop_code": s["crop_code"],
            "started_at": s["started_at"],
            "ended_at": s["ended_at"],
            "cycle_days": s["cycle_days"],
            "feature_version": s["feature_version"],
            "features": s["features"],
            "coverage": s["coverage"],
            "yield_kg_m2": s["yield_kg_m2"],
            "meta": s["meta"],
        }
        for s in samples
    ]

    inserted = 0
    async with SessionLocal() as session:
        async with session.begin():
            stmt = (
                pg_insert(YieldSample)
                .values(payloads)
                .on_conflict_do_nothing(index_elements=["id"])
            )
            res = await session.execute(stmt)
            inserted = int(res.rowcount or 0)
    skipped = len(payloads) - inserted
    return inserted, skipped


async def export_samples_from_db(
    out_path: Path,
    *,
    sources: list[str] | None = None,
    feature_version: int = FEATURE_VERSION,
) -> int:
    """Xuất các mẫu hợp lệ từ bảng `yield_samples` ra file CSV."""
    from sqlalchemy import select

    from core.db import SessionLocal
    from core.models import YieldSample

    async with SessionLocal() as session:
        stmt = select(YieldSample).where(YieldSample.feature_version == feature_version)
        if sources:
            stmt = stmt.where(YieldSample.source.in_(sources))
        stmt = stmt.order_by(YieldSample.created_at.asc())
        rows = list((await session.execute(stmt)).scalars().all())

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source",
        "greenhouse_key",
        "crop_code",
        "started_at",
        "ended_at",
        "cycle_days",
        "feature_version",
        "features",
        "coverage",
        "yield_kg_m2",
        "meta",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(
                {
                    "source": r.source,
                    "greenhouse_key": r.greenhouse_key,
                    "crop_code": r.crop_code,
                    "started_at": r.started_at.isoformat() if r.started_at else "",
                    "ended_at": r.ended_at.isoformat() if r.ended_at else "",
                    "cycle_days": r.cycle_days if r.cycle_days is not None else "",
                    "feature_version": r.feature_version,
                    "features": json.dumps(r.features, ensure_ascii=False),
                    "coverage": r.coverage if r.coverage is not None else "",
                    "yield_kg_m2": r.yield_kg_m2,
                    "meta": json.dumps(r.meta, ensure_ascii=False) if r.meta is not None else "",
                }
            )
    return len(rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="ml.dataset", description="Quản lý dữ liệu yield_samples")
    sub = p.add_subparsers(dest="subcommand", required=True)

    imp = sub.add_parser("import", help="Nhập dữ liệu CSV vào bảng yield_samples")
    imp.add_argument("--source", required=True, choices=["synthetic", "public"])
    imp.add_argument("--file", required=True, help="Đường dẫn file CSV đầu vào")

    exp = sub.add_parser("export", help="Xuất dữ liệu từ bảng yield_samples ra CSV")
    exp.add_argument("--out", required=True, help="Đường dẫn file CSV đầu ra")
    exp.add_argument("--sources", default="", help="Lọc nguồn cách nhau bởi dấu phẩy")
    exp.add_argument("--feature-version", type=int, default=FEATURE_VERSION)

    wur = sub.add_parser(
        "build-wur",
        help="Chuẩn hoá dữ liệu WUR Autonomous Greenhouse Challenge ra CSV (source=public)",
    )
    wur.add_argument("--out", default="data/public_wur.csv", help="Đường dẫn file CSV đầu ra")
    wur.add_argument("--raw-dir", default=None, help="Thư mục dữ liệu thô tải từ 4TU.ResearchData")
    wur.add_argument("--crop-code", default="tomato_cherry", help="Mã cây khi đọc --raw-dir")
    wur.add_argument("--edition", default="4tu_raw", help="Tên kỳ WUR khi đọc --raw-dir")
    wur.add_argument("--windows", type=int, default=5, help="Số cửa sổ mỗi buồng benchmark")
    wur.add_argument("--seed", type=int, default=42)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None

    if args.subcommand == "import":
        file_path = Path(args.file)
        if not file_path.is_absolute():
            file_path = _REPO_ROOT / file_path
        samples, rejected = load_samples_from_csv(file_path, args.source)
        log.info(
            "Đọc %s: %d mẫu hợp lệ, %d mẫu bị loại (coverage < 0.7 hoặc thiếu trường)",
            file_path,
            len(samples),
            rejected,
        )
        inserted, skipped = asyncio.run(import_samples_to_db(samples), loop_factory=loop_factory)
        log.info(
            "Import hoàn tất: %d bản ghi mới, %d bản ghi đã tồn tại (idempotent)",
            inserted,
            skipped,
        )
        return

    if args.subcommand == "export":
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = _REPO_ROOT / out_path
        sources = (
            [s.strip() for s in args.sources.split(",") if s.strip()]
            if args.sources
            else None
        )
        count = asyncio.run(
            export_samples_from_db(out_path, sources=sources, feature_version=args.feature_version),
            loop_factory=loop_factory,
        )
        log.info("Đã xuất %d bản ghi yield_samples -> %s", count, out_path)
        return

    if args.subcommand == "build-wur":
        from ml.wur_adapter import (
            build_wur_benchmark_records,
            parse_raw_4tu_wur_folder,
            write_public_wur_csv,
        )

        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = _REPO_ROOT / out_path

        if args.raw_dir:
            raw_path = Path(args.raw_dir)
            if not raw_path.is_absolute():
                raw_path = _REPO_ROOT / raw_path
            records = parse_raw_4tu_wur_folder(
                raw_path, crop_code=args.crop_code, edition=args.edition
            )
        else:
            records = build_wur_benchmark_records(
                windows_per_compartment=args.windows, seed=args.seed
            )

        saved = write_public_wur_csv(records, out_path)
        log.info("Đã tạo %d mẫu WUR (source='public') -> %s", len(records), saved)


if __name__ == "__main__":
    main()
