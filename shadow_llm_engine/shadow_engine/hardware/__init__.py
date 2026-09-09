from shadow_engine.hardware.detector import (
    HardwareDetector,
    HardwareReport,
    DeviceInfo,
    DeviceType,
    detect_hardware,
    select_devices,
)
from shadow_engine.hardware.npu import (
    NPUPlugin,
    NPUPluginRegistry,
    AppleNeuralEnginePlugin,
    IntelOpenVINOPlugin,
    AMDXDNAPlugin,
    GenericNPUPlugin,
    get_default_registry,
    detect_npu_devices,
)

__all__ = [
    "HardwareDetector", "HardwareReport", "DeviceInfo", "DeviceType",
    "detect_hardware", "select_devices",
    # NPU plugin system
    "NPUPlugin", "NPUPluginRegistry",
    "AppleNeuralEnginePlugin", "IntelOpenVINOPlugin", "AMDXDNAPlugin",
    "GenericNPUPlugin", "get_default_registry", "detect_npu_devices",
]
