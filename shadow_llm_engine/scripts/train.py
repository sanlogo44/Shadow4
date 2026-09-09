"""
Beispiel-Skript: vollständiger Ablauf "von Null" --

    Rohdaten -> Dataset-Pipeline -> Tokenizer trainieren
             -> Modell bauen -> Trainer -> Checkpoint -> Registry speichern

Aufruf:
    python scripts/train.py --data-dir ./data/raw --namespace shadow-model
"""

from __future__ import annotations

import argparse
from pathlib import Path

from shadow_engine.config import load_config
from shadow_engine.dataset import DatasetManager, LocalDirectorySource
from shadow_engine.tokenizer import ShadowTokenizer
from shadow_engine.model_core.architecture import build_model
from shadow_engine.training import ShadowTrainer
from shadow_engine.registry import ModelRegistry
from shadow_engine.hardware import detect_hardware, select_devices


def main():
    parser = argparse.ArgumentParser(description="Shadow LLM Engine -- Trainings-Beispiel")
    parser.add_argument("--data-dir", type=str, default="./data/raw")
    parser.add_argument("--namespace", type=str, default="shadow-model")
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--max-steps", type=int, default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.max_steps:
        cfg.training.max_steps = args.max_steps

    # 1. Hardware erkennen
    hw_report = detect_hardware()
    print(hw_report.summary())
    devices = select_devices(hw_report, cfg.hardware.preferred_device, cfg.hardware.allow_multi_gpu)
    device_str = devices[0].torch_device_string if devices else "cpu"
    print(f"Verwende Device: {device_str}")

    # 2. Datenpipeline
    dataset_mgr = DatasetManager(cfg.dataset)
    source = LocalDirectorySource(args.data_dir)
    stats = dataset_mgr.run_pipeline([source])
    print(f"Datenpipeline: {stats.to_dict()}")

    # 3. Tokenizer trainieren
    tokenizer = ShadowTokenizer(cfg.tokenizer)
    tokenizer.train(dataset_mgr.iter_clean_documents(), verbose=True)
    tokenizer_path = Path(cfg.dataset.tokenized_dir) / "tokenizer.json"
    tokenizer.save(tokenizer_path)
    print(f"Tokenizer gespeichert unter {tokenizer_path} (vocab_size={tokenizer.vocab_size})")

    # 4. Modell von Null bauen
    cfg.model_core.vocab_size = tokenizer.vocab_size
    model = build_model(cfg.model_core, name=args.namespace)
    print(f"Modell gebaut: {model.num_parameters():,} Parameter")

    # 5. Trainer starten (Platzhalter-DataLoader für dieses Beispiel)
    trainer = ShadowTrainer(model, cfg.training, device=device_str)
    print(
        "Trainer bereit. Für einen echten Lauf einen DataLoader aus den "
        "tokenisierten Daten erstellen und `trainer.fit(train_loader)` aufrufen."
    )

    # 6. In der Model Registry speichern (Beispiel mit frisch initialisierten Gewichten)
    import torch
    registry = ModelRegistry(cfg.registry)
    entry = registry.save(
        args.namespace, model,
        state_saver=lambda m, p: torch.save(m.state_dict(), p),
        metrics={"initial": True},
        metadata={"note": "frisch initialisiert, noch nicht trainiert"},
    )
    print(f"In Registry gespeichert: {args.namespace} {entry.version}")


if __name__ == "__main__":
    main()
