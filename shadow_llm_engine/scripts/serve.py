"""
Startet die Shadow LLM API (Schnittstelle für Shadow Chat).

Aufruf:
    python scripts/serve.py
    # oder direkt:
    uvicorn shadow_engine.api.server:app --host 0.0.0.0 --port 8420
"""

import uvicorn

from shadow_engine.config import load_config

if __name__ == "__main__":
    cfg = load_config()
    uvicorn.run("shadow_engine.api.server:app", host=cfg.api.host, port=cfg.api.port, reload=False)
