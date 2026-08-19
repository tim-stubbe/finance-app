#!/usr/bin/env python3
"""Seedet die Umzugs-Roadmap (Schweiz/HSLU) als Goals über die normale API -
bewusst nicht per direktem DB-Zugriff, damit dieselbe Validierung/Business-
Logik wie im Frontend gilt (siehe auch fix_categories*.py-Vorgehen vom
selben Abend). Idempotent: matcht bestehende Goals über den Titel, legt nur
neu an, was fehlt, aktualisiert sonst die übrigen Felder - beliebig oft
erneut ausführbar, ohne Duplikate.

Kategorie-Konvention: "Schweiz: <Thema>" statt nur "<Thema>" - der bestehende
Schweiz-Tab filtert Goals über category.toLowerCase() === "schweiz" (siehe
frontend/app.js isSchweizGoal). Ohne Präfix würden diese Ziele weder im
Schweiz-Tab noch eindeutig auffindbar sein, und generische Kategorienamen wie
"Finanzen" oder "Gewerbe" könnten mit später angelegten, unrelated Zielen
kollidieren. Das Frontend (Roadmap-Ansicht) muss diesen Präfix beim Anzeigen
abschneiden.

Anpassen und erneut laufen lassen: GOALS-Liste unten editieren (Titel bleibt
der Match-Schlüssel - Titel ändern legt ein neues Goal an statt das alte zu
aktualisieren), dann einfach nochmal ausführen.

Aufruf:
    pip install requests   # falls noch nicht vorhanden
    python3 scripts/seed_schweiz_goals.py
    LIVE_URL=https://... python3 scripts/seed_schweiz_goals.py   # andere Adresse
"""
import os
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = os.environ.get("LIVE_URL", "https://100.72.226.91:8000") + "/api"
session = requests.Session()
session.verify = False

# (title, category_theme, target_date_iso_or_None, description_or_None, predecessor_title_or_None)
GOALS = [
    ("Fachabitur abschliessen", "Schule/Studium", "2027-07-01", None, None),
    ("Bewerbungsfrist HSLU verifizieren und Bewerbung einreichen", "Schule/Studium", None,
     "Frist direkt bei HSLU-Zulassungsstelle erfragen, nicht mit Universität Luzern verwechseln", None),
    ("Immatrikulation HSLU abschliessen", "Schule/Studium", "2027-10-01", None, "Fachabitur abschliessen"),

    ("Abmeldung Einwohnermeldeamt Nierstein", "Behörden/Wohnsitz", "2027-07-01", None, None),
    ("Anmeldung Einwohnerkontrolle Luzern", "Behörden/Wohnsitz", "2027-07-01", "Frist 14 Tage nach Zuzug", None),
    ("B-Bewilligung EU/EFTA zu Studienzwecken beantragen", "Behörden/Wohnsitz", "2027-07-01", None, None),
    ("Schweizer Krankenversicherung (KVG) abschliessen", "Behörden/Wohnsitz", "2027-07-01",
     "Frist 3 Monate nach Zuzug, sonst Zwangszuteilung", None),
    ("Wohnung Luzern fixieren, Kautionskonto einrichten", "Behörden/Wohnsitz", "2027-07-01", None, None),

    ("Deutsches Gewerbe: Status nach Umzug klären (weiterführen vs. abmelden)", "Gewerbe", "2027-06-01", None, None),
    ("Nebenerwerb beim Amt für Migration Luzern melden", "Gewerbe", None, "Vor erstem Auftrag in der Schweiz", None),
    ("Schweizer Gewerbestruktur aufbauen (UID-Nummer, ggf. Handelsregister)", "Gewerbe", None, None, None),

    ("CH-Login erstellen (Bundes-Portal)", "Drohne", None, "Nach Zuzug", None),
    ("Betreiber-Registrierung auf UAS.gate (BAZL) für beide Drohnen", "Drohne", None,
     "Nach Zuzug. Betreibernummer CHE... sichtbar an Drohnen anbringen", None),
    ("Kompetenznachweis A1/A3 verifizieren/übertragen lassen", "Drohne", None, "Nach Zuzug", None),
    ("Drohnen-Haftpflichtversicherung mit Mindestdeckung 1 Mio. CHF abschliessen", "Drohne", None,
     "Nach Zuzug. Prüfen ob Privathaftpflicht Drohnen abdeckt", None),

    ("Schweizer Bankkonto eröffnen", "Finanzen", "2027-07-01", "Vor oder direkt nach Umzug", None),
    ("Schweizer SIM-Karte/Mobilfunk", "Finanzen", None, "Nach Zuzug", None),

    ("10-Jahres-Wohnsitzfrist erreicht", "Einbürgerung", "2037-10-01", None, "Anmeldung Einwohnerkontrolle Luzern"),
    ("Einbürgerungsgesuch stellen", "Einbürgerung", None, "Nach Erreichen der 10-Jahres-Frist", "10-Jahres-Wohnsitzfrist erreicht"),
]


def main():
    existing = {g["title"]: g for g in session.get(f"{BASE}/goals").json()}

    created, updated = 0, 0
    title_to_id = {}
    # Pass 1: alle Goals ohne predecessor_goal_id anlegen/aktualisieren, damit
    # in Pass 2 jeder referenzierte Titel schon eine ID hat.
    for title, theme, target_date, description, _pred in GOALS:
        payload = {
            "title": title,
            "description": description,
            "category": f"Schweiz: {theme}",
            "goal_type": "manual",
            "target_date": target_date,
            "all_spaces": True,  # space_id bleibt NULL - nur ein Space vorhanden, aber zukunftssicher
        }
        if title in existing:
            gid = existing[title]["id"]
            r = session.put(f"{BASE}/goals/{gid}", json=payload)
            r.raise_for_status()
            updated += 1
        else:
            r = session.post(f"{BASE}/goals", json=payload)
            r.raise_for_status()
            gid = r.json()["id"]
            created += 1
        title_to_id[title] = gid

    # Pass 2: Vorgänger verketten.
    linked = 0
    for title, _theme, _target_date, _description, pred_title in GOALS:
        if not pred_title:
            continue
        gid = title_to_id[title]
        pred_id = title_to_id[pred_title]
        r = session.put(f"{BASE}/goals/{gid}", json={"predecessor_goal_id": pred_id})
        r.raise_for_status()
        linked += 1

    print(f"Fertig: {created} neu angelegt, {updated} aktualisiert, {linked} Vorgänger-Verkettungen gesetzt.")
    print(f"Gesamt Schweiz-Umzugs-Ziele: {len(GOALS)}")


if __name__ == "__main__":
    main()
