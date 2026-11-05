# syntax=docker/dockerfile:1
# Ảnh dùng chung cho api và worker. Build context = gốc repo:
#   docker build -f platform/Dockerfile .
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libgomp1: runtime của LightGBM
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY platform/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# Mã nguồn: api/, worker/, core/, migrations/ ở /app; ml/ để worker có thể gọi huấn luyện
COPY platform/ /app/
COPY ml/ /app/ml/

RUN useradd --create-home --uid 1000 greenhub \
 && mkdir -p /models && chown greenhub /models \
 && chmod +x /app/docker-entrypoint.sh
USER greenhub

ENV PYTHONPATH=/app \
    MODELS_DIR=/models

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["api"]

