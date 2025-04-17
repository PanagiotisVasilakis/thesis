FROM python:3.9-bullseye-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends     build-essential     && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Create virtual environment and install dependencies
RUN python -m venv /venv
ENV PATH="/venv/bin:/home/appuser/.vscode-server/bin/17baf841131aa23349f217ca7c570c76ee87b957/bin/remote-cli:/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/home/appuser/.vscode-server/data/User/globalStorage/github.copilot-chat/debugCommand"
RUN pip install --no-cache-dir -U pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.9-bullseye-slim

# Create non-root user
RUN useradd -m appuser

# Copy virtual environment from builder
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:/home/appuser/.vscode-server/bin/17baf841131aa23349f217ca7c570c76ee87b957/bin/remote-cli:/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/home/appuser/.vscode-server/data/User/globalStorage/github.copilot-chat/debugCommand"

# Set working directory
WORKDIR /app

# Copy application code
COPY . .

# Set permissions
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 5050

# Set environment variables
ENV FLASK_APP=app.py
ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

# Run the application with gunicorn for production
CMD ["gunicorn", "--bind", "0.0.0.0:5050", "--workers", "4", "--threads", "2", "app:app"]
