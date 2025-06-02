FROM node:18-alpine as frontend_build
ARG BACKEND
WORKDIR /app
COPY . /app


RUN cd /app/platform && \
    rm -rf node_modules package-lock.json && \
    npm install --force --registry=https://registry.npmmirror.com && \
    npm run build


RUN cd /app/client && \
    rm -rf node_modules package-lock.json && \
    npm install --force --registry=https://registry.npmmirror.com && \
    npm run build

FROM nginx
COPY --from=frontend_build /app/platform/build/ /usr/share/nginx/html/platform
COPY --from=frontend_build /app/client/build/ /usr/share/nginx/html/client
COPY /nginx.conf /etc/nginx/conf.d/default.conf
