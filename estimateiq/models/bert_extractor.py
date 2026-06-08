"""
BERT Feature Extractor – bert-base-german-cased.

Extrahiert aus der Spalte "beschreibung" vier semantische Features:

  projekttyp_bert      (str)       – Web | App | Integration | Migration |
                                      Beratung | Infrastruktur | Sonstiges
  technologien         (list[str]) – erkannte Technologien (SAP, React, AWS…)
  komplexitaet         (int 1-5)   – 1 = einfach, 5 = sehr komplex
  schnittstellen_anzahl (int)      – geschätzte Anzahl externer Schnittstellen

Methodik:
  - projekttyp_bert:  Zero-Shot via Kosinus-Ähnlichkeit (Mean-Pooling) zu
                       deutschen Anker-Texten je Kategorie
  - technologien:     Regex-Wörterbuch (50+ Technologien, case-insensitive)
  - komplexitaet:     Gewichteter Score aus 4 Signalen:
                       BERT-Ähnlichkeit zu Komplexitätsankern (25 %)
                       + Textlänge (25 %) + Tech-Anzahl (25 %)
                       + Schlüsselwörter (25 %)
  - schnittstellen_anzahl: Regex + Deutsch-Zahlwörter auf Interface-Kontext
"""

import logging
import math
import re
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd
import torch
from transformers import AutoModel, AutoTokenizer

logger = logging.getLogger(__name__)

MODEL_NAME  = "bert-base-german-cased"
MAX_LENGTH  = 512
BATCH_SIZE  = 16

# ---------------------------------------------------------------------------
# Konfiguration – Anker-Texte für Zero-Shot-Klassifikation
# ---------------------------------------------------------------------------

# Je Projekttyp: 3 deutsche Beschreibungs-Ankersätze.
# Mean-Pooling-Embedding der Beschreibung wird mit dem Mittel aller
# Ankervektoren dieser Kategorie verglichen (Kosinus-Ähnlichkeit).
PROJEKTTYP_ANKER: dict[str, list[str]] = {
    "Web": [
        "Entwicklung eines Webportals und einer Webanwendung mit modernem Frontend",
        "Online-Plattform mit Benutzeroberfläche für Browser und CMS",
        "Responsive Website mit Frontend Backend REST API und Datenbankanbindung",
    ],
    "App": [
        "Entwicklung einer nativen mobilen App für iOS und Android Smartphones",
        "Cross-Platform Mobile Anwendung für App Store und Google Play",
        "Mobile App mit Push-Benachrichtigungen Offline-Funktionalität und GPS",
    ],
    "Integration": [
        "Systemintegration und Schnittstellenentwicklung zwischen verschiedenen IT-Systemen",
        "Middleware API Integration ETL Datenaustausch zwischen Softwaresystemen",
        "Anbindung von Drittsystemen über REST SOAP und Nachrichtenbroker",
    ],
    "Migration": [
        "Datenmigration und Ablösung von Altsystemen auf eine neue Plattform",
        "Legacy-System-Ablösung und Überführung bestehender Daten in neue Systeme",
        "Systemwechsel Datenbankmigrierung Modernisierung veralteter Softwareumgebungen",
    ],
    "Beratung": [
        "IT-Beratung Strategieentwicklung Konzeption und Machbarkeitsanalyse",
        "Consulting Prozessoptimierung IT-Strategie und Fachberatung für Behörden",
        "Beratungsleistungen Anforderungsanalyse und technische Konzepterstellung",
    ],
    "Infrastruktur": [
        "Aufbau und Betrieb von Cloud-Infrastruktur mit Kubernetes Docker und Terraform",
        "Server Netzwerk Rechenzentrum Hosting Monitoring Betrieb und DevOps",
        "IT-Infrastruktur Automatisierung CI/CD Container-Plattform und Cloud-Betrieb",
    ],
    "Sonstiges": [
        "Softwarewartung Pflege und Support bestehender Anwendungen",
        "IT-Schulungen Trainings und allgemeine Dienstleistungen im IT-Bereich",
    ],
}

