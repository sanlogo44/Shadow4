"""
Shadow Node Protocol (SNP) -- Nachrichten-Protokoll über TCP+TLS.

Wire-Format: jedes Frame ist ein Längen-präfixierter JSON-Blob:

    [4 Bytes Big-Endian Länge N][N Bytes JSON-Nutzlast]

Jede Nachricht besteht aus:
    - type:    Befehl (REGISTER | HEARTBEAT | STATUS | SUBMIT_JOB | JOB_RESULT | SHUTDOWN)
    - node_id: Absender
    - signature: HMAC-Signatur (über node_id|timestamp|payload)
    - timestamp: Unix-Zeitstempel (Replay-Schutz)
    - payload: anwendungsspezifische Daten

Das Protokoll nutzt ausschließlich die Python-Standardbibliothek (socket,
ssl, json, hmac, secrets, threading) -- keine externen Abhängigkeiten. Für
produktive Cluster kann es durch gRPC/QUIC ersetzt werden, ohne die
Schnittstelle (NodeServer/NodeClient) zu ändern.
"""

from __future__ import annotations

import json
import socket
import ssl
import struct
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from shadow_engine.nodes.network import NodeAuthenticator, AuthenticationError, create_ssl_context

DEFAULT_PORT = 7331
_FRAME_HEADER = struct.Struct(">I")  # 4 Bytes Big-Endian Länge


class MessageType(str, Enum):
    REGISTER = "REGISTER"
    HEARTBEAT = "HEARTBEAT"
    STATUS = "STATUS"
    SUBMIT_JOB = "SUBMIT_JOB"
    JOB_RESULT = "JOB_RESULT"
    SHUTDOWN = "SHUTDOWN"
    PING = "PING"
    PONG = "PONG"


@dataclass
class NodeMessage:
    type: MessageType
    node_id: str
    payload: dict = field(default_factory=dict)
    timestamp: float = 0.0
    signature: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "node_id": self.node_id,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "signature": self.signature,
        }


# ---------------------------------------------------------------------- #
# Framing (Längen-präfixiert)
# ---------------------------------------------------------------------- #


def send_message(sock: socket.socket, message: NodeMessage) -> None:
    blob = json.dumps(message.to_dict(), ensure_ascii=False).encode("utf-8")
    sock.sendall(_FRAME_HEADER.pack(len(blob)) + blob)


def recv_message(sock: socket.socket, timeout: float = 10.0) -> Optional[NodeMessage]:
    sock.settimeout(timeout)
    header = _recv_exactly(sock, _FRAME_HEADER.size)
    if header is None:
        return None
    (length,) = _FRAME_HEADER.unpack(header)
    if length <= 0 or length > 64 * 1024 * 1024:  # max 64 MiB
        return None
    body = _recv_exactly(sock, length)
    if body is None:
        return None
    data = json.loads(body.decode("utf-8"))
    return NodeMessage(
        type=MessageType(data["type"]),
        node_id=data["node_id"],
        payload=data.get("payload", {}),
        timestamp=data.get("timestamp", 0.0),
        signature=data.get("signature", ""),
    )


def _recv_exactly(sock: socket.socket, n: int) -> Optional[bytes]:
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except socket.timeout:
            return None
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


# ---------------------------------------------------------------------- #
# Authentifizierung pro Nachricht
# ---------------------------------------------------------------------- #


def sign_message(auth: NodeAuthenticator, node_id: str, payload: dict) -> NodeMessage:
    signed = auth.sign_message(node_id, payload)
    return NodeMessage(
        type=MessageType.HEARTBEAT,  # type wird vom Aufrufer überschrieben
        node_id=node_id,
        payload=payload,
        timestamp=signed.timestamp,
        signature=signed.signature,
    )


def make_message(auth: NodeAuthenticator, msg_type: MessageType, node_id: str, payload: dict) -> NodeMessage:
    signed = auth.sign_message(node_id, payload)
    return NodeMessage(
        type=msg_type, node_id=node_id, payload=payload,
        timestamp=signed.timestamp, signature=signed.signature,
    )


def verify_message(auth: NodeAuthenticator, message: NodeMessage) -> bool:
    from shadow_engine.nodes.network import SignedMessage
    signed = SignedMessage(
        payload=message.payload, timestamp=message.timestamp,
        signature=message.signature, node_id=message.node_id,
    )
    try:
        auth.verify_message(signed)
        return True
    except AuthenticationError:
        return False


# ---------------------------------------------------------------------- #
# TLS-Kontext-Helfer
# ---------------------------------------------------------------------- #


def make_server_ssl_context(cert_path=None, key_path=None, ca_path=None) -> ssl.SSLContext:
    return create_ssl_context(cert_path, key_path, ca_path, server_side=True)


def make_client_ssl_context(cert_path=None, key_path=None, ca_path=None) -> ssl.SSLContext:
    return create_ssl_context(cert_path, key_path, ca_path, server_side=False)
