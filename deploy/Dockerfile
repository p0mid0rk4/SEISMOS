FROM python:3.12-slim

LABEL org.opencontainers.image.title="СЕЙСМОС" \
      org.opencontainers.image.description="Сейсмическая система контроля периметра на геофонах GS-20DX" \
      org.opencontainers.image.version="1.0.0"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SEISMOS_PORT=8000 \
    SEISMOS_SITE_CONFIG=config/site.yaml \
    SEISMOS_DATABASE_URL=sqlite:///data/seismos.db

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY seismos/ ./seismos/
COPY console/ ./console/
COPY config/ ./config/
COPY README.md ./

RUN mkdir -p /app/data/recordings

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

CMD ["python", "-m", "seismos.cli.main", "serve", "--host", "0.0.0.0", "--port", "8000"]
