"""Đánh giá mô hình Dự đoán Năng suất & Gợi ý Cây trồng (`task = 'yield'`, spec §8.2–8.3)."""

from __future__ import annotations

import math
from typing import Any

from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error


def calculate_mae(y_true: list[float], y_pred: list[float]) -> float:
    """Sai số tuyệt đối trung bình (MAE, kg/m²)."""
    if not y_true or len(y_true) != len(y_pred):
        return 0.0
    return float(mean_absolute_error(y_true, y_pred))


def calculate_rmse(y_true: list[float], y_pred: list[float]) -> float:
    """Căn bậc hai sai số toàn phương trung bình (RMSE, kg/m²)."""
    if not y_true or len(y_true) != len(y_pred):
        return 0.0
    return float(root_mean_squared_error(y_true, y_pred))


def calculate_r2(y_true: list[float], y_pred: list[float]) -> float:
    """Hệ số xác định R² (trả 0.0 nếu < 2 mẫu hoặc phương sai bằng 0)."""
    if len(y_true) < 2 or len(y_true) != len(y_pred):
        return 0.0
    if len(set(y_true)) <= 1:
        return 0.0
    return float(r2_score(y_true, y_pred))


def calculate_mape(y_true: list[float], y_pred: list[float]) -> float:
    """Sai số phần trăm tuyệt đối trung bình (MAPE, %) trên các mẫu `y_true > 0`."""
    pairs = [(float(t), float(p)) for t, p in zip(y_true, y_pred, strict=False) if t > 0]
    if not pairs:
        return 0.0
    return (sum(abs(t - p) / max(t, 1e-3) for t, p in pairs) / len(pairs)) * 100.0


def calculate_regression_metrics(
    y_true: list[float],
    y_pred: list[float],
    *,
    include_mape: bool = True,
) -> dict[str, Any]:
    """Tính bộ chỉ số hồi quy chuẩn trên đơn vị kg/m²."""
    n = len(y_true)
    if n == 0:
        base: dict[str, Any] = {"n": 0, "mae_kg_m2": 0.0, "rmse_kg_m2": 0.0, "r2": 0.0}
        if include_mape:
            base["mape"] = 0.0
        return base

    out: dict[str, Any] = {
        "n": n,
        "mae_kg_m2": round(calculate_mae(y_true, y_pred), 4),
        "rmse_kg_m2": round(calculate_rmse(y_true, y_pred), 4),
        "r2": round(calculate_r2(y_true, y_pred), 4),
    }
    if include_mape:
        out["mape"] = round(calculate_mape(y_true, y_pred), 2)
    return out


def calculate_ndcg_at_k(
    predicted_order: list[str],
    oracle_scores: dict[str, float],
    k: int = 3,
) -> float:
    """Tính NDCG@k cho thứ hạng cây ứng viên so với `oracle_relative_yields`."""
    if not predicted_order or not oracle_scores or k <= 0:
        return 0.0

    def _dcg(order: list[str]) -> float:
        score = 0.0
        for idx, crop in enumerate(order[:k]):
            rel = max(0.0, float(oracle_scores.get(crop, 0.0)))
            score += ((2.0**rel) - 1.0) / math.log2(idx + 2)
        return score

    ideal_order = sorted(
        oracle_scores.keys(),
        key=lambda c: float(oracle_scores[c]),
        reverse=True,
    )
    idcg = _dcg(ideal_order)
    if idcg <= 0.0:
        return 0.0
    return min(1.0, _dcg(predicted_order) / idcg)


