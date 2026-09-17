FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# CockroachDB CA cert is mounted at runtime (docker run -v ...), not baked into
# the image, since this repo is public and the cert/env must never be committed.
ENV SSL_CERT_FILE=/certs/root.crt

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]