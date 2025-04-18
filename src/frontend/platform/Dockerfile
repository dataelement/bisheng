FROM node:18-alpine as frontend_build
ARG BACKEND
WORKDIR /app
COPY . /app
RUN cd /app/client && npm install --force --registry=https://registry.npmmirror.com && npm run build
RUN cd /app/platform && npm install --force --registry=https://registry.npmmirror.com && npm run build

FROM nginx
COPY --from=frontend_build /app/client/build/ /usr/share/nginx/html/client
COPY --from=frontend_build /app/platform/build/ /usr/share/nginx/html/platform
COPY /nginx.conf /etc/nginx/conf.d/default.conf