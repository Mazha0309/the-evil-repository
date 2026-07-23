import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecretBox:
    def __init__(self, master_secret: str) -> None:
        if len(master_secret) < 24:
            raise ValueError("APP_SECRET must contain at least 24 characters")
        self._cipher = AESGCM(hashlib.sha256(master_secret.encode()).digest())

    def encrypt(self, value: str | None) -> str | None:
        if not value:
            return None
        nonce = os.urandom(12)
        payload = nonce + self._cipher.encrypt(nonce, value.encode(), b"evil-repository")
        return base64.urlsafe_b64encode(payload).decode()

    def decrypt(self, value: str | None) -> str | None:
        if not value:
            return None
        payload = base64.urlsafe_b64decode(value.encode())
        nonce, ciphertext = payload[:12], payload[12:]
        return self._cipher.decrypt(nonce, ciphertext, b"evil-repository").decode()
