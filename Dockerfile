FROM python:3.12-slim

# Pin Pandoc to a known-good version. Bump this in lockstep with
# PANDOC_PINNED_VERSION in config.py so the startup check stays honest.
ARG PANDOC_VERSION=3.9.0.2

# Install Pandoc from the official GitHub .deb. We fetch the architecture
# matching the build platform (amd64 or arm64) so the image works on both
# typical x86_64 builders and Apple Silicon.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates wget; \
    arch="$(dpkg --print-architecture)"; \
    deb="pandoc-${PANDOC_VERSION}-1-${arch}.deb"; \
    wget -q "https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/${deb}"; \
    dpkg -i "${deb}"; \
    rm "${deb}"; \
    apt-get purge -y --auto-remove wget; \
    rm -rf /var/lib/apt/lists/*; \
    pandoc --version | head -n 1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
EXPOSE 8080

CMD ["/bin/sh", "-c", "exec gunicorn word_to_wordpressV4:app --bind 0.0.0.0:${PORT}"]
