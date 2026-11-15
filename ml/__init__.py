"""GreenHub ML: pipeline huấn luyện offline dự đoán năng suất & gợi ý cây trồng (`task='yield'`).

Chạy từ gốc repo với `platform/` trên PYTHONPATH để dùng chung `core.*`:
    $env:PYTHONPATH="platform;."   (PowerShell)
    python -m ml.dataset import --source synthetic --file data/synthetic_yield.csv
    python -m ml.train --task yield --sources synthetic --feature-version 1
"""
