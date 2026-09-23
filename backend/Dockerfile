FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
ENV TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache
RUN python -c "import tiktoken; tiktoken.get_encoding('o200k_base')" && chmod -R a+rX /opt/tiktoken-cache
COPY backend/app ./app
COPY data /data
ENV DATA_DIR=/data
RUN useradd --create-home appuser && mkdir -p /app/state && chown appuser:appuser /app/state
ENV DB_PATH=/app/state/akim.sqlite3 AI_PRICING_PATH=/data/ai_pricing.json
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

