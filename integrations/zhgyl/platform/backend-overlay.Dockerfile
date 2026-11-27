ARG RELEASE_IMAGE=cr.dataelem.com/dataelement/bisheng-backend:v3.0.2-arm64
FROM ${RELEASE_IMAGE}
WORKDIR /app
# Require the exact release lock before reusing its ARM dependencies.
COPY uv.lock /tmp/zhgyl-release-lock
RUN python -c "from pathlib import Path; p=Path('/tmp/zhgyl-release-lock'); assert p.read_bytes() == Path('/app/uv.lock').read_bytes(), 'Release dependency lock differs; rebuild dependencies explicitly'; p.unlink()"
# Overlay merged source only;
# no old D bundle, database, fixture, configuration or credential enters this image.
COPY bisheng /app/bisheng
COPY bisheng_langchain /app/bisheng_langchain
COPY scripts /app/scripts
COPY alembic.ini entrypoint.sh pyproject.toml uv.lock /app/
