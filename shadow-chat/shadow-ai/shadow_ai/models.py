"""Modell-Implementierungen der AI Layer.

EchoModel ist deterministisch und ersetzt das Open-Weight-Modell,
solange Shadow Model Research noch keinen eigenen Adapter liefert.
Ein spaeterer Adapter (z.B. transformers/llama.cpp) implementiert
dieselbe Modell-Schnittstelle und wird im MODEL_REGISTRY eingetragen.
"""

from __future__ import annotations

import time
from typing import Callable, Protocol


class StreamEvent(Protocol):
    def __call__(self, ev: dict) -> None: ...


class Model(Protocol):
    def capabilities(self) -> dict: ...
    def load(self, config: dict) -> None: ...
    def unload(self) -> None: ...
    def stream(self, request: dict, emit: StreamEvent) -> str:
        """Emittiert token/usage/finish-Events und liefert finish_reason zurueck."""
        ...


def _fnv1a(s: str) -> int:
    h = 0xCBF29CE484222325
    for b in s.encode("utf-8"):
        h ^= b
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def _tokenize(text: str) -> list[str]:
    return text.split(" ")  # Wort-Granularitaet, deterministisch


class EchoModel:
    """Deterministischer Platzhalter: echo-artige Antwort aus User-Input.

    Respektiert deadline_ms, max_tokens und stop_sequences aus dem Request -
    dieselbe Semantik wie der Rust-StubAdapter.
    """

    def __init__(self, token_delay_s: float = 0.005) -> None:
        self._loaded = False
        self._token_delay_s = token_delay_s

    def capabilities(self) -> dict:
        return {
            "streaming": True,
            "tool_calling": False,
            "vision": False,
            "context_window": 8192,
            "max_output_tokens": 512,
        }

    def load(self, config: dict) -> None:
        self._loaded = True

    def unload(self) -> None:
        self._loaded = False

    def stream(self, request: dict, emit: StreamEvent) -> str:
        if not self._loaded:
            raise RuntimeError("unavailable")

        params = request.get("params", {})
        constraints = request.get("constraints", {})
        deadline_ms = int(constraints.get("deadline_ms", 120_000))
        max_tokens = int(params.get("max_tokens", 1024))
        stop_sequences = constraints.get("stop_sequences", [])

        last_user = next(
            (m["content"] for m in reversed(request.get("messages", []))
             if m.get("role") == "user"),
            "",
        )
        h = _fnv1a(last_user)
        reply = f"Echo[{h:016x}]: {last_user}"

        started = time.monotonic()
        tokens_in = sum(
            len(m.get("content", "").split())
            for m in request.get("messages", [])
        )
        tokens_out = 0
        out = ""

        for i, tok in enumerate(_tokenize(reply)):
            elapsed_ms = (time.monotonic() - started) * 1000
            if elapsed_ms > deadline_ms:
                emit({"type": "finish", "reason": "cancelled"})
                return "cancelled"
            if tokens_out >= max_tokens:
                emit({"type": "finish", "reason": "length"})
                return "length"

            if self._token_delay_s:
                time.sleep(self._token_delay_s)
            out += tok
            tokens_out += 1
            emit({"type": "token", "text": tok, "index": i})

            if any(s in out for s in stop_sequences):
                emit({"type": "finish", "reason": "stop"})
                return "stop"

        emit({"type": "usage", "tokens_in": tokens_in, "tokens_out": tokens_out})
        emit({"type": "finish", "reason": "stop"})
        return "stop"


MODEL_REGISTRY: dict[str, Callable[[], Model]] = {
    "echo": EchoModel,
}
