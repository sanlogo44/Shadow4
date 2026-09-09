"""
RPC-Schicht: Master-Server und Node-Client für echte Netzwerk-Nodes.

Ersetzt lokale In-Process-Nodes durch echte Netzwerk-Kommunikation über
das Shadow Node Protocol (TCP+TLS, HMAC-Authentifizierung, Heartbeat).

    NodeClient (Worker)  --TLS+SNP-->  NodeServer (Master)
        - REGISTER (Rolle, Schlüssel, Capabilities)
        - HEARTBEAT (periodisch)
        - JOB_RESULT (Ergebnis eines zugewiesenen Jobs)
        - SUBMIT_JOB (Master -> Client, über Push-Channel)

Der Master führt die persistente NodeRegistry und weist Jobs anhand der
Rolle zu (Training/Inference/Storage). Bei Verbindungsabbruch verbindet
sich der Client automatisch neu (Wiederverbindung).
"""

from __future__ import annotations

import socket
import ssl
import threading
import time
from typing import Callable, Optional

from shadow_engine.nodes.base import NodeInfo, NodeRole, NodeStatus
from shadow_engine.nodes.master import Job, JobType
from shadow_engine.nodes.network import NodeAuthenticator
from shadow_engine.nodes.protocol import (
    NodeMessage,
    MessageType,
    make_message,
    recv_message,
    send_message,
    make_client_ssl_context,
    make_server_ssl_context,
)
from shadow_engine.nodes.registry import NodeRegistry


# ---------------------------------------------------------------------- #
# Master-Server
# ---------------------------------------------------------------------- #


