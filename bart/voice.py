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

from .logging_utils import log_event, log_timing


load_dotenv()
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "piper").strip().lower()

# Set by BartWorker to stop playback mid-sentence without killing the process.
_ui_interrupt = None
PIPER_EXE = os.getenv("PIPER_EXE", "piper").strip()
PIPER_MODEL = os.getenv("PIPER_MODEL", "").strip()
PIPER_LENGTH_SCALE = os.getenv("PIPER_LENGTH_SCALE", "1.3").strip()  # >1 = slower
PIPER_STREAM_TARGET_CHARS = max(60, int(os.getenv("PIPER_STREAM_TARGET_CHARS", "110")))
PIPER_PLAYBACK_MARGIN = float(os.getenv("PIPER_PLAYBACK_MARGIN", "0.35"))
PIPER_FIRST_SENTENCE_TIMEOUT = float(os.getenv("PIPER_FIRST_SENTENCE_TIMEOUT", "4.5"))


def _split_sentences(text):
    text = text.strip()
    if not text:
        return []
    pieces = [piece.strip() for piece in re.split(r"(?<=[.!?])\s+", text) if piece.strip()]
    if not pieces:
        return []

    # Merge short adjacent sentences so Piper spends less time pausing between tiny chunks.
    chunks = []
    current = pieces[0]
    for piece in pieces[1:]:
        if len(current) < PIPER_STREAM_TARGET_CHARS:
            current = f"{current} {piece}".strip()
        else:
            chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
    return chunks


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
    overall_started = time.perf_counter()
    text = _strip_non_speakable(text)
    if not _validate_piper():
        return _speak_with_pyttsx3(text, allow_interrupt=allow_interrupt)

    sentences = _split_sentences(text)
    if not sentences:
        return False

    temp_dir = Path(tempfile.gettempdir())
    slots = [temp_dir / "bart_stream_0.wav", temp_dir / "bart_stream_1.wav"]

    first_state = {"error": None, "done": False}

    def synthesize_first():
        try:
            _synthesize_piper(sentences[0], slots[0])
        except Exception as exc:
            first_state["error"] = exc
        finally:
            first_state["done"] = True

    first_started = time.perf_counter()
    first_thread = threading.Thread(target=synthesize_first, daemon=True)
    first_thread.start()
    first_thread.join(timeout=PIPER_FIRST_SENTENCE_TIMEOUT)
    if not first_state["done"]:
        log_event(
            "tts_piper_slow_fallback",
            timeout_seconds=PIPER_FIRST_SENTENCE_TIMEOUT,
            first_chunk=sentences[0][:120],
        )
        print("Piper is taking too long to start speaking, falling back to pyttsx3 for this reply.")
        return _speak_with_pyttsx3(text, allow_interrupt=allow_interrupt)
    if first_state["error"] is not None:
        print(f"Piper speech error, falling back to pyttsx3: {first_state['error']}")
        return _speak_with_pyttsx3(text, allow_interrupt=allow_interrupt)
    log_timing("tts_piper_first_sentence", (time.perf_counter() - first_started) * 1000, sentences=len(sentences))

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
                synth_started = time.perf_counter()
                _synthesize_piper(sentence, path)
                log_timing("tts_piper_buffer_sentence", (time.perf_counter() - synth_started) * 1000, chars=len(sentence))
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

    if interrupted:
        winsound.PlaySound(None, winsound.SND_PURGE)
    log_timing("tts_piper_streamed_total", (time.perf_counter() - overall_started) * 1000, interrupted=interrupted, sentences=len(sentences))
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
    if interrupted:
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
    if time.time() - started_at < duration + PIPER_PLAYBACK_MARGIN:
        return True
    _audio_is_probably_playing.started_at = None
    return False


def speak(text, allow_interrupt=True):
    """Makes Bart speak. Returns True if SPACE interrupted the speech."""
    print(f"Bart: {text}")
    started = time.perf_counter()
    if TTS_PROVIDER == "piper":
        interrupted = _speak_with_piper_streamed(text, allow_interrupt=allow_interrupt)
    else:
        interrupted = _speak_with_pyttsx3(text, allow_interrupt=allow_interrupt)
    log_timing("tts_total", (time.perf_counter() - started) * 1000, provider=TTS_PROVIDER, interrupted=interrupted)
    return interrupted


def _speak_with_pyttsx3(text, allow_interrupt=True):
    started = time.perf_counter()
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
        log_event("tts_error", provider="pyttsx3", error=str(state["error"]))

    log_timing("tts_pyttsx3", (time.perf_counter() - started) * 1000, interrupted=interrupted)
    return interrupted


def speak_blocking(text):
    print(f"Bart: {text}")
    started = time.perf_counter()
    if TTS_PROVIDER == "piper":
        _speak_with_piper(text, allow_interrupt=False)
        log_timing("tts_blocking", (time.perf_counter() - started) * 1000, provider="piper")
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
        log_event("tts_error", provider="pyttsx3", error=str(e))
    finally:
        if engine:
            try:
                engine.stop()
            except Exception:
                pass
    log_timing("tts_blocking", (time.perf_counter() - started) * 1000, provider="pyttsx3")
