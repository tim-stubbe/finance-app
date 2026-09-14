# Kies Call Gateway

Lokaler Anrufpfad: Kies -> HTTP-Gateway -> Asterisk -> SIP-Leitung.

Die SIP-Leitung kann ein in der FRITZ!Box angelegtes IP-Telefon oder später
ein VoLTE-SIM-Gateway sein. Kies selbst muss beim Wechsel nicht geändert
werden. Zugangsdaten gehören ausschließlich in die lokale `.env`.

Erforderliche Variablen am Gateway: `CALL_GATEWAY_TOKEN`, `AMI_SECRET`.
Kies erhält `KIES_LOCAL_CALL_URL`, `KIES_LOCAL_CALL_TOKEN` und `KIES_CALL_TO`.
