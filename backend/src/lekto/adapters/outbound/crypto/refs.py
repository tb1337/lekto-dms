"""AES-SIV for opaque references to values in addresses (RFC 5297).

The key is derived from the configured secret key with HKDF-SHA-256 for this purpose alone, so
the key that encrypts TOTP secrets serves nothing else. A reference: one version byte (1), then
the synthetic IV and the encrypted value, in base64url; the context is authenticated as
associated data.
"""

import binascii

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESSIV
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from lekto.adapters.outbound.crypto.cipher import KEY_BYTES
from lekto.core.domain.encoding import base64url, from_base64url
from lekto.core.ports.identity import DecryptionError

_VERSION = b"\x01"
_INFO = b"lekto refs v1"


class AesSivRefCipher:
    def __init__(self, secret_key: bytes) -> None:
        if len(secret_key) != KEY_BYTES:
            raise ValueError(f"the key must have {KEY_BYTES} bytes")
        key = HKDF(algorithm=SHA256(), length=64, salt=None, info=_INFO).derive(secret_key)
        self._aead = AESSIV(key)

    def seal(self, value: str, *, context: str) -> str:
        return base64url(_VERSION + self._aead.encrypt(value.encode(), [context.encode()]))

    def open(self, ref: str, *, context: str) -> str:
        try:
            data = from_base64url(ref)
        except (ValueError, binascii.Error):
            raise DecryptionError("not a reference") from None
        if not data.startswith(_VERSION):
            raise DecryptionError("unknown reference format")
        try:
            return self._aead.decrypt(data[1:], [context.encode()]).decode()
        except (InvalidTag, ValueError):
            raise DecryptionError("the reference does not open with this key") from None
