# Image of the isolated test runs (Feature 1, S3; S4 adds per-test timeout and network blocking).
# Only the runtime and the test tools: project dependencies go to a separate volume (preflight).
FROM python:3.10-slim

RUN pip install --no-cache-dir pytest==8.3.3 pytest-cov==5.0.0 pytest-timeout==2.3.1 pytest-socket==0.7.0 \
    && groupadd -g 10001 sbx \
    && useradd -u 10001 -g 10001 -M -s /usr/sbin/nologin sbx \
    && mkdir -p /workspace/src /workspace/tests /workspace/deps /out \
    && mkdir -p /deps /manifests && chown 10001:10001 /out /deps /workspace/deps

WORKDIR /workspace
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/workspace/src
USER 10001:10001
