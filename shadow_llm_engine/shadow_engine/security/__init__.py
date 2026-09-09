"""
Shadow Security Layer -- vollständige Verschlüsselung aller Metadaten.

    User Daten -> Encryption Layer -> Database

Implementiert:
    - AES-GCM Feld-Verschlüsselung (authentifiziert, modern)
    - Schlüsselverwaltung: Rotation, Backup, Zugriffskontrolle, Audit-Logs
    - sensible Felder: Benutzername, E-Mail, Rollen, Einstellungen,
      Modellinformationen, Node-Daten, Logs

Schwere Abhängigkeit: `cryptography` (AES-GCM). Ohne das Paket ist die
Layer nicht initialisierbar -- die Engine selbst startet aber weiterhin.
"""

from shadow_engine.security.audit import AuditLog
from shadow_engine.security.keystore import KeyStore, KeyStoreError, AccessDeniedError, KeyVersion
from shadow_engine.security.encryption import (
    EncryptionLayer,
    SENSITIVE_FIELDS,
)

__all__ = [
    "AuditLog",
    "KeyStore", "KeyStoreError", "AccessDeniedError", "KeyVersion",
    "EncryptionLayer", "SENSITIVE_FIELDS",
]
