FROM node:20-alpine AS platform_deps
WORKDIR /app/platform
COPY platform/package.json platform/package-lock.json ./
COPY platform/local-packages ./local-packages
RUN --mount=type=cache,id=bisheng-platform-npm,target=/root/.npm,sharing=locked \
    npm ci --registry=https://registry.npmmirror.com --prefer-offline --no-audit --fund=false

FROM node:20-alpine AS client_deps
WORKDIR /app/client
COPY client/package.json client/package-lock.json ./
COPY client/local-packages ./local-packages
RUN --mount=type=cache,id=bisheng-client-npm,target=/root/.npm,sharing=locked \
    npm ci --registry=https://registry.npmmirror.com --prefer-offline --no-audit --fund=false

FROM node:20-alpine AS frontend_build
ARG BACKEND
WORKDIR /app
COPY --from=platform_deps /app/platform/node_modules ./platform/node_modules
COPY --from=client_deps /app/client/node_modules ./client/node_modules
COPY . .
RUN npm --prefix platform run build
RUN npm --prefix client run build

FROM nginx
COPY --from=frontend_build /app/platform/build/ /usr/share/nginx/html/platform
COPY --from=frontend_build /app/client/build/ /usr/share/nginx/html/client
COPY /nginx.conf /etc/nginx/conf.d/default.conf
