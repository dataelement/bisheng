FROM node:20-alpine as frontend_build
ARG BACKEND
WORKDIR /app
COPY . /app
# pnpm workspace build (registry comes from .npmrc; packageManager pins the version).
RUN corepack enable && corepack prepare pnpm@9.15.9 --activate
RUN cd /app && pnpm install --frozen-lockfile
RUN cd /app && pnpm --filter bisheng build && pnpm --filter bishengchat build

FROM nginx
COPY --from=frontend_build /app/platform/build/ /usr/share/nginx/html/platform
COPY --from=frontend_build /app/client/build/ /usr/share/nginx/html/client
COPY /nginx.conf /etc/nginx/conf.d/default.conf
