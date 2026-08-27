# Kies

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
- ✅ Automatische Bankanbindungen (FinTS, Enable Banking, PayPal, Bitvavo, eBay, Scalable Capital)
- ✅ Native, offline-fähige Companion-Apps für macOS und iOS (eigener Zwei-Wege-Sync, Face ID/Touch-ID-Sperre)
- ✅ Web-Login mit Passwort, optionalem TOTP (2FA) und Passkeys (WebAuthn), automatische Abmeldung nach Inaktivität
- ✅ KI-Assistent (Kategorisierung, Beleg-Auswertung, Chat) über eigenen Ollama-Server
- ✅ Belege automatisch aus E-Mail-Postfach holen und Buchungen zuordnen, Volltextsuche über alle Belege
- ✅ Automatische Datei-Sortierung eines Eingangsordners (Kategorien, Kontoauszug-Import)
- ✅ Immich-Anbindung: doppelte Fotos, alte Bildschirmfotos, unscharfe/leere Fotos
  aufräumen (inkl. Tinder-artigem Swipe-Modus), Personen durchsuchen
- ✅ To-Dos und Kalender-Termine zweiseitig mit dem Handy synchronisiert
  (Radicale/CalDAV), inkl. wiederkehrender Termine (RRULE)
- ✅ Lebensbereiche/Habit-Tracking mit Streak und optionalem Wochenraster-Ziel
- ✅ Kündigungsfristen für Abos (inkl. Jahresersparnis bei Kündigung), Rückgabefristen für einzelne Käufe
- ✅ „Heute“-Fokus-Ansicht im Hub: Termine, fällige To-Dos, Fristen, Ziele in Reichweite, Tagesbilanz
- ✅ Frei definierbare Alarm-Regeln (Ausgaben-Schwelle, Kontostand, Kategorie-Ausreißer, Ziel-Fortschritt)
- ✅ Kontextbezogene Notizen an Zielen, To-Dos, Projekten, Lebensbereichen und dem Schweiz-Tab, durchsuchbar
- ✅ Was-wäre-wenn-Szenarien für Cashflow und Spardistanz (Abo kündigen, Sparrate erhöhen)
- ✅ Telegram-Benachrichtigungen + Chat-Bot, Twilio-Notrufe für Notfälle
- ✅ Vermögensvergleich mit der eigenen Altersgruppe
- ✅ PWA (installierbar auf Handy/Desktop), fünf Themes (inkl. Desktop-Variante mit Top-Navigation),
  EUR/CHF-Umschalter
- ✅ Automatisches Deployment (GitHub Actions → GHCR → Watchtower auf TrueNAS)

Kein festes Datum, keine Garantie, keine feste Roadmap – das hier ist ein
Freizeitprojekt für den Eigenbedarf, das nach Bedarf weiterwächst.

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
- Scalable Capital für Wertpapiere (Positionen, Käufe/Verkäufe inkl. Sparpläne)
- Kursdaten für Wertpapiere
- IMAP-Postfach für Belege aus E-Mail-Anhängen (rein lesend)
- Immich für die eigene Fotobibliothek
- Radicale/CalDAV für zweiseitigen Abgleich von To-Dos und Kalender-Terminen
  mit dem Handy, wiederkehrende Termine (RRULE) werden als Serie erkannt

**Investitionen**
- Positionen mit Einstandskursen und Lots, Gewinn/Verlust, Dividenden
- Ein zweiter Kauf/Sparplan-Vorgang desselben Symbols wird automatisch als
  weiterer Posten an die bestehende Position gehängt statt eine Dublette
  anzulegen – Klick auf eine Position zeigt alle einzelnen Käufe/Verkäufe
- Automatisch synchronisierte Positionen (Bitvavo, Scalable Capital) sind in
  der Bestandstabelle gekennzeichnet, inkl. Fremdwährungsanzeige
- Sortierbare Bestandstabelle, Anzeige des letzten Kursabrufs

