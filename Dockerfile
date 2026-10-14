FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

# gcc + libc headers compile the student programs; util-linux provides `prlimit` (resource limits) and `setpriv`.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev util-linux \
    && rm -rf /var/lib/apt/lists/*

# Unprivileged user that runs both the web server and (inside resource limits) the student programs.
RUN useradd --create-home --uid 1000 evaluator

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY sample_quiz_data ./sample_quiz_data
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Application code is read-only for everyone (student programs cannot modify it);
# only the data directory is writable by the runtime user.
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
    && chmod 0755 /usr/local/bin/docker-entrypoint.sh \
    && mkdir -p /app/data \
    && chown -R root:root /app \
    && chmod -R a-w /app \
    && chown evaluator:evaluator /app/data \
    && chmod u+w /app/data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT', '8000'), timeout=4)"

# Starts as root only to fix ownership of a mounted persistent disk, then drops to uid 1000.
ENTRYPOINT ["docker-entrypoint.sh"]

# One worker on purpose: the job registry and rate limiter live in memory.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*' --timeout-keep-alive 75"]
