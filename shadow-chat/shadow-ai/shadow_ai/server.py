"""Shadow AI Layer Server - JSONL ueber stdio.

Architektur:
- Reader-Thread: liest stdin zeilenweise in eine Queue.
  So kann 'cancel' MITTEN in einem Stream bearbeitet werden.
- Main-Loop: dispatch; waehrend eines Streams prueft emit_checked()
  die Queue auf cancel zwischen Tokens (kooperativer Abbruch).
- Kein Netzwerk, kein threading im Modell selbst.

Exit-Codes: 0 normal, 2 Protokollfehler.
"""

from __future__ import annotations

import json
import queue
import sys
import threading

from .models import MODEL_REGISTRY
from .protocol import PROTOCOL_LINE_MAX, PROTOCOL_VERSION


class Cancelled(Exception):
    pass


def _read_lines(stream, q: "queue.Queue") -> None:
    for raw in stream:
        line = raw.strip()
        if not line:
            continue
        if len(line) > PROTOCOL_LINE_MAX:
            q.put({"type": "error", "code": "internal",
                   "message": "line exceeds protocol limit"})
            continue
        try:
            q.put(json.loads(line))
        except json.JSONDecodeError as e:
            q.put({"type": "error", "code": "internal",
                   "message": f"invalid json: {e}"})
    q.put(None)  # EOF-Marker


def _send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _err(code: str, message: str) -> dict:
    return {"v": PROTOCOL_VERSION, "type": "error", "code": code, "message": message}


def _drain_cancel(q: "queue.Queue") -> None:
    """Verwirft ein Pending-Cancel vor einer neuen Anfrage (kein Rueckstand)."""
    try:
        msg = q.get_nowait()
        if msg is not None and msg.get("type") == "cancel":
            pass  # verworfen
        elif msg is not None:
            q.put(msg)  # fremde Nachricht zuruecklegen
    except queue.Empty:
        pass


def run(adapter_name: str = "echo") -> int:
    model_factory = MODEL_REGISTRY.get(adapter_name)
    if model_factory is None:
        _send(_err("unavailable", f"adapter {adapter_name!r} not found"))
        return 2

    model = model_factory()
    loaded = False

    q: "queue.Queue" = queue.Queue()
    reader = threading.Thread(target=_read_lines, args=(sys.stdin, q), daemon=True)
    reader.start()

    # Versions-Handshake
    try:
        first = q.get(timeout=15)
    except queue.Empty:
        _send(_err("unavailable", "no hello within 15s"))
        return 2
    if first is None:
        return 0
    if first.get("type") != "hello" or first.get("v") != PROTOCOL_VERSION:
        _send(_err("internal", "expected hello with matching protocol version"))
        return 2
    _send({"v": PROTOCOL_VERSION, "type": "hello_ack",
           "protocol": PROTOCOL_VERSION, "adapter": adapter_name})

    while True:
        try:
            msg = q.get(timeout=0.1)
        except queue.Empty:
            continue
        if msg is None:
            break  # EOF
        mtype = msg.get("type")

        if mtype == "shutdown":
            break
        elif mtype == "load":
            try:
                model.load(msg.get("config", {}))
                loaded = True
                _send({"v": PROTOCOL_VERSION, "type": "ok"})
            except Exception as e:  # bewusst breit: Fehler nach außen normieren
                _send(_err("unavailable", str(e)))
        elif mtype == "stream":
            if not loaded:
                _send(_err("unavailable", "model not loaded"))
                continue
            _drain_cancel(q)
            cancelled = {"flag": False}

            def emit_checked(ev: dict) -> None:
                if ev.get("type") == "token":
                    try:
                        pending = q.get_nowait()
                        if pending is None:
                            raise Cancelled
                        if pending.get("type") == "cancel":
                            cancelled["flag"] = True
                            raise Cancelled
                        q.put(pending)  # fremde Nachricht zuruecklegen
                    except queue.Empty:
                        pass
                ev.setdefault("v", PROTOCOL_VERSION)
                _send(ev)

            try:
                model.stream(msg.get("request", {}), emit_checked)
            except Cancelled:
                _send({"v": PROTOCOL_VERSION, "type": "finish", "reason": "cancelled"})
            except Exception as e:
                _send(_err("internal", str(e)))
                _send({"v": PROTOCOL_VERSION, "type": "finish", "reason": "error"})
        elif mtype == "cancel":
            # Nur relevant, wenn ein Stream läuft; sonst harmlos quittieren.
            _send({"v": PROTOCOL_VERSION, "type": "ok"})
        else:
            _send(_err("internal", f"unknown message type: {mtype!r}"))

    model.unload()
    return 0


def main() -> None:
    adapter = "echo"
    for arg in sys.argv[1:]:
        if arg.startswith("--adapter="):
            adapter = arg.split("=", 1)[1]
    sys.exit(run(adapter))


if __name__ == "__main__":
    main()
