FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    REPO2GPT_STORAGE_ROOT=/data/jobs

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --uid 1001 --create-home appuser \
    && mkdir -p /data/jobs \
    && chown -R appuser /data/jobs

USER appuser

EXPOSE 8000

CMD ["gunicorn", "api.server:app", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8000", "--timeout", "300", "--log-level", "info"]
