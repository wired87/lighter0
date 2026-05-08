FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# System deps for image/vector/3D pipeline libs with minimal footprint.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libgl1 \
        libglib2.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi8 \
    && rm -rf /var/lib/apt/lists/*

COPY r.txt ./
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r r.txt

COPY . .

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

CMD ["python", "main.py"]
