"""
System-level tools: time, system info/stats, screenshot,
PowerShell, volume, media controls, clipboard.
"""
import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path

import keyboard


def current_time():
    return datetime.now().strftime("It is %A, %d %B %Y at %H:%M, Sir.")


def system_info():
    return (
        f"System: {platform.system()} {platform.release()} on {platform.machine()}. "
        f"Python: {platform.python_version()}."
    )


def system_stats():
    try:
        import psutil
    except ImportError:
        return "System stats require psutil, Sir. Run: pip install psutil"

    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return (
        f"CPU: {cpu:.1f}% | "
        f"RAM: {ram.percent:.1f}% used ({ram.used // 1024**2} MB / {ram.total // 1024**2} MB) | "
        f"Disk: {disk.percent:.1f}% used ({disk.used // 1024**3} GB / {disk.total // 1024**3} GB), Sir."
    )


def screenshot():
    try:
        from PIL import ImageGrab
    except ImportError:
        return "Screenshot support needs Pillow installed, Sir. Run: pip install pillow"

    folder = Path("data") / "screenshots"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    image = ImageGrab.grab()
    image.save(path)
    return f"Screenshot saved, Sir."


def run_powershell(command):
    if not command.strip():
        return "I need a PowerShell command, Sir."
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = completed.stdout.strip() or completed.stderr.strip() or "No output."
    return f"PowerShell exited with code {completed.returncode}.\n{output[:2000]}"


# --- Volume ---

def volume_up():
    keyboard.send("volume up")
    return "Volume raised, Sir."


def volume_down():
    keyboard.send("volume down")
    return "Volume lowered, Sir."


def mute():
    keyboard.send("volume mute")
    return "Toggled mute, Sir."


# --- Media Controls ---

def media_play_pause():
    keyboard.send("play/pause media")
    return "Done, Sir."


def media_next():
    keyboard.send("next track")
    return "Skipping to the next track, Sir."


def media_prev():
    keyboard.send("previous track")
    return "Going back a track, Sir."


# --- Clipboard ---

def get_clipboard():
    try:
        import pyperclip
        text = pyperclip.paste()
        if not text:
            return "The clipboard is empty, Sir."
        return f"Clipboard: {text[:500]}"
    except ImportError:
        return "Clipboard access requires pyperclip, Sir. Run: pip install pyperclip"


def set_clipboard(text):
    try:
        import pyperclip
        pyperclip.copy(text)
        return f"Copied to clipboard, Sir."
    except ImportError:
        return "Clipboard access requires pyperclip, Sir. Run: pip install pyperclip"
