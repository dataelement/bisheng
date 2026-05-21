FROM dataelement/bisheng-backend:base.v8

WORKDIR /app

COPY ./ ./

# 生成并安装依赖
# dmPython / dmSQLAlchemy / dmAsync 在 Linux 上由 pyproject.toml 自动包含。
# dmPython 安装时会附带 dmssl 包，其中已包含所需的原生 .so 文件，
# 无需额外安装达梦客户端或下载 DPI 驱动包。
RUN uv pip compile pyproject.toml --upgrade --output-file requirements.txt && \
    uv pip install -r requirements.txt --system --no-cache-dir && \
    uv cache clean && \
    rm -f requirements.txt

# Patch SQLAlchemy's aiomysql adapter: AsyncAdapt_aiomysql_connection.ping is
# declared with `reconnect: bool` (no default) in every released 2.0.x, but
# the pymysql dialect's pool pre-checkout calls `dbapi_connection.ping()`
# without args (PyMySQL >= 1.0 defaults reconnect=False, so SQLAlchemy infers
# it can be called bare). The mismatch raises TypeError on every connection
# checkout, which breaks login. Upstream has no fix as of 2.0.49, so we
# inject the default here. Safe to remove once SQLAlchemy ships the fix.
RUN SITE=$(python -c "import site; print(site.getsitepackages()[0])") && \
    AIOMYSQL_PY="$SITE/sqlalchemy/dialects/mysql/aiomysql.py" && \
    if [ -f "$AIOMYSQL_PY" ]; then \
        sed -i 's|def ping(self, reconnect: bool) -> None:|def ping(self, reconnect: bool = False) -> None:|' "$AIOMYSQL_PY" && \
        grep -q "def ping(self, reconnect: bool = False)" "$AIOMYSQL_PY" || (echo "sqlalchemy aiomysql ping patch did not apply, aborting build" && exit 1); \
    fi

# dmPython 附带的 dmssl 包含 libssl.so / libcrypto.so 等原生库。
# 将它们移入 bin/ 子目录，然后设置 DM_HOME，驱动即可找到这些库。
RUN SITE=$(python -c "import site; print(site.getsitepackages()[0])") && \
    DMSSL="$SITE/dmssl" && \
    if [ -d "$DMSSL" ]; then \
        mkdir -p "$DMSSL/bin" && \
        mv "$DMSSL"/*.so "$DMSSL/bin/" 2>/dev/null || true; \
    fi

ENV DM_HOME="/usr/local/lib/python3.10/site-packages/dmssl/"

CMD ["sh entrypoint.sh"]
