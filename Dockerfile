FROM python:3.11-slim

# Tesseract backs image OCR; without it image submissions return HTTP 422.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       tesseract-ocr tesseract-ocr-hin tesseract-ocr-kan tesseract-ocr-mar \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/requirements-ml.txt ./requirements-ml.txt
RUN pip install --no-cache-dir -r requirements-ml.txt

COPY backend/ ./
COPY scripts/docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Runtime image contains live application code only; synthetic benchmark data,
# fixture-backed fictional adapters, and test modules are excluded by
# .dockerignore.
ENV HF_HOME=/opt/finalsay/hf-cache
RUN useradd --create-home --uid 1000 finalsay \
    && mkdir -p "$HF_HOME" \
    && chown -R finalsay:finalsay /app "$HF_HOME"
USER finalsay

# Bake the configured embedding and NLI artifacts into the image. Runtime
# inference then uses the same local models without reaching Hugging Face.
RUN HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 python - <<'PY'
from finalsay.config import get_settings
from sentence_transformers import CrossEncoder, SentenceTransformer

settings = get_settings()
SentenceTransformer(settings.semantic_embedding_model, device="cpu")
CrossEncoder(settings.semantic_nli_model, device="cpu", max_length=512)
PY

ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
