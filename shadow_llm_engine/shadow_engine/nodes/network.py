"""
Netzwerk-Schicht des Node-Systems.

Implementiert:
    - verschlüsselte Kommunikation (TLS, über Python `ssl`-Standardbibliothek)
    - Authentifizierung (HMAC-signierte Tokens zwischen Nodes)
    - sichere Datenübertragung (Nachrichten werden signiert + optional
      verschlüsselt transportiert)

Bewusst ohne externe Abhängigkeiten (nur `ssl`, `hmac`, `secrets`), damit
die Node-Kommunikation ohne zusätzliche Pakete lauffähig ist. Für den
produktiven Cluster-Einsatz kann dies durch mTLS mit echten Zertifikaten
ersetzt werden -- die Schnittstelle (`NodeAuthenticator`, `create_ssl_context`)
bleibt dabei stabil.
"""

from __future__ import annotations

import hmac
import hashlib
import json
import secrets
import ssl
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class AuthenticationError(Exception):
    pass


@dataclass
class SignedMessage:
    payload: dict
    timestamp: float
    signature: str
    node_id: str


class NodeAuthenticator:
    """
    HMAC-basierte Node-zu-Node-Authentifizierung mit gemeinsamem
    Cluster-Secret. Jede Nachricht trägt eine Signatur und einen
    Zeitstempel (Replay-Schutz über `max_age_seconds`).
    """

    def __init__(self, cluster_secret: str, max_age_seconds: int = 30):
        self._secret = cluster_secret.encode("utf-8")
        self.max_age_seconds = max_age_seconds

    @staticmethod
    def generate_cluster_secret() -> str:
        return secrets.token_hex(32)

    def _sign(self, node_id: str, timestamp: float, payload: dict) -> str:
        message = f"{node_id}|{timestamp}|{json.dumps(payload, sort_keys=True)}".encode("utf-8")
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

    def sign_message(self, node_id: str, payload: dict) -> SignedMessage:
        timestamp = time.time()
        signature = self._sign(node_id, timestamp, payload)
        return SignedMessage(payload=payload, timestamp=timestamp, signature=signature, node_id=node_id)

    def verify_message(self, message: SignedMessage) -> bool:
        if abs(time.time() - message.timestamp) > self.max_age_seconds:
            raise AuthenticationError("Nachricht abgelaufen (mögliches Replay).")
        expected = self._sign(message.node_id, message.timestamp, message.payload)
        if not hmac.compare_digest(expected, message.signature):
            raise AuthenticationError(f"Ungültige Signatur von Node '{message.node_id}'.")
        return True


def create_ssl_context(
    cert_path: Optional[str | Path] = None,
    key_path: Optional[str | Path] = None,
    ca_path: Optional[str | Path] = None,
    server_side: bool = True,
) -> ssl.SSLContext:
    """
    Erstellt einen TLS-Kontext für verschlüsselte Node-Kommunikation.

    Ohne übergebene Zertifikate wird ein Kontext mit den System-Defaults
    erzeugt (nützlich für lokale Entwicklung); im produktiven Cluster-
    Betrieb sollten `cert_path`/`key_path`/`ca_path` gesetzt werden
    (mTLS zwischen allen Nodes).
    """
    protocol = ssl.PROTOCOL_TLS_SERVER if server_side else ssl.PROTOCOL_TLS_CLIENT
    context = ssl.SSLContext(protocol)
    context.minimum_version = ssl.TLSVersion.TLSv1_2

    if cert_path and key_path:
        context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    if ca_path:
        context.load_verify_locations(cafile=str(ca_path))
        context.verify_mode = ssl.CERT_REQUIRED

    return context
