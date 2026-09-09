"""
Architektur-unabhängige Basis-Schnittstellen des Model Core.

Ziel: Kein Teil der Engine (Training, Registry, Benchmark, API) darf
hart von "einem" Modell abhängen. Jedes Shadow-Modell implementiert
das `ShadowModel`-Protokoll -- Training/Inferenz/Registry sprechen nur
gegen dieses Protokoll, nie gegen eine konkrete Klasse.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class GenerationConfig:
    max_new_tokens: int = 256
    temperature: float = 0.8
    top_p: float = 0.95
    top_k: int = 50
    repetition_penalty: float = 1.1
    stop_token_ids: tuple[int, ...] = ()


@runtime_checkable
class ShadowModel(Protocol):
    """Vertrag, den jede Shadow-Modellarchitektur erfüllen muss."""

    name: str
    architecture: str

    def forward(self, input_ids: Any, attention_mask: Any = None, **kwargs) -> Any:
        ...

    def generate(self, input_ids: Any, generation_config: GenerationConfig, **kwargs) -> Any:
        ...

    def num_parameters(self) -> int:
        ...

    def state_dict(self) -> dict:
        ...

    def load_state_dict(self, state: dict) -> None:
        ...

    def config_dict(self) -> dict:
        """Vollständige Architektur-Konfiguration, ausreichend zur Rekonstruktion."""
        ...


class ModelBackend(ABC):
    """
    Abstraktion über das eigentliche Rechen-Backend (PyTorch, JAX, ...).

    Model Core, Training und Benchmark rufen nur diese Schnittstelle auf.
    Ein konkretes Backend (z. B. `TorchBackend`) übersetzt das auf die
    jeweilige Bibliothek. Dadurch bleibt der Wechsel Torch <-> JAX
    ohne Änderungen an der Kernlogik möglich.
    """

    name: str = "abstract"

    @abstractmethod
    def build_model(self, model_config, hardware_config) -> ShadowModel:
        ...

    @abstractmethod
    def is_available(self) -> bool:
        ...
