# tours.batumi Instagram Automation
# Python 3.10 + FFmpeg for video composition

FROM python:3.10-slim

# Install system dependencies:
# - ffmpeg: video composition with Ken Burns effect
# - openssh-client: SCP upload to media hosting
# - tzdata: timezone support for scheduler
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    openssh-client \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Set timezone to Moscow (scheduler uses MSK)
ENV TZ=Europe/Moscow

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Install Python dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=appuser:appuser . .

# Create directories for volumes (will be mounted from host)
RUN mkdir -p /app/data /app/logs /app/output \
    && chown -R appuser:appuser /app/data /app/logs /app/output

# Switch to non-root user
USER appuser

# Default command: run full system (scheduler + telegram bot)
CMD ["python", "main.py", "run"]
