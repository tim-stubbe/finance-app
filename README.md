# Finanztool

Selbst gehostetes Finanztool für Privat- und Geschäftsfinanzen in einem. Läuft
komplett auf eigener Hardware, ohne Cloud-Dienst und ohne Konto bei einem
Anbieter. Einzelnutzer-Anwendung, erreichbar im eigenen Netz bzw. über Tailscale.

Oberfläche und Code sind auf Deutsch gehalten.

## Was es kann

**Konten und Buchungen**
- Mehrere Konten, Kategorien, wiederkehrende Buchungen
- CSV-Import für Buchungen und Wertpapierbestände
- Belege als Datei an Buchungen anhängen
- Automatische Erkennung von Umbuchungen zwischen eigenen Konten – die zählen
  weder als Einnahme noch als Ausgabe

**Automatische Anbindungen**
- FinTS/HBCI für deutsche Banken (u. a. ING)
- Enable Banking (PSD2) für Konten ohne FinTS
- PayPal
- Bitvavo für Kryptobestände
- Kursdaten für Wertpapiere

**Investitionen**
- Positionen mit Einstandskursen und Lots, Gewinn/Verlust, Dividenden
- Sortierbare Bestandstabelle, Anzeige des letzten Kursabrufs

**Planung und Auswertung**
- Dashboard mit Vermögensübersicht und Auswertung nach Kategorien
- Budgets pro Kategorie
- Cashflow-Prognose
- Ziele (automatisch aus den App-Daten gemessen oder als manuelle Meilensteine,
  optional in Ketten voneinander abhängig)
- Schulden mit Tilgungsplan, Zinsbindungsfristen, Bereitstellungszinsen,
  Gebühren und Restschuldversicherung
- Eigener Tab für Geschäftliches (Einzelunternehmen – rechtlich ohnehin alles
  Privatvermögen, deshalb nur eine Ansicht, kein getrennter Datenbestand)
- Reisekosten
- Steuerauswertung

**KI-Funktionen** (über einen selbst betriebenen [Ollama](https://ollama.com)-Server)
- Chat-Schaltfläche auf jeder Seite für Anweisungen in normaler Sprache
- Stündliche automatische Kategorisierung noch nicht zugeordneter Buchungen –
  nur wenn das Modell hinreichend sicher ist
- Belege und Kontoauszüge als PDF oder Bild auslesen und in Buchungen umwandeln
- Optionale Websuche über die Brave Search API

Änderungen an der Datenbank schlägt die KI immer nur vor. Übernommen wird erst
nach ausdrücklicher Bestätigung.

**Benachrichtigungen**
- Telegram für Ziele, Cashflow und Budgets
- Der Telegram-Bot beantwortet auch Fragen mit derselben KI wie die Weboberfläche.
  Er hat bewusst **nur Lesezugriff** und kann nichts an den Daten ändern – falls
  das Bot-Token je abhandenkommt, bleibt der Schaden begrenzt
- Telefonanrufe über Twilio, ausschließlich für wirklich zeitkritische Fälle
  (Ziel erreicht, akuter Liquiditätsengpass innerhalb von ein bis drei Tagen)

**Sonstiges**
- Vier Themes, umschaltbar zwischen EUR- und CHF-Anzeige
- Als PWA auf dem Handy installierbar
- Automatische Backups mit einstellbarer Aufbewahrungsdauer

## Technik

| Bereich   | Umsetzung                                                   |
|-----------|-------------------------------------------------------------|
| Backend   | FastAPI, SQLAlchemy, SQLite (135 Endpunkte)                 |
| Frontend  | HTML/CSS/JavaScript ohne Build-Schritt, Chart.js über CDN   |
| Jobs      | APScheduler für Sync, Kursabruf, Kategorisierung, Backups   |
| Betrieb   | Docker, Python 3.12                                          |

Der gesamte Zustand liegt in **einer** Datei: `data/finance.db`.

## Start

```bash
git clone https://github.com/tim-stubbe/finance-app.git
cd finance-app
docker compose up -d
```

Erreichbar unter http://localhost:8000. Beim ersten Start legt die Anwendung
Datenbank und Standardeinstellungen selbst an.

Für die Entwicklung greift zusätzlich `docker-compose.override.yml`: Code wird
ins Bild gemountet und uvicorn startet mit `--reload`.

### Einstellungen

Zugangsdaten für Banken, PayPal, Bitvavo, Telegram, Twilio und Brave werden
nicht über Umgebungsvariablen gesetzt, sondern in der Oberfläche unter
**Einstellungen** hinterlegt. Sie liegen mit Fernet verschlüsselt in der
Datenbank.

Nur zwei Umgebungsvariablen gibt es:

| Variable       | Standard    | Bedeutung                       |
|----------------|-------------|---------------------------------|
| `DATA_DIR`     | `/data`     | Datenbank, Backups, Belege      |
| `FRONTEND_DIR` | `/frontend` | Auslieferung der Oberfläche     |

## Datenhaltung und Sicherung

> **Wichtig:** Alle gespeicherten Zugangsdaten sind mit einem Schlüssel
> verschlüsselt, der **in derselben Datei** `finance.db` liegt. Beim Umzug auf
> ein anderes System muss deshalb immer die **komplette Datei** übertragen
> werden. Werden nur einzelne Tabellen in eine Datenbank mit anderem Schlüssel
> übernommen, sind sämtliche hinterlegten Zugangsdaten dauerhaft unlesbar.

`GET /api/backup` liefert jederzeit ein ZIP mit Datenbank und Belegen. Darauf
setzt auch `scripts/pull-live.sh` auf, das die Live-Daten vom Produktivsystem
auf einen Entwicklungsrechner holt:

```bash
./scripts/pull-live.sh
```

Das Skript läuft bewusst nur in **eine** Richtung. Ein Gegenstück, das lokale
Daten nach oben schreibt, gibt es absichtlich nicht: Bei einer einzelnen
SQLite-Datei bedeutet ein Konflikt schlicht, dass eine Seite überschrieben wird.

## Aktualisierung

Jeder Push auf `main` baut über GitHub Actions ein Docker-Image und lädt es nach
`ghcr.io/tim-stubbe/finance-app:latest`.

## Zugriffsschutz

Die Anwendung hat **keine Anmeldung**. Das ist eine bewusste Entscheidung: Sie
wird von einer einzigen Person genutzt und ist nur im eigenen Netz bzw. über
Tailscale erreichbar, nie offen aus dem Internet.

Wer sie anders betreibt, muss den Zugriff selbst absichern – etwa über einen
vorgeschalteten Reverse Proxy mit Authentifizierung. Ohne das kann jeder, der
die Adresse erreicht, sämtliche Finanzdaten einsehen und die hinterlegten
Bankverbindungen nutzen.

## Lizenz

Privates Projekt, keine Lizenz vergeben. Alle Rechte vorbehalten.
