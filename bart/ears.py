# ears.py
import pyaudio
import wave
import os
import keyboard
import struct
import time
from pathlib import Path
from groq import Groq
from dotenv import load_dotenv

from .logging_utils import log_event, log_timing

load_dotenv()
Path("models/huggingface").mkdir(parents=True, exist_ok=True)
Path("models/whisper").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(Path("models/huggingface").resolve()))
os.environ.setdefault("HF_XET_CACHE", str(Path("models/huggingface/xet").resolve()))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
STT_PROVIDER = os.getenv("STT_PROVIDER", "faster_whisper").strip().lower()
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base.en").strip()
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu").strip()
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8").strip()
_whisper_model = None

FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 1024
MAX_RECORD_SECONDS = 30
MIN_RECORD_SECONDS = 0.4
FOLLOWUP_MAX_RECORD_SECONDS = float(os.getenv("WAKE_FOLLOWUP_MAX_SECONDS", "12"))
FOLLOWUP_START_TIMEOUT = float(os.getenv("WAKE_FOLLOWUP_START_TIMEOUT", "5"))
FOLLOWUP_SILENCE_SECONDS = float(os.getenv("WAKE_FOLLOWUP_SILENCE_SECONDS", "1.0"))
FOLLOWUP_ENERGY_THRESHOLD = int(os.getenv("WAKE_FOLLOWUP_ENERGY_THRESHOLD", "250"))
WAVE_OUTPUT_FILENAME = "bart_temp_audio.wav"


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel

        print(f"Loading local Whisper model: {WHISPER_MODEL} ({WHISPER_DEVICE}, {WHISPER_COMPUTE_TYPE})")
        _whisper_model = WhisperModel(
            WHISPER_MODEL,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
            download_root="models/whisper",
        )
    return _whisper_model


def _transcribe_with_faster_whisper(audio_path):
    started = time.perf_counter()
    model = _get_whisper_model()
    segments, info = model.transcribe(
        audio_path,
        beam_size=5,
        vad_filter=True,
        language="en",
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    log_timing("stt_faster_whisper", (time.perf_counter() - started) * 1000, provider="faster_whisper")
    if not text:
        return ""
    return text


def _transcribe_with_groq(audio_path):
    started = time.perf_counter()
    with open(audio_path, "rb") as file:
        transcription = groq_client.audio.transcriptions.create(
            file=(audio_path, file.read()),
            model="whisper-large-v3-turbo",
            response_format="text"
        )
    log_timing("stt_groq", (time.perf_counter() - started) * 1000, provider="groq")
    return transcription


def _rms(data: bytes) -> float:
    count = len(data) // 2
    if count == 0:
        return 0.0
    shorts = struct.unpack(f"{count}h", data)
    return (sum(sample * sample for sample in shorts) / count) ** 0.5


def _write_wav(audio, frames, output_filename):
    with wave.open(output_filename, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(audio.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b"".join(frames))


def _record_hold_space(output_filename, interrupt_event=None):
    # Wait until SPACE is actually held (guards against spurious triggers).
    deadline = time.time() + 2.0
    while not keyboard.is_pressed("space") and time.time() < deadline:
        if interrupt_event is not None and interrupt_event.is_set():
            return False
        time.sleep(0.02)

    audio = pyaudio.PyAudio()
    print("Bart is listening...")
    stream = audio.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK,
    )

    frames = []
    max_chunks = int(RATE / CHUNK * MAX_RECORD_SECONDS)
    min_chunks = int(RATE / CHUNK * MIN_RECORD_SECONDS)

    try:
        for index in range(max_chunks):
            if interrupt_event is not None and interrupt_event.is_set():
                return False
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)
            if index >= min_chunks and not keyboard.is_pressed("space"):
                break
    finally:
        print("Processing...")
        stream.stop_stream()
        stream.close()
        if frames:
            _write_wav(audio, frames, output_filename)
        audio.terminate()
    return bool(frames)


def _record_until_silence(output_filename, interrupt_event=None):
    audio = pyaudio.PyAudio()
    print("Bart is listening...")
    stream = audio.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK,
    )

    frames = []
    speech_started = False
    started_at = time.time()
    last_voice_at = None
    min_chunks = int(RATE / CHUNK * MIN_RECORD_SECONDS)
    max_chunks = int(RATE / CHUNK * FOLLOWUP_MAX_RECORD_SECONDS)
    silence_chunks = int(RATE / CHUNK * FOLLOWUP_SILENCE_SECONDS)
    quiet_count = 0

    try:
        for index in range(max_chunks):
            if interrupt_event is not None and interrupt_event.is_set():
                return False
            data = stream.read(CHUNK, exception_on_overflow=False)
            energy = _rms(data)

            if energy >= FOLLOWUP_ENERGY_THRESHOLD:
                speech_started = True
                last_voice_at = time.time()
                quiet_count = 0
            elif speech_started:
                quiet_count += 1

            if speech_started:
                frames.append(data)
            elif time.time() - started_at > FOLLOWUP_START_TIMEOUT:
                break

            if speech_started and index >= min_chunks and quiet_count >= silence_chunks:
                break

        if not frames and last_voice_at is None:
            return False
        return True
    finally:
        print("Processing...")
        stream.stop_stream()
        stream.close()
        if frames:
            _write_wav(audio, frames, output_filename)
        audio.terminate()


def listen_and_transcribe(hold_space=True, interrupt_event=None):
    """
    Records audio and returns the transcription.
    hold_space=True records while SPACEBAR is held.
    hold_space=False records the next spoken utterance until silence.
    """
    if hold_space:
        started = time.perf_counter()
        recorded = _record_hold_space(WAVE_OUTPUT_FILENAME, interrupt_event=interrupt_event)
        log_timing("record_hold_space", (time.perf_counter() - started) * 1000, mode="hold_space", recorded=bool(recorded))
        if not recorded:
            return ""
    else:
        started = time.perf_counter()
        recorded = _record_until_silence(WAVE_OUTPUT_FILENAME, interrupt_event=interrupt_event)
        log_timing("record_until_silence", (time.perf_counter() - started) * 1000, mode="followup", recorded=bool(recorded))
        if not recorded:
            return ""

    try:
        if STT_PROVIDER == "groq":
            text = _transcribe_with_groq(WAVE_OUTPUT_FILENAME)
        else:
            text = _transcribe_with_faster_whisper(WAVE_OUTPUT_FILENAME)
        log_event("transcription_complete", provider=STT_PROVIDER, chars=len(text or ""))
        return text
    except Exception as exc:
        log_event("transcription_error", provider=STT_PROVIDER, error=str(exc))
        if STT_PROVIDER != "groq" and os.getenv("GROQ_API_KEY"):
            print(f"Local Whisper failed, trying Groq fallback: {exc}")
            return _transcribe_with_groq(WAVE_OUTPUT_FILENAME)
        raise
    finally:
        if os.path.exists(WAVE_OUTPUT_FILENAME):
            os.remove(WAVE_OUTPUT_FILENAME)
