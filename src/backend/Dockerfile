FROM dataelement/bisheng-backend:base.v1

COPY ./ ./

RUN poetry config virtualenvs.create false
RUN poetry update --without dev

CMD ["sh entrypoint.sh"]
