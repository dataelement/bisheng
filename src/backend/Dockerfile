FROM cr.dataelem.com/dataelement/bisheng-backend:zyrs-0318

WORKDIR /app

COPY ./ ./

RUN poetry config virtualenvs.create false
# RUN poetry update --without dev

CMD ["sh entrypoint.sh"]
