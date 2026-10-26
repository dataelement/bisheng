# Build context: repository root. CI freezes the resulting per-platform digests.
FROM python:3.11-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY src/backend/bisheng/dev_toolkit/artifacts/bisheng_sdk-0.1.1-py3-none-any.whl /tmp/sdk.whl
COPY src/app-runtime/python3.11/requirements.txt /opt/bisheng/requirements.txt
RUN mv /tmp/sdk.whl /tmp/bisheng_sdk-0.1.1-py3-none-any.whl \
    && pip download --only-binary=:all: --dest /opt/bisheng/wheelhouse -r /opt/bisheng/requirements.txt /tmp/bisheng_sdk-0.1.1-py3-none-any.whl \
    && pip install --no-index --find-links=/opt/bisheng/wheelhouse -r /opt/bisheng/requirements.txt bisheng-sdk==0.1.1 \
    && rm /tmp/bisheng_sdk-0.1.1-py3-none-any.whl \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid 10001 --no-create-home app \
    && mkdir -p /workspace/app /data /opt/venv && chown -R 10001:10001 /workspace /data /opt/venv
WORKDIR /workspace/app
USER 10001:10001
EXPOSE 8080
CMD ["python", "main.py"]

FROM runtime AS preparer
USER root
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends build-essential libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.8.22 \
    && pip download --only-binary=:all: --dest /opt/bisheng/wheelhouse setuptools==80.9.0 wheel==0.45.1 hatchling==1.27.0
COPY src/app-runtime/common/prepare.py /opt/bisheng/prepare.py
USER 10001:10001
