# Multi-stage Dockerfile for the qbo-sync Cloud Run service.
# Stage 1: build wheels for all dependencies.
# Stage 2: minimal runtime image.

FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY pyproject.toml ./
COPY src ./src

RUN pip install --upgrade pip wheel \
 && pip wheel --wheel-dir=/wheels .

# ---

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

# Install dependencies from pre-built wheels (faster, deterministic)
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels qbo-sync \
 && rm -rf /wheels

# Run as non-root for security
RUN useradd --create-home --shell /bin/bash app
USER app

EXPOSE 8080

# Cloud Run injects PORT; gunicorn binds to it.
# 2 workers × 4 threads is plenty for this single-user workload.
CMD exec gunicorn \
    --bind=0.0.0.0:${PORT} \
    --workers=2 \
    --threads=4 \
    --timeout=120 \
    --access-logfile=- \
    --error-logfile=- \
    "src.app:create_app()"
