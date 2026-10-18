# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
ARG APP_VERSION=dev
ARG VCS_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/IavnFGV/video-descriptor" \
    org.opencontainers.image.version=$APP_VERSION org.opencontainers.image.revision=$VCS_REF
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/workspace/cache/huggingface VIDEO_DESCRIPTOR_MANAGED_WORKER=1 \
    VIDEO_DESCRIPTOR_EVENTS=/workspace/output/events.jsonl
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg tesseract-ocr tesseract-ocr-eng tesseract-ocr-rus tesseract-ocr-ukr libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/app
COPY requirements-container.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements-container.lock \
    && pip install --no-cache-dir setuptools==80.9.0 wheel==0.45.1
COPY pyproject.toml ./
COPY video_descriptor ./video_descriptor
RUN pip install --no-cache-dir --no-deps --no-build-isolation . \
    && useradd --uid 1000 --create-home app \
    && mkdir -p /workspace && chown app:app /workspace
USER app
WORKDIR /workspace
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()"]
CMD ["python", "-m", "video_descriptor.container_runtime"]
