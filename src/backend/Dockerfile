FROM dataelement/bisheng-backend:base.v8

WORKDIR /app

COPY ./ ./

# 生成并安装依赖
RUN uv pip compile pyproject.toml --upgrade --output-file requirements.txt && \
    uv pip install -r requirements.txt --system --no-cache-dir && \
    uv cache clean && \
    rm -f requirements.txt


# patch langchain-openai lib. remove this when langchain-openai support reasoning_content
RUN patch -p1 < /app/bisheng/patches/langchain_openai.patch /usr/local/lib/python3.10/site-packages/langchain_openai/chat_models/base.py


CMD ["sh entrypoint.sh"]
