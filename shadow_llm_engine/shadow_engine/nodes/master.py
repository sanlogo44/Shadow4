"""
Master Node: verwaltet Training, Modelle und Aufgaben im Cluster.

Nodes werden manuell über `register_node()` hinzugefügt (kein
Auto-Discovery), wie in der Spezifikation gefordert. Der Master
verteilt Aufgaben (Trainingsjobs, Inferenz-Requests) an passende Nodes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from shadow_engine.nodes.base import BaseNode, NodeInfo, NodeRole, NodeStatus


class JobType(str, Enum):
    TRAINING = "training"
    INFERENCE = "inference"
    STORAGE = "storage"


class JobStatus(str, Enum):
    QUEUED = "queued"
    ASSIGNED = "assigned"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Job:
    job_id: str
    job_type: JobType
    payload: dict
    status: JobStatus = JobStatus.QUEUED
    assigned_node_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    result: Optional[dict] = None


class MasterNode(BaseNode):
    role = NodeRole.MASTER

    def __init__(self, host: str, port: int, node_id: Optional[str] = None):
        super().__init__(host, port, node_id)
        self.nodes: dict[str, NodeInfo] = {}
        self.jobs: dict[str, Job] = {}

    # ------------------------------------------------------------------ #
    # Node-Verwaltung (manuelles Hinzufügen, kein Auto-Discovery)
    # ------------------------------------------------------------------ #
    def register_node(self, node_info: NodeInfo) -> NodeInfo:
        node_info.status = NodeStatus.ONLINE
        node_info.last_heartbeat = datetime.now(timezone.utc).isoformat()
        self.nodes[node_info.node_id] = node_info
        return node_info

    def deregister_node(self, node_id: str):
        self.nodes.pop(node_id, None)
        # Laufende Jobs dieses Nodes werden als fehlgeschlagen markiert.
        for job in self.jobs.values():
            if job.assigned_node_id == node_id and job.status in (JobStatus.ASSIGNED, JobStatus.RUNNING):
                job.status = JobStatus.FAILED

    def nodes_by_role(self, role: NodeRole) -> list[NodeInfo]:
        return [n for n in self.nodes.values() if n.role == role and n.status == NodeStatus.ONLINE]

    def mark_heartbeat(self, node_id: str):
        if node_id in self.nodes:
            self.nodes[node_id].last_heartbeat = datetime.now(timezone.utc).isoformat()
            self.nodes[node_id].status = NodeStatus.ONLINE

    # ------------------------------------------------------------------ #
    # Job-Verwaltung
    # ------------------------------------------------------------------ #
    _ROLE_FOR_JOB = {
        JobType.TRAINING: NodeRole.TRAINING,
        JobType.INFERENCE: NodeRole.INFERENCE,
        JobType.STORAGE: NodeRole.STORAGE,
    }

    def submit_job(self, job_type: JobType, payload: dict) -> Job:
        job = Job(job_id=str(uuid.uuid4()), job_type=job_type, payload=payload)
        self.jobs[job.job_id] = job
        self._assign_job(job)
        return job

    def _assign_job(self, job: Job):
        required_role = self._ROLE_FOR_JOB[job.job_type]
        candidates = self.nodes_by_role(required_role)
        if not candidates:
            return  # bleibt QUEUED, bis ein passender Node verfügbar ist
        # Einfache Strategie: erster verfügbarer Node (round-robin/least-load
        # lässt sich hier später ergänzen, ohne die Schnittstelle zu ändern).
        chosen = candidates[0]
        job.assigned_node_id = chosen.node_id
        job.status = JobStatus.ASSIGNED

    def retry_queued_jobs(self):
        for job in self.jobs.values():
            if job.status == JobStatus.QUEUED:
                self._assign_job(job)

    def report_job_result(self, job_id: str, success: bool, result: Optional[dict] = None):
        job = self.jobs.get(job_id)
        if not job:
            return
        job.status = JobStatus.DONE if success else JobStatus.FAILED
        job.result = result

    def cluster_status(self) -> dict:
        return {
            "master": self.to_dict(),
            "nodes": [n.__dict__ if not hasattr(n, "to_dict") else n.to_dict() for n in self.nodes.values()],
            "jobs": {
                "queued": sum(1 for j in self.jobs.values() if j.status == JobStatus.QUEUED),
                "running": sum(1 for j in self.jobs.values() if j.status in (JobStatus.ASSIGNED, JobStatus.RUNNING)),
                "done": sum(1 for j in self.jobs.values() if j.status == JobStatus.DONE),
                "failed": sum(1 for j in self.jobs.values() if j.status == JobStatus.FAILED),
            },
        }
