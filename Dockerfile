# The dashboard and the Drive sync. Nothing personal is baked in: the
# database, backups and Garmin login live in ./data and the archive in Google
# Drive, both mounted by docker-compose.yml.
FROM python:3.12-slim

# Days and hours are cut in the archive's zone (Asia/Kolkata), which needs the
# zone database; flock serialises autosync runs.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata util-linux \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY wellbeing/ wellbeing/
COPY tests/ tests/
COPY autosync.sh ./

# Same uid as the WSL user, so files written to the mounted ./data and Drive
# folder stay owned by you.
RUN useradd --uid 1000 --create-home app && chown -R app /app
USER app

ENV PY=python \
    PYTHONUNBUFFERED=1 \
    PHONE_USAGE_ARCHIVE=/drive/PhoneUsage/archive \
    DASHBOARD_ALWAYS_ON=1

EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/', timeout=4)"
# 0.0.0.0 inside the container; docker-compose.yml publishes it on the
# host's 127.0.0.1 only, so it is still reachable from this PC alone.
CMD ["python", "-m", "wellbeing", "serve", "--host", "0.0.0.0", "--port", "5000"]
