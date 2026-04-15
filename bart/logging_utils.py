import sys
from datetime import datetime
from pathlib import Path


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
    return path
