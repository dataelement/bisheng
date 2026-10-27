# Public HTTP/WebSocket entry proxy; no Engine, host socket or application data access.
# Runs as a non-root user with independently scoped backend identities.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_PROXY_HOST=0.0.0.0 \
    APP_PROXY_PORT=8090

WORKDIR /app

COPY pyproject.toml uv.lock /app/
RUN pip install --no-cache-dir uv==0.8.22 && uv export --frozen --no-dev --no-emit-project --format requirements-txt > /tmp/req.txt \
    && pip install --no-cache-dir -r /tmp/req.txt && rm -f /tmp/req.txt

COPY app_proxy /app/app_proxy

RUN useradd --system --uid 10001 --no-create-home appproxy
USER appproxy

EXPOSE 8090
CMD ["python", "-m", "uvicorn", "app_proxy.main:app", "--host", "0.0.0.0", "--port", "8090", "--no-access-log"]
