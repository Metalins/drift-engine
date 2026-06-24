FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

# Cloud Run inyecta PORT (default 8080). Local dev usa 8000 si no está seteado.
# `exec` reemplaza el shell con uvicorn → permite señales (SIGTERM) lleguen al proceso.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
