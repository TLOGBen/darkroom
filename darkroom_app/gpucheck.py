"""Is another program computing on the GPU? (skip rule for timing checks: app-shell B7, core A17)

`nvidia-smi --query-compute-apps` lists the processes with a compute context. Under the Windows WDDM driver it
also lists ordinary desktop programs (explorer, browsers) as type "C+G"; only type "C" processes (CUDA programs
such as ComfyUI or llama-server) count as compute processes here. A process whose type cannot be determined
counts as a compute process (conservative: the timing is skipped rather than reported under load).
"""
import os
import re
import subprocess


def _run(args):
    r = subprocess.run(["nvidia-smi", *args], capture_output=True, timeout=30)
    if r.returncode != 0:
        raise OSError(r.stderr.decode("utf-8", "replace").strip() or f"nvidia-smi exited {r.returncode}")
    return r.stdout.decode("utf-8", "replace")


def parse_compute_apps(csv_text):
    """'pid, name' lines -> [(pid, name)]."""
    out = []
    for line in csv_text.splitlines():
        if not line.strip():
            continue
        pid, _, name = line.partition(",")
        try:
            out.append((int(pid.strip()), name.strip()))
        except ValueError:
            continue
    return out


def parse_types(q_text):
    """`nvidia-smi -q -d PIDS` -> {pid: type}."""
    types, pid = {}, None
    for line in q_text.splitlines():
        m = re.match(r"\s*Process ID\s*:\s*(\d+)", line)
        if m:
            pid = int(m.group(1))
            continue
        m = re.match(r"\s*Type\s*:\s*(\S+)", line)
        if m and pid is not None:
            types[pid] = m.group(1)
            pid = None
    return types


def other_compute_processes(exclude=(), runner=_run):
    """[(pid, name)] of compute processes other than this process and `exclude`; None if nvidia-smi fails."""
    try:
        apps = parse_compute_apps(runner(["--query-compute-apps=pid,process_name", "--format=csv,noheader"]))
        types = parse_types(runner(["-q", "-d", "PIDS"]))
    except (OSError, subprocess.SubprocessError):
        return None
    mine = {os.getpid(), *exclude}
    return [(pid, name) for pid, name in apps if pid not in mine and types.get(pid, "C") == "C"]


def describe(procs):
    return "、".join(f"{name}（PID {pid}）" for pid, name in procs)
