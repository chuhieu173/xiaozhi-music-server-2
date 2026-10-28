FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app.py .

RUN useradd --create-home --uid 10001 appuser
USER appuser
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-10000}"]
