# Shadow AI Layer

JSONL-Protokoll-Server (`Shadow Node Protocol v1`) ueber stdio.
Wird vom Rust-Core (`PythonAdapter`) als Kindprozess gestartet.

## Start

```bash
# direkt
SHADOW_AI_DIR=$PWD python3 -m shadow_ai

# von der Rust-CLI aus
export SHADOW_AI_DIR=/pfad/zu/shadow-mvp/shadow-ai
cargo run -p shadow-cli -- chat python-echo
```

## Protokoll

Siehe `shadow_ai/protocol.py`. Kurz: NDJSON, erste Nachricht `hello` mit
Versionspruefung, dann `load` / `stream` / `cancel` / `shutdown`.
Streams emittieren `token` → `usage` → `finish`.

## Tests

```bash
cd shadow-ai && python3 -m unittest discover -s tests -v
```
