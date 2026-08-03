"""
Whitelist-Registry für den No-Code-KPI-Builder (Phase 3).

KEIN freies SQL vom Admin. Jede Kennzahl-Definition wird serverseitig gegen
diese Registry validiert: erlaubte Quellen, pro Quelle erlaubte Felder (mit
Typ), erlaubte Aggregationen, erlaubte Operatoren je Feldtyp. Filterwerte
laufen IMMER über SQLAlchemy-Parameterbindung (`Spalte == wert`), NIEMALS
über String-Interpolation in SQL – das ist der eigentliche Injection-Schutz,
nicht eine nachträgliche Prüfung.

Scope-Grenze (bewusst, siehe Phase-2/3-Zusammenfassung): einstufige
Aggregation über EINE Quelle. Mehrstufige Kennzahlen (z. B. "Ø Marge über
alle Projekte" = Verhältnis pro Projekt, dann gemittelt) sind als System-KPI
mit fest programmiertem Resolver abgebildet (siehe SYSTEM_KPI_RESOLVER unten),
nicht über den generischen Builder nachbaubar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Query

from estimateiq.angebot.models import Projekt, Leistungsposition, KpiDefinition


class UngueltigeDefinition(ValueError):
    """Definition verstößt gegen die Registry – wird abgelehnt, nicht korrigiert."""


@dataclass(frozen=True)
class FeldDef:
    typ: str          # 'numerisch' | 'text' | 'bool'
    ausdruck: object  # SQLAlchemy-Spalte oder -Ausdruck (auch virtuell, z.B. Multiplikation)


AGGREGATIONEN = {"count", "sum", "avg", "min", "max", "median"}
ZEITRAUM_TYPEN = {"letzte_30_tage", "quartal", "jahr", "benutzerdefiniert"}

OPERATOREN_JE_TYP: dict[str, set[str]] = {
    "numerisch": {"=", "!=", "<", "<=", ">", ">="},
    "text": {"=", "!=", "in"},
    "bool": {"=", "!="},
}

# Quelle → { Feldname: FeldDef }. Nur diese Felder sind für Aggregation/Filter
# erlaubt – alles andere wird von validiere_definition() abgelehnt.
REGISTRY: dict[str, dict[str, FeldDef]] = {
    "projekte": {
        "auftragswert": FeldDef("numerisch", Projekt.auftragswert),
        "status":       FeldDef("text", Projekt.status),
        "kunde":        FeldDef("text", Projekt.kunde),
    },
    "leistungspositionen": {
        "soll_stunden": FeldDef("numerisch", Leistungsposition.soll_stunden),
        "ist_stunden":  FeldDef("numerisch", Leistungsposition.ist_stunden),
        # Virtuelle Felder: SQL-Ausdruck statt einfacher Spalte, für den
        # Query-Executor identisch behandelbar.
        "soll_kosten":  FeldDef("numerisch", Leistungsposition.soll_stunden * Leistungsposition.stundensatz_snapshot),
        "ist_kosten":   FeldDef("numerisch", Leistungsposition.ist_stunden * Leistungsposition.stundensatz_snapshot),
        "phase":        FeldDef("text", Leistungsposition.phase),
    },
}

# Zusätzliche Filterfelder nur für leistungspositionen, die einen FESTEN
# (nicht generischen) Join auf Projekt brauchen. Kein beliebiger Join – nur
# dieser eine, fest verdrahtete Pfad.
JOIN_FILTER_FELDER: dict[str, dict[str, FeldDef]] = {
    "leistungspositionen": {
        "projekt_status": FeldDef("text", Projekt.status),
    },
}

QUELLEN_MODELLE = {"projekte": Projekt, "leistungspositionen": Leistungsposition}

# Felder, die standardmäßig als sensibel gelten (Vorschlag für die UI –
# die tatsächliche Durchsetzung läuft über kpi_definitions.required_permission,
# das der Ersteller frei setzen kann).
SENSIBLE_FELDER = {("leistungspositionen", "soll_kosten"), ("leistungspositionen", "ist_kosten")}


def _alle_filterfelder(quelle: str) -> dict[str, FeldDef]:
    return {**REGISTRY[quelle], **JOIN_FILTER_FELDER.get(quelle, {})}


def validiere_definition(
    quelle: str, feld: str, aggregation: str,
    filters: list[dict] | None = None, zeitraum: dict | None = None,
) -> None:
    """Wirft UngueltigeDefinition bei jedem Verstoß gegen die Whitelist."""
    if quelle not in REGISTRY:
        raise UngueltigeDefinition(f"Unbekannte Quelle: '{quelle}'.")
    if feld not in REGISTRY[quelle]:
        raise UngueltigeDefinition(f"Unbekanntes Feld '{feld}' für Quelle '{quelle}'.")
    if aggregation not in AGGREGATIONEN:
        raise UngueltigeDefinition(f"Unbekannte Aggregation: '{aggregation}'.")

    filterfelder = _alle_filterfelder(quelle)
    for f in (filters or []):
        f_feld = f.get("feld")
        f_operator = f.get("operator")
        if f_feld not in filterfelder:
            raise UngueltigeDefinition(f"Unbekanntes Filterfeld: '{f_feld}'.")
        feld_typ = filterfelder[f_feld].typ
        if f_operator not in OPERATOREN_JE_TYP[feld_typ]:
            raise UngueltigeDefinition(
                f"Operator '{f_operator}' ist für Feldtyp '{feld_typ}' nicht erlaubt."
            )

    if zeitraum and zeitraum.get("typ") not in ZEITRAUM_TYPEN:
        raise UngueltigeDefinition(f"Unbekannter Zeitraum-Typ: '{zeitraum.get('typ')}'.")


def _wende_filter_an(query: Query, ausdruck, operator: str, wert) -> Query:
    """Immer parametrisiert – `wert` wird nie in einen SQL-String interpoliert."""
    if operator == "=":
        return query.filter(ausdruck == wert)
    if operator == "!=":
        return query.filter(ausdruck != wert)
    if operator == "<":
        return query.filter(ausdruck < wert)
    if operator == "<=":
        return query.filter(ausdruck <= wert)
    if operator == ">":
        return query.filter(ausdruck > wert)
    if operator == ">=":
        return query.filter(ausdruck >= wert)
    if operator == "in":
        werte = wert if isinstance(wert, list) else [wert]
        return query.filter(ausdruck.in_(werte))
    raise UngueltigeDefinition(f"Nicht unterstützter Operator: '{operator}'.")


def _zeitraum_bereich(zeitraum: dict) -> tuple[datetime | None, datetime | None]:
    typ = zeitraum.get("typ")
    jetzt = datetime.now(timezone.utc)
    if typ == "letzte_30_tage":
        return jetzt - timedelta(days=30), None
    if typ == "quartal":
        start_monat = ((jetzt.month - 1) // 3) * 3 + 1
        return jetzt.replace(month=start_monat, day=1, hour=0, minute=0, second=0, microsecond=0), None
    if typ == "jahr":
        return jetzt.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0), None
    if typ == "benutzerdefiniert":
        von = datetime.fromisoformat(zeitraum["von"]) if zeitraum.get("von") else None
        bis = datetime.fromisoformat(zeitraum["bis"]) if zeitraum.get("bis") else None
        return von, bis
    return None, None


def berechne_kennzahl(
    db, tenant_id: str, quelle: str, feld: str, aggregation: str,
    filters: list[dict] | None = None, zeitraum: dict | None = None,
    sichtbarkeits_filter=None,
) -> float:
    """
    Führt eine validierte Definition aus. `sichtbarkeits_filter` ist eine
    optionale zusätzliche SQLAlchemy-Bedingung (z. B. Ownership-Scoping nach
    Phase-1-Regeln), die der Aufrufer übergibt – der Registry-Code selbst
    kennt keine Berechtigungslogik.
    """
    validiere_definition(quelle, feld, aggregation, filters, zeitraum)

    modell = QUELLEN_MODELLE[quelle]
    feld_def = REGISTRY[quelle][feld]
    filterfelder = _alle_filterfelder(quelle)

    query = db.query(modell).filter(modell.tenant_id == tenant_id)
    if sichtbarkeits_filter is not None:
        query = query.filter(sichtbarkeits_filter)

    braucht_projekt_join = quelle == "leistungspositionen" and any(
        f["feld"] in JOIN_FILTER_FELDER.get(quelle, {}) for f in (filters or [])
    )
    if braucht_projekt_join:
        query = query.join(Projekt, Projekt.id == Leistungsposition.projekt_id)

    for f in (filters or []):
        f_def = filterfelder[f["feld"]]
        query = _wende_filter_an(query, f_def.ausdruck, f["operator"], f["wert"])

    if zeitraum:
        von, bis = _zeitraum_bereich(zeitraum)
        if von:
            query = query.filter(modell.erstellt_am >= von)
        if bis:
            query = query.filter(modell.erstellt_am <= bis)

    if aggregation == "count":
        return float(query.count())

    if aggregation == "median":
        werte = sorted(v for (v,) in query.with_entities(feld_def.ausdruck).all() if v is not None)
        if not werte:
            return 0.0
        mitte = len(werte) // 2
        return float(werte[mitte] if len(werte) % 2 else (werte[mitte - 1] + werte[mitte]) / 2)

    agg_func = {"sum": func.sum, "avg": func.avg, "min": func.min, "max": func.max}[aggregation]
    ergebnis = query.with_entities(agg_func(feld_def.ausdruck)).scalar()
    return float(ergebnis) if ergebnis is not None else 0.0


def _sichtbare_projekte_query(db, tenant_id: str, sichtbarkeits_filter):
    q = (
        db.query(Projekt)
        .filter(Projekt.tenant_id == tenant_id, Projekt.ist_referenz == False)  # noqa: E712
        .filter(Projekt.name != "__historisch__")
    )
    if sichtbarkeits_filter is not None:
        q = q.filter(sichtbarkeits_filter)
    return q


def _resolver_offene_angebote_anzahl(db, tenant_id, sichtbarkeits_filter, hat_marge) -> dict:
    n = _sichtbare_projekte_query(db, tenant_id, sichtbarkeits_filter).filter(
        Projekt.status.in_(["entwurf", "angeboten"])
    ).count()
    return {"typ": "zahl", "wert": n}


def _resolver_offene_angebote_wert(db, tenant_id, sichtbarkeits_filter, hat_marge) -> dict | None:
    if not hat_marge:
        return None
    projekte = _sichtbare_projekte_query(db, tenant_id, sichtbarkeits_filter).filter(
        Projekt.status.in_(["entwurf", "angeboten"])
    ).all()
    wert = sum(
        pos.soll_stunden * (pos.stundensatz_snapshot or 0.0)
        for p in projekte for pos in p.positionen if not pos.ist_historisch
    )
    return {"typ": "zahl", "wert": round(wert, 2)}


def _resolver_trefferquote(db, tenant_id, sichtbarkeits_filter, hat_marge) -> dict:
    projekte = _sichtbare_projekte_query(db, tenant_id, sichtbarkeits_filter).all()
    gewonnen = sum(1 for p in projekte if p.status in ("beauftragt", "abgeschlossen"))
    verloren = sum(1 for p in projekte if p.status == "abgelehnt")
    gesamt = gewonnen + verloren
    quote = round(gewonnen / gesamt * 100, 1) if gesamt > 0 else None
    return {"typ": "zahl", "wert": quote, "n_gewonnen": gewonnen, "n_verloren": verloren}


def _resolver_laufende_projekte_tabelle(db, tenant_id, sichtbarkeits_filter, hat_marge) -> dict:
    projekte = _sichtbare_projekte_query(db, tenant_id, sichtbarkeits_filter).filter(
        Projekt.status == "beauftragt"
    ).order_by(Projekt.erstellt_am.desc()).limit(10).all()

    zeilen = []
    for p in projekte:
        aktiv = [pos for pos in p.positionen if not pos.ist_historisch]
        soll_h = sum(pos.soll_stunden for pos in aktiv)
        ist_h = sum(pos.ist_stunden or 0.0 for pos in aktiv)
        zeile = {"id": p.id, "name": p.name, "kunde": p.kunde, "soll_stunden": soll_h, "ist_stunden": ist_h}
        if hat_marge:
            soll_kosten = sum(pos.soll_stunden * (pos.stundensatz_snapshot or 0.0) for pos in aktiv)
            zeile["marge_pct"] = (
                round((p.auftragswert - soll_kosten) / p.auftragswert * 100, 1)
                if p.auftragswert else None
            )
        zeilen.append(zeile)
    return {"typ": "tabelle", "zeilen": zeilen}


# key → Resolver(db, tenant_id, sichtbarkeits_filter, hat_marge) -> dict | None
# None bedeutet: Wert ohne die nötige Permission nicht Teil der Response.
SYSTEM_KPI_RESOLVER = {
    "offene_angebote_anzahl": _resolver_offene_angebote_anzahl,
    "offene_angebote_wert": _resolver_offene_angebote_wert,
    "trefferquote": _resolver_trefferquote,
    "laufende_projekte_tabelle": _resolver_laufende_projekte_tabelle,
}

# Initiale System-KPIs, die ensure_system_kpis() pro Tenant anlegt.
# (key, label, darstellungstyp, format, required_permission)
SYSTEM_KPI_KATALOG: list[tuple[str, str, str, str | None, str | None]] = [
    ("offene_angebote_anzahl",   "Offene Angebote",          "zahl",    "anzahl", None),
    ("offene_angebote_wert",     "Offene Angebote (Wert)",   "zahl",    "eur",    "projekte.marge_einsehen"),
    ("trefferquote",             "Trefferquote",              "zahl",    "prozent", None),
    ("laufende_projekte_tabelle","Laufende Projekte",         "tabelle", None,     None),
]


def berechne_kpi_wert(
    db, tenant_id: str, kpi: KpiDefinition, sichtbarkeits_filter,
    viewer_permissions: frozenset[str],
) -> dict | None:
    """
    Einheitlicher Einstiegspunkt für System- UND Custom-KPIs. Gibt None
    zurück, wenn required_permission fehlt – der Wert ist dann serverseitig
    NICHT Teil der Response (Aufrufer lässt das Widget dann komplett weg).
    """
    if kpi.required_permission and kpi.required_permission not in viewer_permissions:
        return None

    hat_marge = "projekte.marge_einsehen" in viewer_permissions
    if kpi.is_system:
        resolver = SYSTEM_KPI_RESOLVER.get(kpi.key)
        return resolver(db, tenant_id, sichtbarkeits_filter, hat_marge) if resolver else None

    wert = berechne_kennzahl(
        db, tenant_id, kpi.quelle, kpi.feld, kpi.aggregation,
        filters=kpi.get_filters(), zeitraum=kpi.get_zeitraum(),
        sichtbarkeits_filter=sichtbarkeits_filter,
    )
    return {"typ": "zahl", "wert": wert}


def registry_katalog() -> dict:
    """Für die Wizard-UI: Quellen, Felder (mit Typ), Aggregationen, Operatoren, Zeitraum-Typen."""
    return {
        "quellen": {
            quelle: [
                {"feld": name, "typ": fd.typ, "sensibel": (quelle, name) in SENSIBLE_FELDER}
                for name, fd in felder.items()
            ]
            for quelle, felder in REGISTRY.items()
        },
        "filterfelder": {
            quelle: sorted(_alle_filterfelder(quelle).keys())
            for quelle in REGISTRY
        },
        "aggregationen": sorted(AGGREGATIONEN),
        "operatoren_je_typ": {typ: sorted(ops) for typ, ops in OPERATOREN_JE_TYP.items()},
        "zeitraum_typen": sorted(ZEITRAUM_TYPEN),
    }
