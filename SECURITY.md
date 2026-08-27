# Sicherheit

Dies ist ein privates Freizeitprojekt für den Eigenbedarf, keine
kommerzielle Software. Es gibt kein Sicherheitsteam und keine zugesagten
Reaktionszeiten – aber gefundene Probleme werden ernst genommen und so
schnell wie möglich behoben.

## Was hier bereits gemacht wird

- **GitHub Code Scanning (CodeQL)** läuft automatisch gegen jeden Push.
- **Dependabot** meldet bekannte Sicherheitslücken in Abhängigkeiten und
  öffnet wöchentlich Pull Requests für Versions-Updates (Python-Pakete,
  Docker-Basis-Image, GitHub Actions).
- **Web-Login** (Passwort + optional TOTP/Passkeys, siehe „Zugriffsschutz"
  in der [README](README.md)) schützt jetzt jeden `/api/*`-Endpunkt mit
  Finanzdaten - ausgenommen `/api/sync/*` (nativer Client) und
  `/api/webhook/*` (n8n), die statt eines Browser-Logins weiterhin ein
  eigenes, geteiltes Secret im Header verlangen. Passwörter werden nur als
  Argon2id-Hash gespeichert (passlib), nie im Klartext oder reversibel.
  TOTP-Secrets liegen wie alle anderen Zugangsdaten Fernet-verschlüsselt in
  der Datenbank. Login/TOTP sind rate-limitiert (progressive Sperre nach 5
  Fehlversuchen), zustandsändernde Anfragen zusätzlich per
  Double-Submit-CSRF-Token abgesichert.
- Alle Zugangsdaten (Bank-, KI-, Benachrichtigungs-Anbindungen) liegen
  Fernet-verschlüsselt in der Datenbank, nie im Klartext oder als
  Umgebungsvariable.
- Datei-Endpunkte (Belege, Backups) sind gegen Pfad-Manipulation abgesichert.
- Externe Skript-Einbindungen tragen eine Subresource-Integrity-Prüfung.
- Die Anwendung ist zusätzlich bewusst nicht öffentlich aus dem Internet
  erreichbar (nur eigenes Netz / Tailscale) – siehe „Zugriffsschutz" in der
  [README](README.md). Das bleibt die wichtigste Absicherung überhaupt und
  entschärft die meisten sonst kritischen Funde deutlich, auch mit Login.

## Eine Schwachstelle melden

Wer hier ein Sicherheitsproblem findet:

- Am liebsten über **GitHub Security Advisories** dieses Repos
  (Reiter „Security" → „Report a vulnerability") – das erzeugt einen
  privaten Meldekanal, sichtbar nur für den Repo-Inhaber, nicht öffentlich
  einsehbar.
- Alternativ: eine E-Mail an die im GitHub-Profil hinterlegte Adresse.

Meldungen werden in der Regel innerhalb von **24 Stunden** gesichtet. Das ist
eine realistische Zusage von einer Einzelperson, kein Firmen-SLA – wie lange
ein tatsächlicher Fix dann dauert, hängt vom Umfang des Problems ab.

Bitte **keine öffentlichen Issues** für Sicherheitsfragen, damit eine Lücke
nicht publik wird, bevor ein Fix da ist.

## Was explizit außerhalb des Rahmens liegt

- Diese Anwendung ist für **einen einzigen Nutzer** gedacht und wird das
  auch bleiben – es gibt seit Kurzem einen Web-Login (siehe oben), aber
  bewusst kein Mehrbenutzer-System, keine Rollen, keine Registrierung für
  Dritte. Wer sie öffentlich erreichbar machen will, muss trotzdem selbst
  für zusätzlichen Zugriffsschutz sorgen (siehe README).
- Der Telegram-Bot hat bewusst nur Lesezugriff, gerade damit ein
  kompromittiertes Bot-Token keinen Schreibzugriff auf die Daten ermöglicht.