# Anker-Texte für Komplexitätsbewertung (Pole niedrig ↔ hoch)
KOMPLEX_ANKER_HOCH = [
    "Hochkomplexes Großprojekt mit zahlreichen Schnittstellen zu Fremdsystemen, "
    "Echtzeit-Datenmigration, Microservices-Architektur und Multi-Mandanten-Fähigkeit",
    "Komplexe System-Integration mit SAP-Migration, KI-Komponenten, "
    "verteiltem Betrieb und strikten SLA-Anforderungen",
]
KOMPLEX_ANKER_NIEDRIG = [
    "Einfache kleine Softwareanpassung mit überschaubarem Umfang",
    "Geringfügige Wartungsarbeiten an bestehender Anwendung ohne Schnittstellen",
]

# ---------------------------------------------------------------------------
# Technologie-Wörterbuch (Regex-Muster, case-insensitive)
# ---------------------------------------------------------------------------

TECH_PATTERNS: dict[str, str] = {
    # Cloud & DevOps
    "AWS":          r"\bAWS\b|Amazon Web Services",
    "Azure":        r"\bAzure\b|Microsoft Azure",
    "GCP":          r"\bGCP\b|Google Cloud",
    "Kubernetes":   r"\bKubernetes\b|\bK8s\b",
    "Docker":       r"\bDocker\b|Containerisierung",
    "Terraform":    r"\bTerraform\b",
    "Ansible":      r"\bAnsible\b",
    "CI/CD":        r"\bCI/CD\b|Jenkins\b|GitLab CI|GitHub Actions",
    # Enterprise
    "SAP":          r"\bSAP\b",
    "Oracle":       r"\bOracle\b(?!\s+DB)",
    "Oracle DB":    r"\bOracle\s*DB\b|Oracle\s*Database",
    "Salesforce":   r"\bSalesforce\b",
    "ServiceNow":   r"\bServiceNow\b",
    "SharePoint":   r"\bSharePoint\b",
    "Dynamics 365": r"\bDynamics\s*365\b|Microsoft\s*Dynamics",
    "DATEV":        r"\bDATEV\b",
    "Navision":     r"\bNavision\b",
    # Programmiersprachen
    "Python":       r"\bPython\b",
    "Java":         r"\bJava\b(?!Script)",
    "JavaScript":   r"\bJavaScript\b|\bNode\.js\b|\bNodeJS\b",
    "TypeScript":   r"\bTypeScript\b",
    ".NET":         r"\.NET\b|dotnet\b",
    "C#":           r"\bC#\b",
    "C++":          r"\bC\+\+\b",
    "PHP":          r"\bPHP\b",
    "Go":           r"\bGolang\b",
    "Rust":         r"\bRust\b(?!\s*belt)",
    "Ruby":         r"\bRuby\b(?:\s*on\s*Rails)?",
    "Kotlin":       r"\bKotlin\b",
    "Swift":        r"\bSwift\b",
    # Frontend-Frameworks
    "React":        r"\bReact\b(?:\.js)?",
    "Angular":      r"\bAngular\b",
    "Vue.js":       r"\bVue\.?[Jj]s\b|\bVue\b",
    "Next.js":      r"\bNext\.js\b",
    "Flutter":      r"\bFlutter\b",
    # Datenbanken
    "PostgreSQL":   r"\bPostgreSQL\b|\bPostgres\b",
    "MySQL":        r"\bMySQL\b",
    "MSSQL":        r"\bMSSQL\b|SQL\s*Server",
    "MongoDB":      r"\bMongoDB\b",
    "Redis":        r"\bRedis\b",
    "Elasticsearch":r"\bElasticsearch\b|\bElastic\b",
    "Cassandra":    r"\bCassandra\b",
    # Integration & Messaging
    "REST":         r"\bREST(?:ful)?\b",
    "SOAP":         r"\bSOAP\b",
    "GraphQL":      r"\bGraphQL\b",
    "Kafka":        r"\bKafka\b|Apache Kafka",
    "RabbitMQ":     r"\bRabbitMQ\b",
    "gRPC":         r"\bgRPC\b",
    # Security & IAM
    "OAuth":        r"\bOAuth\b",
    "LDAP":         r"\bLDAP\b",
    "Keycloak":     r"\bKeycloak\b",
    "SSO":          r"\bSSO\b|Single Sign.On",
    "Active Directory": r"\bActive\s*Directory\b|\bAD\b(?=\s+Anbindung|\s+Integration)",
    # KI / Data
    "Machine Learning": r"\bMachine\s*Learning\b|\bML\b(?=\s+Modell|\s+Pipeline)",
    "TensorFlow":   r"\bTensorFlow\b",
    "PyTorch":      r"\bPyTorch\b",
    "Power BI":     r"\bPower\s*BI\b",
    "Tableau":      r"\bTableau\b",
}

