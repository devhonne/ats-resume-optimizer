# Resume Studios public beta: one container serves the API and the built React app.
FROM node:20.18-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 FRONTEND_DIST=/srv/frontend/dist
COPY backend/requirements.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY --from=web /web/dist frontend/dist
WORKDIR /srv/backend
EXPOSE 8000
# --proxy-headers: trust the hosting platform's proxy for the real client IP (used by the rate limit)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
