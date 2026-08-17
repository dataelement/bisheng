# BiSheng runtime-manager —— 编排器（F054 T074）
#
# 它是全平台唯一被允许持有容器编排访问面的进程。镜像里**不装** docker CLI：
# 它通过挂进来的 /var/run/docker.sock 直接说 HTTP API，装 CLI 只会扩大攻击面。
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    RTM_HOST=0.0.0.0 \
    RTM_PORT=8091

WORKDIR /app

# 依赖层单独 COPY：只改代码时不重新解析依赖树。
COPY pyproject.toml uv.lock /app/
RUN pip install --no-cache-dir uv && uv export --frozen --no-dev --format requirements-txt > /tmp/req.txt \
    && pip install --no-cache-dir -r /tmp/req.txt && rm -f /tmp/req.txt

COPY runtime_manager /app/runtime_manager

EXPOSE 8091
# 以 root 运行是**必要**的：它要访问 docker socket。这也正是它必须与 backend
# 分进程、分容器的理由——backend 永远不该有这个权限（arch-guard RULE-10）。
CMD ["python", "-m", "uvicorn", "runtime_manager.main:app", "--host", "0.0.0.0", "--port", "8091", "--no-access-log"]
