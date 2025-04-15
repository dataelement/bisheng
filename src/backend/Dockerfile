FROM dataelement/bisheng-backend:base.v1

WORKDIR /app

COPY ./ ./

# 临时先删除旧的langgraph相关的库，不然安装有bug。后续重新打包一个base镜像
RUN pip uninstall -y langgraph langgraph-prebuilt langgraph-checkpoint langgraph-sdk

RUN poetry config virtualenvs.create false
RUN poetry update --without dev

# patch langchain-openai lib. remove this when upgrade langchain-openai
RUN patch -p1 < /app/bisheng/patches/langchain_openai.patch /usr/local/lib/python3.10/site-packages/langchain_openai/chat_models/base.py

# patch fastapi-jwt-auth lib. remove this when remove fastapi-jwt-auth
# fix fastapi-jwt-auth not support pydantic:v2
RUN patch -p1 < /app/bisheng/patches/fastapi_jwt_auth.patch /usr/local/lib/python3.10/site-packages/fastapi_jwt_auth/config.py
RUN patch -p1 < /app/bisheng/patches/fastapi_jwt_auth_auth_jwt.patch /usr/local/lib/python3.10/site-packages/fastapi_jwt_auth/auth_jwt.py

CMD ["sh entrypoint.sh"]
