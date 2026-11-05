# syntax=docker/dockerfile:1
# Build web console (React + Vite) rồi đóng vào ảnh Caddy. Build context = gốc repo.
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM caddy:2.8-alpine
COPY --from=web /web/dist /srv
COPY deploy/caddy/Caddyfile /etc/caddy/Caddyfile

