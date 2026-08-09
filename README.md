# Finanztool

Selbst gehostetes Finanztool für Privat- und Geschäftsfinanzen in einem. Läuft
komplett auf eigener Hardware, ohne Cloud-Dienst und ohne Konto bei einem
Anbieter. Einzelnutzer-Anwendung, erreichbar im eigenen Netz bzw. über Tailscale.

Oberfläche und Code sind auf Deutsch gehalten.

## Roadmap

Die Grundidee: **ein** Tool statt vieler einzelner Dienste – nicht nur
Finanzen, sondern nach und nach alles, was sich sinnvoll an einer Stelle
bündeln lässt. Neue Anbindungen werden dabei immer *eingebunden*, nicht
nachgebaut: wenn ein Dienst etwas schon gut kann (z. B. Immichs eigene
KI-Duplikatserkennung), wird das genutzt statt neu erfunden.

**Fertig:**
- ✅ Konten, Buchungen, Investments, Ziele, Schulden, Steuerauswertung
- ✅ Automatische Bankanbindungen (FinTS, Enable Banking, PayPal, Bitvavo)
- ✅ KI-Assistent (Kategorisierung, Beleg-Auswertung, Chat) über eigenen Ollama-Server
- ✅ Belege automatisch aus E-Mail-Postfach holen und Buchungen zuordnen
- ✅ Immich-Anbindung: doppelte Fotos und alte Bildschirmfotos aufräumen
- ✅ Telegram-Benachrichtigungen + Chat-Bot, Twilio-Notrufe für Notfälle
- ✅ Vermögensvergleich mit der eigenen Altersgruppe
- ✅ PWA (installierbar auf Handy/Desktop), vier Themes, EUR/CHF-Umschalter
- ✅ Automatisches Deployment (GitHub Actions → GHCR → Watchtower auf TrueNAS)

**Als Nächstes geplant** (siehe Projektnotizen für Details zum jeweiligen
Interaktionsmodell):
- 🔜 eBay-Verkäufe als vollwertige Anbindung – Umsätze fließen wie ein Konto
  ins Dashboard und Nettovermögen ein, nicht nur als separates Widget
- 🔜 Weitere Immich-Funktionen (aktuell nur Duplikate + Screenshots)

Kein festes Datum, keine Garantie – das hier ist ein Freizeitprojekt für den
Eigenbedarf, kein Produkt mit Fahrplan.

## Was es kann

**Konten und Buchungen**
- Mehrere Konten, Kategorien, wiederkehrende Buchungen
- CSV-Import für Buchungen und Wertpapierbestände
- Belege als Datei an Buchungen anhängen – manuell, per KI-Chat oder
  automatisch aus E-Mail-Anhängen geholt und zugeordnet
- Automatische Erkennung von Umbuchungen zwischen eigenen Konten – die zählen
  weder als Einnahme noch als Ausgabe

**Automatische Anbindungen**
- FinTS/HBCI für deutsche Banken (u. a. ING)
- Enable Banking (PSD2) für Konten ohne FinTS
- PayPal
- Bitvavo für Kryptobestände
- Kursdaten für Wertpapiere
- IMAP-Postfach für Belege aus E-Mail-Anhängen (rein lesend)
- Immich für die eigene Fotobibliothek

**Investitionen**
- Positionen mit Einstandskursen und Lots, Gewinn/Verlust, Dividenden
- Sortierbare Bestandstabelle, Anzeige des letzten Kursabrufs

**Planung und Auswertung**
- Dashboard mit Vermögensübersicht und Auswertung nach Kategorien
- Vermögensvergleich mit der eigenen Altersgruppe (Bundesbank-Vermögensbefragung)
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

**Fotos** (über eine bestehende [Immich](https://immich.app)-Instanz)
- Duplikate: Immichs eigene Erkennung wird angezeigt und lässt sich nach
  Bestätigung anwenden – jedes Bild einzeln auswählbar (auch alle oder keins),
  inklusive prozentualer Bildähnlichkeit und Nebeneinander-Vergleich
- Alte Bildschirmfotos nach Alter filtern und aufräumen
- Wandert grundsätzlich nur in Immichs Papierkorb, nie direkt und endgültig weg

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
- Versionsanzeige in der Seitenleiste – zeigt an, ob ein Update tatsächlich
  angekommen ist, mit Warnung bei veraltetem Stand

## Technik

| Bereich   | Umsetzung                                                   |
|-----------|-------------------------------------------------------------|
| Backend   | FastAPI, SQLAlchemy, SQLite (160 Endpunkte)                  |
| Frontend  | HTML/CSS/JavaScript ohne Build-Schritt, Chart.js über CDN   |
| Jobs      | APScheduler für Sync, Kursabruf, Kategorisierung, Backups   |
| Betrieb   | Docker, Python 3.14                                          |

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

Zugangsdaten für Banken, PayPal, Bitvavo, Telegram, Twilio, Brave, das
E-Mail-Postfach und Immich werden nicht über Umgebungsvariablen gesetzt,
sondern in der Oberfläche unter **Einstellungen** hinterlegt. Sie liegen mit
Fernet verschlüsselt in der Datenbank.

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
`ghcr.io/tim-stubbe/finance-app:latest`. Ein wöchentlicher (und nach jedem Build
laufender) Workflow räumt alte Image-Versionen aus der Registry auf und behält
die zehn neuesten. Auf dem Produktivsystem zieht Watchtower neue Versionen
automatisch, sobald sie verfügbar sind (Abfrage alle 5 Minuten).

Welcher Stand gerade läuft, zeigt die Versionsanzeige unten in der Seitenleiste
(Commit-Kurzform + Alter des Builds), mit Warnung, falls ein neuerer Stand
veröffentlicht, aber noch nicht angekommen ist.

## Sicherheit

- Automatisierte Prüfung über GitHub Code Scanning (CodeQL) und Dependabot
  (Sicherheitslücken + wöchentliche Versions-Updates für Python-Pakete,
  Docker-Basis-Image und GitHub Actions).
- Externe Skript-Einbindungen (Chart.js) tragen eine Subresource-Integrity-Prüfung.
- Datei-Endpunkte (Belege, Backups) sind gegen Pfad-Manipulation abgesichert.
- Gefundene Sicherheitslücken bitte **nicht** als öffentliches Issue melden
  (Repository ist zwar privat, aber falls das je geändert wird) – siehe
  [SECURITY.md](SECURITY.md).

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
