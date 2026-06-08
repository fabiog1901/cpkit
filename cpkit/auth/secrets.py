"""Versioned symmetric secret encryption helpers."""

import base64
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ENCRYPTED_SECRET_VERSION = b"\x01"
DEFAULT_MASTER_KEY_ENV_VAR = "API_KEY_MASTER_KEY"


def validate_secret_crypto_config(
    *,
    master_key_env_var: str = DEFAULT_MASTER_KEY_ENV_VAR,
) -> None:
    _secret_master_key(master_key_env_var=master_key_env_var)


def encrypt_secret(
    secret: bytes | str,
    *,
    master_key_env_var: str = DEFAULT_MASTER_KEY_ENV_VAR,
) -> bytes:
    nonce = secrets.token_bytes(12)
    key = _secret_master_key(master_key_env_var=master_key_env_var)
    ciphertext = AESGCM(key).encrypt(nonce, _secret_bytes(secret), None)
    return ENCRYPTED_SECRET_VERSION + nonce + ciphertext


def decrypt_secret(
    secret: bytes | str,
    *,
    master_key_env_var: str = DEFAULT_MASTER_KEY_ENV_VAR,
) -> bytes:
    encrypted_secret = _secret_bytes(secret)
    if not encrypted_secret:
        raise RuntimeError("Encrypted secret is empty.")
    if encrypted_secret[:1] != ENCRYPTED_SECRET_VERSION:
        raise RuntimeError(
            "Encrypted secret has an unsupported format. Migrate stored secrets to the versioned encrypted format."
        )

    nonce = encrypted_secret[1:13]
    ciphertext = encrypted_secret[13:]
    if len(nonce) != 12 or not ciphertext:
        raise RuntimeError("Encrypted secret is malformed.")

    try:
        return AESGCM(
            _secret_master_key(master_key_env_var=master_key_env_var)
        ).decrypt(nonce, ciphertext, None)
    except Exception as exc:
        raise RuntimeError(
            f"Encrypted secret could not be decrypted. Check {master_key_env_var} and stored key material."
        ) from exc


def _secret_master_key(*, master_key_env_var: str) -> bytes:
    encoded_key = os.getenv(master_key_env_var, "").strip()
    if not encoded_key:
        raise RuntimeError(f"{master_key_env_var} must be set for secret encryption.")

    try:
        key = base64.b64decode(encoded_key, validate=True)
    except ValueError as exc:
        raise RuntimeError(f"{master_key_env_var} must be valid base64.") from exc

    if len(key) != 32:
        raise RuntimeError(f"{master_key_env_var} must decode to exactly 32 bytes.")

    return key


def _secret_bytes(secret: bytes | str) -> bytes:
    if isinstance(secret, bytes):
        return secret
    return secret.encode("utf-8")