def evaluate_recommendations(
    predicted_rankings: list[list[str]],
    oracle_dicts: list[dict[str, float]],
) -> dict[str, float | int]:
    """Tính Top-1 accuracy và NDCG@3 trên tập mẫu có `oracle_relative_yields`."""
    if not predicted_rankings or len(predicted_rankings) != len(oracle_dicts):
        return {"n_eval": 0, "top1_accuracy": 0.0, "ndcg_at_3": 0.0}

    top1_hits = 0
    ndcgs: list[float] = []
    valid = 0
    for pred_order, oracle in zip(predicted_rankings, oracle_dicts, strict=True):
        if not pred_order or not oracle:
            continue
        valid += 1
        max_oracle = max(float(v) for v in oracle.values())
        best_crops = {k for k, v in oracle.items() if abs(float(v) - max_oracle) <= 1e-6}
        if pred_order[0] in best_crops:
            top1_hits += 1
        ndcgs.append(calculate_ndcg_at_k(pred_order, oracle, k=3))

    if valid == 0:
        return {"n_eval": 0, "top1_accuracy": 0.0, "ndcg_at_3": 0.0}

    return {
        "n_eval": valid,
        "top1_accuracy": round(top1_hits / valid, 4),
        "ndcg_at_3": round(sum(ndcgs) / len(ndcgs), 4),
    }


def evaluate_yield_predictions(
    *,
    y_true_kg: list[float],
    y_pred_kg: list[float],
    crops: list[str],
    sources: list[str],
    recommendation_metrics: dict[str, float | int] | None = None,
) -> dict[str, Any]:
    """Tổng hợp metrics trên tập test: tổng thể, theo từng cây, theo nguồn (`by_source`)."""
    overall = calculate_regression_metrics(y_true_kg, y_pred_kg, include_mape=True)

    by_crop: dict[str, dict[str, Any]] = {}
    for crop_code in sorted(set(crops)):
        idx = [i for i, c in enumerate(crops) if c == crop_code]
        yt = [y_true_kg[i] for i in idx]
        yp = [y_pred_kg[i] for i in idx]
        by_crop[crop_code] = calculate_regression_metrics(yt, yp, include_mape=False)

    by_source: dict[str, dict[str, Any]] = {}
    for src in sorted(set(sources)):
        idx = [i for i, s in enumerate(sources) if s == src]
        yt = [y_true_kg[i] for i in idx]
        yp = [y_pred_kg[i] for i in idx]
        src_metrics = calculate_regression_metrics(yt, yp, include_mape=False)
        by_source[src] = {
            "n": src_metrics["n"],
            "mae_kg_m2": src_metrics["mae_kg_m2"],
            "rmse_kg_m2": src_metrics["rmse_kg_m2"],
        }

    result: dict[str, Any] = {
        **overall,
        "by_crop": by_crop,
        "by_source": by_source,
    }
    if recommendation_metrics:
        result["top1_accuracy"] = recommendation_metrics.get("top1_accuracy", 0.0)
        result["ndcg_at_3"] = recommendation_metrics.get("ndcg_at_3", 0.0)
        result["recommendation_n_eval"] = recommendation_metrics.get("n_eval", 0)
    return result


def check_activation_gate(
    new_metrics: dict[str, Any],
    baseline_metrics: dict[str, dict[str, Any]],
    active_metrics: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Kiểm tra cổng kích hoạt: thắng cả B0, B1 và mô hình đang active về MAE trên tập test."""
    mae_new = float(new_metrics["mae_kg_m2"])
    mae_b0 = float(baseline_metrics["B0"]["mae_kg_m2"])
    mae_b1 = float(baseline_metrics["B1"]["mae_kg_m2"])

    if mae_new >= mae_b0:
        return (
            False,
            f"Không kích hoạt: MAE test {mae_new:.4f} >= B0 {mae_b0:.4f} kg/m²",
        )
    if mae_new >= mae_b1:
        return (
            False,
            f"Không kích hoạt: MAE test {mae_new:.4f} >= B1 {mae_b1:.4f} kg/m²",
        )
    if active_metrics is not None and active_metrics.get("mae_kg_m2") is not None:
        mae_active = float(active_metrics["mae_kg_m2"])
        if mae_new >= mae_active:
            return (
                False,
                f"Không kích hoạt: MAE test {mae_new:.4f} >= bản active {mae_active:.4f} kg/m²",
            )
    return (
        True,
        f"Kích hoạt: MAE test {mae_new:.4f} thắng B0 ({mae_b0:.4f}) và B1 ({mae_b1:.4f}) kg/m²",
    )
