# Build context: repository root; runtime contains Node's native headers.
FROM python:3.11-slim-bookworm AS certificates

FROM node:20-bookworm-slim AS runtime
# The Node slim image lacks an OS CA bundle required by apt/Python HTTPS.
COPY --from=certificates /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
ENV NODE_ENV=production npm_config_cache=/tmp/npm npm_config_update_notifier=false
RUN npm install --global npm@10.8.2 \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid 10001 --no-create-home app \
    && mkdir -p /workspace/app /data && chown -R 10001:10001 /workspace /data
WORKDIR /workspace/app
USER 10001:10001
EXPOSE 8080
CMD ["node", "server.js"]

FROM runtime AS preparer
USER root
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends python3 python3-venv make g++ \
    && ln -s /usr/bin/python3 /usr/local/bin/python && rm -rf /var/lib/apt/lists/*
COPY src/app-runtime/common/prepare.py /opt/bisheng/prepare.py
ENV NODE_ENV=development
USER 10001:10001
