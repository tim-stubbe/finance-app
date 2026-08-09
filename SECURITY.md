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
- Alle Zugangsdaten (Bank-, KI-, Benachrichtigungs-Anbindungen) liegen
  Fernet-verschlüsselt in der Datenbank, nie im Klartext oder als
  Umgebungsvariable.
- Datei-Endpunkte (Belege, Backups) sind gegen Pfad-Manipulation abgesichert.
- Externe Skript-Einbindungen tragen eine Subresource-Integrity-Prüfung.
- Die Anwendung ist bewusst nicht öffentlich aus dem Internet erreichbar
  (nur eigenes Netz / Tailscale) – siehe „Zugriffsschutz" in der
  [README](README.md). Das ist die wichtigste Absicherung überhaupt und
  entschärft die meisten sonst kritischen Funde deutlich.

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
  auch bleiben – es gibt bewusst keine Anmeldung/Mehrbenutzer-Trennung.
  Wer sie öffentlich oder mehrbenutzerfähig betreiben will, muss selbst für
  Zugriffsschutz sorgen (siehe README).
- Der Telegram-Bot hat bewusst nur Lesezugriff, gerade damit ein
  kompromittiertes Bot-Token keinen Schreibzugriff auf die Daten ermöglicht.
