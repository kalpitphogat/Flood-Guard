"""Detached run worker: survives an API restart, stops at once, reports honestly."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.core import worker
from app.core.jobs import JobRunner, JobStatus, JobStore


def _sleeper(seconds: float = 60.0) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({seconds})"])


def _running_job(store: JobStore, pid: int, beat: bool = True) -> tuple[str, Path]:
    job = store.create("s", {})
    store.mark_running(job.id)
    jdir = store.job_dir(job.id)
    jdir.mkdir(parents=True)
    worker.write_json_atomic(jdir / "worker.json", {"pid": pid, "started": time.time()})
    if beat:
        (jdir / "heartbeat").touch()
    return job.id, jdir


def test_pid_running_sees_a_live_process_and_not_a_dead_one():
    proc = _sleeper()
    try:
        assert worker.pid_running(proc.pid)
    finally:
        proc.kill()
        proc.wait()
    assert not worker.pid_running(proc.pid)


def test_a_stale_heartbeat_means_dead_even_if_the_pid_exists(tmp_path):
    proc = _sleeper()
    try:
        worker.write_json_atomic(tmp_path / "worker.json", {"pid": proc.pid})
        (tmp_path / "heartbeat").touch()
        assert worker.worker_alive(tmp_path)
        old = time.time() - worker.STALE_AFTER_S - 5
        import os

        os.utime(tmp_path / "heartbeat", (old, old))
        assert not worker.worker_alive(tmp_path)  # a recycled pid is never "our" worker
    finally:
        proc.kill()
        proc.wait()


def test_kill_tree_stops_the_worker(tmp_path):
    proc = _sleeper()
    worker.kill_tree(proc.pid)
    proc.wait(timeout=10)
    assert not worker.pid_running(proc.pid)


def test_watch_relays_progress_and_the_outcome(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite")
    proc = _sleeper(2.0)
    job_id, jdir = _running_job(store, proc.pid)
    lines = [{"fraction": 0.5, "phase": "solve", "message": "half way", "t_s": 10.0}]
    (jdir / "progress.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    worker.write_json_atomic(jdir / "status.json", {"status": "succeeded", "result_path": "r.json"})
    JobRunner(store, tmp_path)._watch(job_id, poll_s=0.05)
    job = store.get(job_id)
    assert job.status == JobStatus.SUCCEEDED and job.result_path == "r.json"
    assert job.progress.fraction == 0.5 and "half way" in job.progress.log[-1]
    proc.kill()
    proc.wait()


def test_stop_kills_the_worker_and_discards_partial_output(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite")
    proc = _sleeper()
    job_id, jdir = _running_job(store, proc.pid)
    partial = tmp_path / "runs" / job_id
    partial.mkdir(parents=True)
    (partial / "frames_000.npz").write_bytes(b"x")
    assert store.cancel(job_id)
    JobRunner(store, tmp_path)._watch(job_id, poll_s=0.05)
    proc.wait(timeout=10)
    assert store.get(job_id).status == JobStatus.CANCELLED
    assert not partial.exists()
    assert worker.read_json(jdir / "status.json") == {"status": "cancelled"}


def test_a_worker_that_dies_without_a_result_is_a_failure_not_a_success(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite")
    proc = _sleeper(0.1)
    proc.wait()
    job_id, _ = _running_job(store, proc.pid)
    JobRunner(store, tmp_path)._watch(job_id, poll_s=0.02)
    job = store.get(job_id)
    assert job.status == JobStatus.FAILED and "without a result" in job.error


def test_restart_reattaches_live_workers_and_settles_the_rest(tmp_path):
    db = tmp_path / "jobs.sqlite"
    store = JobStore(db)
    live = _sleeper()
    try:
        alive_id, _ = _running_job(store, live.pid)
        done_id, done_dir = _running_job(store, 999_999_1, beat=False)
        worker.write_json_atomic(done_dir / "status.json", {"status": "failed", "error": "boom"})
        dead_id, _ = _running_job(store, 999_999_2, beat=False)

        restarted = JobStore(db)  # what the API does on startup
        assert restarted.reattach == [alive_id]
        assert restarted.get(alive_id).status == JobStatus.RUNNING
        assert restarted.get(done_id).status == JobStatus.FAILED
        assert restarted.get(done_id).error == "boom"
        assert restarted.get(dead_id).status == JobStatus.INTERRUPTED
    finally:
        live.kill()
        live.wait()


def test_worker_run_writes_a_failed_status_for_a_bad_scenario(tmp_path):
    (tmp_path / "scenario.json").write_text("{}")
    (tmp_path / "run_meta.json").write_text("{}")
    assert worker.run(tmp_path, "j", tmp_path) == 1
    outcome = worker.read_json(tmp_path / "status.json")
    assert outcome["status"] == "failed" and "ValidationError" in outcome["error"]


@pytest.mark.parametrize("pid", [0, -1])
def test_nonsense_pids_are_not_running(pid):
    assert not worker.pid_running(pid)