**Planung und Auswertung**
- Hub-Startseite mit „Heute“-Fokus (Termine inkl. Fahrzeit, fällige To-Dos,
  Fristen, Ziele in Reichweite, Tagesbilanz), Finanzüberblick und nächste Ziele
- Dashboard mit Vermögensübersicht und Auswertung nach Kategorien
- Vermögensvergleich mit der eigenen Altersgruppe (Bundesbank-Vermögensbefragung)
- Budgets pro Kategorie
- Frei definierbare Alarm-Regeln (Ausgaben in einer Kategorie über Schwelle,
  Kontostand unter Schwelle, Kategorie weicht stark vom Schnitt ab, Ziel zu
  X % erreicht), per Telegram gemeldet
- Wiederkehrende Zahlungen automatisch erkannt, mit Kündigungsfrist direkt in
  der Übersicht und Anzeige der Jahresersparnis bei Kündigung; Cashflow-Prognose
  und Was-wäre-wenn-Szenarien (Abo kündigen, Sparrate ändern) darauf aufbauend
- Kündigungsfristen für Abos (Verlängerungstermin rückt bei erkannter Häufigkeit
  automatisch weiter) und Rückgabefristen für einzelne Käufe – beide erinnern
  rechtzeitig per Telegram
- Ziele (automatisch aus den App-Daten gemessen oder als manuelle Meilensteine,
  optional in Ketten voneinander abhängig), wahlweise als Kachelraster oder
  grafischer Zeitstrahl
- Lebensbereiche als Habit-Tracking: freies Tagebuch mit Fortschritt, Streak
  und 30-Tage-Verlauf, optional mit festem Wochenraster-Ziel (z. B. 3x/Woche)
- Kontextbezogene, durchsuchbare Notizen an Zielen, To-Dos, Projekten,
  Lebensbereichen und dem Schweiz-Tab
- Schweiz-Tab für den geplanten Umzug: eigener Zeitstrahl, Lebenshaltungskosten-
  Vergleich und Spardistanz-Rechner (inkl. Vergleich aktuelle vs. erhöhte Sparrate)
- Schulden mit Tilgungsplan, Zinsbindungsfristen, Bereitstellungszinsen,
  Gebühren und Restschuldversicherung
- Eigener Tab für Geschäftliches (Einzelunternehmen – rechtlich ohnehin alles
  Privatvermögen, deshalb nur eine Ansicht, kein getrennter Datenbestand)
- Reisekosten
- Steuerauswertung mit filterbarem CSV-/PDF-Export

