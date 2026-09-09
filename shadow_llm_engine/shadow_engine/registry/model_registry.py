"""
Model Registry: Speichern, Laden, Versionierung, Vergleich und Rollback
von Shadow-Modellen.

Layout auf der Platte:

    <root_dir>/<namespace>/
        manifest.json              (Liste aller Versionen, aktueller Pointer)
        v0.1/
            config.json
            weights.pt              (oder .safetensors / .npz je nach Backend)
            metrics.json
            metadata.json
        v0.2/
            ...
        v1.0/
            ...
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from shadow_engine.config import RegistryConfig


@dataclass
class ModelVersion:
    version: str
    created_at: str
    architecture: str
    num_parameters: int
    metrics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    parent_version: Optional[str] = None


class VersionError(Exception):
    pass


def _parse_semver(v: str) -> tuple[int, int]:
    v = v.lstrip("v")
    parts = v.split(".")
    major = int(parts[0]) if parts and parts[0].isdigit() else 0
    minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    return major, minor


class ModelRegistry:
    """
    Verwaltet versionierte Shadow-Modelle, unabhängig vom Rechen-Backend.

    Das Speichern der Gewichte selbst wird an eine `state_saver`/`state_loader`
    Callback delegiert, damit die Registry weder Torch noch JAX importieren
    muss (Architektur-Unabhängigkeit, siehe model_core.base).
    """

    def __init__(self, config: Optional[RegistryConfig] = None):
        self.config = config or RegistryConfig()
        self.root = Path(self.config.root_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    def _namespace_dir(self, namespace: str) -> Path:
        d = self.root / namespace
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _manifest_path(self, namespace: str) -> Path:
        return self._namespace_dir(namespace) / "manifest.json"

    def _read_manifest(self, namespace: str) -> dict:
        path = self._manifest_path(namespace)
        if not path.exists():
            return {"namespace": namespace, "current": None, "versions": []}
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_manifest(self, namespace: str, manifest: dict):
        self._manifest_path(namespace).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ------------------------------------------------------------------ #
    def list_versions(self, namespace: str) -> list[ModelVersion]:
        manifest = self._read_manifest(namespace)
        return [ModelVersion(**v) for v in manifest["versions"]]

    def current_version(self, namespace: str) -> Optional[str]:
        return self._read_manifest(namespace).get("current")

    def next_version(self, namespace: str, bump: str = "minor") -> str:
        """bump: 'minor' (v0.1 -> v0.2) oder 'major' (v0.2 -> v1.0)."""
        versions = self.list_versions(namespace)
        if not versions:
            return "v0.1"
        latest = max(versions, key=lambda v: _parse_semver(v.version))
        major, minor = _parse_semver(latest.version)
        if bump == "major":
            return f"v{major + 1}.0"
        return f"v{major}.{minor + 1}"

    # ------------------------------------------------------------------ #
    def save(
        self,
        namespace: str,
        model,
        state_saver,
        version: Optional[str] = None,
        bump: str = "minor",
        metrics: Optional[dict] = None,
        metadata: Optional[dict] = None,
        set_current: bool = True,
    ) -> ModelVersion:
        """
        Speichert eine neue Modellversion.

        `state_saver(model, weights_path)` ist ein Callback des jeweiligen
        Backends (z. B. `lambda m, p: torch.save(m.state_dict(), p)`).
        """
        version = version or self.next_version(namespace, bump=bump)
        version_dir = self._namespace_dir(namespace) / version
        if version_dir.exists():
            raise VersionError(f"Version {version} existiert bereits in '{namespace}'.")
        version_dir.mkdir(parents=True)

        weights_path = version_dir / "weights.bin"
        state_saver(model, weights_path)

        config_dict = model.config_dict() if hasattr(model, "config_dict") else {}
        (version_dir / "config.json").write_text(
            json.dumps(config_dict, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        entry = ModelVersion(
            version=version,
            created_at=datetime.now(timezone.utc).isoformat(),
            architecture=config_dict.get("architecture", "unknown"),
            num_parameters=model.num_parameters() if hasattr(model, "num_parameters") else 0,
            metrics=metrics or {},
            metadata=metadata or {},
            parent_version=self.current_version(namespace),
        )
        (version_dir / "metrics.json").write_text(json.dumps(entry.metrics, indent=2), encoding="utf-8")
        (version_dir / "metadata.json").write_text(json.dumps(entry.metadata, indent=2), encoding="utf-8")

        manifest = self._read_manifest(namespace)
        manifest["versions"].append(entry.__dict__)
        if set_current:
            manifest["current"] = version
        self._write_manifest(namespace, manifest)

        return entry

    def load(
        self,
        namespace: str,
        state_loader,
        build_model_fn,
        version: Optional[str] = None,
    ):
        """
        Lädt eine Modellversion.

        `build_model_fn(config_dict) -> ShadowModel` konstruiert ein leeres
        Modell aus der gespeicherten Architektur-Konfiguration.
        `state_loader(model, weights_path)` lädt die Gewichte hinein
        (Backend-Callback, z. B. `lambda m, p: m.load_state_dict(torch.load(p))`).
        """
        version = version or self.current_version(namespace)
        if version is None:
            raise VersionError(f"Keine Version für Namespace '{namespace}' vorhanden.")

        version_dir = self._namespace_dir(namespace) / version
        if not version_dir.exists():
            raise VersionError(f"Version {version} nicht gefunden in '{namespace}'.")

        config_dict = json.loads((version_dir / "config.json").read_text(encoding="utf-8"))
        model = build_model_fn(config_dict)
        state_loader(model, version_dir / "weights.bin")
        return model, config_dict

    # ------------------------------------------------------------------ #
    def compare(self, namespace: str, version_a: str, version_b: str) -> dict:
        """Vergleicht zwei Versionen anhand ihrer gespeicherten Metriken."""
        versions = {v.version: v for v in self.list_versions(namespace)}
        if version_a not in versions or version_b not in versions:
            raise VersionError("Eine der angegebenen Versionen existiert nicht.")
        a, b = versions[version_a], versions[version_b]

        all_keys = set(a.metrics) | set(b.metrics)
        diff = {}
        for k in sorted(all_keys):
            va, vb = a.metrics.get(k), b.metrics.get(k)
            delta = (vb - va) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else None
            diff[k] = {"a": va, "b": vb, "delta": delta}

        return {
            "namespace": namespace,
            "version_a": version_a,
            "version_b": version_b,
            "metric_diff": diff,
            "parameter_diff": b.num_parameters - a.num_parameters,
        }

    def rollback(self, namespace: str, to_version: str) -> ModelVersion:
        """Setzt den 'current'-Pointer der Registry auf eine frühere Version zurück."""
        versions = {v.version: v for v in self.list_versions(namespace)}
        if to_version not in versions:
            raise VersionError(f"Rollback fehlgeschlagen: Version {to_version} existiert nicht.")

        manifest = self._read_manifest(namespace)
        manifest["current"] = to_version
        self._write_manifest(namespace, manifest)
        return versions[to_version]

    def delete_version(self, namespace: str, version: str):
        version_dir = self._namespace_dir(namespace) / version
        if version_dir.exists():
            shutil.rmtree(version_dir)
        manifest = self._read_manifest(namespace)
        manifest["versions"] = [v for v in manifest["versions"] if v["version"] != version]
        if manifest.get("current") == version:
            manifest["current"] = manifest["versions"][-1]["version"] if manifest["versions"] else None
        self._write_manifest(namespace, manifest)
