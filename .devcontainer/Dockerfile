# syntax=docker/dockerfile:1
FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

# The base image includes Yarn's APT source; this Python project does not use it.
# Remove it so a stale third-party signing key cannot block Debian packages.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-dev.txt /tmp/video-descriptor-build/requirements-dev.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install -r /tmp/video-descriptor-build/requirements-dev.txt
