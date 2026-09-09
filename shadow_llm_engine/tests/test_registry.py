import json

from shadow_engine.registry import ModelRegistry
from shadow_engine.config import RegistryConfig


class DummyModel:
    """Minimales Objekt, das den Registry-Ansprüchen genügt (kein Torch nötig)."""

    architecture = "dummy"

    def __init__(self, params=10):
        self._params = params

    def config_dict(self):
        return {"architecture": self.architecture, "params": self._params}

    def num_parameters(self):
        return self._params


def _saver(model, path):
    path.write_text(json.dumps({"params": model._params}))


def _loader(model, path):
    data = json.loads(path.read_text())
    model._params = data["params"]


def _builder(config_dict):
    return DummyModel(params=config_dict.get("params", 0))


def test_save_and_load_roundtrip(tmp_path):
    registry = ModelRegistry(RegistryConfig(root_dir=str(tmp_path)))
    model = DummyModel(params=42)

    entry = registry.save("test-model", model, state_saver=_saver, metrics={"loss": 1.23})
    assert entry.version == "v0.1"
    assert registry.current_version("test-model") == "v0.1"

    loaded_model, config_dict = registry.load("test-model", _loader, _builder)
    assert loaded_model._params == 42


def test_versioning_and_rollback(tmp_path):
    registry = ModelRegistry(RegistryConfig(root_dir=str(tmp_path)))
    m1 = DummyModel(params=10)
    m2 = DummyModel(params=20)

    registry.save("m", m1, state_saver=_saver, metrics={"loss": 2.0})
    registry.save("m", m2, state_saver=_saver, metrics={"loss": 1.0})

    versions = [v.version for v in registry.list_versions("m")]
    assert versions == ["v0.1", "v0.2"]
    assert registry.current_version("m") == "v0.2"

    diff = registry.compare("m", "v0.1", "v0.2")
    assert diff["metric_diff"]["loss"]["delta"] == -1.0

    registry.rollback("m", "v0.1")
    assert registry.current_version("m") == "v0.1"
