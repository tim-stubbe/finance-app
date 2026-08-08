#!/usr/bin/env bash
#
# Holt die echten Live-Daten von der TrueNAS-Instanz auf den Mac.
#
# Richtung: TrueNAS  --->  Mac.  NIEMALS umgekehrt.
#
# TrueNAS ist ab sofort die einzige echte Datenbank ("Produktion"). Die lokale
# Kopie auf dem Mac ist nur eine Arbeitskopie zum Entwickeln und Testen. Alles,
# was hier lokal gebucht oder geaendert wird, geht beim naechsten Aufruf dieses
# Skripts verloren - das ist so gewollt und der Grund, warum es kein
# Gegenstueck "push-live.sh" gibt.
#
# Aufruf:
#   ./scripts/pull-live.sh              # holt von der Standard-Adresse
#   LIVE_URL=http://... ./scripts/pull-live.sh
#
set -euo pipefail

LIVE_URL="${LIVE_URL:-http://100.72.226.91:8000}"

# Projektwurzel bestimmen, damit das Skript aus jedem Verzeichnis heraus geht.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$ROOT/data"
DB_PATH="$DATA_DIR/finance.db"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "==> Hole Live-Backup von $LIVE_URL"
http_code="$(curl -sS -m 120 -o "$TMP_DIR/backup.zip" -w '%{http_code}' "$LIVE_URL/api/backup" || true)"

if [ "$http_code" != "200" ]; then
    echo "FEHLER: Server antwortete mit HTTP $http_code." >&2
    echo "        Laeuft die TrueNAS-Instanz? Ist Tailscale verbunden?" >&2
    exit 1
fi

# Pruefen, dass wirklich ein brauchbares Archiv ankam, bevor irgendetwas
# Lokales angefasst wird.
if ! unzip -l "$TMP_DIR/backup.zip" | grep -q 'finance\.db'; then
    echo "FEHLER: Das Archiv enthaelt keine finance.db - Abbruch." >&2
    exit 1
fi

unzip -q "$TMP_DIR/backup.zip" -d "$TMP_DIR/entpackt"
NEW_DB="$TMP_DIR/entpackt/finance.db"

# Die heruntergeladene Datei pruefen, solange die lokale noch unberuehrt ist.
integrity="$(sqlite3 "$NEW_DB" 'PRAGMA integrity_check;')"
if [ "$integrity" != "ok" ]; then
    echo "FEHLER: Integritaetspruefung fehlgeschlagen: $integrity" >&2
    exit 1
fi

mkdir -p "$DATA_DIR"

# Die bisherige lokale Datenbank zur Sicherheit wegsichern.
if [ -f "$DB_PATH" ]; then
    stamp="$(date +%Y%m%d-%H%M%S)"
    cp "$DB_PATH" "$DB_PATH.vor-pull-$stamp"
    echo "==> Lokale DB gesichert als finance.db.vor-pull-$stamp"
fi

cp "$NEW_DB" "$DB_PATH"

# Belege mitnehmen, falls im Archiv enthalten.
if [ -d "$TMP_DIR/entpackt/uploads" ]; then
    mkdir -p "$DATA_DIR/uploads"
    cp -R "$TMP_DIR/entpackt/uploads/." "$DATA_DIR/uploads/"
    echo "==> Belege uebernommen"
fi

echo "==> Uebernommen. Stand der Live-Daten:"
sqlite3 "$DB_PATH" <<'SQL'
.mode list
.separator ": "
SELECT 'Konten',       COUNT(*) FROM accounts;
SELECT 'Buchungen',    COUNT(*) FROM transactions;
SELECT 'Positionen',   COUNT(*) FROM holdings;
SELECT 'Kategorien',   COUNT(*) FROM categories;
SQL

echo
echo "Fertig. Die lokale Kopie ist eine Arbeitskopie - Aenderungen hier"
echo "wandern NICHT zurueck auf TrueNAS."
