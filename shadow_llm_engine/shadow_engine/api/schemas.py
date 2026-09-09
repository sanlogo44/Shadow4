"""Pydantic-Schemas für die Shadow LLM API."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    prompt: str
    namespace: str = "shadow-model"
    version: Optional[str] = None
    max_new_tokens: int = 256
    temperature: float = 0.8
    top_p: float = 0.95
    top_k: int = 50


class GenerateResponse(BaseModel):
    text: str
    namespace: str
    version: str


class LoadModelRequest(BaseModel):
    namespace: str
    version: Optional[str] = None


class TrainingStartRequest(BaseModel):
    namespace: str = "shadow-model"
    dataset_path: str
    max_steps: Optional[int] = None
    resume: bool = True


class TrainingControlResponse(BaseModel):
    state: str
    detail: str = ""


class BenchmarkStartRequest(BaseModel):
    namespace: str
    version: Optional[str] = None
    categories: Optional[list[str]] = None
    admin_token: str = Field(..., description="Admin-Token, erforderlich für Benchmark-Zugriff.")


class RegistryVersionResponse(BaseModel):
    version: str
    created_at: str
    architecture: str
    num_parameters: int
    metrics: dict
    parent_version: Optional[str] = None
