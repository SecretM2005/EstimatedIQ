"""
BERT Feature Extraction mit bert-base-german-cased.
Wandelt Ausschreibungstexte in numerische Embeddings um.
"""

import logging
from functools import lru_cache

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

logger = logging.getLogger(__name__)

MODEL_NAME = "bert-base-german-cased"
MAX_LENGTH = 512
BATCH_SIZE = 16


@lru_cache(maxsize=1)
def _load_model_and_tokenizer():
    """Lädt Tokenizer und Modell einmalig und cached das Ergebnis."""
    logger.info("Lade BERT-Modell: %s", MODEL_NAME)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModel.from_pretrained(MODEL_NAME)
    model.eval()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = model.to(device)
    logger.info("Modell geladen auf: %s", device)
    return tokenizer, model, device


def extract_embeddings(texts: list[str]) -> np.ndarray:
    """
    Gibt [CLS]-Embeddings (768-dim) für eine Liste von Texten zurück.
    Verarbeitet in Batches, um GPU-Speicher zu schonen.
    """
    tokenizer, model, device = _load_model_and_tokenizer()
    all_embeddings = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        encoded = tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=MAX_LENGTH,
            return_tensors="pt",
        )
        encoded = {k: v.to(device) for k, v in encoded.items()}

        with torch.no_grad():
            output = model(**encoded)

        # [CLS]-Token als Satzrepräsentation
        cls_embeddings = output.last_hidden_state[:, 0, :].cpu().numpy()
        all_embeddings.append(cls_embeddings)

        if (i // BATCH_SIZE + 1) % 10 == 0:
            logger.info("Batch %d/%d verarbeitet", i // BATCH_SIZE + 1, len(texts) // BATCH_SIZE + 1)

    return np.vstack(all_embeddings)
