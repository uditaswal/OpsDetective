FROM python:3.12-slim
WORKDIR /app
COPY services/worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --system --uid 10003 app
USER app
CMD ["rq", "worker", "investigations", "--url", "redis://redis:6379/0"]
