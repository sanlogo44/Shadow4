"""Tests für Hardware/NPU-Erkennung (System 6): Plugin-System,
Auto-Detection, manuelle Auswahl, GPU/CPU/TPU/NPU."""

from __future__ import annotations

import os

import pytest

from shadow_engine.hardware import (
    AMDXDNAPlugin,
    AppleNeuralEnginePlugin,
    DeviceInfo,
    DeviceType,
    GenericNPUPlugin,
    HardwareDetector,
    HardwareReport,
    IntelOpenVINOPlugin,
    NPUPlugin,
    NPUPluginRegistry,
    detect_hardware,
    detect_npu_devices,
    get_default_registry,
    select_devices,
)


def test_detect_hardware_returns_report():
    report = detect_hardware()
    assert isinstance(report, HardwareReport)
    assert report.platform
    assert report.cpu_count >= 1


def test_npu_plugin_registry_defaults():
    reg = NPUPluginRegistry()
    names = [p.name for p in reg.list_plugins()]
    assert "apple-neural-engine" in names
    assert "intel-openvino" in names
    assert "amd-xdna" in names
    assert "generic-env" in names


def test_npu_plugins_compatible_check():
    assert AppleNeuralEnginePlugin().compatible in (True, False)
    assert AMDXDNAPlugin().available in (True, False)
    assert IntelOpenVINOPlugin().available in (True, False)


def test_generic_npu_plugin_env_detection(monkeypatch):
    monkeypatch.delenv("SHADOW_NPU_DEVICE", raising=False)
    assert GenericNPUPlugin().available is False
    assert GenericNPUPlugin().detect() == []
    monkeypatch.setenv("SHADOW_NPU_DEVICE", "TestNPU")
    monkeypatch.setenv("SHADOW_NPU_MEMORY_MB", "2048")
    devices = GenericNPUPlugin().detect()
    assert len(devices) == 1
    assert devices[0].device_type == DeviceType.NPU
    assert devices[0].name == "TestNPU"
    assert devices[0].memory_total_mb == 2048


def test_custom_npu_plugin_registration():
    class MyNPU(NPUPlugin):
        name = "my-npu"

        @property
        def available(self):
            return True

        def detect(self):
            return [DeviceInfo(device_type=DeviceType.NPU, index=0, name="My NPU",
                               extra={"tops": 11})]

    reg = NPUPluginRegistry()
    reg.register(MyNPU())
    devices = reg.detect_all()
    assert any(d.name == "My NPU" for d in devices)


def test_detect_npu_devices_empty_without_sdk(monkeypatch):
    monkeypatch.delenv("SHADOW_NPU_DEVICE", raising=False)
    # ohne Vendor-SDK und ohne Env -> keine NPU-Geräte
    devices = detect_npu_devices()
    assert devices == []


def test_select_devices_manual_cpu():
    report = detect_hardware()
    # explizite CPU-Auswahl durch Admin
    selected = select_devices(report, preferred_device="cpu", allow_multi_gpu=False)
    assert all(d.device_type == DeviceType.CPU for d in selected)


def test_select_devices_auto_falls_back_to_cpu():
    report = HardwareReport(platform="test", cpu_count=2, devices=[])
    selected = select_devices(report, preferred_device="auto")
    assert selected[0].device_type == DeviceType.CPU


def test_hardware_report_summary():
    report = HardwareReport(platform="Linux", cpu_count=4, devices=[
        DeviceInfo(device_type=DeviceType.CPU, index=0, name="CPU"),
    ])
    s = report.summary()
    assert "Linux" in s
    assert "CPU" in s


def test_device_type_enum_values():
    assert DeviceType.CPU.value == "cpu"
    assert DeviceType.CUDA.value == "cuda"
    assert DeviceType.NPU.value == "npu"
    assert DeviceType.TPU.value == "tpu"
