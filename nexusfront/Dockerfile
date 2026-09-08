FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
# vite lives in devDependencies — never omit dev deps here
RUN npm ci --include=dev
COPY . .
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

# Static production server with SPA fallback (fixes blank page from vite preview without config)
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
RUN printf 'server {\n  listen 80;\n  root /usr/share/nginx/html;\n  index index.html;\n  location / { try_files $uri $uri/ /index.html; }\n  location /assets/ { expires 1y; add_header Cache-Control "public, immutable"; }\n}\n' > /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
