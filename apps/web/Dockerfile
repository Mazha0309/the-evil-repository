FROM node:22-alpine AS builder
ARG VITE_API_BASE=http://127.0.0.1:8080/api/v1
ENV VITE_API_BASE=$VITE_API_BASE
RUN corepack enable && corepack prepare pnpm@11.3.0 --activate
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json ./apps/web/package.json
RUN pnpm install --frozen-lockfile --filter @evil-repository/web...
COPY apps/web ./apps/web
RUN pnpm --filter @evil-repository/web build

FROM nginx:1.29-alpine
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/apps/web/dist /usr/share/nginx/html
EXPOSE 80
