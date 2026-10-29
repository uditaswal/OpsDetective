FROM python:3.12-slim
WORKDIR /app
COPY services/gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --system --uid 10004 app
COPY services/gateway/app.py .
USER app
EXPOSE 4318
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "4318"]
