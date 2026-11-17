"""Identifier helpers: UUIDv7 primary keys and human-friendly short codes."""
import os
import secrets
import time
import uuid

# Crockford base32 without I, L, O, U: safe to read aloud and type on a basic phone.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def uuid7() -> uuid.UUID:
    """RFC 9562 UUIDv7: 48-bit unix-ms timestamp + random. Time-ordered for index locality.

    Not strictly monotonic within the same millisecond, which is fine for primary keys.
    """
    ts_ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")  # 80 random bits
    rand_a = (rand >> 68) & 0xFFF  # 12 bits
    rand_b = rand & ((1 << 62) - 1)  # 62 bits
    value = (ts_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76  # version 7
    value |= rand_a << 64
    value |= 0b10 << 62  # RFC 4122 variant
    value |= rand_b
    return uuid.UUID(int=value)


def short_code(prefix: str = "", length: int = 6) -> str:
    """e.g. R-4F7K2M. Used for SMS replies ('YES R-4F7K2M'). Uniqueness is enforced by the DB;
    callers retry on IntegrityError."""
    body = "".join(secrets.choice(_CROCKFORD) for _ in range(length))
    return f"{prefix}-{body}" if prefix else body