# ---------------------------------------------------------------------------
# Schlüsselwörter für Komplexitätsbewertung
# ---------------------------------------------------------------------------

KOMPLEX_HOCH_KEYWORDS = [
    r"\bMigration\b", r"\bEchtzeit\b", r"\bhochverfügbar\b",
    r"\bMicroservices?\b", r"\bKI\b", r"\bkünstliche Intelligenz\b",
    r"\bMachine Learning\b", r"\bBig Data\b", r"\bMulti.Mandant", r"\bCluster\b",
    r"\b災害復旧\b",  # wird nie matchen, hält Liste offen
    r"\bSkalier", r"\bLastverteilung\b", r"\bFail.?over\b", r"\bContainer\b",
]
KOMPLEX_MITTEL_KEYWORDS = [
    r"\bSchnittstelle", r"\bIntegration\b", r"\bAPI\b", r"\bWorkflow\b",
    r"\bRechtemanagement\b", r"\bAuthentifizierung\b", r"\bBerichtswesen\b",
    r"\bRechenzentrum\b", r"\bClustering\b",
]
KOMPLEX_NIEDRIG_KEYWORDS = [
    r"\bPflege\b", r"\bWartung\b", r"\bkleine Anpassung\b",
    r"\bgeringfügig\b", r"\beinzel", r"\bunter.*\d+\s*Tag",
]

# ---------------------------------------------------------------------------
# Zahlwörter für Schnittstellen-Schätzung
# ---------------------------------------------------------------------------

ZAHLWOERTER: dict[str, int] = {
    "keine": 0, "eine": 1, "einem": 1, "einer": 1, "ein": 1,
    "zwei": 2, "drei": 3, "vier": 4, "fünf": 5,
    "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
    "mehrere": 3, "verschiedene": 4, "zahlreiche": 6, "diverse": 4,
    "wenige": 2, "viele": 5,
}


# ---------------------------------------------------------------------------
# BERT-Modell (einmalig laden, gecacht)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _lade_modell_gecacht():
    """Lädt Tokenizer und Modell einmalig; wird durch lru_cache für die Prozesslaufzeit gecacht."""
    logger.info("[BERT] Lade %s ...", MODEL_NAME)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model     = AutoModel.from_pretrained(MODEL_NAME)
    model.eval()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model  = model.to(device)
    logger.info("[BERT] Modell geladen auf: %s", device)
    return tokenizer, model, device


def _mean_pooling(token_embeddings: torch.Tensor, attention_mask: torch.Tensor) -> np.ndarray:
    """
    Mean-Pooling über Token-Embeddings (Padding ausgeblendet).
    Liefert bessere Satzrepräsentationen als reiner [CLS]-Token
    bei nicht-feingetuntem BERT.
    """
    mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
    summe   = torch.sum(token_embeddings * mask_expanded, dim=1)
    count   = torch.clamp(mask_expanded.sum(dim=1), min=1e-9)
    pooled  = (summe / count).cpu().numpy()
    # L2-Normalisierung für Kosinus-Ähnlichkeit
    normen  = np.linalg.norm(pooled, axis=1, keepdims=True)
    return pooled / np.maximum(normen, 1e-12)


