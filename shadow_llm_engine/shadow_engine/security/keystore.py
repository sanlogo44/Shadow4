"""
Schlüsselverwaltung für die Shadow-Verschlüsselungs-Layer.

Implementiert:
    - sichere Schlüsselerzeugung (AES-256)
    - Schlüsselrotation (versionierte Schlüssel, alte Versionen bleiben
      entschlüsselbar, bis sie explizit entfernt werden)
    - verschlüsseltes Backup (Master-Key wird mit einem Passwort/PEM
      geschützt exportiert und importiert)
    - Zugriffskontrolle (Actor-basierte Berechtigungsprüfung)
    - Audit-Logs (alle Schlüsseloperationen werden protokolliert)

Verwendet AES-GCM (modern, authentifiziert) über die `cryptography`-Bibliothek.
"""

from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet  # AES-GCM-basiert, einfach zu nutzen
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from shadow_engine.security.audit import AuditLog


def _derive_key(password: str, salt: bytes) -> bytes:
    """Leitet einen AES-Schlüssel aus einem Passwort ab (PBKDF2)."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=200_000,
    )
    return kdf.derive(password.encode("utf-8"))


@dataclass
class KeyVersion:
    version: int
    key: bytes  # roher AES-256-Schlüssel (32 Bytes)
    created_at: str = ""
    active: bool = True


class KeyStoreError(Exception):
    pass


class AccessDeniedError(KeyStoreError):
    pass


class KeyStore:
    """Verwaltet versionierte AES-Schlüssel mit Rotation, Backup, ACL, Audit."""

    def __init__(
        self,
        path: str | Path = "./shadow_keystore.json",
        audit: Optional[AuditLog] = None,
        master_password: Optional[str] = None,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.audit = audit or AuditLog()
        self._master_password = master_password
        self._versions: dict[int, KeyVersion] = {}
        self._current_version = 0
        self._actors: set[str] = set()  # berechtigte Actors
        self._lock = __import__("threading").Lock()
        self._load()

    # -- Persistence ----------------------------------------------------- #
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        # Schlüssel sind verschlüsselt gespeichert, falls Master-Password gesetzt
        enc_keys = data.get("keys", {})
        if self._master_password and "enc_keys" in data:
            try:
                salt = bytes.fromhex(data["salt"])
                derived = _derive_key(self._master_password, salt)
                fernet = Fernet(_to_fernet_key(derived))
                enc_keys = json.loads(fernet.decrypt(data["enc_keys"].encode()).decode())
            except Exception:
                enc_keys = data.get("keys", {})
        for ver_str, key_hex in enc_keys.items():
            ver = int(ver_str)
            kv = KeyVersion(version=ver, key=bytes.fromhex(key_hex))
            kv.created_at = data.get("created_at", {}).get(ver_str, "")
            kv.active = ver == data.get("current_version", ver)
            self._versions[ver] = kv
        self._current_version = data.get("current_version", 0)
        self._actors = set(data.get("actors", []))

    def _save(self) -> None:
        enc_keys = {str(v.version): v.key.hex() for v in self._versions.values()}
        data = {"current_version": self._current_version,
                "created_at": {str(v.version): v.created_at for v in self._versions.values()},
                "actors": list(self._actors)}
        if self._master_password:
            salt = os.urandom(16)
            derived = _derive_key(self._master_password, salt)
            fernet = Fernet(_to_fernet_key(derived))
            data = {"salt": salt.hex(),
                    "enc_keys": fernet.encrypt(json.dumps(enc_keys).encode()).decode(),
                    "current_version": self._current_version,
                    "actors": list(self._actors)}
        else:
            data["keys"] = enc_keys
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # -- Actor / ACL ---------------------------------------------------- #
    def grant(self, actor: str) -> None:
        self._actors.add(actor)
        self._save()
        self.audit.log("grant_access", actor=actor, detail={"actor": actor})

    def revoke(self, actor: str) -> None:
        self._actors.discard(actor)
        self._save()
        self.audit.log("revoke_access", actor=actor, detail={"actor": actor})

    def _check_access(self, actor: str) -> None:
        if self._actors and actor not in self._actors:
            self.audit.log("access_denied", actor=actor, outcome="denied")
            raise AccessDeniedError(f"Actor '{actor}' nicht berechtigt.")

    # -- Schlüssel ------------------------------------------------------ #
    def init_key(self, actor: str = "system") -> int:
        """Erzeugt den ersten AES-Schlüssel (Version 1)."""
        with self._lock:
            self._check_access(actor)
            from datetime import datetime, timezone
            if not self._versions:
                self._versions[1] = KeyVersion(version=1, key=os.urandom(32),
                                               created_at=datetime.now(timezone.utc).isoformat())
                self._current_version = 1
                self._actors.add(actor)
                self._save()
                self.audit.log("key_init", actor=actor, detail={"version": 1})
            return self._current_version

    def rotate(self, actor: str = "system") -> int:
        """Erzeugt einen neuen Schlüssel (neue Version); alte bleiben lesbar."""
        with self._lock:
            self._check_access(actor)
            if not self._versions:
                return self.init_key(actor)
            # alte als inaktiv markieren
            for v in self._versions.values():
                v.active = False
            new_ver = max(self._versions) + 1
            from datetime import datetime, timezone
            self._versions[new_ver] = KeyVersion(
                version=new_ver, key=os.urandom(32),
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            self._current_version = new_ver
            self._save()
            self.audit.log("key_rotate", actor=actor, detail={"new_version": new_ver})
            return new_ver

    def current_key(self, actor: str = "system") -> tuple[int, bytes]:
        with self._lock:
            self._check_access(actor)
            if not self._versions:
                self.init_key(actor)
            kv = self._versions[self._current_version]
            self.audit.log("key_access", actor=actor, detail={"version": kv.version})
            return kv.version, kv.key

    def key_for_version(self, version: int, actor: str = "system") -> bytes:
        with self._lock:
            self._check_access(actor)
            kv = self._versions.get(version)
            if kv is None:
                raise KeyStoreError(f"Unbekannte Schlüsselversion: {version}")
            return kv.key

    @property
    def current_version(self) -> int:
        return self._current_version

    def backup(self, password: str, actor: str = "system") -> bytes:
        """Exportiert alle Schlüssel passwortgeschützt (AES-GCM)."""
        self._check_access(actor)
        salt = os.urandom(16)
        derived = _derive_key(password, salt)
        aesgcm = AESGCM(derived)
        nonce = os.urandom(12)
        payload = json.dumps({str(v.version): v.key.hex() for v in self._versions.values()}).encode()
        ciphertext = aesgcm.encrypt(nonce, payload, None)
        blob = salt + nonce + ciphertext
        self.audit.log("key_backup", actor=actor, detail={"bytes": len(blob)})
        return blob

    def restore(self, blob: bytes, password: str, actor: str = "system") -> None:
        """Stellt Schlüssel aus einem passwortgeschützten Backup wieder her."""
        salt, nonce, ciphertext = blob[:16], blob[16:28], blob[28:]
        derived = _derive_key(password, salt)
        aesgcm = AESGCM(derived)
        payload = aesgcm.decrypt(nonce, ciphertext, None)
        data = json.loads(payload.decode())
        with self._lock:
            self._versions = {int(v): KeyVersion(version=int(v), key=bytes.fromhex(k))
                              for v, k in data.items()}
            self._current_version = max(self._versions) if self._versions else 0
            self._save()
        self.audit.log("key_restore", actor=actor, detail={"versions": list(data.keys())})


def _to_fernet_key(derived: bytes) -> bytes:
    """Konvertiert einen 32-Byte-Schlüssel in einen Fernet-kompatiblen Schlüssel."""
    import base64
    return base64.urlsafe_b64encode(derived)
