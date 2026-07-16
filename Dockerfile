# EstimateIQ Backend – FastAPI + sentence-transformers
# Läuft auf Hugging Face Spaces (SDK: docker), ebenso auf Railway/Render.
# HF führt den Container als Nutzer mit UID 1000 aus – daher non-root + HF_HOME
# an einem für diesen Nutzer les-/schreibbaren Ort.

FROM python:3.11-slim

# Nutzer 1000 anlegen (HF-Konvention)
RUN useradd -m -u 1000 user

ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/home/user/.cache/huggingface \
    HF_HUB_DISABLE_TELEMETRY=1

USER user
WORKDIR /home/user/app

# Abhängigkeiten zuerst (bessere Layer-Caches)
COPY --chown=user requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Embedding-Modell ins Image laden → schneller, netzunabhängiger Start
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

# Anwendungscode
COPY --chown=user estimateiq ./estimateiq
COPY --chown=user migrations ./migrations

# Port: HF nutzt app_port (README) = 8000; Railway/Render setzen $PORT.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn estimateiq.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
