"""
System-level tools: time, system info/stats, screenshot,
PowerShell, volume, media controls, clipboard.
"""
import os
import platform
import subprocess
import base64
import io
from datetime import datetime
from pathlib import Path

import keyboard


def current_time():
    return datetime.now().strftime("it's %A, %d %B %Y at %H:%M.")


def system_info():
    return (
        f"running {platform.system()} {platform.release()} on {platform.machine()}, "
        f"python {platform.python_version()}."
    )


def system_stats():
    try:
        import psutil
    except ImportError:
        return "need psutil for that bro — run: pip install psutil"

    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return (
        f"CPU: {cpu:.1f}% | "
        f"RAM: {ram.percent:.1f}% ({ram.used // 1024**2} MB / {ram.total // 1024**2} MB) | "
        f"Disk: {disk.percent:.1f}% ({disk.used // 1024**3} GB / {disk.total // 1024**3} GB)"
    )


def screenshot():
    try:
        from PIL import ImageGrab
    except ImportError:
        return "need pillow for screenshots bro — run: pip install pillow"

    folder = Path("data") / "screenshots"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    image = ImageGrab.grab()
    image.save(path)
    return f"screenshot saved, bro."


def look_at_screen(query="what's on my screen?"):
    try:
        from PIL import ImageGrab
    except ImportError:
        return "need pillow for screen vision bro - run: pip install pillow"

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return "gemini api key isn't set bro, so i can't see the screen yet."

    try:
        import warnings

        warnings.simplefilter("ignore", FutureWarning)
        import google.generativeai as genai

        image = ImageGrab.grab()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        png_bytes = buffer.getvalue()
        image_b64 = base64.b64encode(png_bytes).decode("ascii")

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash"))
        prompt = query or "what's on my screen?"
        try:
            response = model.generate_content([
                prompt,
                {"inline_data": {"mime_type": "image/png", "data": image_b64}},
            ])
        except Exception:
            response = model.generate_content([
                prompt,
                {"mime_type": "image/png", "data": png_bytes},
            ])
        text = getattr(response, "text", "").strip()
        return text or "i looked, but gemini didn't give me a description."
    except Exception as exc:
        return f"couldn't read the screen rn bro: {exc}"


def run_powershell(command):
    if not command.strip():
        return "need a command to run bro."
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = completed.stdout.strip() or completed.stderr.strip() or "no output."
    return f"powershell exited {completed.returncode}.\n{output[:2000]}"


# --- Window controls ---

def show_desktop():
    keyboard.send("windows+d")
    return "showing desktop."


def switch_window():
    keyboard.send("alt+tab")
    return "switched windows."


def minimize_window():
    keyboard.send("windows+down")
    return "minimized the active window."


def maximize_window():
    keyboard.send("windows+up")
    return "maximized the active window."


def snap_window_left():
    keyboard.send("windows+left")
    return "snapped the active window left."


def snap_window_right():
    keyboard.send("windows+right")
    return "snapped the active window right."


def close_active_window():
    keyboard.send("alt+f4")
    return "closed the active window."


# --- Session / power controls ---

def lock_screen():
    subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
    return "locked the computer."


def sleep_computer():
    subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
    return "putting the computer to sleep."


# --- Processes ---

def list_processes(query: str = "", limit: int = 10):
    try:
        import psutil
    except ImportError:
        return "need psutil for that bro - run: pip install psutil"

    query = (query or "").strip().lower()
    limit = max(1, min(int(limit or 10), 30))
    rows = []
    for proc in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent"]):
        try:
            name = proc.info.get("name") or ""
            if query and query not in name.lower():
                continue
            mem = proc.info.get("memory_info")
            mem_mb = int(mem.rss / 1024 / 1024) if mem else 0
            rows.append((mem_mb, proc.info.get("pid"), name))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    rows.sort(reverse=True)
    if not rows:
        return "couldn't find matching processes bro."
    lines = [f"{name} (pid {pid}, {mem_mb} MB)" for mem_mb, pid, name in rows[:limit]]
    return "running processes:\n" + "\n".join(lines)


def close_process(name: str):
    try:
        import psutil
    except ImportError:
        return "need psutil for that bro - run: pip install psutil"

    target = (name or "").strip().lower()
    if not target:
        return "need a process name bro."

    closed = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            proc_name = proc.info.get("name") or ""
            if target in proc_name.lower():
                proc.terminate()
                closed.append(f"{proc_name} pid {proc.info.get('pid')}")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not closed:
        return f"couldn't find a process matching {name!r} bro."
    return "asked these processes to close:\n" + "\n".join(closed[:10])


# --- Volume ---

def volume_up():
    keyboard.send("volume up")
    return "turned up bro."


def volume_down():
    keyboard.send("volume down")
    return "turned down bro."


def mute():
    keyboard.send("volume mute")
    return "toggled mute."


# --- Media Controls ---

def media_play_pause():
    keyboard.send("play/pause media")
    return "done."


def media_next():
    keyboard.send("next track")
    return "skipped."


def media_prev():
    keyboard.send("previous track")
    return "went back."


# --- Clipboard ---

def get_clipboard():
    try:
        import pyperclip
        text = pyperclip.paste()
        if not text:
            return "clipboard's empty bro."
        return f"clipboard: {text[:500]}"
    except ImportError:
        return "need pyperclip bro — run: pip install pyperclip"


def set_clipboard(text):
    try:
        import pyperclip
        pyperclip.copy(text)
        return "copied to clipboard."
    except ImportError:
        return "need pyperclip bro — run: pip install pyperclip"
