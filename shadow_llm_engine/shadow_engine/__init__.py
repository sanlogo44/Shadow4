"""
Shadow LLM Engine
=================

Eine von der Shadow-Chat-Anwendung vollständig getrennte KI-Engine.

Enthält:
    - model_core      : modulare, architekturunabhängige Modell-Definitionen
    - tokenizer        : eigener BPE-Tokenizer (mehrsprachig vorbereitet)
    - training          : Trainer, Scheduler, Checkpoints
    - dataset           : Datenimport, Reinigung, Qualitätsprüfung
    - benchmark         : Admin-only Benchmark-Suiten
    - hardware          : Hardware-Erkennung (CPU/GPU/TPU/NPU)
    - registry          : Model Registry (Speichern/Laden/Versionierung/Rollback)
    - agents            : Agent-, Schwarm- und Ziel-Agent-Framework
    - nodes             : Cluster-Node-System (Master/Training/Inference/Storage)
    - api               : Shadow LLM API (Schnittstelle für Shadow Chat)

Die Engine ist absichtlich backend-agnostisch: PyTorch ist die Referenz-
Implementierung, JAX/CUDA/ROCm/Metal/TPU/NPU werden über die
Hardware-Abstraktionsschicht (shadow_engine.hardware) vorbereitet, ohne dass
Kernmodule eine harte Abhängigkeit von einem bestimmten Backend haben.
"""

from shadow_engine.config import EngineConfig, load_config

__version__ = "0.1.0"
__all__ = ["EngineConfig", "load_config", "__version__"]
