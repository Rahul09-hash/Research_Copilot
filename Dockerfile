FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RC_DATA_DIR=/app/data \
    RC_OLLAMA_HOST=http://host.docker.internal:11434

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

CMD ["uvicorn", "fast_app:app", "--host=0.0.0.0", "--port=8501"]