def _einbetten(texte: list[str]) -> np.ndarray:
    """
    Berechnet normalisierte Mean-Pooling-Embeddings (768-dim) für eine Textliste.
    Verarbeitet in Batches, GPU-sicher.
    """
    if not texte:
        return np.empty((0, 768), dtype=np.float32)

    tokenizer, model, device = _lade_modell_gecacht()
    alle_embeddings: list[np.ndarray] = []

    for i in range(0, len(texte), BATCH_SIZE):
        batch   = texte[i : i + BATCH_SIZE]
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

        pooled = _mean_pooling(output.last_hidden_state, encoded["attention_mask"])
        alle_embeddings.append(pooled)

        if len(texte) > BATCH_SIZE and (i // BATCH_SIZE + 1) % 5 == 0:
            logger.info("[BERT] Batch %d/%d", i // BATCH_SIZE + 1, math.ceil(len(texte) / BATCH_SIZE))

    return np.vstack(alle_embeddings).astype(np.float32)


# ---------------------------------------------------------------------------
# Anker-Embeddings (einmalig nach Modell-Load berechnen)
# ---------------------------------------------------------------------------

_anker_cache: dict[str, Any] = {}


def _hole_anker_embeddings() -> dict[str, Any]:
    """
    Berechnet und cached Anker-Embeddings für Projekttypen und Komplexität.
    Wird beim ersten Aufruf einmalig berechnet.
    """
    if _anker_cache:
        return _anker_cache

    logger.info("[BERT] Berechne Anker-Embeddings ...")

    # Projekttyp-Anker: pro Kategorie einen gemittelten Vektor
    typ_embeddings: dict[str, np.ndarray] = {}
    for kategorie, texte in PROJEKTTYP_ANKER.items():
        embs = _einbetten(texte)
        typ_embeddings[kategorie] = embs.mean(axis=0)

    # Komplexitäts-Pole
    emb_hoch    = _einbetten(KOMPLEX_ANKER_HOCH).mean(axis=0)
    emb_niedrig = _einbetten(KOMPLEX_ANKER_NIEDRIG).mean(axis=0)

    _anker_cache["projekttypen"]    = typ_embeddings
    _anker_cache["komplex_hoch"]    = emb_hoch
    _anker_cache["komplex_niedrig"] = emb_niedrig

    logger.info("[BERT] Anker-Embeddings bereit.")
    return _anker_cache


# ---------------------------------------------------------------------------
# Feature 1 – Projekttyp-Klassifikation (Zero-Shot)
# ---------------------------------------------------------------------------

def _klassifiziere_projekttyp(embeddings: np.ndarray) -> list[str]:
    """
    Ordnet jedes Embedding dem Projekttyp mit höchster Kosinus-Ähnlichkeit zu.
    """
    anker = _hole_anker_embeddings()["projekttypen"]
    kategorien = list(anker.keys())
    # Matrix: [n_kategorien, 768]
    anker_matrix = np.stack([anker[k] for k in kategorien])

    # Kosinus-Ähnlichkeit: da alle Vektoren L2-normiert sind, ist dot = cosine
    scores = embeddings @ anker_matrix.T  # [n, n_kategorien]
    beste  = scores.argmax(axis=1)
    return [kategorien[i] for i in beste]


# ---------------------------------------------------------------------------
# Feature 2 – Technologie-Erkennung (Regex)
# ---------------------------------------------------------------------------

_tech_compiled = {
    name: re.compile(pattern, re.IGNORECASE)
    for name, pattern in TECH_PATTERNS.items()
}


def _erkenne_technologien(text: str) -> list[str]:
    """Gibt eine sortierte Liste aller erkannten Technologien zurück."""
    gefunden = [name for name, regex in _tech_compiled.items() if regex.search(text)]
    return sorted(gefunden)


# ---------------------------------------------------------------------------
# Feature 3 – Komplexität (Hybrid: BERT + Heuristik)
# ---------------------------------------------------------------------------

_komplex_hoch_re    = [re.compile(p, re.IGNORECASE) for p in KOMPLEX_HOCH_KEYWORDS]
_komplex_mittel_re  = [re.compile(p, re.IGNORECASE) for p in KOMPLEX_MITTEL_KEYWORDS]
_komplex_niedrig_re = [re.compile(p, re.IGNORECASE) for p in KOMPLEX_NIEDRIG_KEYWORDS]


def _heuristik_komplexitaet(text: str, tech_anzahl: int, schnittstellen: int) -> float:
    """
    Heuristischer Komplexitäts-Score [0, 1] aus drei Signalen.
    """
    # Signal A: Textlänge (logarithmisch, normiert auf [0,1] mit Sättigungspunkt 3000)
    laenge_score = min(math.log1p(len(text)) / math.log1p(3000), 1.0)

    # Signal B: Technologie-Anzahl
    tech_score = min(tech_anzahl / 8.0, 1.0)

    # Signal C: Schlüsselwörter
    hoch_hits   = sum(1 for r in _komplex_hoch_re    if r.search(text))
    mittel_hits = sum(1 for r in _komplex_mittel_re  if r.search(text))
    niedrig_hits= sum(1 for r in _komplex_niedrig_re if r.search(text))
    # Schnittstellen-Anzahl ebenfalls als Komplexitätssignal
    kw_score = min((hoch_hits * 0.3 + mittel_hits * 0.15 + schnittstellen * 0.1
                    - niedrig_hits * 0.2), 1.0)
    kw_score = max(kw_score, 0.0)

    return (laenge_score + tech_score + kw_score) / 3.0


def _berechne_komplexitaet(
    texte: list[str],
    tech_listen: list[list[str]],
    schnittstellen_liste: list[int],
    embeddings: np.ndarray,
) -> list[int]:
    """
    Berechnet Komplexitätswerte 1–5 als gewichtetes Mittel aus:
      25 % BERT-Ähnlichkeit zu Komplexitätsankern
      75 % Heuristik (Textlänge, Tech-Anzahl, Keywords)
    """
    anker  = _hole_anker_embeddings()
    v_hoch = anker["komplex_hoch"]
    v_nied = anker["komplex_niedrig"]

    ergebnisse: list[int] = []
    for i, (text, techs, schn) in enumerate(zip(texte, tech_listen, schnittstellen_liste)):
        # BERT-Signal: wie viel näher am "hoch"- als am "niedrig"-Pol?
        sim_hoch = float(np.dot(embeddings[i], v_hoch))
        sim_nied = float(np.dot(embeddings[i], v_nied))
        # Normierung: [0,1], 0.5 = neutral
        bert_score = (sim_hoch - sim_nied + 2.0) / 4.0
        bert_score = max(0.0, min(1.0, bert_score))

        heuristik_score = _heuristik_komplexitaet(text, len(techs), schn)

        gesamt = 0.25 * bert_score + 0.75 * heuristik_score
        # Auf Skala 1–5 abbilden
        wert = round(1 + 4 * gesamt)
        ergebnisse.append(int(max(1, min(5, wert))))

    return ergebnisse


# ---------------------------------------------------------------------------
# Feature 4 – Schnittstellen-Anzahl (Regex + Zahlwörter)
# ---------------------------------------------------------------------------

# Explizite Zahlen vor Interface-Wörtern: "3 Schnittstellen", "5 APIs"
_re_zahl_vor_schnittstelle = re.compile(
    r"(\d+)\s*(?:externe\s+)?(?:Schnittstellen?|APIs?|Systeme|Anbindungen?|Services?)",
    re.IGNORECASE,
)
# Zahlwörter vor Interface-Wörtern
_re_zahlwort_pattern = re.compile(
    r"\b(" + "|".join(ZAHLWOERTER.keys()) + r")\b"
    r"[\s\w]{0,20}?"
    r"(?:Schnittstellen?|APIs?|Anbindungen?|externe Systeme)",
    re.IGNORECASE,
)
# Aufzählungen "Anbindung von A, B und C" → zählen
_re_aufzaehlung = re.compile(
    r"(?:Anbindung|Anbindungen|Integration|Schnittstelle)\s+(?:von|an|zu)?\s+"
    r"((?:[A-ZÄÖÜ]\w+[\s,]+){1,8}(?:und\s+)?[A-ZÄÖÜ]\w+)",
    re.IGNORECASE,
)


def _schaetze_schnittstellen(text: str) -> int:
    """
    Schätzt die Anzahl externer Schnittstellen aus dem Text.
    Gibt 0 zurück wenn kein Hinweis gefunden.
    """
    maximum = 0

    # 1. Explizite Ziffern
    for treffer in _re_zahl_vor_schnittstelle.finditer(text):
        maximum = max(maximum, int(treffer.group(1)))

    # 2. Zahlwörter
    for treffer in _re_zahlwort_pattern.finditer(text):
        wort = treffer.group(1).lower()
        maximum = max(maximum, ZAHLWOERTER.get(wort, 0))

    # 3. Aufzählungen ("Anbindung von SAP, Oracle und Dynamics")
    for treffer in _re_aufzaehlung.finditer(text):
        inhalt = treffer.group(1)
        # Komma-getrennte Elemente + "und"-Element zählen
        elemente = re.split(r"[,\s]+und\s+|,\s*", inhalt)
        n = len([e for e in elemente if e.strip()])
        maximum = max(maximum, n)

    return maximum


# ---------------------------------------------------------------------------
# Haupt-API: DataFrame anreichern
# ---------------------------------------------------------------------------

def anreichere_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Fügt vier BERT-basierte Feature-Spalten zum DataFrame hinzu:
      projekttyp_bert, technologien, komplexitaet, schnittstellen_anzahl

    Args:
        df: DataFrame mit Spalte "beschreibung" (aus preprocess.py)

    Returns:
        Erweiterter DataFrame (neue Spalten werden in-place angefügt).
    """
    if "beschreibung" not in df.columns:
        raise ValueError("DataFrame muss eine Spalte 'beschreibung' enthalten.")

    texte = df["beschreibung"].fillna("").tolist()
    n     = len(texte)
    logger.info("[BertExtractor] Verarbeite %d Texte ...", n)

    # --- Embeddings einmal berechnen (für projekttyp + komplexitaet) ---
    embeddings = _einbetten(texte)

    # --- Feature 1: Projekttyp ---
    logger.info("[BertExtractor] Klassifiziere Projekttypen ...")
    projekttypen = _klassifiziere_projekttyp(embeddings)

    # --- Feature 2: Technologien ---
    logger.info("[BertExtractor] Erkenne Technologien ...")
    technologien = [_erkenne_technologien(t) for t in texte]

    # --- Feature 4 zuerst (wird für Komplexität benötigt) ---
    logger.info("[BertExtractor] Schätze Schnittstellen-Anzahl ...")
    schnittstellen = [_schaetze_schnittstellen(t) for t in texte]

    # --- Feature 3: Komplexität ---
    logger.info("[BertExtractor] Berechne Komplexitäts-Scores ...")
    komplexitaet = _berechne_komplexitaet(texte, technologien, schnittstellen, embeddings)

    df = df.copy()
    df["projekttyp_bert"]       = projekttypen
    df["technologien"]          = technologien
    df["komplexitaet"]          = komplexitaet
    df["schnittstellen_anzahl"] = schnittstellen

    logger.info("[BertExtractor] Fertig. Neue Spalten: projekttyp_bert, technologien, komplexitaet, schnittstellen_anzahl")
    return df


# ---------------------------------------------------------------------------
# Hilfsfunktion für einzelne Texte (z. B. API-Aufruf)
# ---------------------------------------------------------------------------

def extrahiere_features(beschreibung: str) -> dict:
    """
    Extrahiert alle vier Features für einen einzelnen Text.
    Gibt ein Dict zurück (geeignet für API-Antworten).
    """
    df_einzel = pd.DataFrame([{"beschreibung": beschreibung}])
    df_result = anreichere_dataframe(df_einzel)
    zeile     = df_result.iloc[0]
    return {
        "projekttyp_bert":       zeile["projekttyp_bert"],
        "technologien":          zeile["technologien"],
        "komplexitaet":          int(zeile["komplexitaet"]),
        "schnittstellen_anzahl": int(zeile["schnittstellen_anzahl"]),
    }


# ---------------------------------------------------------------------------
# Test – 3 Beispielbeschreibungen
# ---------------------------------------------------------------------------

_TEST_BESCHREIBUNGEN = [
    {
        "label": "Bürgerportal (Web)",
        "text": (
            "Gegenstand der Ausschreibung ist die Entwicklung und der Betrieb eines "
            "Bürgerportals als Webanwendung für die Stadtverwaltung. Das Portal soll "
            "auf Basis von React und einer Python-Backend-API (FastAPI) realisiert werden. "
            "Als Datenbank wird PostgreSQL eingesetzt. Das System muss über eine REST-API "
            "an das bestehende Einwohnermeldewesen sowie an das SAP-Finanzmodul angebunden "
            "werden (2 Schnittstellen). OAuth 2.0-Authentifizierung ist vorgeschrieben. "
            "Laufzeit: 18 Monate, responsives Design für mobile Endgeräte erforderlich."
        ),
    },
    {
        "label": "SAP-Migration (komplex)",
        "text": (
            "Ablösung des bestehenden SAP ECC 6.0 auf SAP S/4HANA. Im Rahmen der Migration "
            "sind Daten aus drei Altsystemen (Oracle DB, Microsoft Dynamics, DATEV) zu "
            "überführen. Die Datenmigration umfasst ca. 15 Mio. Datensätze in Echtzeit. "
            "Es sind zahlreiche Schnittstellen zu Fremdsystemen (AWS, Kafka-Eventbus, "
            "LDAP/Active Directory) neu zu entwickeln. Hochverfügbarkeit (99,9 % SLA) "
            "und Multi-Mandantenfähigkeit sind Pflicht. Kubernetes-Cluster für den Betrieb. "
            "Projektlaufzeit: 36 Monate, Gesamtbudget ca. 8,5 Mio. EUR."
        ),
    },
    {
        "label": "Cloud-Infrastruktur (Infrastruktur)",
        "text": (
            "Neuaufbau der IT-Infrastruktur auf Basis von Amazon Web Services (AWS). "
            "Containerisierung aller Anwendungen mit Docker und Kubernetes (K8s). "
            "Automatisierung der Bereitstellung via Terraform und Ansible, "
            "CI/CD-Pipeline mit GitLab CI. Monitoring und Alerting über Elasticsearch "
            "und Grafana. Active Directory-Integration für das Rechtemanagement. "
            "Geplant sind vier separate Umgebungen (Dev, Test, Stage, Prod). "
            "Keine Datenmigration, kein Frontend erforderlich."
        ),
    },
]


def _drucke_testergebnis(label: str, features: dict) -> None:
    """Formatierte Ausgabe eines einzelnen Test-Ergebnisses."""
    trenner = "─" * 56
    techs   = ", ".join(features["technologien"]) if features["technologien"] else "–"
    kompl   = "█" * features["komplexitaet"] + "░" * (5 - features["komplexitaet"])
    print(f"\n  {trenner}")
    print(f"  Beispiel: {label}")
    print(f"  {trenner}")
    print(f"  Projekttyp (BERT):      {features['projekttyp_bert']}")
    print(f"  Komplexität (1–5):      [{kompl}] {features['komplexitaet']}/5")
    print(f"  Schnittstellen:         {features['schnittstellen_anzahl']}")
    print(f"  Technologien ({len(features['technologien'])}):")
    for i in range(0, len(features["technologien"]), 5):
        chunk = features["technologien"][i : i + 5]
        print(f"    {', '.join(chunk)}")
    if not features["technologien"]:
        print("    –")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    print("\n" + "=" * 58)
    print("  EstimateIQ – BERT Feature Extractor  Test")
    print("=" * 58)

    for beispiel in _TEST_BESCHREIBUNGEN:
        features = extrahiere_features(beispiel["text"])
        _drucke_testergebnis(beispiel["label"], features)

    print("\n" + "=" * 58)
    print("  Test abgeschlossen.")
    print("=" * 58 + "\n")
