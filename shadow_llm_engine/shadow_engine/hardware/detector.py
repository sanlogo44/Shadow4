"""
Hardware Manager: erkennt verfügbare Rechen-Hardware und stellt eine
einheitliche `DeviceHandle`-Abstraktion bereit, unabhängig davon, ob
am Ende PyTorch, JAX oder ein anderes Backend rechnet.

Erkennt:
    - CPU (immer verfügbar)
    - NVIDIA GPUs über CUDA
    - AMD GPUs über ROCm (via PyTorch-ROCm-Build, das intern ebenfalls
      die CUDA-API von Torch nutzt)
    - Apple Silicon über Metal (MPS)
    - TPU (über torch_xla / JAX, falls installiert)
    - NPU (Platzhalter-Erkennung für zukünftige Backends, z. B. über
      Umgebungsvariablen oder Vendor-SDKs)

Unterstützt außerdem:
    - mehrere GPUs
    - GPU + NPU gemischt
    - verteilte Hardware (Cluster, siehe shadow_engine.nodes)
"""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DeviceType(str, Enum):
    CPU = "cpu"
    CUDA = "cuda"       # NVIDIA
    ROCM = "rocm"        # AMD
    MPS = "mps"          # Apple Metal
    TPU = "tpu"
    NPU = "npu"


@dataclass
class DeviceInfo:
    device_type: DeviceType
    index: int
    name: str
    memory_total_mb: Optional[int] = None
    extra: dict = field(default_factory=dict)

    @property
    def torch_device_string(self) -> str:
        if self.device_type in (DeviceType.CUDA, DeviceType.ROCM):
            return f"cuda:{self.index}"
        if self.device_type == DeviceType.MPS:
            return "mps"
        if self.device_type == DeviceType.CPU:
            return "cpu"
        return str(self.device_type.value)


@dataclass
class HardwareReport:
    platform: str
    cpu_count: int
    devices: list[DeviceInfo] = field(default_factory=list)

    @property
    def has_gpu(self) -> bool:
        return any(d.device_type in (DeviceType.CUDA, DeviceType.ROCM, DeviceType.MPS) for d in self.devices)

    @property
    def has_accelerator(self) -> bool:
        return self.has_gpu or any(
            d.device_type in (DeviceType.TPU, DeviceType.NPU) for d in self.devices
        )

    def summary(self) -> str:
        lines = [f"Plattform: {self.platform} | CPUs: {self.cpu_count}"]
        if not self.devices:
            lines.append("  Keine Beschleuniger erkannt -- Fallback auf CPU.")
        for d in self.devices:
            mem = f"{d.memory_total_mb} MB" if d.memory_total_mb else "unbekannt"
            lines.append(f"  [{d.device_type.value}:{d.index}] {d.name} (Speicher: {mem})")
        return "\n".join(lines)


class HardwareDetector:
    """Führt die eigentliche Erkennung durch. Keine harte Abhängigkeit von Torch/JAX."""

    def detect(self) -> HardwareReport:
        report = HardwareReport(platform=platform.platform(), cpu_count=os.cpu_count() or 1)

        report.devices.extend(self._detect_cuda_or_rocm())
        report.devices.extend(self._detect_mps())
        report.devices.extend(self._detect_tpu())
        report.devices.extend(self._detect_npu())

        return report

    # ------------------------------------------------------------------ #
    def _detect_cuda_or_rocm(self) -> list[DeviceInfo]:
        devices: list[DeviceInfo] = []
        try:
            import torch
            if torch.cuda.is_available():
                is_rocm = bool(getattr(torch.version, "hip", None))
                dtype = DeviceType.ROCM if is_rocm else DeviceType.CUDA
                for i in range(torch.cuda.device_count()):
                    props = torch.cuda.get_device_properties(i)
                    devices.append(DeviceInfo(
                        device_type=dtype,
                        index=i,
                        name=props.name,
                        memory_total_mb=int(props.total_memory / (1024 ** 2)),
                    ))
                return devices
        except ImportError:
            pass

        # Fallback ohne Torch: nvidia-smi abfragen (nur Erkennung, kein Compute)
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3,
            )
            if out.returncode == 0:
                for i, line in enumerate(out.stdout.strip().splitlines()):
                    name, mem = [x.strip() for x in line.split(",")]
                    devices.append(DeviceInfo(
                        device_type=DeviceType.CUDA, index=i, name=name, memory_total_mb=int(mem)
                    ))
        except (FileNotFoundError, subprocess.SubprocessError):
            pass

        return devices

    def _detect_mps(self) -> list[DeviceInfo]:
        if platform.system() != "Darwin":
            return []
        try:
            import torch
            if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                return [DeviceInfo(device_type=DeviceType.MPS, index=0, name="Apple Metal GPU")]
        except ImportError:
            pass
        return []

    def _detect_tpu(self) -> list[DeviceInfo]:
        devices: list[DeviceInfo] = []
        if os.environ.get("TPU_NAME") or os.environ.get("COLAB_TPU_ADDR"):
            devices.append(DeviceInfo(device_type=DeviceType.TPU, index=0, name="TPU (env-detected)"))
            return devices
        try:
            import torch_xla.core.xla_model as xm  # type: ignore
            devices.append(DeviceInfo(device_type=DeviceType.TPU, index=0, name=str(xm.xla_device())))
        except ImportError:
            pass
        return devices

    def _detect_npu(self) -> list[DeviceInfo]:
        """
        Vorbereitete, aber vendor-agnostische NPU-Erkennung. Konkrete
        Vendor-SDKs (z. B. Ascend CANN, Intel NPU, Qualcomm QNN) werden
        hier als optionale Plugins registriert, sobald verfügbar.
        """
        devices: list[DeviceInfo] = []
        if os.environ.get("SHADOW_NPU_DEVICE"):
            devices.append(DeviceInfo(
                device_type=DeviceType.NPU, index=0,
                name=os.environ["SHADOW_NPU_DEVICE"],
                extra={"source": "env:SHADOW_NPU_DEVICE"},
            ))
        return devices


def detect_hardware() -> HardwareReport:
    return HardwareDetector().detect()


def select_devices(
    report: HardwareReport,
    preferred_device: str = "auto",
    allow_multi_gpu: bool = True,
) -> list[DeviceInfo]:
    """Wählt anhand der Config und des Reports die zu nutzenden Devices aus."""
    if preferred_device != "auto":
        matches = [d for d in report.devices if d.device_type.value == preferred_device]
        return matches if allow_multi_gpu else matches[:1]

    if report.has_accelerator:
        best_type = next(
            (t for t in (DeviceType.CUDA, DeviceType.ROCM, DeviceType.MPS, DeviceType.TPU, DeviceType.NPU)
             if any(d.device_type == t for d in report.devices)),
            None,
        )
        matches = [d for d in report.devices if d.device_type == best_type]
        return matches if allow_multi_gpu else matches[:1]

    return [DeviceInfo(device_type=DeviceType.CPU, index=0, name=platform.processor() or "CPU")]