class NodeServer:
    """Master-Node-Server: nimmt Verbindungen von Workern entgegen, führt die
    persistente Registry und weist Jobs zu."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 7331,
        cluster_secret: Optional[str] = None,
        registry_path: Optional[str] = None,
        ssl_context: Optional[ssl.SSLContext] = None,
        use_tls: bool = False,
    ):
        self.host = host
        self.port = port
        self.auth = NodeAuthenticator(cluster_secret or NodeAuthenticator.generate_cluster_secret())
        self.registry = NodeRegistry(registry_path or "./node_registry.json")
        self.use_tls = use_tls
        self.ssl_context = ssl_context or (make_server_ssl_context() if use_tls else None)
        self._sock: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._jobs: dict[str, Job] = {}
        self._job_queue: dict[str, list[Job]] = {"training": [], "inference": [], "storage": []}
        self._clients: dict[str, socket.socket] = {}
        self._lock = threading.Lock()
        self.cluster_secret = self.auth._secret.decode("utf-8")  # für Worker-Verteilung

    # -- Lifecycle ------------------------------------------------------ #
    def start(self, blocking: bool = False) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(64)
        self._running = True
        if blocking:
            self._accept_loop()
        else:
            self._thread = threading.Thread(target=self._accept_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        with self._lock:
            for c in self._clients.values():
                try:
                    c.close()
                except OSError:
                    pass
            self._clients.clear()

    def _accept_loop(self):
        while self._running:
            try:
                conn, addr = self._sock.accept()
            except OSError:
                break
            try:
                if self.use_tls and self.ssl_context:
                    conn = self.ssl_context.wrap_socket(conn, server_side=True)
            except ssl.SSLError:
                conn.close()
                continue
            t = threading.Thread(target=self._handle_client, args=(conn, addr), daemon=True)
            t.start()

    # -- Request-Handling ---------------------------------------------- #
    def _handle_client(self, conn: socket.socket, addr):
        try:
            while self._running:
                msg = recv_message(conn, timeout=15.0)
                if msg is None:
                    break
                response = self._dispatch(msg, conn)
                if response is not None:
                    send_message(conn, response)
        except (socket.error, OSError):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _dispatch(self, msg: NodeMessage, conn: socket.socket) -> Optional[NodeMessage]:
        from shadow_engine.nodes.protocol import verify_message
        if not verify_message(self.auth, msg):
            return make_message(self.auth, MessageType.STATUS, "server",
                                {"ok": False, "error": "auth_failed"})

        if msg.type == MessageType.REGISTER:
            role = msg.payload.get("role", "training")
            info = NodeInfo(
                node_id=msg.node_id,
                role=NodeRole(role),
                host=msg.payload.get("host", "unknown"),
                port=int(msg.payload.get("port", 0)),
                capabilities=msg.payload.get("capabilities", {}),
            )
            self.registry.add(info, cluster_secret=self.cluster_secret)
            with self._lock:
                self._clients[msg.node_id] = conn
            return make_message(self.auth, MessageType.STATUS, "server",
                                {"ok": True, "node_id": msg.node_id, "role": role})

        if msg.type == MessageType.HEARTBEAT:
            self.registry.update_status(msg.node_id, NodeStatus.ONLINE,
                                        last_heartbeat=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            # Worker-Poll: falls ein passender Job in der Queue liegt,
            # antworten wir mit SUBMIT_JOB statt PONG (vermeidet
            # Message-Interleaving, da der Worker die Konversation treibt).
            role = msg.payload.get("role")
            with self._lock:
                queue = self._job_queue.get(role, [])
                if queue:
                    job = queue.pop(0)
                    job.assigned_node_id = msg.node_id
                    job.status = "assigned"
                    return make_message(self.auth, MessageType.SUBMIT_JOB, "server",
                                        {"job_id": job.job_id, "payload": job.payload})
            return make_message(self.auth, MessageType.PONG, "server", {"ok": True})

        if msg.type == MessageType.JOB_RESULT:
            job_id = msg.payload.get("job_id")
            success = msg.payload.get("success", False)
            result = msg.payload.get("result")
            if job_id in self._jobs:
                self._jobs[job_id].status = "done" if success else "failed"
                self._jobs[job_id].result = result
            return make_message(self.auth, MessageType.STATUS, "server", {"ok": True})

        if msg.type == MessageType.STATUS:
            return make_message(self.auth, MessageType.STATUS, "server",
                                {"ok": True, "nodes": self.registry.list()})

        return make_message(self.auth, MessageType.STATUS, "server",
                            {"ok": False, "error": "unknown_type"})

    # -- Job-Verteilung (Master -> Worker über Poll) -------------------- #
    def submit_job(self, job_type: JobType, payload: dict) -> Job:
        """Reiht einen Job in die Warteschlange der passenden Rolle ein.
        Der nächste Worker-Poll (Heartbeat) holt den Job ab."""
        role_map = {JobType.TRAINING: "training",
                    JobType.INFERENCE: "inference",
                    JobType.STORAGE: "storage"}
        role_key = role_map[job_type]
        job = Job(job_id=payload.get("job_id", f"job-{int(time.time())}"),
                  job_type=job_type, payload=payload)
        with self._lock:
            self._jobs[job.job_id] = job
            self._job_queue[role_key].append(job)
        return job

    def cluster_status(self) -> dict:
        return {"nodes": self.registry.list(), "jobs": {jid: {"status": j.status} for jid, j in self._jobs.items()}}


# ---------------------------------------------------------------------- #
# Node-Client (Worker)
# ---------------------------------------------------------------------- #


class NodeClient:
    """Worker-Node-Client: verbindet sich mit dem Master, registriert sich,
    sendet Heartbeats und führt zugewiesene Jobs aus (via execute_fn)."""

    def __init__(
        self,
        master_host: str,
        master_port: int,
        node_id: str,
        role: NodeRole,
        cluster_secret: str,
        capabilities: Optional[dict] = None,
        ssl_context: Optional[ssl.SSLContext] = None,
        use_tls: bool = False,
        execute_fn: Optional[Callable[[dict], dict]] = None,
    ):
        self.master_host = master_host
        self.master_port = master_port
        self.node_id = node_id
        self.role = role
        self.auth = NodeAuthenticator(cluster_secret)
        self.capabilities = capabilities or {}
        self.use_tls = use_tls
        self.ssl_context = ssl_context or (make_client_ssl_context() if use_tls else None)
        self.execute_fn = execute_fn or (lambda payload: {"success": True})
        self._sock: Optional[socket.socket] = None
        self._running = False
        self._registered = False
        self._reconnect_delay = 1.0
        self._thread: Optional[threading.Thread] = None

    # -- Verbindung ----------------------------------------------------- #
    def connect(self) -> bool:
        raw = socket.create_connection((self.master_host, self.master_port), timeout=5.0)
        if self.use_tls and self.ssl_context:
            raw = self.ssl_context.wrap_socket(raw, server_hostname=self.master_host)
        raw.settimeout(10.0)
        self._sock = raw
        return self._register()

    def _register(self) -> bool:
        msg = make_message(self.auth, MessageType.REGISTER, self.node_id, {
            "role": self.role.value, "host": "worker", "port": 0,
            "capabilities": self.capabilities,
        })
        send_message(self._sock, msg)
        resp = recv_message(self._sock, timeout=10.0)
        if resp and resp.payload.get("ok"):
            self._registered = True
            self._reconnect_delay = 1.0
            return True
        return False

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass

    def _loop(self):
        while self._running:
            try:
                if self._sock is None or self._registered is False:
                    self.connect()
                self._poll_once()
                time.sleep(0.5)
            except (socket.error, OSError):
                self._registered = False
                self._sock = None
                if not self._running:
                    break
                time.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 30.0)

    def _poll_once(self) -> None:
        """Ein Poll-Zyklus: Heartbeat senden, Antwort auswerten. Ist die
        Antwort ein SUBMIT_JOB, wird der Job ausgeführt und das Ergebnis
        zurückgemeldet. Der Worker treibt die Konversation, was
        Message-Interleaving vermeidet."""
        if self._sock is None:
            return
        msg = make_message(self.auth, MessageType.HEARTBEAT, self.node_id,
                           {"status": "online", "role": self.role.value})
        send_message(self._sock, msg)
        resp = recv_message(self._sock, timeout=5.0)
        if resp is None:
            self._registered = False
            self._sock = None
            return
        if resp.type == MessageType.SUBMIT_JOB:
            payload = resp.payload.get("payload", resp.payload)
            job_id = resp.payload.get("job_id", "unknown")
            try:
                result = self.execute_fn(payload)
                success = True
            except Exception as e:
                result = {"error": str(e)}
                success = False
            ack = make_message(self.auth, MessageType.JOB_RESULT, self.node_id,
                               {"job_id": job_id, "success": success, "result": result})
            send_message(self._sock, ack)
            recv_message(self._sock, timeout=5.0)  # Bestätigung abholen


def start_worker_node(
    master_host: str, master_port: int, node_id: str, role: NodeRole,
    cluster_secret: str, execute_fn: Optional[Callable[[dict], dict]] = None,
) -> NodeClient:
    """Startet einen Worker-Node, der sich beim Master registriert und
    Jobs der entsprechenden Rolle ausführt."""
    client = NodeClient(master_host, master_port, node_id, role, cluster_secret, execute_fn=execute_fn)
    client.start()
    return client
