"""Top-Level CLI für die Shadow AI Engine.

Aufruf::

    shadow node add/list/status/remove/serve/worker
    shadow train --config shadow.yaml   (geplant)
    shadow version

Diese CLI ist der Einstiegspunkt (console-script ``shadow``). Sie delegiert
an die spezialisierten Sub-CLIs und erweitert die bestehende Architektur,
ohne sie zu verändern.
"""

from __future__ import annotations

import sys
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        _print_help()
        return 0

    command = args[0]
    rest = args[1:]

    if command in ("version", "-V", "--version"):
        from shadow_engine import __version__
        print(f"shadow-engine {__version__}")
        return 0

    if command == "node":
        from shadow_engine.nodes.cli import main as node_main
        node_main(rest)
        return 0

    if command == "train":
        print("Training wird über scripts/train.py gestartet.")
        print("Beispiel: PYTHONPATH=. python scripts/train.py --config shadow.yaml")
        return 0

    print(f"Unbekannter Befehl: {command}", file=sys.stderr)
    _print_help()
    return 1


def _print_help() -> None:
    print("shadow -- Shadow AI Engine CLI\n")
    print("Befehle:")
    print("  node     Node-Verwaltung (add/list/status/remove/serve/worker)")
    print("  train    Training starten")
    print("  version  Version ausgeben")


if __name__ == "__main__":
    sys.exit(main())
