FROM cr.dataelem.com/canglan/bisheng-backend:zyrs-base-0616

WORKDIR /app

COPY ./ ./

RUN poetry config virtualenvs.create false
# RUN pip install bisheng_langchain=="1.1.1"
RUN pip install soundfile==0.13.1
# RUN poetry update --without dev

# patch langchain-openai lib. remove this when upgrade langchain-openai
RUN patch -p1 < /app/bisheng/patches/langchain_openai.patch /usr/local/lib/python3.10/site-packages/langchain_openai/chat_models/base.py

# patch fastapi-jwt-auth lib. remove this when remove fastapi-jwt-auth
# fix fastapi-jwt-auth not support pydantic:v2
RUN patch -p1 < /app/bisheng/patches/fastapi_jwt_auth.patch /usr/local/lib/python3.10/site-packages/fastapi_jwt_auth/config.py

CMD ["sh entrypoint.sh"]
