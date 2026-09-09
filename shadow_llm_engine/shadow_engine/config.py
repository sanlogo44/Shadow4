"""
Zentrale Konfiguration der Shadow LLM Engine.

Alle Module lesen ihre Einstellungen aus einer einzigen `EngineConfig`-Instanz,
die aus einer YAML/JSON-Datei, Umgebungsvariablen oder Defaults geladen wird.
Dadurch bleibt die Engine unabhängig von einem konkreten Deployment-Kontext
(lokal, Server, Cluster).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

try:
    import yaml  # optional, nur wenn YAML-Configs genutzt werden
except ImportError:  # pragma: no cover
    yaml = None


@dataclass
class ModelCoreConfig:
    architecture: str = "shadow-transformer"
    hidden_size: int = 1024
    num_layers: int = 12
    num_heads: int = 16
    vocab_size: int = 32000
    max_sequence_length: int = 4096
    ffn_multiplier: float = 4.0
    dropout: float = 0.0
    rope_theta: float = 10000.0
    tie_embeddings: bool = True


@dataclass
class TokenizerConfig:
    vocab_size: int = 32000
    model_type: str = "bpe"          # bpe | byte-level-bpe
    special_tokens: list = field(default_factory=lambda: [
        "<pad>", "<bos>", "<eos>", "<unk>", "<mask>"
    ])
    languages: list = field(default_factory=lambda: ["auto"])


@dataclass
class TrainingConfig:
    batch_size: int = 8
    grad_accum_steps: int = 1
    learning_rate: float = 3e-4
    weight_decay: float = 0.01
    warmup_steps: int = 1000
    max_steps: int = 100_000
    checkpoint_every: int = 1000
    eval_every: int = 500
    checkpoint_dir: str = "./checkpoints"
    resume_from: Optional[str] = None
    precision: str = "bf16"          # fp32 | fp16 | bf16
    seed: int = 1337


@dataclass
class HardwareConfig:
    preferred_backend: str = "auto"  # auto | torch | jax
    preferred_device: str = "auto"   # auto | cpu | cuda | rocm | mps | tpu | npu
    allow_multi_gpu: bool = True
    distributed: bool = False


@dataclass
class RegistryConfig:
    root_dir: str = "./model_registry"
    default_namespace: str = "shadow-model"


@dataclass
class DatasetConfig:
    raw_dir: str = "./data/raw"
    clean_dir: str = "./data/clean"
    tokenized_dir: str = "./data/tokenized"
    min_doc_length: int = 20
    dedupe_method: str = "simhash"   # exact | simhash | minhash
    quality_threshold: float = 0.5


@dataclass
class NodeConfig:
    role: str = "standalone"         # standalone | master | training | inference | storage
    node_id: str = "node-0"
    master_host: Optional[str] = None
    master_port: int = 7331
    use_tls: bool = True


@dataclass
class APIConfig:
    host: str = "0.0.0.0"
    port: int = 8420
    admin_token_env: str = "SHADOW_ADMIN_TOKEN"


@dataclass
class EngineConfig:
    model_core: ModelCoreConfig = field(default_factory=ModelCoreConfig)
    tokenizer: TokenizerConfig = field(default_factory=TokenizerConfig)
    training: TrainingConfig = field(default_factory=TrainingConfig)
    hardware: HardwareConfig = field(default_factory=HardwareConfig)
    registry: RegistryConfig = field(default_factory=RegistryConfig)
    dataset: DatasetConfig = field(default_factory=DatasetConfig)
    node: NodeConfig = field(default_factory=NodeConfig)
    api: APIConfig = field(default_factory=APIConfig)

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            if path.suffix in (".yaml", ".yml") and yaml is not None:
                yaml.safe_dump(self.to_dict(), f, sort_keys=False)
            else:
                json.dump(self.to_dict(), f, indent=2)


def _merge_dataclass(dc, overrides: dict[str, Any]):
    for k, v in overrides.items():
        if hasattr(dc, k):
            current = getattr(dc, k)
            if hasattr(current, "__dataclass_fields__") and isinstance(v, dict):
                _merge_dataclass(current, v)
            else:
                setattr(dc, k, v)
    return dc


def load_config(path: Optional[str | Path] = None) -> EngineConfig:
    """
    Lädt die Engine-Konfiguration.

    Reihenfolge: Defaults -> Datei (YAML/JSON) -> Umgebungsvariable
    SHADOW_ENGINE_CONFIG (Pfad zu einer weiteren Config-Datei).
    """
    cfg = EngineConfig()

    env_path = os.environ.get("SHADOW_ENGINE_CONFIG")
    candidates = [p for p in (path, env_path) if p]

    for candidate in candidates:
        candidate = Path(candidate)
        if not candidate.exists():
            continue
        with open(candidate, "r", encoding="utf-8") as f:
            if candidate.suffix in (".yaml", ".yml"):
                if yaml is None:
                    raise RuntimeError("pyyaml ist nicht installiert, aber eine YAML-Config wurde angegeben.")
                data = yaml.safe_load(f) or {}
            else:
                data = json.load(f)
        for section, values in data.items():
            if hasattr(cfg, section) and isinstance(values, dict):
                _merge_dataclass(getattr(cfg, section), values)

    return cfg
