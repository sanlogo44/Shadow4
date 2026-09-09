from shadow_engine.nodes import MasterNode, TrainingNode, InferenceNode, JobType, NodeStatus


def test_master_manual_registration_and_job_assignment():
    master = MasterNode(host="127.0.0.1", port=7331)
    inference_node = InferenceNode(
        host="127.0.0.1", port=7333, generate_fn=lambda p: f"echo:{p['prompt']}"
    )

    master.register_node(inference_node.info)
    assert inference_node.info.node_id in master.nodes

    job = master.submit_job(JobType.INFERENCE, {"prompt": "hi"})
    assert job.assigned_node_id == inference_node.info.node_id

    result = inference_node.execute_job(job.payload)
    assert result["success"] is True
    master.report_job_result(job.job_id, True, result["result"])
    assert master.jobs[job.job_id].status.value == "done"


def test_job_queued_without_matching_node():
    master = MasterNode(host="127.0.0.1", port=7331)
    job = master.submit_job(JobType.TRAINING, {"max_steps": 100})
    assert job.status.value == "queued"
    assert job.assigned_node_id is None

    training_node = TrainingNode(host="127.0.0.1", port=7332, run_training_fn=lambda p: {"ok": True})
    master.register_node(training_node.info)
    master.retry_queued_jobs()
    assert job.status.value == "assigned"
