FROM python:3.12-slim
WORKDIR /app
COPY services/demo-app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --system --uid 10002 app
COPY services/demo-app/*.py .
USER app
EXPOSE 8001
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001", "--no-access-log"]
