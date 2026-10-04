FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AMYPO_MYSQL_HOST=mysql \
    AMYPO_MYSQL_PORT=3306 \
    AMYPO_MYSQL_DATABASE=amypo

WORKDIR /app

# System deps kept minimal; no build toolchain needed for the default extras.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY scripts /app/scripts
COPY db /app/db
COPY openapi.yaml /app/openapi.yaml

WORKDIR /app/backend

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
