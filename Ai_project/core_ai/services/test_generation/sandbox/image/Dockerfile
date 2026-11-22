# Image of the isolated test runs (Feature 1, S3). Built by the compose service testgen_sandbox_image.
# Only the runtime and the test tools: no project dependency is installed here.
FROM python:3.10-slim

RUN pip install --no-cache-dir pytest==8.3.3 pytest-cov==5.0.0 \
 && groupadd -g 10001 sbx \
 && useradd -u 10001 -g 10001 -M -s /usr/sbin/nologin sbx \
 && mkdir -p /workspace/src /workspace/tests /out \
 && chown 10001:10001 /out

WORKDIR /workspace
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/workspace/src
USER 10001:10001
