# Multi-stage build for security and efficiency
FROM python:3.10-slim-bullseye AS builder

# Set build arguments for security
ARG BUILD_DATE
ARG VCS_REF
ARG VERSION

# Add metadata labels
LABEL maintainer="ML Service Team" \
      org.label-schema.build-date=$BUILD_DATE \
      org.label-schema.name="ml-service" \
      org.label-schema.description="5G Network Optimization ML Service" \
      org.label-schema.vcs-ref=$VCS_REF \
      org.label-schema.vcs-url="https://github.com/example/5g-optimization" \
      org.label-schema.version=$VERSION \
      org.label-schema.schema-version="1.0"

WORKDIR /app

# Install build dependencies with security updates
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create virtual environment and upgrade pip
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Copy requirements first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.10-slim-bullseye AS production

# Install runtime dependencies and security updates
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    libgomp1 \
    dumb-init \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user with specific UID/GID for security
RUN groupadd --gid 1001 appuser && \
    useradd --uid 1001 --gid appuser --shell /bin/bash --create-home appuser

# Copy virtual environment from builder
COPY --from=builder /venv /venv

# Set secure PATH
ENV PATH="/venv/bin:/usr/local/bin:/usr/bin:/bin"

# Set working directory
WORKDIR /app

# Copy application code with proper ownership
COPY --chown=appuser:appuser . .

# Create necessary directories with proper permissions
RUN mkdir -p /app/logs /app/data /app/models /app/tmp && \
    chown -R appuser:appuser /app && \
    chmod -R 755 /app && \
    chmod 700 /app/logs /app/data /app/models /app/tmp

# Switch to non-root user
USER appuser

# Expose port (non-privileged)
EXPOSE 5050

# Set secure environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    FLASK_APP=app.py \
    FLASK_ENV=production \
    LOG_LEVEL=INFO \
    WORKER_PROCESSES=4 \
    WORKER_THREADS=2 \
    REQUEST_TIMEOUT=30 \
    MAX_REQUEST_SIZE=52428800 \
    A3_HYSTERESIS_DB=2.0 \
    A3_TTT_S=0.0

# Add health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5050/api/health || exit 1

# Use dumb-init to handle signals properly
ENTRYPOINT ["/usr/bin/dumb-init", "--"]

# Run with secure gunicorn configuration
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5050", \
     "--workers", "4", \
     "--threads", "2", \
    "--timeout", "30", \
    "--keep-alive", "5", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "100", \
     "--preload", \
     "--log-level", "info", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--capture-output", \
     "--worker-class", "gthread", \
     "--worker-tmp-dir", "/dev/shm", \
     "app:app"]
