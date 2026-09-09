"""
Shadow LLM API -- die einzige Schnittstelle zwischen der Shadow-Chat-
Anwendung und der LLM Engine:

    Shadow Chat  ->  Shadow LLM API  ->  LLM Engine

Die Chat-Anwendung kennt NUR diese HTTP-API, niemals die internen
Module (model_core, training, registry, ...) direkt. Das erfüllt die
Anforderung "vollständig getrennt von der Chat-Anwendung".

Funktionen:
    POST /v1/generate           Text generieren
    POST /v1/models/load        Modell laden (Registry -> Speicher)
    GET  /v1/models/{namespace}/versions   Versionen auflisten
    POST /v1/training/start     Training starten
    POST /v1/training/pause     Training pausieren
    POST /v1/training/resume    Training fortsetzen
    POST /v1/training/stop      Training stoppen
    POST /v1/benchmark/start    Benchmark starten (Admin-only)
    GET  /v1/hardware           Hardware-Report
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Header

from shadow_engine.api.schemas import (
    GenerateRequest, GenerateResponse, LoadModelRequest,
    TrainingStartRequest, TrainingControlResponse,
    BenchmarkStartRequest, RegistryVersionResponse,
)
from shadow_engine.config import EngineConfig, load_config
from shadow_engine.registry import ModelRegistry
from shadow_engine.hardware import detect_hardware
from shadow_engine.training import TrainingScheduler
from shadow_engine.benchmark import BenchmarkRunner, AdminContext, DEFAULT_SUITES, NotAuthorizedError

try:
    import torch
    from shadow_engine.model_core import build_model, GenerationConfig
    from shadow_engine.model_core.architecture import ModelCoreConfig
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False


class EngineState:
    """Hält den In-Memory-Zustand der Engine (geladenes Modell, Scheduler, etc.)."""

    def __init__(self, config: EngineConfig):
        self.config = config
        self.registry = ModelRegistry(config.registry)
        self.scheduler = TrainingScheduler()
        self.benchmark_runner = BenchmarkRunner(DEFAULT_SUITES)
        self.loaded_model = None
        self.loaded_namespace: Optional[str] = None
        self.loaded_version: Optional[str] = None
        self.tokenizer = None


def create_app(config: Optional[EngineConfig] = None) -> FastAPI:
    config = config or load_config()
    state = EngineState(config)
    app = FastAPI(title="Shadow LLM API", version="0.1.0")

    def _require_admin(x_admin_token: str = Header(default="")):
        expected = os.environ.get(config.api.admin_token_env, "")
        if not expected or x_admin_token != expected:
            raise HTTPException(status_code=403, detail="Admin-Token ungültig oder fehlend.")
        return AdminContext(admin_id="admin", is_admin=True)

    # ------------------------------------------------------------------ #
    @app.get("/v1/health")
    def health():
        return {"status": "ok"}

    @app.get("/v1/hardware")
    def hardware():
        report = detect_hardware()
        return {
            "platform": report.platform,
            "cpu_count": report.cpu_count,
            "has_gpu": report.has_gpu,
            "devices": [d.__dict__ for d in report.devices],
        }

    # ------------------------------------------------------------------ #
    # Modellverwaltung
    # ------------------------------------------------------------------ #
    @app.post("/v1/models/load")
    def load_model(req: LoadModelRequest):
        if not _TORCH_AVAILABLE:
            raise HTTPException(status_code=500, detail="PyTorch nicht installiert.")

        def build_model_fn(config_dict: dict):
            model_cfg = ModelCoreConfig(**{
                k: v for k, v in config_dict.items()
                if k in ModelCoreConfig.__dataclass_fields__
            })
            return build_model(model_cfg, name=config_dict.get("name", req.namespace))

        def state_loader(model, path):
            model.load_state_dict(torch.load(path, map_location="cpu"))

        try:
            model, config_dict = state.registry.load(
                req.namespace, state_loader, build_model_fn, version=req.version
            )
        except Exception as e:
            raise HTTPException(status_code=404, detail=str(e))

        state.loaded_model = model
        state.loaded_namespace = req.namespace
        state.loaded_version = config_dict.get("version") or state.registry.current_version(req.namespace)
        return {"status": "loaded", "namespace": req.namespace, "version": state.loaded_version}

    @app.get("/v1/models/{namespace}/versions", response_model=list[RegistryVersionResponse])
    def list_versions(namespace: str):
        versions = state.registry.list_versions(namespace)
        return [
            RegistryVersionResponse(
                version=v.version, created_at=v.created_at, architecture=v.architecture,
                num_parameters=v.num_parameters, metrics=v.metrics, parent_version=v.parent_version,
            )
            for v in versions
        ]

    @app.post("/v1/models/{namespace}/rollback/{version}")
    def rollback(namespace: str, version: str, _admin: AdminContext = Depends(_require_admin)):
        try:
            entry = state.registry.rollback(namespace, version)
        except Exception as e:
            raise HTTPException(status_code=404, detail=str(e))
        return {"status": "rolled_back", "current_version": entry.version}

    # ------------------------------------------------------------------ #
    # Text-Generierung
    # ------------------------------------------------------------------ #
    @app.post("/v1/generate", response_model=GenerateResponse)
    def generate(req: GenerateRequest):
        if state.loaded_model is None or state.tokenizer is None:
            raise HTTPException(
                status_code=400,
                detail="Kein Modell/Tokenizer geladen. Zuerst /v1/models/load aufrufen.",
            )

        gen_cfg = GenerationConfig(
            max_new_tokens=req.max_new_tokens, temperature=req.temperature,
            top_p=req.top_p, top_k=req.top_k,
        )
        input_ids = torch.tensor([state.tokenizer.encode(req.prompt)])
        output_ids = state.loaded_model.generate(input_ids, gen_cfg)
        text = state.tokenizer.decode(output_ids[0].tolist())

        return GenerateResponse(
            text=text, namespace=state.loaded_namespace or "", version=state.loaded_version or ""
        )

    # ------------------------------------------------------------------ #
    # Training
    # ------------------------------------------------------------------ #
    @app.post("/v1/training/start", response_model=TrainingControlResponse)
    def start_training(req: TrainingStartRequest, _admin: AdminContext = Depends(_require_admin)):
        # Der eigentliche train_fn wird hier bewusst nur skizziert -- er
        # verdrahtet DatasetManager -> Tokenizer -> ShadowTrainer und wird
        # in scripts/train.py konkretisiert, um die API-Schicht schlank
        # und unabhängig von einer konkreten Trainings-Konfiguration zu halten.
        def train_fn():
            raise NotImplementedError(
                "Trainingslogik ist in scripts/train.py zu konfigurieren "
                "und hier als Callback einzuhängen."
            )

        try:
            state.scheduler.start(train_fn)
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))
        return TrainingControlResponse(state=state.scheduler.state.value, detail="Training gestartet.")

    @app.post("/v1/training/pause", response_model=TrainingControlResponse)
    def pause_training(_admin: AdminContext = Depends(_require_admin)):
        try:
            state.scheduler.pause()
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))
        return TrainingControlResponse(state=state.scheduler.state.value)

    @app.post("/v1/training/resume", response_model=TrainingControlResponse)
    def resume_training(_admin: AdminContext = Depends(_require_admin)):
        try:
            state.scheduler.resume()
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))
        return TrainingControlResponse(state=state.scheduler.state.value)

    @app.post("/v1/training/stop", response_model=TrainingControlResponse)
    def stop_training(_admin: AdminContext = Depends(_require_admin)):
        try:
            state.scheduler.stop()
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))
        return TrainingControlResponse(state=state.scheduler.state.value)

    @app.get("/v1/training/status")
    def training_status():
        return state.scheduler.status()

    # ------------------------------------------------------------------ #
    # Benchmark (Admin-only)
    # ------------------------------------------------------------------ #
    @app.post("/v1/benchmark/start")
    def start_benchmark(req: BenchmarkStartRequest, admin: AdminContext = Depends(_require_admin)):
        if state.loaded_model is None or state.tokenizer is None:
            raise HTTPException(status_code=400, detail="Kein Modell geladen.")

        def generate_fn(prompt: str) -> str:
            gen_cfg = GenerationConfig(max_new_tokens=64)
            input_ids = torch.tensor([state.tokenizer.encode(prompt)])
            output_ids = state.loaded_model.generate(input_ids, gen_cfg)
            return state.tokenizer.decode(output_ids[0].tolist())

        try:
            report = state.benchmark_runner.run(
                admin, generate_fn, req.namespace, req.version or "unknown", req.categories
            )
        except NotAuthorizedError as e:
            raise HTTPException(status_code=403, detail=str(e))

        return report.to_dict()

    @app.get("/v1/benchmark/{namespace}/history")
    def benchmark_history(namespace: str, _admin: AdminContext = Depends(_require_admin)):
        return state.benchmark_runner.history(namespace)

    return app


# Für `uvicorn shadow_engine.api.server:app`
app = create_app()
