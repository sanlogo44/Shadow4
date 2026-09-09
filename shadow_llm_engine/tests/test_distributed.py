"""Tests für verteiltes Training (System 2): Worker-Registrierung,
Synchronisation, Fehlererkennung, Checkpoint-Verteilung, ZeRO-Sharding.
Läuft ohne GPUs (SimulatedDistributedBackend)."""

from __future__ import annotations

import pytest

from shadow_engine.training.distributed import (
    DistributedConfig,
    DistributedRunner,
    ShardingStrategy,
    SimulatedDistributedBackend,
    WorkerInfo,
    WorkerRegistry,
    ZeroOptimizer,
    ReduceOp,
    FaultToleranceError,
    get_backend,
)


def test_simulated_backend_init_barrier_destroy():
    backend = SimulatedDistributedBackend()
    assert backend.is_initialized is False
    backend.init(rank=0, world_size=2)
    assert backend.is_initialized is True
    backend.barrier()
    backend.all_reduce([1, 2, 3], op=ReduceOp.SUM)
    backend.broadcast("x", src=0)
    backend.destroy()
    assert backend.is_initialized is False
    assert any("barrier" in op for op in backend._ops)  # Barrier wurde ausgeführt


def test_worker_registry_register_and_list():
    reg = WorkerRegistry()
    for r in range(3):
        reg.register(WorkerInfo(rank=r, world_size=3))
    assert len(reg.list_workers()) == 3
    assert reg.list_workers()[0].status == "online"


def test_worker_registry_detect_failures():
    reg = WorkerRegistry()
    for r in range(3):
        reg.register(WorkerInfo(rank=r, world_size=3))
    # kurzer Timeout -> alle ohne Herzschlag gelten als verloren
    lost = reg.detect_failures(timeout=0.0)
    assert sorted(lost) == [0, 1, 2]


def test_distributed_runner_setup_and_sync():
    cfg = DistributedConfig(world_size=2, rank=0, strategy=ShardingStrategy.DDP)
    runner = DistributedRunner(cfg)
    runner.setup()
    assert runner.backend.is_initialized
    runner.synchronize()
    runner.teardown()
    assert runner.backend.is_initialized is False


def test_runner_synchronize_raises_when_not_initialized():
    runner = DistributedRunner(DistributedConfig())
    with pytest.raises(FaultToleranceError):
        runner.synchronize()


def test_zero_optimizer_sharding():
    params = list(range(100))
    zo0 = ZeroOptimizer(params, ShardingStrategy.ZERO_3, rank=0, world_size=3)
    zo1 = ZeroOptimizer(params, ShardingStrategy.ZERO_3, rank=1, world_size=3)
    zo2 = ZeroOptimizer(params, ShardingStrategy.ZERO_3, rank=2, world_size=3)
    # Shards sind disjunkt und überdecken alle Parameter
    all_ids = set(zo0.shard) | set(zo1.shard) | set(zo2.shard)
    assert all_ids == set(params)
    assert zo0.shard_size + zo1.shard_size + zo2.shard_size == 100


def test_zero_optimizer_no_shard_for_zero1():
    zo = ZeroOptimizer(list(range(10)), ShardingStrategy.ZERO_1, rank=0, world_size=4)
    assert zo.shard_size == 10  # Stage 1 sharded nur Optimizer-State, nicht Params


def test_checkpoint_distribution_broadcast():
    runner = DistributedRunner(DistributedConfig(world_size=2, rank=0))
    runner.setup()
    state = {"weights": "shard0"}
    result = runner.broadcast_checkpoint(state, src=0)
    assert result == state
    assert len(runner._checkpoint_history) == 1
    runner.teardown()


def test_distributed_checkpoint_saved_to_disk(tmp_path):
    cfg = DistributedConfig(world_size=2, rank=1, checkpoint_dir=str(tmp_path))
    runner = DistributedRunner(cfg)
    runner.setup()
    path = runner.save_distributed_checkpoint({"step": 5}, step=5)
    assert path.exists()
    assert "rank1" in path.name
    runner.teardown()


def test_get_backend_returns_simulated_without_torch():
    backend = get_backend(prefer_torch=False)
    assert isinstance(backend, SimulatedDistributedBackend)


def test_train_step_runs_with_simulation():
    cfg = DistributedConfig(world_size=2, rank=0, strategy=ShardingStrategy.DDP)
    runner = DistributedRunner(cfg)
    runner.setup()

    class FakeModel:
        def backward(self, loss):
            return None

    def forward_fn(model, batch):
        return batch.get("loss", 0.5)

    result = runner.train_step(FakeModel(), optimizer=None, batch={"loss": 0.5}, forward_fn=forward_fn)
    assert result["rank"] == 0
    assert result["world_size"] == 2
    runner.teardown()
