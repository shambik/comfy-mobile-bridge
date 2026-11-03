"""Per-job diagnostics: what ran, on what machine state, and where the time went.

The worker stores these under ``metrics_json["diagnostics"]`` (internal, never
returned by the public job API) while a job runs and again when it finishes, so
stuck and failed jobs keep their evidence too.
"""
import ctypes
import json
import os
import subprocess
from pathlib import Path

try:
    import psutil
except ImportError:  # optional: diagnostics degrade to what nvidia-smi and Windows report
    psutil = None

# Samples are taken every 5 s. Keep the start of the job (model loading and the
# first sampling step, where stalls show up) and the most recent stretch.
SAMPLES_HEAD = 120
SAMPLES_TAIL = 600
PROGRESS_MARKS_PER_NODE = 400
TIMELINE_LIMIT = 400
LOG_LINES_LIMIT = 200
LOG_BYTES_LIMIT = 4 * 1024 * 1024
# ComfyUI log lines worth keeping: model loads, offload/staging decisions,
# memory warnings and errors.  Progress-bar lines are recorded as step times.
LOG_KEYWORDS = (
    "requested to load", "loaded partially", "loaded completely", "unloaded", "offloaded",
    "dynamic vram", "staged", "lowvram", "out of memory", "oom", "error", "exception",
    "traceback", "warning", "prompt executed", "got prompt", "free",
)


def memory_mode_from_argv(argv: list[str]) -> str | None:
    """Name the ComfyUI memory mode from its launch arguments."""
    if not argv:
        return None
    if "--disable-dynamic-vram" in argv:
        return "legacy"
    if "--enable-dynamic-vram" in argv:
        return "dynamic"
    return "default"


def keep_samples(samples: list[dict]) -> list[dict]:
    if len(samples) <= SAMPLES_HEAD + SAMPLES_TAIL:
        return list(samples)
    return samples[:SAMPLES_HEAD] + samples[-SAMPLES_TAIL:]


def _number(text: str):
    text = text.strip()
    try:
        value = float(text)
    except ValueError:
        return None  # nvidia-smi prints "[N/A]" for unsupported fields
    return int(value) if value.is_integer() else value


def _nvidia_smi(fields: list[str]) -> dict:
    try:
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={','.join(fields)}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode or not result.stdout.strip():
        return {}
    values = result.stdout.strip().splitlines()[0].split(",")
    return dict(zip(fields, (value.strip() for value in values)))


def windows_memory() -> dict:
    """Physical RAM and commit charge in MiB (Windows only)."""
    if os.name != "nt":
        return {}

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                    ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                    ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
                    ("avail_extended", ctypes.c_ulonglong)]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return {}
    mib = 1024 * 1024
    return {
        "ram_used_mib": round((status.total_phys - status.avail_phys) / mib),
        "ram_total_mib": round(status.total_phys / mib),
        "ram_available_mib": round(status.avail_phys / mib),
        # "Page" here is the commit limit (RAM + page file) and what remains of it.
        "commit_used_mib": round((status.total_page - status.avail_page) / mib),
        "commit_limit_mib": round(status.total_page / mib),
    }


def process_sample(pid: int | None) -> dict:
    """Memory, page faults and CPU time of the ComfyUI process that owns the port."""
    if not pid or psutil is None:
        return {}
    try:
        process = psutil.Process(pid)
        with process.oneshot():
            memory = process.memory_info()
            times = process.cpu_times()
            sample = {
                "comfy_working_set_mib": round(memory.rss / 1024 / 1024),
                # On Windows vms is the private commit (pagefile-backed bytes).
                "comfy_private_mib": round(memory.vms / 1024 / 1024),
                "comfy_cpu_seconds": round(times.user + times.system, 1),
                "comfy_threads": process.num_threads(),
            }
            faults = getattr(memory, "num_page_faults", None)
            if faults is not None:
                sample["comfy_page_faults"] = faults
            return sample
    except (psutil.Error, OSError):
        return {}


GPU_SAMPLE_FIELDS = [
    "memory.used", "memory.total", "utilization.gpu", "temperature.gpu",
    "power.draw", "clocks.sm", "utilization.memory", "pcie.link.gen.current",
]


def system_sample(pid: int | None = None) -> dict:
    """One 5-second sample: GPU, system memory, CPU and the ComfyUI process."""
    raw = _nvidia_smi(GPU_SAMPLE_FIELDS)
    if not raw:
        return {}
    numbers = {field: _number(value) for field, value in raw.items()}
    sample = {
        "vram_used_mib": numbers["memory.used"], "vram_total_mib": numbers["memory.total"],
        "gpu_util_percent": numbers["utilization.gpu"], "gpu_temp_c": numbers["temperature.gpu"],
        "gpu_power_w": numbers["power.draw"], "gpu_sm_clock_mhz": numbers["clocks.sm"],
        "gpu_memory_util_percent": numbers["utilization.memory"],
        "pcie_gen": numbers["pcie.link.gen.current"],
    }
    sample.update(windows_memory())
    if psutil is not None:
        sample["cpu_percent"] = psutil.cpu_percent(interval=None)
    sample.update(process_sample(pid))
    return sample


