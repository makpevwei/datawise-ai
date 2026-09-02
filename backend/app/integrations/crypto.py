"""Encryption at rest for connected-source OAuth refresh tokens.

The first value in this codebase that needs to be *recovered*, not just
compared -- User.reset_token_hash (app/db/models.py) is a one-way SHA-256
digest, which works for "does this match" but not "give me back the raw
token to call Google with." Fernet (symmetric, authenticated encryption,
from the `cryptography` package) is the standard fit for exactly this case.

TOKEN_ENCRYPTION_KEY must be a Fernet key -- generate one with:
    python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings


class TokenEncryptionNotConfiguredError(Exception):
    """Raised when TOKEN_ENCRYPTION_KEY is unset. Callers must report this
    honestly rather than silently storing a token some other, less safe way."""


class TokenDecryptionError(Exception):
    """Raised when a stored value fails to decrypt -- wrong/rotated key, or
    the value was corrupted. Never leaks the ciphertext or key in the message."""


def _fernet(settings: Settings) -> Fernet:
    if not settings.token_encryption_key:
        raise TokenEncryptionNotConfiguredError(
            "TOKEN_ENCRYPTION_KEY is not configured -- cannot store or read a connected source's "
            "refresh token safely. Generate one with Fernet.generate_key() and set it before "
            "connecting any Google integration."
        )
    try:
        return Fernet(settings.token_encryption_key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise TokenEncryptionNotConfiguredError("TOKEN_ENCRYPTION_KEY is set but is not a valid Fernet key.") from exc


def encrypt_refresh_token(raw_token: str, settings: Settings) -> str:
    return _fernet(settings).encrypt(raw_token.encode("utf-8")).decode("utf-8")


def decrypt_refresh_token(encrypted_token: str, settings: Settings) -> str:
    try:
        return _fernet(settings).decrypt(encrypted_token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise TokenDecryptionError(
            "Stored refresh token could not be decrypted -- TOKEN_ENCRYPTION_KEY may have changed, "
            "or the stored value is corrupted. The integration will need to be reconnected."
        ) from exc
