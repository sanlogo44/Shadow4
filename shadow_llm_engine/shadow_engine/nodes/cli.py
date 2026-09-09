"""
Shadow Node CLI -- Verwaltung von Cluster-Nodes.

    shadow node add    --host HOST --port PORT --role ROLE [--capabilities ...]
    shadow node list
    shadow node status [NODE_ID]
    shadow node remove NODE_ID
    shadow node serve  (Master-Server starten)
    shadow node worker  --host HOST --port PORT --role ROLE (Worker starten)

Die CLI spricht gegen die persistente NodeRegistry bzw. startet einen
Master/Worker direkt. Authentifizierung über das Cluster-Secret
(Umgebungsvariable SHADOW_CLUSTER_SECRET).
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from shadow_engine.nodes.base import NodeRole, NodeStatus
from shadow_engine.nodes.registry import NodeRegistry
from shadow_engine.nodes.rpc import NodeServer, NodeClient


def _registry(args) -> NodeRegistry:
    return NodeRegistry(args.registry)


def cmd_add(args) -> int:
    reg = _registry(args)
    from shadow_engine.nodes.base import NodeInfo
    info = NodeInfo(
        node_id=args.node_id or f"node-{args.host}-{args.port}",
        role=NodeRole(args.role),
        host=args.host, port=args.port,
        capabilities={"manual": True},
    )
    saved = reg.add(info)
    print(f"Node hinzugefügt: {saved.node_id} (Rolle: {args.role}, Host: {args.host}:{args.port})")
    return 0


def cmd_list(args) -> int:
    reg = _registry(args)
    nodes = reg.list()
    if not nodes:
        print("Keine Nodes registriert.")
        return 0
    print(f"{'NODE_ID':32} {'ROLLE':10} {'HOST':20} {'PORT':6} {'STATUS':8}")
    print("-" * 80)
    for n in nodes:
        print(f"{n.get('node_id',''):32} {n.get('role',''):10} "
              f"{n.get('host',''):20} {str(n.get('port','')):6} {n.get('status',''):8}")
    return 0


def cmd_status(args) -> int:
    reg = _registry(args)
    if args.node_id:
        node = reg.get(args.node_id)
        if not node:
            print(f"Node {args.node_id} nicht gefunden.")
            return 1
        for k, v in node.items():
            print(f"{k:16}: {v}")
        return 0
    nodes = reg.list()
    online = sum(1 for n in nodes if n.get("status") == NodeStatus.ONLINE.value)
    print(f"Registrierte Nodes: {len(nodes)} (davon online: {online})")
    for n in nodes:
        print(f"  - {n.get('node_id')} [{n.get('role')}] {n.get('status')}")
    return 0


def cmd_remove(args) -> int:
    reg = _registry(args)
    if reg.remove(args.node_id):
        print(f"Node entfernt: {args.node_id}")
        return 0
    print(f"Node nicht gefunden: {args.node_id}")
    return 1


def cmd_serve(args) -> int:
    secret = os.environ.get("SHADOW_CLUSTER_SECRET")
    server = NodeServer(host=args.host, port=args.port, cluster_secret=secret,
                       registry_path=args.registry)
    print(f"Master-Server startet auf {args.host}:{args.port}")
    print(f"Cluster-Secret: {server.cluster_secret}")
    server.start(blocking=True)
    return 0


def cmd_worker(args) -> int:
    secret = os.environ.get("SHADOW_CLUSTER_SECRET")
    if not secret:
        print("SHADOW_CLUSTER_SECRET nicht gesetzt.", file=sys.stderr)
        return 1
    from shadow_engine.nodes.base import NodeRole
    client = NodeClient(
        master_host=args.host, master_port=args.port,
        node_id=args.node_id, role=NodeRole(args.role),
        cluster_secret=secret,
        execute_fn=lambda p: {"success": True, "echo": p},
    )
    client.start()
    print(f"Worker {args.node_id} ({args.role}) verbunden mit {args.host}:{args.port}")
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        client.stop()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shadow node", description="Shadow Node-Verwaltung")
    parser.add_argument("--registry", default="./node_registry.json",
                        help="Pfad zur persistenten Node-Registry")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Node registrieren")
    p_add.add_argument("--host", required=True)
    p_add.add_argument("--port", type=int, required=True)
    p_add.add_argument("--role", required=True, choices=[r.value for r in NodeRole])
    p_add.add_argument("--node-id", default=None)
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="Nodes auflisten")
    p_list.set_defaults(func=cmd_list)

    p_status = sub.add_parser("status", help="Node-Status abrufen")
    p_status.add_argument("node_id", nargs="?", default=None)
    p_status.set_defaults(func=cmd_status)

    p_remove = sub.add_parser("remove", help="Node entfernen")
    p_remove.add_argument("node_id")
    p_remove.set_defaults(func=cmd_remove)

    p_serve = sub.add_parser("serve", help="Master-Server starten")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=7331)
    p_serve.set_defaults(func=cmd_serve)

    p_worker = sub.add_parser("worker", help="Worker-Node starten")
    p_worker.add_argument("--host", required=True)
    p_worker.add_argument("--port", type=int, default=7331)
    p_worker.add_argument("--role", required=True, choices=[r.value for r in NodeRole])
    p_worker.add_argument("--node-id", default=None)
    p_worker.set_defaults(func=cmd_worker)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
