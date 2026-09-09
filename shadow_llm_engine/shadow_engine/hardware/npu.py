"""
NPU-Plugin-System für die Shadow-Hardware-Abstraktion.

Erweitert die Shadow Compute Layer um NPU-Unterstützung über ein
Plugin-System:

    Shadow Compute Layer
    ├── CPU
    ├── CUDA
    ├── ROCm
    ├── Metal
    ├── TPU
    └── NPU  <-- Apple Neural Engine / Intel OpenVINO+ NPU / AMD XDNA / ...

Jedes NPU-Plugin implementiert `NPUPlugin.detect()` und liefert eine Liste
erkannter `DeviceInfo`-Einträge. Plugins sind vendor-agnostisch registrierbar
und werden nur aktiv, wenn das jeweilige Vendor-SDK installiert ist
(graceful degradation -- fehlt das SDK, liefert das Plugin eine leere Liste).

Eingebaute Plugins:
    - AppleNeuralEnginePlugin  (Apple Silicon, Neural Engine)
    - IntelOpenVINOPlugin      (Intel NPU via OpenVINO)
    - AMDXDNAPlugin             (AMD NPU via XDNA/RYZEN AI)
    - GenericNPUPlugin          (Umgebungsvariable SHADOW_NPU_DEVICE)

Wichtig: Es erfolgt KEINE automatische Auswahl -- `detect_hardware()`
meldet lediglich verfügbare/kompatible Geräte mit Leistung/Speicher; der
Benutzer/Admin entscheidet über `select_devices(..., preferred_device=...)`,
welches Gerät genutzt wird.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import Optional

from shadow_engine.hardware.detector import DeviceInfo, DeviceType


class NPUPlugin(ABC):
    """Schnittstelle für vendor-spezifische NPU-Erkennung."""

    name: str = "generic"

    @property
    def available(self) -> bool:
        """True, wenn das Vendor-SDK installiert/verfügbar ist."""
        return False

    @property
    def compatible(self) -> bool:
        """True, wenn die Plattform kompatibel ist."""
        return True

    @abstractmethod
    def detect(self) -> list[DeviceInfo]:
        """Liefert erkannte NPU-Geräte (leer, falls keine/SDK fehlt)."""
        ...

    def describe(self) -> dict:
        return {
            "name": self.name,
            "available": self.available,
            "compatible": self.compatible,
        }


# ---------------------------------------------------------------------- #
# Apple Neural Engine
# ---------------------------------------------------------------------- #


class AppleNeuralEnginePlugin(NPUPlugin):
    """Apple Neural Engine (ANE) auf Apple Silicon."""

    name = "apple-neural-engine"

    @property
    def available(self) -> bool:
        return platform.system() == "Darwin" and platform.machine() == "arm64"

    @property
    def compatible(self) -> bool:
        return platform.system() == "Darwin"

    def detect(self) -> list[DeviceInfo]:
        if not self.available:
            return []
        # Der ANE ist auf allen Apple Silicon Macs vorhanden. Leistung und
        # Speicher sind vendor-seitig nicht direkt auslesbar; wir melden
        # ein Gerät mit Typ NPU und markieren die Quelle.
        return [DeviceInfo(
            device_type=DeviceType.NPU, index=0,
            name="Apple Neural Engine",
            memory_total_mb=None,
            extra={"source": "apple-silicon", "plugin": self.name,
                   "estimated_tops": 15.8},  # typisch M1, nur Hinweis
        )]


# ---------------------------------------------------------------------- #
# Intel OpenVINO / NPU
# ---------------------------------------------------------------------- #


class IntelOpenVINOPlugin(NPUPlugin):
    """Intel NPU über OpenVINO (falls `openvino` installiert ist)."""

    name = "intel-openvino"

    @property
    def available(self) -> bool:
        try:
            import openvino  # type: ignore
            return True
        except ImportError:
            return False

    @property
    def compatible(self) -> bool:
        return platform.processor().lower().startswith(("intel", "genuineintel")) or self.available

    def detect(self) -> list[DeviceInfo]:
        if not self.available:
            return []
        devices: list[DeviceInfo] = []
        try:
            from openvino import Core  # type: ignore
            core = Core()
            for i, dev_name in enumerate(core.available_devices):
                if "NPU" in dev_name or "CPU" == dev_name and False:
                    pass
                if "NPU" in dev_name:
                    devices.append(DeviceInfo(
                        device_type=DeviceType.NPU, index=i,
                        name=f"Intel NPU ({dev_name})",
                        extra={"source": "openvino", "plugin": self.name,
                               "device_name": dev_name},
                    ))
        except Exception:
            return []
        return devices


# ---------------------------------------------------------------------- #
# AMD XDNA
# ---------------------------------------------------------------------- #


class AMDXDNAPlugin(NPUPlugin):
    """AMD NPU über XDNA / Ryzen AI SDK (falls installiert oder Gerät vorhanden)."""

    name = "amd-xdna"

    @property
    def available(self) -> bool:
        # Prüfe auf XDNA-Geräte-Datei (Linux) oder amdxdna-Modul
        if os.path.exists("/dev/accel/accel0"):
            return True
        try:
            import importlib
            importlib.import_module("amdxdna")  # type: ignore
            return True
        except ImportError:
            return False

    @property
    def compatible(self) -> bool:
        return True

    def detect(self) -> list[DeviceInfo]:
        if not self.available:
            return []
        return [DeviceInfo(
            device_type=DeviceType.NPU, index=0,
            name="AMD XDNA NPU",
            extra={"source": "xdna", "plugin": self.name},
        )]


# ---------------------------------------------------------------------- #
# Generic / Umgebungsvariable
# ---------------------------------------------------------------------- #


class GenericNPUPlugin(NPUPlugin):
    """Fallback: NPU über Umgebungsvariable SHADOW_NPU_DEVICE."""

    name = "generic-env"

    @property
    def available(self) -> bool:
        return bool(os.environ.get("SHADOW_NPU_DEVICE"))

    def detect(self) -> list[DeviceInfo]:
        name = os.environ.get("SHADOW_NPU_DEVICE")
        if not name:
            return []
        mem = os.environ.get("SHADOW_NPU_MEMORY_MB")
        return [DeviceInfo(
            device_type=DeviceType.NPU, index=0,
            name=name,
            memory_total_mb=int(mem) if mem and mem.isdigit() else None,
            extra={"source": "env:SHADOW_NPU_DEVICE", "plugin": self.name},
        )]


# ---------------------------------------------------------------------- #
# Plugin-Registry
# ---------------------------------------------------------------------- #


class NPUPluginRegistry:
    """Registriert NPU-Plugins und sammelt deren Erkennungsergebnisse."""

    def __init__(self):
        self._plugins: list[NPUPlugin] = []
        self._register_defaults()

    def _register_defaults(self) -> None:
        for plugin_cls in (AppleNeuralEnginePlugin, IntelOpenVINOPlugin,
                           AMDXDNAPlugin, GenericNPUPlugin):
            self.register(plugin_cls())

    def register(self, plugin: NPUPlugin) -> NPUPlugin:
        self._plugins.append(plugin)
        return plugin

    def list_plugins(self) -> list[NPUPlugin]:
        return list(self._plugins)

    def detect_all(self) -> list[DeviceInfo]:
        """Fragt alle registrierten Plugins ab und liefert vereinigte NPU-Geräte."""
        devices: list[DeviceInfo] = []
        for plugin in self._plugins:
            try:
                found = plugin.detect()
            except Exception:
                continue
            if found:
                devices.extend(found)
        # Indexe eindeutig machen
        for i, d in enumerate(devices):
            d.index = i
        return devices

    def report(self) -> dict:
        return {"plugins": [p.describe() for p in self._plugins]}


# Modul-globaler Default-Registry (für HardwareDetector)
_default_registry: Optional[NPUPluginRegistry] = None


def get_default_registry() -> NPUPluginRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = NPUPluginRegistry()
    return _default_registry


def detect_npu_devices() -> list[DeviceInfo]:
    """Erkennt alle verfügbaren NPU-Geräte über die Plugin-Registry."""
    return get_default_registry().detect_all()
