import sys
import json
import os
from datetime import datetime
from pathlib import Path

try:
    import psutil
except Exception:
    psutil = None

_SESSION_ID = datetime.now().strftime("%Y%m%d_%H%M%S")


class _Tee:
    def __init__(self, stream, log_file):
        self.stream = stream
        self.log_file = log_file

    def write(self, text):
        self.stream.write(text)
        self.log_file.write(text)

    def flush(self):
        self.stream.flush()
        self.log_file.flush()

    def isatty(self):
        return self.stream.isatty()


def setup_console_logging(prefix="bart"):
    """Mirror stdout/stderr to data/logs so CLI output can be shared later."""
    if getattr(sys, "_bart_console_logging", False):
        return getattr(sys, "_bart_log_path", None)

    log_dir = Path("data") / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_file = path.open("a", encoding="utf-8", buffering=1)

    sys.stdout = _Tee(sys.stdout, log_file)
    sys.stderr = _Tee(sys.stderr, log_file)
    sys._bart_console_logging = True
    sys._bart_log_path = path
    print(f"[log] console output mirrored to {path}")
    print(f"[log] structured events mirrored to {_event_log_path()}")
    return path


def _event_log_path():
    log_dir = Path("data") / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"bart_events_{datetime.now().strftime('%Y%m%d')}.jsonl"


def _chat_log_path():
    log_dir = Path("data") / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"bart_chat_{datetime.now().strftime('%Y%m%d')}.jsonl"


def log_event(event_type, **fields):
    """Append a lightweight structured event so failures are easier to inspect."""
    payload = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "session": _SESSION_ID,
        "event": event_type,
        **fields,
    }
    try:
        path = _event_log_path()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception:
        pass


def get_event_log_path():
    return _event_log_path()


def log_chat(role, text, **fields):
    payload = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "session": _SESSION_ID,
        "role": role,
        "text": text,
        **fields,
    }
    try:
        path = _chat_log_path()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception:
        pass


def log_timing(stage, elapsed_ms, **fields):
    log_event("timing", stage=stage, elapsed_ms=round(float(elapsed_ms), 1), **fields)


def log_process_snapshot(label, **fields):
    payload = {
        "label": label,
        **fields,
    }
    if psutil is None:
        log_event("process_snapshot", **payload)
        return
    try:
        proc = psutil.Process(os.getpid())
        with proc.oneshot():
            mem_info = proc.memory_info()
            payload.update({
                "pid": proc.pid,
                "rss_mb": round(mem_info.rss / (1024 * 1024), 1),
                "vms_mb": round(mem_info.vms / (1024 * 1024), 1),
                "threads": proc.num_threads(),
                "cpu_percent": proc.cpu_percent(interval=None),
            })
        payload.update({
            "system_cpu_percent": psutil.cpu_percent(interval=None),
            "system_ram_percent": psutil.virtual_memory().percent,
        })
    except Exception as exc:
        payload["snapshot_error"] = str(exc)
    log_event("process_snapshot", **payload)
