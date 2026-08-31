"""Optionale Verschluesselung fuer Backup-ZIPs.

Ist `Settings.backup_passphrase_encrypted` gesetzt, schreiben sowohl die
geplanten Auto-Backups (`write_backup_to_disk`) als auch der manuelle Download
(`GET /api/backup`) einen verschluesselten Container statt eines nackten ZIPs -
damit ein Backup, das die Maschine verlaesst (Cloud-Sync, USB-Stick, weg-
kopiert), ohne die Passphrase wertlos ist. `POST /api/restore` erkennt den
Container am Magic und verlangt dann die Passphrase.

Container-Format (alles am Stueck, big-endian):
    MAGIC (8 B) | salt (16 B) | Fernet-Token( zip_bytes )
Key = PBKDF2-HMAC-SHA256(passphrase, salt, 600_000 Runden, 32 B)
      -> urlsafe-b64 -> Fernet (AES-128-CBC + HMAC-SHA256, wie ueberall sonst
      im Projekt, siehe bank_sync._fernet).
"""
import base64
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

MAGIC = b"KIESBK\x00\x01"          # 8 Bytes, Version steckt im letzten Byte
_SALT_LEN = 16
_PBKDF2_ROUNDS = 600_000
_HEADER_LEN = len(MAGIC) + _SALT_LEN

ENCRYPTED_EXT = ".kies"
PLAIN_EXT = ".zip"


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=_PBKDF2_ROUNDS)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def is_encrypted(blob: bytes) -> bool:
    return blob[:len(MAGIC)] == MAGIC


def encrypt(zip_bytes: bytes, passphrase: str) -> bytes:
    salt = os.urandom(_SALT_LEN)
    token = Fernet(_derive_key(passphrase, salt)).encrypt(zip_bytes)
    return MAGIC + salt + token


def decrypt(blob: bytes, passphrase: str) -> bytes:
    if not is_encrypted(blob):
        raise ValueError("Kein Kies-Backup-Container.")
    salt = blob[len(MAGIC):_HEADER_LEN]
    token = blob[_HEADER_LEN:]
    try:
        return Fernet(_derive_key(passphrase, salt)).decrypt(token)
    except InvalidToken:
        raise ValueError("Falsche Passphrase oder beschaedigtes Backup.")
