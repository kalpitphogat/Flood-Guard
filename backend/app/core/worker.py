"""Detached run worker: a simulation in its own process, outside the API.

Before this, a job ran on a thread inside the API process. Restarting the API
(a code reload, a crash, closing the terminal) killed the run, and Stop could
only take effect at the solver's next progress tick. Now each job runs as a
separate, detached OS process that communicates through files in its job
folder, `data/jobs/<job_id>/`:

    scenario.json   the validated scenario        (written by the API)
    run_meta.json   how the run is labelled        (written by the API)
    worker.json     pid + start time               (written by the API)
    progress.jsonl  one JSON progress event a line (appended by the worker)
    heartbeat       touched every few seconds      (by the worker)
    status.json     the outcome, written last      (by the worker)
    worker.log      the worker's stdout/stderr

Because the files, not the process, carry the state, an API that restarts
finds a still-running worker and reattaches to it (jobs.JobStore), and a
worker that finished while the API was down is recorded with its real outcome.
Stop kills the whole process tree immediately.

Liveness is "the pid is running AND the heartbeat is fresh", so a recycled pid
belonging to some other program is never mistaken for the worker.

Run by the API as:  python -m app.core.worker <job_dir> <job_id> <data_dir>
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

HEARTBEAT_S = 3.0
#: A heartbeat older than this means the worker is gone, whatever its pid says.
STALE_AFTER_S = 30.0

BACKEND_DIR = Path(__file__).resolve().parents[2]


# --- files --------------------------------------------------------------------------


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, default=str), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def heartbeat_age_s(job_dir: Path) -> float | None:
    try:
        return time.time() - (job_dir / "heartbeat").stat().st_mtime
    except OSError:
        return None


# --- processes ----------------------------------------------------------------------


def pid_running(pid: int) -> bool:
    """Whether a process with this pid exists. Never signals it."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ok = k32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok) and code.value == STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)  # POSIX: signal 0 only checks existence
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def worker_alive(job_dir: Path) -> bool:
    info = read_json(job_dir / "worker.json") or {}
    age = heartbeat_age_s(job_dir)
    return (
        pid_running(int(info.get("pid", 0)))
        and age is not None
        and age < STALE_AFTER_S
        and not (job_dir / "status.json").exists()
    )


def spawn(job_dir: Path, job_id: str, data_dir: Path) -> int:
    """Start a detached worker; returns its pid. It outlives the API process."""
    log_fh = open(job_dir / "worker.log", "ab")  # noqa: SIM115 - handed to the child
    kwargs: dict[str, Any] = {
        "cwd": str(BACKEND_DIR),
        "stdin": subprocess.DEVNULL,
        "stdout": log_fh,
        "stderr": subprocess.STDOUT,
        "env": {**os.environ, "PYTHONUNBUFFERED": "1"},
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NO_WINDOW
        )
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.core.worker", str(job_dir), job_id, str(data_dir)], **kwargs
    )
    log_fh.close()
    # The heartbeat starts now, so a worker still importing numba is not
    # declared dead by a reattach in its first seconds.
    (job_dir / "heartbeat").touch()
    write_json_atomic(job_dir / "worker.json", {"pid": proc.pid, "started": time.time()})
    return proc.pid


def kill_tree(pid: int) -> None:
    """Stop a worker and everything it started (numba threads die with it)."""
    if not pid_running(pid):
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
    else:
        try:
            os.killpg(pid, signal.SIGTERM)  # start_new_session: pgid == pid
        except ProcessLookupError:
            return
        for _ in range(50):
            if not pid_running(pid):
                return
            time.sleep(0.1)
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


# --- the worker itself --------------------------------------------------------------


def _beat(job_dir: Path, stop: threading.Event) -> None:
    while not stop.wait(HEARTBEAT_S):
        try:
            (job_dir / "heartbeat").touch()
        except OSError:
            pass


def run(job_dir: Path, job_id: str, data_dir: Path) -> int:
    from floodguard.pipeline import simulate
    from floodguard.scenario import Scenario

    stop = threading.Event()
    threading.Thread(target=_beat, args=(job_dir, stop), daemon=True).start()
    progress_path = job_dir / "progress.jsonl"

    def progress(*, fraction, phase, message, **extra):
        event = {"fraction": fraction, "phase": phase, "message": message,
                 **{k: v for k, v in extra.items()
                    if isinstance(v, (str, int, float, bool, type(None), list, dict))}}
        with progress_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, default=str) + "\n")

    try:
        scenario = Scenario.model_validate(read_json(job_dir / "scenario.json"))
        run_meta = read_json(job_dir / "run_meta.json")
        result = simulate(scenario, data_dir, progress=progress, run_id=job_id, run_meta=run_meta)
        outcome = {"status": "succeeded", "result_path": str(result.out_dir / "result.json")}
        code = 0
    except Exception as exc:  # noqa: BLE001
        outcome = {"status": "failed",
                   "error": f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=5)}"}
        code = 1
    stop.set()
    write_json_atomic(job_dir / "status.json", outcome)
    return code


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    sys.exit(run(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])))
