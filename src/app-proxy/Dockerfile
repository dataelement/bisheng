# BiSheng app-proxy —— 托管应用入口反代（F054 T074）
#
# 与 runtime-manager 的关键差别：**不需要任何 docker 权限**，也不挂 socket。
# 它只做「解析路由 → 剥归一化头 → 注入身份 → 转发」，因此以非 root 运行。
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_PROXY_HOST=0.0.0.0 \
    APP_PROXY_PORT=8090

WORKDIR /app

COPY pyproject.toml uv.lock /app/
RUN pip install --no-cache-dir uv && uv export --frozen --no-dev --format requirements-txt > /tmp/req.txt \
    && pip install --no-cache-dir -r /tmp/req.txt && rm -f /tmp/req.txt

COPY app_proxy /app/app_proxy

RUN useradd --system --uid 10001 --no-create-home appproxy
USER appproxy

EXPOSE 8090
CMD ["python", "-m", "uvicorn", "app_proxy.main:app", "--host", "0.0.0.0", "--port", "8090", "--no-access-log"]
