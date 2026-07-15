"""
Gemeinsame pytest-Fixtures für die Backend-Tests.

Strategie: ephemere SQLite (temporäre Datei) + ECHTE Auth
(AUTH_DISABLED=false + HS256-Test-Secret), damit die Tenant-Auflösung aus dem
JWT wirklich durchlaufen wird – nur so lässt sich die Isolation echt testen.
Die echte Demo-/Dev-DB wird nie angefasst.

WICHTIG: Die Umgebungsvariablen müssen gesetzt sein, BEVOR estimateiq-Module
importiert werden (config.py liest env beim Import).
"""

import hashlib
import os
import tempfile
import time
from pathlib import Path

# ── Umgebung fixieren (vor jedem estimateiq-Import) ───────────────────────────
os.environ["AUTH_DISABLED"] = "false"
os.environ["SUPABASE_JWT_SECRET"] = "test-secret-fuer-pytest"
os.environ["DATABASE_URL"] = ""  # erzwingt SQLite, verhindert .env-Override
_TMP_DIR = tempfile.mkdtemp(prefix="estimateiq-test-")
os.environ["SQLITE_PATH"] = str(Path(_TMP_DIR) / "test.db")

import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from estimateiq.angebot import config, models  # noqa: E402
from estimateiq.angebot.database import Base, SessionLocal, engine  # noqa: E402
from estimateiq.api.main import app  # noqa: E402


class Helpers:
    """Test-Konstanten + JWT-Helfer, per `h`-Fixture in Tests verfügbar."""
    TENANT_A = "tenant-a"
    TENANT_B = "tenant-b"
    USER_A = "user-a"      # Mitglied in Tenant A
    USER_B = "user-b"      # Mitglied in Tenant B
    ADMIN_A = "admin-a"    # Admin in Tenant A

    @staticmethod
    def token(user_id: str) -> str:
        return jwt.encode(
            {"sub": user_id, "aud": "authenticated", "exp": int(time.time()) + 3600},
            config.SUPABASE_JWT_SECRET,
            algorithm="HS256",
        )

    @classmethod
    def auth(cls, user_id: str) -> dict:
        return {"Authorization": f"Bearer {cls.token(user_id)}"}


def unit_vector(index: int, dim: int = 384) -> list[float]:
    """Einheitsvektor mit 1.0 an `index` – für deterministische Cosine-Tests."""
    v = [0.0] * dim
    v[index % dim] = 1.0
    return v


@pytest.fixture()
def h() -> type[Helpers]:
    return Helpers


@pytest.fixture()
def db_factory():
    """Frische Tabellen + zwei Tenants/Benutzer je Test. Liefert die SessionLocal-Factory."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    s = SessionLocal()
    try:
        s.add_all([
            models.Tenant(id=Helpers.TENANT_A, name="Tenant A GmbH"),
            models.Tenant(id=Helpers.TENANT_B, name="Tenant B GmbH"),
            models.TenantUser(user_id=Helpers.USER_A, tenant_id=Helpers.TENANT_A, email="a@a.de", rolle="mitglied"),
            models.TenantUser(user_id=Helpers.USER_B, tenant_id=Helpers.TENANT_B, email="b@b.de", rolle="mitglied"),
            models.TenantUser(user_id=Helpers.ADMIN_A, tenant_id=Helpers.TENANT_A, email="admin@a.de", rolle="admin"),
        ])
        s.commit()
    finally:
        s.close()
    yield SessionLocal
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db_factory) -> TestClient:
    # Kein Context-Manager → Lifespan (und damit der Embedding-Warmup) läuft nicht.
    return TestClient(app)


@pytest.fixture()
def fake_embed(monkeypatch):
    """
    Ersetzt das echte Sentence-Transformer-Modell durch deterministische Vektoren.
    So laden Tests kein 120-MB-Modell (schnell, offline, CI-tauglich).
    """
    def _embed(text: str) -> list[float]:
        idx = int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16) % 384
        return unit_vector(idx)

    def _embed_batch(texts):
        return [_embed(t) for t in texts]

    monkeypatch.setattr("estimateiq.angebot.embeddings.embed", _embed, raising=False)
    monkeypatch.setattr("estimateiq.angebot.embeddings.embed_batch", _embed_batch, raising=False)
    return _embed
