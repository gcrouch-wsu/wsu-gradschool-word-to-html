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

# Railway sets PORT env var at runtime
CMD ["python", "-c", "import os, subprocess; port = os.environ.get('PORT', '5000'); subprocess.run(['gunicorn', 'word_to_wordpressV4:app', '--bind', f'0.0.0.0:{port}'])"]
