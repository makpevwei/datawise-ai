FROM python:3.12-slim

# poppler-utils: pdf2image's runtime dependency (PDF -> image, for OCR fallback).
# tesseract-ocr: pytesseract's runtime dependency.
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --no-install-project

COPY . .
RUN uv sync --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# Cloud Run sets $PORT; default 8080 matches its convention for local testing.
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
