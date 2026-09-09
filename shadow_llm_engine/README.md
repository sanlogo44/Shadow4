# Shadow LLM Engine

Eigenständige KI-Engine für das Shadow-Projekt — **vollständig getrennt von
der Shadow-Chat-Anwendung**. Die Chat-App kommuniziert ausschließlich über
die HTTP-Schnittstelle in `shadow_engine/api`, niemals direkt mit den
internen Modulen.

```
Shadow Chat  --HTTP-->  Shadow LLM API  -->  LLM Engine
```

## Architekturüberblick

```
shadow_engine/
├── model_core/     Architekturunabhängiges Modell-Protokoll + Referenz-
│                   Transformer (RoPE, RMSNorm, SwiGLU, KV-Cache)
├── tokenizer/      Eigener Byte-Level-BPE-Tokenizer (sprachunabhängig)
├── training/       Trainer, Checkpoints, Scheduler (Start/Stop/Pause/Plan)
├── dataset/        Reinigung, Duplikat-Erkennung, Qualitätsprüfung
├── benchmark/      Admin-only Benchmarks: Sprache/Logik/Code/Leistung
├── hardware/       Erkennung: CPU/CUDA/ROCm/Metal/TPU/NPU
├── registry/       Model Registry: speichern/laden/versionieren/rollback
├── agents/         Agent, Schwarm, Ziel-Agent (Vorbereitung)
├── nodes/          Master/Training/Inference/Storage-Node + TLS/Auth
└── api/            FastAPI-Schnittstelle für die Shadow-Chat-Anwendung
```

Kernprinzip: **kein Modul hängt hart von einer bestimmten Modellarchitektur
oder einem bestimmten Rechen-Backend ab.** Training, Registry, Benchmark und
API sprechen ausschließlich gegen das `ShadowModel`-Protokoll
(`model_core/base.py`). Neue Architekturen werden einfach in der
`ARCHITECTURE_REGISTRY` ergänzt.

## Installation

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# optional: JAX-Backend, TPU-Unterstützung
pip install -r requirements-optional.txt
```

Python ≥ 3.10 wird vorausgesetzt.

## Schnellstart

### 1. Konfiguration

```bash
cp config/engine.example.yaml config/engine.yaml
export SHADOW_ENGINE_CONFIG=./config/engine.yaml
```

### 2. Eigenes Modell von Null trainieren (Beispiel-Pipeline)

```bash
mkdir -p data/raw
echo "Dein Trainingstext hier..." > data/raw/beispiel.txt

python scripts/train.py --data-dir ./data/raw --namespace shadow-model
```

Das Skript durchläuft: **Rohdaten → Reinigung → Dedup → Qualitätsprüfung
→ Tokenizer-Training → Modellaufbau → Trainer-Initialisierung → Registry-
Speicherung** (`v0.1`).

### 3. Shadow LLM API starten

```bash
export SHADOW_ADMIN_TOKEN=dein-geheimes-token
python scripts/serve.py
# API läuft unter http://localhost:8420
```

Wichtige Endpunkte:

| Methode | Pfad                                   | Zweck                          |
|---------|-----------------------------------------|---------------------------------|
| POST    | `/v1/models/load`                       | Modellversion laden             |
| GET     | `/v1/models/{namespace}/versions`       | Versionen auflisten             |
| POST    | `/v1/models/{namespace}/rollback/{v}`   | Rollback (Admin)                |
| POST    | `/v1/generate`                          | Text generieren                 |
| POST    | `/v1/training/start\|pause\|resume\|stop` | Training steuern (Admin)      |
| POST    | `/v1/benchmark/start`                   | Benchmark starten (Admin)       |
| GET     | `/v1/hardware`                          | Hardware-Report                 |

Admin-Endpunkte erwarten den Header `X-Admin-Token: <SHADOW_ADMIN_TOKEN>`.

### 4. Cluster-Node-System testen (lokal)

```bash
python scripts/cluster_demo.py
```

Zeigt manuelles Hinzufügen von Training-/Inference-/Storage-Nodes zu einem
Master und eine einfache Job-Zuweisung.

## Tests

```bash
pip install pytest
pytest tests/ -v
```

Die Tests für Tokenizer, Dataset-Pipeline, Model Registry und Node-System
laufen ohne PyTorch/FastAPI (reine Python-Standardbibliothek + eigener
Code). Tests, die den Referenz-Transformer oder die API betreffen,
benötigen zusätzlich `torch` bzw. `fastapi`.

## Docker

```bash
# Lokale Entwicklung (CPU)
docker build -f docker/Dockerfile.dev -t shadow-llm-engine:dev .
docker run -p 8420:8420 -e SHADOW_ADMIN_TOKEN=dev-token shadow-llm-engine:dev

