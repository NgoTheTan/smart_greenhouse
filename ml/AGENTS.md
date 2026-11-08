# Hướng dẫn Coding Assistant – `ml/`

Thư mục này chứa pipeline **AI/ML huấn luyện offline** (`features.py`, `train.py`, `evaluate.py`), dùng chung hàm trích đặc trưng với `platform/worker/inference.py` (đã copy vào `/app/ml/` trong `platform/Dockerfile`).

- Tài liệu chi tiết: [FEATURE_AI_ML_AND_EXPERIMENTS.md](./FEATURE_AI_ML_AND_EXPERIMENTS.md)
- Bất biến quan trọng:
  - **Không dùng LLM** và không dùng mạng nơ-ron lớn (chỉ Ridge, LightGBM, Random Forest).
  - **Chia train/val/test theo thời gian**, tuyệt đối không xáo trộn (`shuffle=False`).
  - Loại bỏ toàn bộ mẫu `quality != 'ok'` khỏi tập huấn luyện và đánh giá.
  - Chỉ số đánh giá báo cáo chính **MUST** tính trên dữ liệu `source = 'real'` (dữ liệu `sim` chỉ dùng để test pipeline & tải).
  - Chỉ kích hoạt `is_active = True` khi mô hình thắng **cả baseline lẫn mô hình đang chạy** trên tập test.
  - Khi chạy CLI trên laptop, đặt `$env:PYTHONPATH = "platform;."` (lưu ý `ml/requirements.txt` kế thừa `platform/requirements.txt` để tương thích phiên bản joblib/scikit-learn/LightGBM).
