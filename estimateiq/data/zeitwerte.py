"""
Zeitwerte-Datenbank pro Leistungsposition.

Format: "Position": (h_pro_einheit, einheit, material_faktor, gewerk)
  h_pro_einheit   – Arbeitsstunden je Mengeneinheit
  einheit         – "m²", "St" (Stück) oder "m³"
  material_faktor – Materialkosten = Lohnkosten × material_faktor
  gewerk          – Schlüssel in stundensaetze.STUNDENSAETZE
"""

from __future__ import annotations

ZEITWERTE: dict[str, tuple[float, str, float, str]] = {

    # ── MALERARBEITEN ─────────────────────────────────────────────────────────
    "maler_wand_innen":        (0.15, "m²", 0.30, "Maler"),
    "maler_decke":             (0.20, "m²", 0.30, "Maler"),
    "maler_fassade":           (0.25, "m²", 0.50, "Maler"),
    "tapezieren_wand":         (0.35, "m²", 0.80, "Maler"),
    "spachteln_glaetten":      (0.20, "m²", 0.40, "Maler"),

    # ── FLIESENARBEITEN ───────────────────────────────────────────────────────
    "fliesen_boden":           (0.80, "m²", 1.80, "Fliesen"),
    "fliesen_wand":            (1.00, "m²", 1.80, "Fliesen"),
    "fliesen_duschbereich":    (1.20, "m²", 2.00, "Fliesen"),
    "estrich_schwimmend":      (0.30, "m²", 1.20, "Fliesen"),

    # ── SANITÄR / SHK ─────────────────────────────────────────────────────────
    "wc_komplett":             (6.0,  "St", 2.50, "Sanitär"),
    "waschbecken_komplett":    (4.0,  "St", 2.00, "Sanitär"),
    "dusche_komplett":         (12.0, "St", 2.80, "Sanitär"),
    "badewanne_komplett":      (10.0, "St", 2.50, "Sanitär"),
    "heizkoerper_tauschen":    (3.0,  "St", 2.00, "Sanitär"),
    "fussbodenheizung":        (0.40, "m²", 1.50, "Sanitär"),
    "waermepumpe_luft":        (40.0, "St", 8.00, "Sanitär"),
    "gasheizung_komplett":     (24.0, "St", 6.00, "Sanitär"),

    # ── ELEKTRO ───────────────────────────────────────────────────────────────
    "steckdose_neu":           (1.5,  "St", 1.00, "Elektro"),
    "lichtschalter_neu":       (1.0,  "St", 0.80, "Elektro"),
    "unterverteilung_neu":     (8.0,  "St", 2.00, "Elektro"),
    "elektro_grundinstall_m2": (0.80, "m²", 1.20, "Elektro"),
    "aussenbeleuchtung":       (2.0,  "St", 1.50, "Elektro"),

    # ── TROCKENBAU ────────────────────────────────────────────────────────────
    "trockenbau_wand":         (0.50, "m²", 1.20, "Trockenbau"),
    "trockenbau_decke":        (0.60, "m²", 1.20, "Trockenbau"),
    "daemmung_dach_innen":     (0.45, "m²", 1.50, "Trockenbau"),
    "daemmung_fassade_wdvs":   (0.55, "m²", 2.00, "Trockenbau"),

    # ── HOCHBAU ───────────────────────────────────────────────────────────────
    "mauerwerk_aussen":        (1.20, "m²", 3.00, "Hochbau"),
    "beton_decke":             (1.80, "m²", 4.00, "Hochbau"),
    "fundament":               (2.50, "m³", 5.00, "Hochbau"),
    "dachstuhl_holz":          (0.80, "m²", 3.50, "Hochbau"),

    # ── BODENBELAG ────────────────────────────────────────────────────────────
    "parkett_verlegen":        (0.45, "m²", 2.50, "Boden"),
    "laminat_verlegen":        (0.25, "m²", 1.50, "Boden"),
    "teppich_verlegen":        (0.20, "m²", 1.20, "Boden"),
    "vinyl_kleben":            (0.30, "m²", 1.30, "Boden"),
}

# Einheiten-Klartext für Ausgaben
EINHEIT_LABEL: dict[str, str] = {
    "m²": "m²",
    "St": "Stk",
    "m³": "m³",
}
