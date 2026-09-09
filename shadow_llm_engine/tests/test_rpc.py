"""Tests für das persistente Node-RPC-System (System 3): Verbindung,
Wiederverbindung, Authentifizierung/Verschlüsselung, Job-Ausführung, CLI."""

from __future__ import annotations

import socket
import threading
import time

import pytest

from shadow_engine.nodes import NodeClient, NodeRegistry, NodeRole, NodeServer, NodeStatus
from shadow_engine.nodes.master import JobType
from shadow_engine.nodes.protocol import (
    MessageType,
    NodeAuthenticator,
    NodeMessage,
    make_message,
    recv_message,
    send_message,
    verify_message,
)
from shadow_engine.nodes.cli import main as cli_main


@pytest.fixture()
def running_server(tmp_path):
    server = NodeServer(
        host="127.0.0.1", port=0, cluster_secret="test-secret",
        registry_path=str(tmp_path / "reg.json"), use_tls=False,
    )
    server._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server._sock.bind(("127.0.0.1", 0))
    server._sock.listen(64)
    port = server._sock.getsockname()[1]
    server._running = True
    threading.Thread(target=server._accept_loop, daemon=True).start()
    yield server, port
    server.stop()


def test_node_registry_persistence(tmp_path):
    reg = NodeRegistry(path=str(tmp_path / "reg.json"))
    from shadow_engine.nodes.base import NodeInfo
    info = reg.add(NodeInfo(node_id="n1", role=NodeRole.TRAINING, host="h1", port=100))
    assert reg.get("n1")["host"] == "h1"
    assert "node_secret" in reg.get("n1")
    # persistiert über Neustart
    reg2 = NodeRegistry(path=str(tmp_path / "reg.json"))
    assert reg2.get("n1")["role"] == "training"
    reg2.remove("n1")
    assert reg2.get("n1") is None


def test_message_auth_verification():
    auth = NodeAuthenticator("secret")
    msg = make_message(auth, MessageType.HEARTBEAT, "node-1", {"status": "online"})
    assert verify_message(auth, msg) is True
    # manipulierte Nachricht
    msg.payload = {"status": "tampered"}
    assert verify_message(auth, msg) is False


def test_send_recv_message_roundtrip():
    auth = NodeAuthenticator("secret")
    a, b = socket.socketpair()
    msg = make_message(auth, MessageType.PING, "n1", {"hello": "world"})
    send_message(a, msg)
    received = recv_message(b, timeout=2.0)
    assert received is not None
    assert received.type == MessageType.PING
    assert received.payload["hello"] == "world"
    a.close(); b.close()


def test_register_and_heartbeat(running_server):
    server, port = running_server
    client = NodeClient("127.0.0.1", port, "worker-1", NodeRole.TRAINING,
                        "test-secret", use_tls=False)
    assert client.connect() is True
    client._poll_once()  # einmal pollen (Heartbeat)
    client.stop()
    assert NodeRegistry(str(server.registry.path)).get("worker-1") is not None


def test_job_dispatch_and_execution(running_server):
    server, port = running_server
    results = []

    def execute_fn(payload):
        results.append(payload)
        return {"success": True, "computed": payload.get("x", 0) * 2}

    client = NodeClient("127.0.0.1", port, "worker-2", NodeRole.TRAINING,
                        "test-secret", execute_fn=execute_fn, use_tls=False)
    client.connect()
    client.start()
    time.sleep(0.3)
    server.submit_job(JobType.TRAINING, {"job_id": "job-1", "x": 21})
    time.sleep(1.5)
    client.stop()
    assert len(results) == 1
    job = server._jobs["job-1"]
    assert job.status == "done"
    assert job.result["computed"] == 42


def test_auth_failure_rejected():
    """Ein Client mit falschem Secret wird abgelehnt."""
    server = NodeServer(host="127.0.0.1", port=0, cluster_secret="real-secret",
                        registry_path="/tmp/_reg_test.json", use_tls=False)
    server._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server._sock.bind(("127.0.0.1", 0))
    server._sock.listen(64)
    port = server._sock.getsockname()[1]
    server._running = True
    threading.Thread(target=server._accept_loop, daemon=True).start()
    try:
        client = NodeClient("127.0.0.1", port, "evil", NodeRole.TRAINING,
                            "wrong-secret", use_tls=False)
        connected = client.connect()
        assert connected is False  # Auth schlägt fehl
    finally:
        server.stop()


def test_reconnection_after_disconnect(running_server):
    """Nach Verbindungsabbruch verbindet sich der Client erneut."""
    server, port = running_server
    client = NodeClient("127.0.0.1", port, "worker-3", NodeRole.INFERENCE,
                        "test-secret", use_tls=False)
    assert client.connect() is True
    assert client._registered is True
    # simuliere Verbindungsabbruch
    client._sock.close()
    client._registered = False
    client._sock = None
    # erneutes connect() sollte wieder registrieren
    assert client.connect() is True
    assert client._registered is True
    client.stop()


def test_cli_add_list_status_remove(tmp_path, capsys):
    reg = str(tmp_path / "cli_reg.json")
    cli_main(["--registry", reg, "add", "--host", "10.0.0.1", "--port", "7331",
              "--role", "training", "--node-id", "gpu-1"])
    cli_main(["--registry", reg, "list"])
    cli_main(["--registry", reg, "status", "gpu-1"])
    cli_main(["--registry", reg, "remove", "gpu-1"])
    out = capsys.readouterr().out
    assert "Node entfernt: gpu-1" in out
