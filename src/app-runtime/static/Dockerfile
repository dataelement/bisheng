# Build context: repository root. Static compilation uses node20's preparer.
FROM nginx:stable-bookworm AS runtime
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid 10001 --no-create-home app \
    && mkdir -p /workspace/app /data && chown -R 10001:10001 /workspace /data
COPY src/app-runtime/static/nginx.conf /opt/bisheng/nginx.conf
COPY --chmod=755 src/app-runtime/static/entrypoint.sh /opt/bisheng/entrypoint.sh
WORKDIR /workspace/app
USER 10001:10001
ENTRYPOINT ["/opt/bisheng/entrypoint.sh"]
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
