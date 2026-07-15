# frontend/Dockerfile
# Stage 1: build the SPA. No VITE_API_BASE on purpose — apiBase.ts then defaults to
# the relative "/api/v1", which is correct behind the chart's same-origin Ingress.
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json .npmrc ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: serve the static build.
FROM nginx:1.27-alpine
# Patch the base image's OS packages. Upstream rebuilds this tag on its own
# cadence, so its Alpine packages lag the security repo: the M4 pipeline's
# Trivy gate blocked this image on CVE-2026-31789 (openssl heap overflow via
# large X.509 certs), where the base shipped libssl3/libcrypto3 3.3.3-r0 while
# Alpine v3.21 already had the fixed 3.3.7-r0. Upgrading in place fixes it now
# rather than waiting on an upstream rebuild, and keeps doing so for the next
# such CVE instead of pinning a version that goes stale.
RUN apk --no-cache upgrade
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
