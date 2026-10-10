# syntax=docker/dockerfile:1
# Intel validates Lunar Lake / WSL compute runtime on Ubuntu 24.04.
# Keep the original Debian/CPU devcontainer available as a separate profile.
FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04
RUN apt-get update \
    && apt-get install -y --no-install-recommends software-properties-common \
       python3 python3-venv python3-dev ffmpeg tesseract-ocr tesseract-ocr-eng \
    && add-apt-repository -y ppa:kobuk-team/intel-graphics \
    && apt-get update \
    && apt-get install -y --no-install-recommends libze-intel-gpu1 libze1 \
       intel-opencl-icd clinfo intel-ocloc \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/video-descriptor-python \
    && chown -R vscode:vscode /opt/video-descriptor-python
ENV PATH="/opt/video-descriptor-python/bin:${PATH}"
RUN ln -s /opt/video-descriptor-python/bin/python /usr/local/bin/python
COPY requirements-dev.txt /tmp/video-descriptor-build/requirements-dev.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install -r /tmp/video-descriptor-build/requirements-dev.txt
