FROM python:3.12-slim

# Install Pandoc
RUN apt-get update && \
    apt-get install -y --no-install-recommends pandoc && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
RUN pip install --no-cache-dir \
    flask~=3.0 \
    python-docx~=1.1 \
    beautifulsoup4~=4.12 \
    lxml~=5.1 \
    werkzeug~=3.0 \
    gunicorn~=22.0

# Copy application
COPY . .

# Railway sets PORT env var
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh
CMD ["/app/start.sh"]