# Server mit NVIDIA-GPU
docker build -f docker/Dockerfile.server -t shadow-llm-engine:server .

# Mehr-Node-Simulation
cd docker && docker compose up
```

Für AMD-ROCm: Basis-Image in `Dockerfile.server` gegen ein
`rocm/pytorch:<tag>`-Image tauschen.

## Hardware-Abstraktion

`shadow_engine.hardware.detect_hardware()` erkennt automatisch:

- CPU (immer verfügbar, Fallback)
- NVIDIA-GPUs (CUDA)
- AMD-GPUs (ROCm, über Torch-ROCm-Build)
- Apple-Silicon (Metal/MPS)
- TPU (über `torch_xla` oder Umgebungsvariablen)
- NPU (vorbereitet, vendor-agnostisch über `SHADOW_NPU_DEVICE`)

`select_devices()` wählt anhand der Konfiguration (`hardware.preferred_device`,
`hardware.allow_multi_gpu`) die zu nutzenden Geräte aus — inklusive
Mehr-GPU- und gemischten GPU+NPU-Setups.

## Model Registry: Versionierung

```python
from shadow_engine.registry import ModelRegistry

registry = ModelRegistry()
registry.save("shadow-model", model, state_saver=...)      # -> v0.1
registry.save("shadow-model", model, state_saver=...)      # -> v0.2
registry.compare("shadow-model", "v0.1", "v0.2")             # Metrik-Diff
registry.rollback("shadow-model", "v0.1")                    # current -> v0.1
```

## Agent Framework (Vorbereitung)

```python
from shadow_engine.agents import Agent, Swarm, GoalAgent

agent = Agent("mein-agent", plan_fn, execute_fn)
task = agent.handle("Fasse den Bericht zusammen")

swarm = Swarm(plan_fn, execute_fn)
swarm.spawn(3)
result = swarm.dispatch(["Teilaufgabe A", "Teilaufgabe B", "Teilaufgabe C"])
```

`plan_fn`/`execute_fn` sind austauschbare Callbacks, die intern die
Shadow LLM API (`/v1/generate`) aufrufen — das Agent-Framework selbst
kennt kein konkretes Modell.

## Node-System (Cluster-Vorbereitung)

Rollen: **Master** (verwaltet Training/Modelle/Aufgaben), **Training**
(Berechnungen), **Inference** (Chat-Anfragen), **Storage** (Daten).
Nodes werden **manuell** über `MasterNode.register_node()` hinzugefügt —
kein Auto-Discovery. Kommunikation ist über `nodes/network.py`
TLS-verschlüsselt und HMAC-authentifiziert vorbereitet.

## Designprinzipien

1. **Architektur- und Backend-Unabhängigkeit** — alles läuft gegen
   Protokolle/Schnittstellen, nie gegen konkrete Klassen.
2. **Trennung von Trainings-Checkpoints und Modell-Registry** —
   Checkpoints sind interne Wiederaufnahme-Punkte, Registry-Einträge sind
   versionierte, auslieferbare Modelle.
3. **Admin-Gate für Benchmark und Training** — sicherheitsrelevante
   Operationen verlangen einen Admin-Kontext/Token.
4. **Keine harten Abhängigkeiten von optionalen Backends** — JAX/TPU-
   Pakete liegen in `requirements-optional.txt`, der Rest der Engine
   bleibt ohne sie lauffähig.

## Status / nächste Schritte

Dies ist ein vollständiges, lauffähiges **Grundgerüst** mit echter Logik
in jedem Modul (kein reiner Stub-Code), kein fertig trainiertes Modell.
Sinnvolle nächste Ausbaustufen:

- Realer `DataLoader` aus tokenisierten `.jsonl`-Daten für `ShadowTrainer.fit()`
- JAX-Backend-Implementierung von `ModelBackend` (siehe `model_core/base.py`)
- Verteiltes Training (DDP/FSDP) über die bestehende `HardwareConfig.distributed`
- Persistenter, authentifizierter RPC-Layer zwischen den Node-Rollen
  (aktuell sind Master/Nodes In-Process-Objekte; `nodes/network.py`
  liefert die Bausteine für echte Netzwerkkommunikation)
