# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# Install system deps (none needed — pure Python)
# Copy requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory for SQLite + Telethon session
RUN mkdir -p /app/data

CMD ["python", "main.py"]
