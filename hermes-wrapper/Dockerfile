FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Run as root to access Docker socket
# The wrapper is isolated by: loopback-only port, no-new-privileges,
# mem_limit, and network isolation on hermes-net.

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5000"]
