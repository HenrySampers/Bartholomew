"""
Wake word listener via openWakeWord.

Public API intentionally matches the older wakeword.py:
start(), stop(), restart(), is_triggered(), clear_trigger().
"""
import os
import threading
import time

import numpy as np
import pyaudio


RATE = 16000
CHUNK = 1280  # 80 ms at 16 kHz, openWakeWord's expected frame size.
WAKE_MODEL = os.getenv("WAKE_MODEL", "hey_mycroft").strip()
WAKE_THRESHOLD = float(os.getenv("WAKE_THRESHOLD", "0.35"))
WAKE_DEBUG = os.getenv("WAKE_DEBUG", "false").lower() == "true"

_triggered = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None
_model = None


def is_triggered() -> bool:
    return _triggered.is_set()


def clear_trigger() -> None:
    _triggered.clear()


def start() -> None:
    """Start the wake word listener thread."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _triggered.clear()
    _thread = threading.Thread(target=_listen_loop, daemon=True)
    _thread.start()


def restart() -> None:
    """Stop and restart after Bart handles a wake event."""
    stop()
    time.sleep(0.2)
    start()


def stop() -> None:
    _stop.set()
    if _thread is not None and _thread.is_alive():
        _thread.join(timeout=1.0)


def _load_model():
    global _model
    if _model is not None:
        return _model

    try:
        from openwakeword.model import Model
        from openwakeword.utils import download_models
    except ImportError as exc:
        raise RuntimeError("openwakeword is not installed. run: pip install openwakeword") from exc

    try:
        download_models([WAKE_MODEL])
    except Exception:
        pass

    try:
        _model = Model(wakeword_models=[WAKE_MODEL], inference_framework="onnx")
    except Exception as exc:
        print(f"[wake word] couldn't load {WAKE_MODEL!r}, loading all built-ins: {exc}")
        _model = Model(inference_framework="onnx")
    loaded = ", ".join(getattr(_model, "models", {}).keys()) or WAKE_MODEL
    print(f"[wake word] openWakeWord ready: {loaded} (threshold {WAKE_THRESHOLD})")
    return _model


def _listen_loop() -> None:
    try:
        model = _load_model()
    except Exception as exc:
        print(f"[wake word] model error: {exc}")
        return

    pa = pyaudio.PyAudio()
    try:
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK,
        )
    except Exception as exc:
        print(f"[wake word] mic error: {exc}")
        pa.terminate()
        return

    try:
        while not _stop.is_set():
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
            except Exception:
                break

            frame = np.frombuffer(data, dtype=np.int16)
            try:
                scores = model.predict(frame)
            except Exception as exc:
                print(f"[wake word] predict error: {exc}")
                break

            score = scores.get(WAKE_MODEL)
            if score is None:
                score = next((value for key, value in scores.items() if WAKE_MODEL in key), None)
            if score is None:
                score = max(scores.values()) if scores else 0.0
            if WAKE_DEBUG and int(time.time() * 10) % 10 == 0:
                best_name = max(scores, key=scores.get) if scores else "none"
                print(f"[wake word] best={best_name} score={score:.3f}")
            if score >= WAKE_THRESHOLD:
                print(f"[wake word] triggered at {score:.3f}")
                try:
                    import winsound

                    winsound.Beep(1000, 80)
                except Exception:
                    pass
                _triggered.set()
                break
    finally:
        try:
            stream.close()
            pa.terminate()
        except Exception:
            pass
