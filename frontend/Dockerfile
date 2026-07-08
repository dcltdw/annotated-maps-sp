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
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
