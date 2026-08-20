# Roadmap (privat)

Diese Datei ist bewusst nicht öffentlich (siehe `.gitignore`) - eine Liste
offener Baustellen und interner Prioritäten gehört nicht in ein Repo, das
andere lesen können.

## Status

- **Web-App**: vollständiges Life OS - Finanzen (Konten, Buchungen,
  Investments, Ziele, Schulden, Steuerauswertung), Automatisierung (Alarm-
  Regeln, KI-Kategorisierung, Beleg-Auswertung, Was-wäre-wenn-Szenarien) und
  Bereiche außerhalb der Finanzen (Fotos, Datei-Sortierung, To-Dos/Kalender,
  Projekte, Lebensbereiche, Kontakte, Leseliste, Gesundheits-Grunddaten,
  Zeiterfassung). Fünf Themes, PWA, EUR/CHF.
- **macOS-Foundation**: `macos/Kies/` - KiesCore (GRDB-SQLite, Offline-Sync
  mit Outbox/Tombstones, Pairing per Secret, Keychain), eine schlanke SwiftUI-
  App (Konten/Buchungen/Todos) und KiesCLI als Test-Werkzeug für die Sync-
  Engine ohne aktive Display-Session.
- **Backend-Sync-Schicht**: `backend/app/sync.py` + `sync_registry.py` decken
  bereits die meisten Entitäten pull-fähig ab (viele davon auch push-fähig),
  Last-Write-Wins über `updated_at`, generisches Tombstone-Protokoll über
  einen SQLAlchemy-Session-Hook (`sync_tombstones.py`) - deckt automatisch
  auch künftige Modelle ab, ohne crud.py anzufassen.

## Offene Bausteine

### Hoch
- **Native iOS-App (Shared KiesCore)**: KiesCore multiplatform machen
  (iOS + macOS), eigenes SwiftUI-App-Target für iOS. Erste Version schlank:
  Heute/Konten/Buchungen/Todos, gleicher Pairing-Flow wie macOS.
- **KI-Review-Queue**: `ai_auto.py` wendet Kategorisierungen ab einer
  Konfidenz-Schwelle direkt an oder lässt sie liegen - es gibt keine Warteliste
  für unsichere Vorschläge, die der Nutzer explizit bestätigen/ablehnen kann.
  Wäre eine eigene Tabelle (Vorschlag + Konfidenz + Status) plus eine kleine
  Review-UI, vermutlich im Hub oder KI-Assistent-Tab.

### Mittel
- **Globale Volltextsuche**: Es gibt bereits Volltextsuche über Belege
  (`crud.search_receipts`) und über Notizen (`crud.search_notes`), aber keine
  gemeinsame Suche über Buchungen/Ziele/Projekte/Kontakte/Leseliste hinweg.
  Müsste entweder die bestehenden Teil-Suchen in einem gemeinsamen Endpunkt
  bündeln oder eine eigene, generische Volltext-Tabelle einführen.
- **Code-Modularisierung**: `main.py` (~5900 Zeilen), `app.js` (~8500 Zeilen)
  und `crud.py` (~3800 Zeilen) sind mittlerweile sehr groß für eine Datei.
  Aufteilung nach fachlichem Bereich (z.B. `routers/investments.py`,
  `routers/goals.py`, …) würde die Navigation im Code erleichtern - reine
  Struktur-Änderung, keine Verhaltensänderung, deshalb mit Bedacht und in
  kleinen Schritten.

### Niedrig
- **macOS-Client weiter ausbauen**: Feature-Parität mit der Web-App ist
  explizit NICHT das Ziel - aber Investments/Ziele/Kategorien-Bearbeitung
  wären naheliegende nächste Schritte, sobald die iOS-Version steht (Shared
  KiesCore profitiert dann von beiden Seiten).
- **Strukturierteres Habit-Tracking**: `LifeArea`/`LifeCheckIn` decken ein
  freies Tagebuch mit Fortschritt ab, aber kein festes Wochenraster/Streak-
  System für tägliche/wöchentliche Häkchen wie eine dedizierte Habit-App.
- **Reichere CalDAV/wiederkehrende Termine**: `CalendarEvent` kennt keine
  RRULE-Wiederholung (jeder Termin einer Serie ist ein eigener Eintrag, so wie
  Radicale ihn liefert) - eine native Wiederholungsregel würde u.a. die
  „Heute"-Ansicht und Konfliktprüfung robuster machen.

## Bewusst nicht geplant

- **Dokumenten-Tresor**: kein eigenes Passwort-/Dokumenten-Ablage-System -
  Vaultwarden übernimmt das bereits auf demselben TrueNAS, würde hier nur
  doppelt gebaut.
- **Multi-User**: Die App ist absichtlich Single-User ohne Auth-System (siehe
  `auth.py`/`sync.py`-Docstrings) - ein echtes Berechtigungssystem wäre eine
  komplett andere Architektur-Klasse, nicht "noch ein Feature".
- **Cloud-Zwang**: Alles läuft selbst gehostet auf eigener Hardware. Cloud-
  Anbindungen (falls je nötig) bleiben optional, nie Voraussetzung.
