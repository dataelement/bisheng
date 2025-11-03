FROM dataelement/bisheng-backend:base.v6

WORKDIR /app

COPY ./ ./

RUN uv pip install -r <(uv pip compile pyproject.toml --upgrade) --system --no-cache-dir && \
    uv cache clean

# patch langchain-openai lib. remove this when langchain-openai support reasoning_content
RUN patch -p1 < /app/bisheng/patches/langchain_openai.patch /usr/local/lib/python3.10/site-packages/langchain_openai/chat_models/base.py


CMD ["sh entrypoint.sh"]
