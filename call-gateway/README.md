# Kies Call Gateway

Lokaler Anrufpfad: Kies -> HTTP-Gateway -> Asterisk -> SIP-Leitung.

Die SIP-Leitung kann ein in der FRITZ!Box angelegtes IP-Telefon oder später
ein VoLTE-SIM-Gateway sein. Kies selbst muss beim Wechsel nicht geändert
werden. Zugangsdaten gehören ausschließlich in die lokale `.env`.

Erforderliche Variablen am Gateway: `CALL_GATEWAY_TOKEN`, `AMI_SECRET`.
Kies erhält `KIES_LOCAL_CALL_URL`, `KIES_LOCAL_CALL_TOKEN` und `KIES_CALL_TO`.

## Interaktive Anrufe

Für Anrufe mit gesprochener Antwort wird derzeit Twilio verwendet. Der Kies-
Container braucht dafür zusätzlich:

- `KIES_CALL_CALLBACK_URL`: öffentlich erreichbare Basis-URL der Kies-App
- `KIES_CALL_CALLBACK_TOKEN`: langes zufälliges Secret für den Rückruf

Ohne beide Werte wird kein interaktiver Anruf ausgelöst. Einweg-Anrufe bleiben
standardmäßig gesperrt, damit Kies keine Mailboxen mit Ansagen füllt.
