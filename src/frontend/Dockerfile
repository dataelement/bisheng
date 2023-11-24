FROM node:18-alpine as frontend_build
ARG BACKEND
WORKDIR /app
COPY . /app
RUN npm install --force
RUN npm run build

FROM nginx
COPY --from=frontend_build /app/build/ /usr/share/nginx/html
COPY /nginx.conf /etc/nginx/conf.d/default.conf