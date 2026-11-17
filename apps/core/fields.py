"""Field-level encryption and blind indexes for PII.

Settings required:
    REACH_FIELD_KEYS            list of Fernet keys, newest first (MultiFernet rotates)
    REACH_BLIND_INDEX_KEYS      {version: bytes}
    REACH_BLIND_INDEX_CURRENT   version used for new hashes
"""
import hashlib
import hmac

from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings
from django.db import models


def _fernet() -> MultiFernet:
    return MultiFernet([Fernet(k) for k in settings.REACH_FIELD_KEYS])


class EncryptedTextField(models.TextField):
    """Encrypted at rest. Not searchable or indexable: pair with blind_index() when lookup is needed."""

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None:
            return None
        return _fernet().encrypt(value.encode()).decode()

    def from_db_value(self, value, expression, connection):
        if value is None:
            return None
        return _fernet().decrypt(value.encode()).decode()


def blind_index(value: str, key_version: int | None = None) -> str:
    """HMAC-SHA256 hex digest for equality lookup over encrypted values."""
    version = key_version if key_version is not None else settings.REACH_BLIND_INDEX_CURRENT
    key = settings.REACH_BLIND_INDEX_KEYS[version]
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def normalise_msisdn(raw: str, default_cc: str = "254") -> str:
    """'0712 345 678' / '+254712345678' / '254712345678' -> '+254712345678'.

    Normalise BEFORE hashing, or the blind index will never match inbound SMS senders.
    """
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0"):
        digits = default_cc + digits[1:]
    elif not digits.startswith(default_cc) and len(digits) == 9:
        digits = default_cc + digits
    if not 10 <= len(digits) <= 15:
        raise ValueError(f"Not a plausible phone number: {raw!r}")
    return "+" + digits
