"""Verschluesselte Backups (backup_crypto.py + /api/backup, /api/restore,
/api/settings/backup-encryption)."""
import io
import zipfile

import pytest

from app import backup_crypto


def test_crypto_roundtrip():
    blob = backup_crypto.encrypt(b"hallo welt", "geheim-123")
    assert backup_crypto.is_encrypted(blob)
    assert not backup_crypto.is_encrypted(b"PK\x03\x04rest")
    assert backup_crypto.decrypt(blob, "geheim-123") == b"hallo welt"


def test_crypto_wrong_passphrase():
    blob = backup_crypto.encrypt(b"x", "richtig")
    with pytest.raises(ValueError):
        backup_crypto.decrypt(blob, "falsch")


def test_backup_plain_by_default(auth_client):
    r = auth_client.get("/api/backup")
    assert r.status_code == 200
    assert r.content[:2] == b"PK"  # ZIP


def test_backup_encrypted_when_passphrase_set(auth_client):
    assert auth_client.put("/api/settings/backup-encryption",
                           json={"passphrase": "super-geheim"}).status_code == 200
    assert auth_client.get("/api/settings/backup-encryption").json()["configured"] is True

    r = auth_client.get("/api/backup")
    assert r.status_code == 200
    assert backup_crypto.is_encrypted(r.content)
    inner = backup_crypto.decrypt(r.content, "super-geheim")
    assert "finance.db" in zipfile.ZipFile(io.BytesIO(inner)).namelist()


def test_restore_encrypted_needs_passphrase(auth_client):
    auth_client.put("/api/settings/backup-encryption", json={"passphrase": "pw-12345"})
    blob = auth_client.get("/api/backup").content

    r = auth_client.post("/api/restore",
                         files={"file": ("b.kies", blob, "application/octet-stream")})
    assert r.status_code == 400

    r = auth_client.post("/api/restore",
                         files={"file": ("b.kies", blob, "application/octet-stream")},
                         data={"passphrase": "nope"})
    assert r.status_code == 400

    r = auth_client.post("/api/restore",
                         files={"file": ("b.kies", blob, "application/octet-stream")},
                         data={"passphrase": "pw-12345"})
    assert r.status_code == 200, r.text


def test_short_passphrase_rejected(auth_client):
    r = auth_client.put("/api/settings/backup-encryption", json={"passphrase": "kurz"})
    assert r.status_code == 400
