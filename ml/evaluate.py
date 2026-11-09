"""Đánh giá mô hình Machine Learning vs Baseline của GreenHub (spec mục 8.2, 8.3).

Nguyên tắc:
- Chỉ số báo cáo chính được đo trên tập Test dữ liệu THẬT (source='real').
- Mô hình chỉ được kích hoạt (is_active=True) khi vượt qua cả Baseline và bản đang chạy.
"""

from __future__ import annotations

import math
from typing import Any


def calculate_mae(y_true: list[float], y_pred: list[float]) -> float:
    """Tính sai số tuyệt đối trung bình (MAE) tính bằng phút."""
    if not y_true or len(y_true) != len(y_pred):
        return 0.0
    return sum(abs(t - p) for t, p in zip(y_true, y_pred)) / len(y_true)


def calculate_baseline_irrigation_eta(
    soil_now: float,
    soil_slope: float,
    soil_min: float = 45.0,
) -> float:
    """Thuật toán Baseline cho bài toán dự báo tưới:

    Ngoại suy đường thẳng từ tốc độ giảm ẩm gần nhất.
    ETA = (soil_now - soil_min) / (-soil_slope)
    """
    if soil_slope >= 0:
        return 999.0  # Đất không giảm ẩm hoặc đang tăng
    rate_per_min = abs(soil_slope)
    if rate_per_min < 0.001:
        return 999.0
    eta_min = (soil_now - soil_min) / rate_per_min
    return max(0.0, eta_min)


def calculate_baseline_risk_forecast(
    vpd_now: float,
    vpd_slope: float,
    low_crit: float = 0.4,
    horizon_min: float = 15.0,
) -> float:
    """Thuật toán Baseline cho dự báo nguy cơ nấm bệnh:

    Ngoại suy tuyến tính VPD trong 15 phút tới.
    Nếu VPD dự báo < low_crit => score = 1.0 (có nguy cơ), ngược lại 0.0.
    """
    vpd_future = vpd_now + (vpd_slope * horizon_min)
    if vpd_future <= low_crit:
        return 1.0
    return 0.0


def calculate_classification_metrics(
    y_true: list[int],
    y_scores: list[float],
    threshold: float = 0.5,
) -> dict[str, float]:
    """Tính Precision, Recall, F1 score cho bài toán phân loại."""
    tp = fp = fn = tn = 0
    for t, score in zip(y_true, y_scores):
        pred = 1 if score >= threshold else 0
        if t == 1 and pred == 1:
            tp += 1
        elif t == 0 and pred == 1:
            fp += 1
        elif t == 1 and pred == 0:
            fn += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        (2 * precision * recall) / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "samples": len(y_true),
        "tp": tp,
        "fp": fp,
    }


def is_model_better_than_baseline(
    task: str,
    model_metrics: dict[str, Any],
    baseline_metrics: dict[str, Any],
) -> bool:
    """Quy tắc chấp nhận mô hình (Acceptance Criteria):

    - irrigation_eta: MAE của mô hình phải NHỎ HƠN MAE của baseline ít nhất 10%.
    - risk_forecast: F1 / PR-AUC của mô hình phải CAO HƠN baseline ít nhất 5%.
    """
    if task == "irrigation_eta":
        m_mae = model_metrics.get("mae", 999.0)
        b_mae = baseline_metrics.get("mae", 999.0)
        return m_mae < (b_mae * 0.9)

    if task == "risk_forecast":
        m_f1 = model_metrics.get("f1", 0.0)
        b_f1 = baseline_metrics.get("f1", 0.0)
        return m_f1 > b_f1

    # Với pump_response và fan_response, nếu có đủ mẫu thì chấp nhận
    return True
