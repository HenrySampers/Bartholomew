"""
Wake word listener — say 'Bart' (or 'Hey Bart') to activate hands-free.

Uses energy gating + the existing faster-whisper model (tiny.en for speed)
so no extra dependencies are needed. Enable with WAKE_WORD_ENABLED=true in .env.

Flow:
  1. Background thread owns the mic and listens in 1-second windows.
  2. If RMS energy exceeds ENERGY_THRESHOLD, buffer and transcribe.
  3. If 'bart' appears in the transcript, close the mic and set _triggered.
  4. main.py sees _triggered, calls _handle_input() (which opens the mic via ears.py).
  5. After _handle_input() returns, call wakeword.restart() to resume listening.
"""
import os
import struct
import tempfile
import threading
import time
import wave

import pyaudio

CHUNK = 1024
RATE = 16000
ENERGY_THRESHOLD = int(os.getenv("WAKE_ENERGY_THRESHOLD", "400"))
WAKE_PHRASE = os.getenv("WAKE_PHRASE", "bart").lower()
WHISPER_MODEL_SIZE = "tiny.en"

_triggered = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None
_model = None  # lazy-loaded tiny.en model


def is_triggered() -> bool:
    return _triggered.is_set()


def clear_trigger() -> None:
    _triggered.clear()


def start() -> None:
    """Start the wake word listener thread."""
    global _thread
    _stop.clear()
    _triggered.clear()
    _thread = threading.Thread(target=_listen_loop, daemon=True)
    _thread.start()


def restart() -> None:
    """Stop and restart — called after main handles a triggered wake."""
    stop()
    time.sleep(0.3)
    start()


def stop() -> None:
    _stop.set()


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _load_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        print("[wake word] loading tiny.en model...")
        _model = WhisperModel(
            WHISPER_MODEL_SIZE,
            device="cpu",
            compute_type="int8",
            download_root="models/whisper",
        )
        print("[wake word] ready.")
    return _model


def _rms(data: bytes) -> float:
    count = len(data) // 2
    if count == 0:
        return 0.0
    shorts = struct.unpack(f"{count}h", data)
    return (sum(s * s for s in shorts) / count) ** 0.5


def _transcribe(frames: list[bytes], pa: pyaudio.PyAudio) -> str:
    model = _load_model()
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_path = tmp.name
    try:
        with wave.open(tmp_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(pa.get_sample_size(pyaudio.paInt16))
            wf.setframerate(RATE)
            wf.writeframes(b"".join(frames))
        tmp.close()
        segments, _ = model.transcribe(tmp_path, language="en", beam_size=1, vad_filter=True)
        return " ".join(s.text for s in segments).lower()
    except Exception:
        return ""
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _listen_loop() -> None:
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

    buffer: list[bytes] = []
    silent_chunks = 0
    speaking = False

    try:
        while not _stop.is_set():
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
            except Exception:
                break

            energy = _rms(data)

            if energy > ENERGY_THRESHOLD:
                speaking = True
                silent_chunks = 0
                buffer.append(data)
            elif speaking:
                buffer.append(data)
                silent_chunks += 1
                if silent_chunks >= 10:  # ~0.6s of silence = end of utterance
                    transcript = _transcribe(buffer, pa)
                    if WAKE_PHRASE in transcript:
                        import winsound
                        winsound.Beep(1000, 80)   # quick beep = Bart heard you
                        stream.close()
                        pa.terminate()
                        _triggered.set()
                        return
                    buffer = []
                    speaking = False
                    silent_chunks = 0
            else:
                buffer = []
    finally:
        try:
            stream.close()
            pa.terminate()
        except Exception:
            pass
