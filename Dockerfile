# syntax=docker/dockerfile:1.7
# =============================================================================
# bitamed application image
#
# One image serves both the web app and the ingestion worker. The OCR
# toolchain is heavy (~700 MB), but splitting it into a second image means
# maintaining two dependency sets for no real gain at this size.
#
# Builds natively on linux/amd64 (WSL2) and linux/arm64 (Apple Silicon).
# =============================================================================

FROM python:3.12-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# ocrmypdf pulls the whole pipeline: ghostscript (PDF/A), unpaper (--clean),
# qpdf (linearization), pngquant/jbig2 (size). The tesseract language packs
# are the three we support; each is a few MB.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-spa \
        tesseract-ocr-por \
        tesseract-ocr-eng \
        ocrmypdf \
        ghostscript \
        unpaper \
        qpdf \
        pngquant \
        poppler-utils \
        libjpeg62-turbo \
        zlib1g \
        curl \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# opencv-python-headless, not opencv-python: no GUI libs, ~200 MB smaller,
# and libGL is not present in a slim image anyway.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt


# --- dev -------------------------------------------------------------------
FROM base AS dev

RUN pip install --no-cache-dir \
        watchfiles ruff mypy pytest pytest-asyncio httpx

ENV PYTHONPATH=/srv
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


# --- prod ------------------------------------------------------------------
FROM base AS prod

# Never run as root in production.
RUN useradd --create-home --uid 10001 bitamed

COPY --chown=bitamed:bitamed ./app       /srv/app
COPY --chown=bitamed:bitamed ./templates /srv/templates
COPY --chown=bitamed:bitamed ./static    /srv/static
COPY --chown=bitamed:bitamed ./db        /srv/db

USER bitamed
ENV PYTHONPATH=/srv

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]
