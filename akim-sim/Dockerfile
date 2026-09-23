# Один образ: собираем фронтенд, кладём рядом с FastAPI, который раздаёт его статикой.
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY data ./data
COPY backend ./backend
COPY --from=web /web/dist ./frontend/dist
ENV AKIM_DB_PATH=/data/akim.db
VOLUME ["/data"]
EXPOSE 8000
WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
