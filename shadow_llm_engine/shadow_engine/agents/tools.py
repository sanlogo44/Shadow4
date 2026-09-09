"""
Werkzeuge (Tools) für Shadow-Agenten.

Ein `Tool` ist eine benannte, beschriebene Fähigkeit mit einer `run`-Funktion.
Agenten können Werkzeuge registrieren und im Plan/Execute-Zyklus nutzen.

Die eigentliche Werkzeug-Logik (z. B. Web-Suche, Code-Ausführung,
Datenbankzugriff) wird als `run_fn` injiziert -- typischerweise ein dünner
Wrapper um die Shadow LLM API oder externe Dienste. So bleibt das Framework
unabhängig von konkreten Backends.

Eingebaute, abhängigkeitsfreie Werkzeuge:
    - CalculatorTool: arithmetische Ausdrücke sicher auswerten.
    - TextRegexTool: Regex-Suche/Extraktion auf Text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Tool:
    name: str
    description: str
    run_fn: Callable[[str], Any]
    schema: dict = field(default_factory=dict)

    def run(self, input_text: str) -> Any:
        return self.run_fn(input_text)

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description, "schema": self.schema}


class ToolRegistry:
    """Registriert Werkzeuge für einen Agenten und erlaubt Aufruf nach Namen."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def call(self, name: str, input_text: str) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"Werkzeug nicht registriert: {name}")
        return tool.run(input_text)

    def list(self) -> list[dict]:
        return [t.to_dict() for t in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)


# ---------------------------------------------------------------------- #
# Eingebaute, abhängigkeitsfreie Werkzeuge
# ---------------------------------------------------------------------- #


def _safe_arithmetic(expr: str) -> float:
    """Wertet arithmetische Ausdrücke sicher aus (nur Zahlen und + - * / ( ) )."""
    if not re.fullmatch(r"[\d\s\+\-\*/\(\)\.]+", expr or ""):
        raise ValueError("Ausdruck enthält unerlaubte Zeichen.")
    return float(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307 - eingeschränkt


CalculatorTool = Tool(
    name="calculator",
    description="Wertet einen arithmetischen Ausdruck (Zahlen, + - * / Klammern) aus.",
    run_fn=_safe_arithmetic,
    schema={"input": "arithmetischer Ausdruck als String"},
)

TextRegexTool = Tool(
    name="regex",
    description="Sucht einen regulären Ausdruck in einem Text und liefert alle Treffer.",
    run_fn=lambda args: re.findall(args.split("::", 1)[0], args.split("::", 1)[1]),
    schema={"input": "pattern::text"},
)


def default_tools() -> ToolRegistry:
    """Registry mit den eingebauten Basis-Werkzeugen."""
    reg = ToolRegistry()
    reg.register(CalculatorTool)
    reg.register(TextRegexTool)
    return reg
