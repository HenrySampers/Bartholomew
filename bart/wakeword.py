"""
Wake activation listener.

Supports either:
- openWakeWord phrase models
- a simple double-clap detector

Public API intentionally matches the older wakeword.py:
start(), stop(), restart(), is_triggered(), clear_trigger().
"""
import os
import threading
import time

import numpy as np
import pyaudio
from dotenv import load_dotenv

from .logging_utils import log_event


load_dotenv()


RATE = 16000
CHUNK = 1280  # 80 ms at 16 kHz, openWakeWord's expected frame size.
WAKE_METHOD = os.getenv("WAKE_METHOD", "openwakeword").strip().lower()
WAKE_MODEL = os.getenv("WAKE_MODEL", "hey_mycroft").strip()
WAKE_THRESHOLD = float(os.getenv("WAKE_THRESHOLD", "0.35"))
WAKE_DEBUG = os.getenv("WAKE_DEBUG", "false").lower() == "true"
CLAP_THRESHOLD = int(os.getenv("CLAP_THRESHOLD", "3500"))
CLAP_MIN_GAP = float(os.getenv("CLAP_MIN_GAP", "0.12"))
CLAP_MAX_GAP = float(os.getenv("CLAP_MAX_GAP", "0.6"))
CLAP_COOLDOWN = float(os.getenv("CLAP_COOLDOWN", "1.5"))
CLAP_DYNAMIC_RATIO = float(os.getenv("CLAP_DYNAMIC_RATIO", "3.5"))
CLAP_RESET_AFTER = float(os.getenv("CLAP_RESET_AFTER", "1.0"))

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


def activation_label() -> str:
    if WAKE_METHOD == "clap":
        return "double clap"
    return WAKE_MODEL.replace("_", " ")


def _beep():
    try:
        import winsound

        winsound.Beep(1000, 80)
    except Exception:
        pass


def _trigger(source: str, score: float | None = None) -> None:
    if score is None:
        print(f"[wake word] triggered by {source}")
    else:
        print(f"[wake word] triggered by {source} at {score:.3f}")
    log_event("wake_trigger", source=source, score=score)
    _beep()
    _triggered.set()


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


def _open_stream():
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
        return None, None
    return pa, stream


def _listen_loop_openwakeword() -> None:
    try:
        model = _load_model()
    except Exception as exc:
        print(f"[wake word] model error: {exc}")
        return

    pa, stream = _open_stream()
    if pa is None or stream is None:
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
                _trigger("openwakeword", score)
                break
    finally:
        try:
            stream.close()
            pa.terminate()
        except Exception:
            pass


def _listen_loop_clap() -> None:
    pa, stream = _open_stream()
    if pa is None or stream is None:
        return

    print(
        f"[wake word] clap detector ready "
        f"(threshold {CLAP_THRESHOLD}, gap {CLAP_MIN_GAP:.2f}-{CLAP_MAX_GAP:.2f}s)"
    )
    last_clap_at = None
    cooldown_until = 0.0
    noise_floor = float(CLAP_THRESHOLD) / CLAP_DYNAMIC_RATIO

    try:
        while not _stop.is_set():
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
            except Exception:
                break

            now = time.time()
            frame = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            if frame.size == 0:
                continue

            peak = float(np.max(np.abs(frame)))
            noise_floor = max(200.0, (noise_floor * 0.94) + (peak * 0.06))
            dynamic_threshold = max(float(CLAP_THRESHOLD), noise_floor * CLAP_DYNAMIC_RATIO)
            if WAKE_DEBUG and int(now * 10) % 10 == 0:
                print(
                    f"[wake word] clap peak={peak:.0f} "
                    f"noise={noise_floor:.0f} threshold={dynamic_threshold:.0f}"
                )

            if last_clap_at is not None and (now - last_clap_at) > CLAP_RESET_AFTER:
                last_clap_at = None

            if now < cooldown_until or peak < dynamic_threshold:
                continue

            if last_clap_at is None:
                last_clap_at = now
                log_event(
                    "clap_detected",
                    stage="first",
                    peak=round(peak, 1),
                    threshold=round(dynamic_threshold, 1),
                )
                continue

            gap = now - last_clap_at
            if CLAP_MIN_GAP <= gap <= CLAP_MAX_GAP:
                cooldown_until = now + CLAP_COOLDOWN
                last_clap_at = None
                log_event("clap_detected", stage="second", gap=round(gap, 3))
                _trigger("double clap")
                break

            last_clap_at = now
    finally:
        try:
            stream.close()
            pa.terminate()
        except Exception:
            pass


def _listen_loop() -> None:
    if WAKE_METHOD == "clap":
        _listen_loop_clap()
    else:
        _listen_loop_openwakeword()
