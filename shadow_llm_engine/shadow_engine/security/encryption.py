"""
Feld-Verschlüsselungs-Layer für alle sensiblen Shadow-Metadaten.

Verschlüsselt (AES-GCM, authentifiziert) folgende sensiblen Felder:
    - Benutzername, E-Mail, Rollen
    - Einstellungen (sensitive Anteile)
    - Modellinformationen (Lizenz, Konfiguration)
    - Node-Daten (Adressen, Schlüssel)
    - Logs (sensitive Inhalte)

Klartext fließt NIE in die Datenbank -- das Layer sits zwischen Anwendung
und Speicher:

    User Daten -> Encryption Layer -> Database

Token-Format:  enc:v<version>:<nonce_hex>:<ciphertext_hex>

Alte Versionen bleiben entschlüsselbar (Schlüsselrotation ohne Datenverlust).
Zugriffskontrolle über den Actor; alle Operationen im Audit-Log.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from shadow_engine.security.audit import AuditLog
from shadow_engine.security.keystore import KeyStore, AccessDeniedError

# Sensible Felder, die immer verschlüsselt werden.
SENSITIVE_FIELDS = {
    "username", "email", "roles", "settings", "password_hash",
    "model_info", "node_data", "node_secret", "logs",
    "api_key", "token", "secret", "phone", "address",
}

_TOKEN_PREFIX = "enc:"


class EncryptionLayer:
    """Verschlüsselt sensible Felder in einem Dict feldweise (AES-GCM)."""

    def __init__(self, keystore: KeyStore, sensitive_fields: Optional[set[str]] = None,
                 audit: Optional[AuditLog] = None):
        self.keystore = keystore
        self.sensitive = sensitive_fields or SENSITIVE_FIELDS
        self.audit = audit or keystore.audit

    # -- Einzelne Werte -------------------------------------------------- #
    def encrypt_value(self, value: Any, actor: str = "system") -> str:
        if value is None:
            return value  # None bleibt None
        version, key = self.keystore.current_key(actor)
        plaintext = json.dumps(value, ensure_ascii=False).encode("utf-8")
        nonce = __import__("os").urandom(12)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        token = f"{_TOKEN_PREFIX}v{version}:{nonce.hex()}:{ciphertext.hex()}"
        self.audit.log("encrypt", actor=actor, detail={"version": version, "field_type": type(value).__name__})
        return token

    def decrypt_value(self, token: str, actor: str = "system") -> Any:
        if not isinstance(token, str) or not token.startswith(_TOKEN_PREFIX):
            return token  # bereits Klartext -> zurückgeben
        body = token[len(_TOKEN_PREFIX):]
        try:
            ver_part, nonce_hex, ct_hex = body.split(":")
            version = int(ver_part.lstrip("v"))
            nonce = bytes.fromhex(nonce_hex)
            ciphertext = bytes.fromhex(ct_hex)
            key = self.keystore.key_for_version(version, actor)
            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            self.audit.log("decrypt", actor=actor, detail={"version": version})
            return json.loads(plaintext.decode("utf-8"))
        except AccessDeniedError:
            raise
        except Exception as e:
            self.audit.log("decrypt_failed", actor=actor, outcome="error", detail={"error": str(e)})
            raise ValueError(f"Entschlüsselung fehlgeschlagen: {e}") from e

    # -- Dict-Felder ---------------------------------------------------- #
    def encrypt_fields(self, record: dict, actor: str = "system",
                       fields: Optional[set[str]] = None) -> dict:
        """Verschlüsselt alle sensiblen Felder in `record` (Kopie)."""
        sensitive = fields or self.sensitive
        out = dict(record)
        for k, v in out.items():
            if k in sensitive and v is not None and not _is_encrypted(v):
                out[k] = self.encrypt_value(v, actor)
        self.audit.log("encrypt_fields", actor=actor,
                       detail={"fields": [k for k in out if k in sensitive]})
        return out

    def decrypt_fields(self, record: dict, actor: str = "system",
                       fields: Optional[set[str]] = None) -> dict:
        """Entschlüsselt alle verschlüsselten Felder in `record` (Kopie)."""
        sensitive = fields or self.sensitive
        out = dict(record)
        for k, v in out.items():
            if k in sensitive and isinstance(v, str) and _is_encrypted(v):
                out[k] = self.decrypt_value(v, actor)
        return out

    def is_encrypted(self, value: Any) -> bool:
        return _is_encrypted(value)


def _is_encrypted(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(_TOKEN_PREFIX)
