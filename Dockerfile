FROM python:3.12-slim

# Install Pandoc
RUN apt-get update && \
    apt-get install -y --no-install-recommends pandoc && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
EXPOSE 8080

CMD ["/bin/sh", "-c", "exec gunicorn word_to_wordpressV4:app --bind 0.0.0.0:${PORT}"]
