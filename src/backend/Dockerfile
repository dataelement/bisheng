FROM dataelement/bisheng-backend:base.v3

WORKDIR /app

COPY ./ ./

RUN poetry config virtualenvs.create false
RUN poetry update --without dev

# patch langchain-openai lib. remove this when langchain-openai support reasoning_content
RUN patch -p1 < /app/bisheng/patches/langchain_openai.patch /usr/local/lib/python3.10/site-packages/langchain_openai/chat_models/base.py

# patch fastapi-jwt-auth lib. remove this when remove fastapi-jwt-auth
# fix fastapi-jwt-auth not support pydantic:v2
RUN patch -p1 < /app/bisheng/patches/fastapi_jwt_auth.patch /usr/local/lib/python3.10/site-packages/fastapi_jwt_auth/config.py

CMD ["sh entrypoint.sh"]
