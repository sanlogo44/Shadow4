"""
Demo: Cluster-Node-System (Master + Training + Inference + Storage Node),
manuell zusammengesteckt -- kein Auto-Discovery, wie spezifiziert.

Aufruf:
    python scripts/cluster_demo.py
"""

from shadow_engine.nodes import (
    MasterNode, TrainingNode, InferenceNode, StorageNode,
    NodeRole, JobType, NodeInfo,
)


def dummy_training(payload: dict) -> dict:
    return {"status": "trained", "steps": payload.get("max_steps", 0)}


def dummy_generate(payload: dict) -> str:
    return f"[dummy output for prompt: {payload.get('prompt', '')}]"


def main():
    master = MasterNode(host="127.0.0.1", port=7331)

    training_node = TrainingNode(host="127.0.0.1", port=7332, run_training_fn=dummy_training)
    inference_node = InferenceNode(host="127.0.0.1", port=7333, generate_fn=dummy_generate)
    storage_node = StorageNode(host="127.0.0.1", port=7334, storage_root="./cluster_storage")

    # Manuelles Hinzufügen der Nodes zum Master
    for node in (training_node, inference_node, storage_node):
        master.register_node(node.info)

    print("Cluster-Status nach Registrierung:")
    print(master.cluster_status())

    job = master.submit_job(JobType.INFERENCE, {"prompt": "Hallo Shadow!"})
    print(f"\nJob eingereicht: {job.job_id} -> zugewiesen an {job.assigned_node_id}")

    result = inference_node.execute_job(job.payload)
    master.report_job_result(job.job_id, result["success"], result.get("result"))

    print("\nCluster-Status nach Job-Ausführung:")
    print(master.cluster_status())


if __name__ == "__main__":
    main()
