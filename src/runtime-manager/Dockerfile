# API access is restricted by the external socket proxy. No Docker CLI or MinIO credentials.
FROM python:3.11-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 RTM_HOST=0.0.0.0 RTM_PORT=8091
WORKDIR /app
COPY pyproject.toml uv.lock /app/
RUN pip install --no-cache-dir uv==0.8.22 \
    && uv export --frozen --no-dev --no-emit-project --format requirements-txt >/tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt
COPY runtime_manager /app/runtime_manager
# Root is used only to hand local bind-directory ownership to each runtime's UID.
# The manager has no host socket mount; its API orchestration capability still requires isolation.
EXPOSE 8091
CMD ["python", "-m", "uvicorn", "runtime_manager.main:app", "--host", "0.0.0.0", "--port", "8091", "--workers", "1", "--no-access-log"]