def _power_plan() -> str | None:
    if os.name != "nt":
        return None
    try:
        result = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = result.stdout.strip()
    return text[text.find("(") + 1:text.rfind(")")] if "(" in text else (text or None)


def _top_processes(limit: int = 10) -> list[dict]:
    if psutil is None:
        return []
    rows = []
    for process in psutil.process_iter(["pid", "name", "memory_info"]):
        info = process.info
        memory = info.get("memory_info")
        if memory is None:
            continue
        rows.append({"pid": info["pid"], "name": info["name"],
                     "working_set_mib": round(memory.rss / 1024 / 1024),
                     "private_mib": round(memory.vms / 1024 / 1024)})
    rows.sort(key=lambda row: row["working_set_mib"], reverse=True)
    return rows[:limit]


def host_snapshot() -> dict:
    """Machine state when a job starts: GPU and driver, memory, power plan and
    the processes holding the most RAM (other apps compete with offloaded weights)."""
    gpu = _nvidia_smi(["name", "driver_version", "pcie.link.gen.max", "pcie.link.width.max",
                       "pcie.link.width.current", "power.limit", "memory.used"])
    snapshot = {
        "gpu": {key.replace(".", "_"): (_number(value) if key != "name" and key != "driver_version" else value)
                for key, value in gpu.items()},
        "memory": windows_memory(),
        "power_plan": _power_plan(),
        "top_processes": _top_processes(),
    }
    if psutil is not None:
        snapshot["cpu_count"] = psutil.cpu_count()
        try:
            swap = psutil.swap_memory()
            snapshot["memory"]["pagefile_used_mib"] = round(swap.used / 1024 / 1024)
            snapshot["memory"]["pagefile_total_mib"] = round(swap.total / 1024 / 1024)
        except (psutil.Error, OSError):
            pass
    return snapshot


def workflow_graph(workflow: dict) -> dict:
    """The exact graph sent to ComfyUI: every node with its input values.

    Links stay as ComfyUI writes them, [source node id, output index]."""
    return json.loads(json.dumps(workflow, ensure_ascii=False, default=str))


class JobTimeline:
    """Collect node execution order and per-node progress from ComfyUI websocket events."""

    def __init__(self, workflow: dict):
        self.classes = {str(node_id): str(node.get("class_type")) for node_id, node in workflow.items()}
        self.nodes: list[list] = []
        self.cached: list[str] = []
        self.progress: dict[str, dict] = {}

    def record(self, event_type: str, data: dict, seconds: float) -> None:
        seconds = round(seconds, 1)
        if event_type == "execution_cached":
            self.cached = [str(node) for node in data.get("nodes") or []]
        elif event_type == "executing":
            node = data.get("node")
            if node is None:
                self._add_node(None, "finished", seconds)
            else:
                self._add_node(str(node), self.classes.get(str(node), "?"), seconds)
        elif event_type == "progress":
            node = str(data.get("node")) if data.get("node") is not None else "?"
            try:
                value, total = float(data.get("value", 0)), int(float(data.get("max", 0)))
            except (TypeError, ValueError):
                return
            entry = self.progress.setdefault(node, {"class_type": self.classes.get(node, "?"), "max": total, "marks": []})
            entry["max"] = total
            if entry["marks"] and entry["marks"][-1][0] == value:
                return
            if len(entry["marks"]) < PROGRESS_MARKS_PER_NODE:
                entry["marks"].append([value, seconds])

    def _add_node(self, node: str | None, class_type: str, seconds: float) -> None:
        if len(self.nodes) < TIMELINE_LIMIT:
            self.nodes.append([node, class_type, seconds])

    def as_dict(self) -> dict:
        return {
            "nodes": self.nodes, "cached_nodes": self.cached, "progress": self.progress,
            "step_seconds": self.step_seconds(),
        }

    def step_seconds(self) -> dict[str, list[float]]:
        """Duration of each progress step per node, e.g. each sampling step."""
        durations = {}
        for node, entry in self.progress.items():
            marks = entry["marks"]
            durations[node] = [round(later[1] - earlier[1], 1) for earlier, later in zip(marks, marks[1:])]
        return durations


def log_offset(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def comfy_log_lines(path: Path, offset: int) -> list[str]:
    """ComfyUI log lines written since ``offset`` that explain loading and memory."""
    try:
        size = path.stat().st_size
        start = max(offset, size - LOG_BYTES_LIMIT) if offset <= size else max(0, size - LOG_BYTES_LIMIT)
        with path.open("rb") as handle:
            handle.seek(start)
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    kept = []
    for line in text.replace("\r", "\n").splitlines():
        line = line.strip()
        if line and any(keyword in line.lower() for keyword in LOG_KEYWORDS) and "it/s]" not in line and "s/it]" not in line:
            kept.append(line[:400])
    if len(kept) <= LOG_LINES_LIMIT:
        return kept
    # Model loading happens at the start of a job; keep it and the latest lines.
    head = LOG_LINES_LIMIT * 3 // 4
    return kept[:head] + kept[-(LOG_LINES_LIMIT - head):]
