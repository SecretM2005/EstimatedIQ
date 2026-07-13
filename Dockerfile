# EstimateIQ Backend – FastAPI + sentence-transformers
# Für Railway oder Render (baut direkt aus diesem Dockerfile).

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /app

# Abhängigkeiten zuerst (bessere Layer-Caches)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Embedding-Modell schon ins Image laden → schneller, netzunabhängiger Start
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

# Anwendungscode
COPY estimateiq ./estimateiq
COPY migrations ./migrations

# Plattformen (Railway/Render) geben den Port über $PORT vor.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn estimateiq.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
