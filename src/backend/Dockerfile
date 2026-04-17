FROM dataelement/bisheng-backend:base.v8

WORKDIR /app

COPY ./ ./

# 生成并安装依赖
RUN uv pip compile pyproject.toml --upgrade --output-file requirements.txt && \
    uv pip install -r requirements.txt --system --no-cache-dir && \
    uv cache clean && \
    rm -f requirements.txt


CMD ["sh entrypoint.sh"]
