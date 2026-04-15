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
