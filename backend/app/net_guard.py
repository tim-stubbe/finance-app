"""SSRF-Schutz fuer vom Nutzer konfigurierte Zieladressen (Ollama-Server,
SearXNG-Instanz).

Kies laeuft im LAN/Tailscale-Netz - `localhost` und private IPs (RFC1918,
`127.0.0.1`, Docker-Servicenamen) sind hier der NORMALFALL: Ollama, Home
Assistant, Immich, SearXNG laufen typischerweise auf demselben Host oder im
selben Netz. Ein pauschaler Block privater Adressen wuerde also die uebliche
Installation kaputt machen.

Blockiert wird deshalb nur, was fuer diese Dienste NIE ein legitimes Ziel
ist:
  * fremde URL-Schemes (nur http/https)
  * der Link-Local-Bereich 169.254.0.0/16 - dort liegt u.a. der
    Cloud-Metadata-Endpunkt 169.254.169.254 (AWS/GCP/Azure IMDS)
  * IPv6-Link-Local (fe80::/10) und die unspezifizierten Adressen

Zusaetzlich sollten die aufrufenden Clients `allow_redirects=False` setzen,
damit ein an sich harmloses Ziel nicht per 3xx auf eine gesperrte Adresse
weiterleiten kann.
"""

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    """Die Ziel-URL ist aus Sicherheitsgruenden nicht erlaubt."""


_BLOCKED_NETS = [
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local inkl. 169.254.169.254 (Metadata)
    ipaddress.ip_network("fe80::/10"),       # IPv6 Link-local
    ipaddress.ip_network("::/128"),          # unspecified
    ipaddress.ip_network("0.0.0.0/32"),
]


def _ip_blocked(ip: ipaddress._BaseAddress) -> bool:
    return any(ip.version == net.version and ip in net for net in _BLOCKED_NETS)


def validate_external_url(raw: str) -> str:
    """Gibt die URL unveraendert zurueck, wenn sie erlaubt ist - sonst
    `UnsafeURLError`. DNS-Aufloesung, die fehlschlaegt (z.B. ein nur zur
    Laufzeit aufloesbarer Docker-Name), gilt NICHT als Fehler: dann kann der
    spaetere Request selbst scheitern, aber das Speichern der Einstellung
    wird nicht blockiert."""
    raw = (raw or "").strip()
    if not raw:
        raise UnsafeURLError("Leere URL.")
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError("Nur http- oder https-URLs sind erlaubt.")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL ohne Host.")

    # Ist der Host bereits eine IP? Dann direkt pruefen.
    try:
        ip = ipaddress.ip_address(host)
        if _ip_blocked(ip):
            raise UnsafeURLError(f"Zieladresse {ip} ist gesperrt (Link-Local/Metadata).")
        return raw
    except ValueError:
        pass  # kein IP-Literal -> aufloesen

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return raw  # nicht aufloesbar -> nicht hier blockieren
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _ip_blocked(ip):
            raise UnsafeURLError(
                f"Host {host} loest auf die gesperrte Adresse {ip} auf (Link-Local/Metadata)."
            )
    return raw
