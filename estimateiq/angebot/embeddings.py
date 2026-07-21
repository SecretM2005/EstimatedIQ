"""
Sentence-Transformer-Wrapper für Positions-Embeddings.
Modell: paraphrase-multilingual-MiniLM-L12-v2 (384 Dims, ~120 MB)
Lazy-geladen beim ersten Aufruf.
"""

from __future__ import annotations
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@lru_cache(maxsize=1)
def _get_model():
    from sentence_transformers import SentenceTransformer
    logger.info("Lade Embedding-Modell %s …", MODEL_NAME)
    return SentenceTransformer(MODEL_NAME)


def embed(text: str) -> list[float]:
    """Gibt einen 384-dimensionalen Embedding-Vektor zurück."""
    model = _get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Batch-Embedding für Imports."""
    if not texts:
        return []
    model = _get_model()
    vecs = model.encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False)
    return [v.tolist() for v in vecs]
