FROM dataelement/bisheng-backend:base.v1

WORKDIR /app

COPY ./ ./

RUN poetry config virtualenvs.create false
RUN poetry update --without dev

# patch langchain-openai lib. remove this when upgrade langchain-openai
RUN patch -p1 < /app/bisheng/patches/langchain_openai.patch /usr/local/lib/python3.10/site-packages/langchain_openai/chat_models/base.py

CMD ["sh entrypoint.sh"]
