FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY products/api-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=10001:10001 products/api-service ./products/api-service
COPY --chown=10001:10001 products/url-shortener ./products/url-shortener
COPY --chown=10001:10001 products/uptime-monitor ./products/uptime-monitor
RUN mkdir -p \
      /app/products/api-service/data \
      /app/products/url-shortener/data \
      /app/products/uptime-monitor/data \
    && chown -R 10001:10001 /app/products

USER 10001:10001
EXPOSE 8080

WORKDIR /app/products/api-service
CMD ["python", "main.py"]
