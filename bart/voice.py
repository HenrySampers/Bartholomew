import os
import re
import subprocess
import tempfile
import threading
import time
import winsound
from pathlib import Path

import keyboard
import pyttsx3
from dotenv import load_dotenv


load_dotenv()
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "piper").strip().lower()

# Set by BartWorker to stop playback mid-sentence without killing the process.
_ui_interrupt = None
PIPER_EXE = os.getenv("PIPER_EXE", "piper").strip()
PIPER_MODEL = os.getenv("PIPER_MODEL", "").strip()
PIPER_LENGTH_SCALE = os.getenv("PIPER_LENGTH_SCALE", "1.3").strip()  # >1 = slower


def _split_sentences(text):
    text = text.strip()
    if not text:
        return []
    pieces = re.split(r"(?<=[.!?])\s+", text)
    return [piece.strip() for piece in pieces if piece.strip()]


def _strip_non_speakable(text):
    """Remove emojis and characters Piper can't encode."""
    return text.encode("ascii", errors="ignore").decode("ascii").strip()


def _validate_piper():
    if not PIPER_MODEL:
        print("Piper is selected, but PIPER_MODEL is not set. Falling back to pyttsx3.")
        return False

    model_path = Path(PIPER_MODEL)
    if not model_path.exists():
        print(f"Piper voice model not found: {model_path}. Falling back to pyttsx3.")
        return False

    return True


def _piper_command(output_path):
    return [
        PIPER_EXE,
        "--model",
        str(Path(PIPER_MODEL)),
        "--output_file",
        str(output_path),
        "--length-scale",
        PIPER_LENGTH_SCALE,
    ]


def _synthesize_piper(text, output_path):
    subprocess.run(
        _piper_command(output_path),
        input=text,
        text=True,
        capture_output=True,
        timeout=90,
        check=True,
    )


def _interrupted(allow_interrupt):
    if _ui_interrupt is not None and _ui_interrupt.is_set():
        return True
    return allow_interrupt and keyboard.is_pressed("space")


def _wait_for_playback(path, allow_interrupt=True):
    _audio_is_probably_playing.started_at = None
    _audio_is_probably_playing.path = None

    while True:
        if _interrupted(allow_interrupt):
            winsound.PlaySound(None, winsound.SND_PURGE)
            return True
        time.sleep(0.05)
        if not _audio_is_probably_playing(path):
            return False


def _speak_with_piper_streamed(text, allow_interrupt=True):
    text = _strip_non_speakable(text)
    if not _validate_piper():
        return _speak_with_pyttsx3(text, allow_interrupt=allow_interrupt)

    sentences = _split_sentences(text)
    if not sentences:
        return False

    temp_dir = Path(tempfile.gettempdir())
    slots = [temp_dir / "bart_stream_0.wav", temp_dir / "bart_stream_1.wav"]

    try:
        _synthesize_piper(sentences[0], slots[0])
    except Exception as exc:
        print(f"Piper speech error, falling back to pyttsx3: {exc}")
        return _speak_with_pyttsx3(text, allow_interrupt=allow_interrupt)

    next_index = 1
    synth_thread = None
    synth_state = {"error": None}

    def start_next():
        nonlocal synth_thread, next_index
        if next_index >= len(sentences):
            synth_thread = None
            return

        sentence = sentences[next_index]
        path = slots[next_index % 2]
        next_index += 1
        synth_state["error"] = None

        def worker():
            try:
                _synthesize_piper(sentence, path)
            except Exception as exc:
                synth_state["error"] = exc

        synth_thread = threading.Thread(target=worker, daemon=True)
        synth_thread.start()

    interrupted = False
    current_slot = 0

    for _ in range(len(sentences)):
        current_path = slots[current_slot]
        winsound.PlaySound(str(current_path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        start_next()

        if _wait_for_playback(current_path, allow_interrupt=allow_interrupt):
            interrupted = True
            break

        if synth_thread is not None:
            synth_thread.join()
            if synth_state["error"]:
                print(f"Piper streaming error: {synth_state['error']}")
                break

        current_slot = 1 - current_slot

    winsound.PlaySound(None, winsound.SND_PURGE)
    return interrupted


def _speak_with_piper(text, allow_interrupt=True):
    text = _strip_non_speakable(text)
    if not _validate_piper():
        return _speak_with_pyttsx3(text, allow_interrupt=allow_interrupt)

    output_path = Path(tempfile.gettempdir()) / "bart_piper_output.wav"

    try:
        _synthesize_piper(text, output_path)
    except Exception as exc:
        print(f"Piper speech error, falling back to pyttsx3: {exc}")
        return _speak_with_pyttsx3(text, allow_interrupt=allow_interrupt)

    winsound.PlaySound(str(output_path), winsound.SND_FILENAME | winsound.SND_ASYNC)
    interrupted = _wait_for_playback(output_path, allow_interrupt=allow_interrupt)
    winsound.PlaySound(None, winsound.SND_PURGE)
    return interrupted


def _audio_is_probably_playing(path):
    # winsound does not expose playback state. Estimate from WAV duration.
    try:
        import wave

        with wave.open(str(path), "rb") as file:
            frames = file.getnframes()
            rate = file.getframerate()
        duration = frames / float(rate)
    except Exception:
        duration = 1.0

    started_at = getattr(_audio_is_probably_playing, "started_at", None)
    current_path = getattr(_audio_is_probably_playing, "path", None)
    if started_at is None or current_path != str(path):
        _audio_is_probably_playing.started_at = time.time()
        _audio_is_probably_playing.path = str(path)
        return True
    if time.time() - started_at < duration + 0.2:
        return True
    _audio_is_probably_playing.started_at = None
    return False


def speak(text, allow_interrupt=True):
    """Makes Bart speak. Returns True if SPACE interrupted the speech."""
    print(f"Bart: {text}")
    if TTS_PROVIDER == "piper":
        return _speak_with_piper_streamed(text, allow_interrupt=allow_interrupt)
    return _speak_with_pyttsx3(text, allow_interrupt=allow_interrupt)


def _speak_with_pyttsx3(text, allow_interrupt=True):
    state = {"engine": None, "done": False, "error": None}
    interrupted = False

    def speech_worker():
        engine = None
        try:
            engine = pyttsx3.init()
            state["engine"] = engine
            engine.setProperty("rate", 180)
            engine.setProperty("volume", 0.9)
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            state["error"] = e
        finally:
            if engine:
                try:
                    engine.stop()
                except Exception:
                    pass
            state["done"] = True

    speech_thread = threading.Thread(target=speech_worker, daemon=True)
    speech_thread.start()

    while not state["done"]:
        if allow_interrupt and keyboard.is_pressed("space"):
            interrupted = True
            engine = state.get("engine")
            if engine:
                try:
                    engine.stop()
                except Exception:
                    pass
            break
        time.sleep(0.05)

    speech_thread.join(timeout=1)

    if state["error"]:
        print(f"Speech error (ignoring): {state['error']}")

    return interrupted


def speak_blocking(text):
    print(f"Bart: {text}")
    if TTS_PROVIDER == "piper":
        _speak_with_piper(text, allow_interrupt=False)
        return

    engine = None
    try:
        engine = pyttsx3.init()
        engine.setProperty("rate", 180)
        engine.setProperty("volume", 0.9)
        engine.say(text)
        engine.runAndWait()
    except Exception as e:
        print(f"Speech error (ignoring): {e}")
    finally:
        if engine:
            try:
                engine.stop()
            except Exception:
                pass
