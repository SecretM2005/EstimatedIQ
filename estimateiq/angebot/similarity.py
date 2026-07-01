"""
Cosine-Ähnlichkeitssuche über Leistungspositionen.
"""

from __future__ import annotations
import numpy as np
from sqlalchemy.orm import Session
from estimateiq.angebot.models import Leistungsposition, Projekt


def suche_aehnliche(
    query_vec: list[float],
    db: Session,
    k: int = 5,
    nur_historisch: bool = False,
    exclude_projekt_id: int | None = None,
) -> dict:
    """
    Gibt die k ähnlichsten Leistungspositionen zurück.
    Vektoren müssen bereits L2-normiert sein (normalize_embeddings=True).
    """
    q = db.query(Leistungsposition).filter(
        Leistungsposition.embedding_json.isnot(None)
    )
    if nur_historisch:
        q = q.filter(Leistungsposition.ist_historisch == True)  # noqa: E712
    if exclude_projekt_id is not None:
        q = q.filter(Leistungsposition.projekt_id != exclude_projekt_id)

    positionen = q.all()
    if not positionen:
        return {
            "treffer": [],
            "schaetzvorschlag": None,
            "konfidenz": "niedrig",
            "avg_aehnlichkeit": 0.0,
            "n_verglichen": 0,
        }

    query_arr = np.array(query_vec, dtype=np.float32)
    kandidaten = []
    for pos in positionen:
        vec = pos.get_embedding()
        if vec is None:
            continue
        arr = np.array(vec, dtype=np.float32)
        sim = float(np.dot(query_arr, arr))
        kandidaten.append((sim, pos))

    kandidaten.sort(key=lambda x: x[0], reverse=True)
    top = kandidaten[:k]

    if not top:
        return {
            "treffer": [],
            "schaetzvorschlag": None,
            "konfidenz": "niedrig",
            "avg_aehnlichkeit": 0.0,
            "n_verglichen": len(positionen),
        }

    avg_sim = sum(s for s, _ in top) / len(top)
    if avg_sim >= 0.75:
        konfidenz = "hoch"
    elif avg_sim >= 0.50:
        konfidenz = "mittel"
    else:
        konfidenz = "niedrig"

    treffer = []
    for sim, pos in top:
        treffer.append({
            "id":                pos.id,
            "beschreibung_text": pos.beschreibung_text,
            "soll_stunden":      pos.soll_stunden,
            "ist_stunden":       pos.ist_stunden,
            "rolle_name":        pos.rolle.name if pos.rolle else None,
            "aehnlichkeit":      round(sim, 4),
            "konfidenz":         konfidenz,
        })

    # Gewichteter Durchschnitt der Ist-Stunden (falls vorhanden) oder Soll-Stunden
    stunden_gewichtet = [
        (pos.ist_stunden if pos.ist_stunden is not None else pos.soll_stunden, sim)
        for sim, pos in top
    ]
    gesamt_gewicht = sum(s for _, s in stunden_gewichtet)
    if gesamt_gewicht > 0:
        vorschlag = sum(h * s for h, s in stunden_gewichtet) / gesamt_gewicht
    else:
        vorschlag = sum(h for h, _ in stunden_gewichtet) / len(stunden_gewichtet)

    return {
        "treffer":           treffer,
        "schaetzvorschlag":  round(vorschlag, 1),
        "konfidenz":         konfidenz,
        "avg_aehnlichkeit":  round(avg_sim, 4),
        "n_verglichen":      len(positionen),
    }


def suche_aehnliche_projekte(
    query_vec: list[float],
    db: Session,
    k: int = 3,
    exclude_projekt_id: int | None = None,
) -> list[dict]:
    """
    Findet die k ähnlichsten Referenzprojekte anhand ihres Projekt-Embeddings.
    Gibt für jedes Treffer-Projekt auch seine Positionen zurück.
    """
    q = db.query(Projekt).filter(
        Projekt.ist_referenz == True,  # noqa: E712
        Projekt.embedding_json.isnot(None),
    )
    if exclude_projekt_id is not None:
        q = q.filter(Projekt.id != exclude_projekt_id)

    projekte = q.all()
    if not projekte:
        return []

    query_arr = np.array(query_vec, dtype=np.float32)
    kandidaten = []
    for proj in projekte:
        vec = proj.get_embedding()
        if vec is None:
            continue
        arr = np.array(vec, dtype=np.float32)
        sim = float(np.dot(query_arr, arr))
        kandidaten.append((sim, proj))

    kandidaten.sort(key=lambda x: x[0], reverse=True)
    top = kandidaten[:k]

    ergebnisse = []
    for sim, proj in top:
        positionen = [
            {
                "id":                p.id,
                "beschreibung_text": p.beschreibung_text,
                "soll_stunden":      p.soll_stunden,
                "ist_stunden":       p.ist_stunden,
                "rolle_name":        p.rolle.name if p.rolle else None,
                "stundensatz_snapshot": p.stundensatz_snapshot,
            }
            for p in proj.positionen
            if not p.ist_historisch  # Sicherheitsfilter (sollte nie zutreffen)
        ]
        ergebnisse.append({
            "projekt_id":   proj.id,
            "projekt_name": proj.name,
            "aehnlichkeit": round(sim, 4),
            "n_positionen": len(positionen),
            "positionen":   positionen,
        })

    return ergebnisse
