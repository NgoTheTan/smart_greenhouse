# Hướng dẫn Coding Assistant – `ml/`

Thư mục này chứa pipeline **AI/ML huấn luyện offline** (`dataset.py`, `train.py`, `evaluate.py`), dùng chung hàm trích đặc trưng khí hậu `platform/core/climate_features.py` (Python thuần) với `platform/worker/inference.py` và `tools/simulator`.

- Tài liệu chi tiết: [FEATURE_AI_YIELD_AND_RECOMMENDATION.md](./FEATURE_AI_YIELD_AND_RECOMMENDATION.md)
- Bất biến quan trọng:
  - **Không dùng LLM** và không dùng mạng nơ-ron lớn (chỉ LightGBM regressor + baseline B0/B1 Ridge).
  - **Một mô hình toàn cục** (`task = 'yield'`) cho mọi farm/zone, dự đoán `relative_yield = yield_kg_m2 / reference_kg_m2(crop)` từ dữ liệu gộp nhiều nhà kính (`yield_samples`).
  - **Chia train/val/test theo nhà kính** (`GroupShuffleSplit` theo `greenhouse_key`, 70/15/15) — tuyệt đối không để cùng `greenhouse_key` xuất hiện ở hai tập.
  - Dữ liệu huấn luyện từ `yield_samples` chỉ được tổng hợp từ bản ghi `quality == 'ok'` với `coverage >= ai.min_coverage` (0.7). Báo cáo metrics theo từng cây và tách theo `source` (`synthetic`, `sim`, `real`, `public`); mẫu `real` báo cáo riêng, trung thực.
  - Chỉ kích hoạt `is_active = True` khi mô hình thắng **cả B0, B1 lẫn mô hình đang active** về MAE trên tập test.
  - Khi chạy CLI trên laptop, đặt `$env:PYTHONPATH = "platform;."` (lưu ý `ml/requirements.txt` kế thừa `platform/requirements.txt` để tương thích phiên bản joblib/scikit-learn/LightGBM).