**Fotos** (über eine bestehende [Immich](https://immich.app)-Instanz)
- Duplikate: Immichs eigene Erkennung wird angezeigt und lässt sich nach
  Bestätigung anwenden – jedes Bild einzeln auswählbar (auch alle oder keins),
  inklusive prozentualer Bildähnlichkeit und Nebeneinander-Vergleich
- Alte Bildschirmfotos nach Alter filtern und aufräumen
- Unscharfe/leere Fotos automatisch erkannt (Hintergrund-Scan der Bibliothek)
- Tinder-artiger Swipe-Modus als Alternative zur Raster-Auswahl: rechts wischen
  = behalten, links = Papierkorb
- Personen (Immichs eigene Gesichtserkennung) gezielt durchsuchen
- Wandert grundsätzlich nur in Immichs Papierkorb, nie direkt und endgültig weg

**Datei-Sortierung**
- Ein Eingangsordner (z. B. wo E-Mail-Anhänge/Scans landen) wird automatisch
  in Kategorie-Unterordner einsortiert – Ollama liest den Inhalt, bei
  Unsicherheit wird nichts geraten, sondern liegen gelassen
- Ein zweiter, vom Nutzer selbst befüllter Ordner funktioniert genauso als
  zweiter aktiver Eingang (z. B. vom Desktop reingezogene Dateien)
- Optionaler dritter Unterordner: Kontoauszüge werden dort automatisch als
  Buchungen importiert (Konto-Erkennung + Duplikat-Schutz), ohne manuelles
  Bestätigen

**KI-Funktionen** (über einen selbst betriebenen [Ollama](https://ollama.com)-Server)
- Chat-Schaltfläche auf jeder Seite für Anweisungen in normaler Sprache
- Stündliche automatische Kategorisierung noch nicht zugeordneter Buchungen –
  nur wenn das Modell hinreichend sicher ist
- Belege und Kontoauszüge als PDF oder Bild auslesen und in Buchungen umwandeln
- Optionale Websuche über die Brave Search API oder eine selbst gehostete SearXNG-Instanz

Änderungen an der Datenbank schlägt die KI immer nur vor. Übernommen wird erst
nach ausdrücklicher Bestätigung.

**Benachrichtigungen ("Jarvis"-Verhalten)**
- Telegram für Ziele, Cashflow und Budgets, außerdem ein 3-stündlicher
  Finanz-Digest und ein optionales **Morgen-Briefing** (Uhrzeit einstellbar,
  Default 7:30) mit heutigen Terminen + Fahrzeit, fälligen/überfälligen
  To-Dos, einer knappen Finanzzeile und nahen Fristen – bleibt bewusst still,
  wenn nichts Relevantes ansteht
- **Quiet Mode**: einstellbare Ruhezeiten (z. B. 22–7 Uhr) plus manuelles
  „Ruhe bis HH:MM" (App oder Telegram-Kommando `/ruhe`). In Ruhezeiten bleiben
  reine Info-Meldungen aus, wirklich Dringendes (Losfahren-Erinnerung,
  Dispo-/Cashflow-Risiko) kommt trotzdem durch
- **Vorschläge mit Bestätigen**: z. B. „To-Do seit 14 Tagen ohne Datum" –
  Kies fragt statt still zu handeln, per Telegram mit `/ok`, `/später` oder
  `/verwerfen` zu beantworten. Entscheidungen stehen unter Einstellungen →
  Benachrichtigungen → „Assistent – was Jarvis getan hat"
- `/haengt` in Telegram zeigt auf Zuruf eine Zusammenfassung liegengebliebener
  Dinge (To-Dos ohne Datum, überfällige To-Dos, offene Projekt-Punkte,
  überfällige Check-ins/Wunschlisten-Prüfungen)
- **Routinen**: frei definierbare wiederkehrende Checklisten (Name,
  Wochentage, Uhrzeit, Punkte) – kommen zur eingestellten Zeit per Telegram,
  abgehakt wird im Hub (Einstellungen → Benachrichtigungen → „Routinen")
- Der Telegram-Bot beantwortet auch Fragen mit derselben KI wie die
  Weboberfläche und kann To-Dos/Termine/Projekt-Punkte/Check-ins/Wunschlisten-
  Einträge anlegen bzw. abhaken (per festem Kommando oder KI-erkannter
  Absicht, mit Bestätigungsmeldung) – Kontostände und Buchungen bleiben davon
  ausdrücklich ausgenommen: `/saldo <Konto> <Betrag>` und
  `/ausgabe <Konto>; <Betrag>; <Text>` sind feste Kommandos ohne
  KI-Interpretation, bei Geld wird nichts geraten
- Telefonanrufe über Twilio, ausschließlich für wirklich zeitkritische Fälle
  (Ziel erreicht, akuter Liquiditätsengpass innerhalb von ein bis drei Tagen)

**Native Apps** (macOS/iOS, optional zur PWA)
- Eigener Sync-Client (KiesCore) statt reinem Web-Wrapper: SQLite-Offline-
  Kopie der wichtigsten Daten, Outbox+Tombstones für Änderungen ohne
  Verbindung, Pairing per Secret statt Login
- iOS-App mit Heute-Fokus, Konten/Buchungen, To-Dos/Kalender, Zielen,
  Lebensbereichen, Wunschliste und Kategorien; Face ID/Touch-ID-Sperre,
  Quick-Capture-Button für Buchung/To-Do/Check-in in einem Sheet
- macOS-App mit denselben Kernbereichen, gleiche Sync-Basis

**Sonstiges**
- Fünf Themes (Dunkel, Hell, Gelb, Alpen, Alpen Desktop mit Top-Navigation für
  breite Bildschirme), umschaltbar zwischen EUR- und CHF-Anzeige
- Als PWA auf dem Handy installierbar
- Automatische Backups mit einstellbarer Aufbewahrungsdauer
- Versionsanzeige in der Seitenleiste – zeigt an, ob ein Update tatsächlich
  angekommen ist, mit Warnung bei veraltetem Stand

## Technik

| Bereich   | Umsetzung                                                   |
|-----------|-------------------------------------------------------------|
| Backend   | FastAPI, SQLAlchemy, SQLite (290 Endpunkte, modular in `routers/`/`crud_*.py`) |
| Frontend  | HTML/CSS/JavaScript ohne Build-Schritt (modular in `frontend/js/`), Chart.js über CDN |
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

Zugangsdaten für Banken, PayPal, Bitvavo, Telegram, Twilio, Brave/SearXNG, das
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
- Gefundene Sicherheitslücken bitte **nicht** als öffentliches Issue melden,
  sondern über den privaten Meldeweg – siehe [SECURITY.md](SECURITY.md).

## Zugriffsschutz

Die Web-App braucht seit Kurzem eine **echte Anmeldung** – vorher gab es
bewusst keine, weil die App nur im eigenen Netz bzw. über Tailscale
erreichbar ist. Das bleibt die wichtigste Absicherung, kommt aber jetzt
zusätzlich zu einem Login, statt sich allein darauf zu verlassen. Die App
bleibt weiterhin **Single-User** – kein Mehrbenutzer-System, keine
Registrierung, nur ein Passwort für die eine Person, die sie nutzt.

- **Passwort** – beim ersten Start fragt ein Setup-Assistent ein Passwort ab
  (mind. 10 Zeichen), gehasht mit Argon2id (nie im Klartext gespeichert).
- **Zwei-Faktor (TOTP)** – optional, 30-Sekunden-Code aus einer
  Authenticator-App (Authy, Aegis, Google Authenticator, 1Password, …),
  einrichtbar unter Einstellungen → Allgemein → „Anmeldung & Sicherheit“.
  Ein einmaliger Wiederherstellungscode wird beim Aktivieren angezeigt, für
  den Fall, dass das Gerät mit der Authenticator-App verloren geht.
- **Passkeys (WebAuthn)** – optional, Anmeldung per Face ID/Touch ID/
  Sicherheitsschlüssel statt Passwort+TOTP. Braucht einen echten Domainnamen
  (z. B. den Tailscale-MagicDNS-Hostnamen) – über eine reine IP-Adresse
  funktionieren Passkeys aus Browser-Gründen grundsätzlich nicht.
- **Automatische Abmeldung** nach Inaktivität, Standard 5 Minuten, in den
  Einstellungen anpassbar.
- Login-Versuche sind rate-limitiert (progressive Sperre nach 5
  Fehlversuchen).

**Was weiterhin ohne diesen Login läuft** (siehe [SECURITY.md](SECURITY.md)
für Details): der native Sync für die macOS-/iOS-Apps (`/api/sync/*`, eigenes
Pairing-Secret) und der eingehende n8n-Webhook (`/api/webhook/*`, eigenes
Secret) – beide haben nie einen Browser-Login gebraucht und bekommen auch
jetzt keinen, sie bleiben bei ihrem jeweiligen geteilten Secret im Header.

Wer die App zusätzlich öffentlich aus dem Internet erreichbar machen will,
muss dafür trotzdem selbst sorgen (z. B. über einen vorgeschalteten Reverse
Proxy) – dafür ist sie nicht gedacht, das Tailscale-/eigene-Netz-Modell
bleibt die Grundannahme.

## Lizenz

[Apache License 2.0](LICENSE) © 2026 Tim Stubbe. Nutzung, Änderung und
Weitergabe sind damit ausdrücklich erlaubt – Namensnennung/Copyright-Hinweis
muss dabei erhalten bleiben.
