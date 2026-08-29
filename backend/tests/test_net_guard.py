"""SSRF-Schutz fuer nutzerkonfigurierte Zieladressen (Ollama/SearXNG).
Kies laeuft im LAN - localhost/private IPs muessen ERLAUBT bleiben, nur
Link-Local/Cloud-Metadata und fremde Schemes werden geblockt."""
import pytest

from app import net_guard


@pytest.mark.parametrize("url", [
    "http://localhost:11434",
    "http://127.0.0.1:11434",
    "http://192.168.1.50:11434",
    "http://10.0.0.5:8080",
    "http://ollama:11434",          # Docker-Servicename, nicht aufloesbar -> erlaubt
    "https://searx.example.com/",
])
def test_allowed_targets(url):
    assert net_guard.validate_external_url(url) == url


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",  # AWS/GCP/Azure IMDS
    "http://169.254.170.2/",
    "file:///etc/passwd",
    "gopher://127.0.0.1:6379/_",
    "ftp://example.com/",
    "not-a-url",
    "",
])
def test_blocked_targets(url):
    with pytest.raises(net_guard.UnsafeURLError):
        net_guard.validate_external_url(url)
