# ears.py
import pyaudio
import wave
import os
import keyboard
from pathlib import Path
from groq import Groq
from dotenv import load_dotenv

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
    model = _get_whisper_model()
    segments, info = model.transcribe(
        audio_path,
        beam_size=5,
        vad_filter=True,
        language="en",
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    if not text:
        return ""
    return text


def _transcribe_with_groq(audio_path):
    with open(audio_path, "rb") as file:
        transcription = groq_client.audio.transcriptions.create(
            file=(audio_path, file.read()),
            model="whisper-large-v3-turbo",
            response_format="text"
        )
    return transcription

def listen_and_transcribe():
    """
    Records audio while SPACEBAR is held, then returns the transcription.
    """
    # Recording settings
    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    RATE = 16000
    CHUNK = 1024
    MAX_RECORD_SECONDS = 30
    MIN_RECORD_SECONDS = 0.4
    WAVE_OUTPUT_FILENAME = "bart_temp_audio.wav"

    audio = pyaudio.PyAudio()

    print("Bart is listening... (Hold SPACE and speak, release SPACE to send)")
    stream = audio.open(format=FORMAT, channels=CHANNELS,
                        rate=RATE, input=True,
                        frames_per_buffer=CHUNK)

    frames = []
    max_chunks = int(RATE / CHUNK * MAX_RECORD_SECONDS)
    min_chunks = int(RATE / CHUNK * MIN_RECORD_SECONDS)

    for index in range(max_chunks):
        data = stream.read(CHUNK)
        frames.append(data)
        if index >= min_chunks and not keyboard.is_pressed("space"):
            break

    print("Processing, Sir...")
    stream.stop_stream()
    stream.close()
    audio.terminate()

    # Save temp file
    with wave.open(WAVE_OUTPUT_FILENAME, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(audio.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b''.join(frames))

    try:
        if STT_PROVIDER == "groq":
            return _transcribe_with_groq(WAVE_OUTPUT_FILENAME)
        return _transcribe_with_faster_whisper(WAVE_OUTPUT_FILENAME)
    except Exception as exc:
        if STT_PROVIDER != "groq" and os.getenv("GROQ_API_KEY"):
            print(f"Local Whisper failed, trying Groq fallback: {exc}")
            return _transcribe_with_groq(WAVE_OUTPUT_FILENAME)
        raise
    finally:
        if os.path.exists(WAVE_OUTPUT_FILENAME):
            os.remove(WAVE_OUTPUT_FILENAME)
