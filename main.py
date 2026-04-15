"""
Bartholomew (Bart) — entry point.

Hold SPACE to speak, release to send.
Hold SPACE while Bart is speaking to interrupt him.
Press ESC to shut down.
"""
import time

import keyboard

from bart import brain, ears, voice
from bart.state import BartState, STATE_LABELS
from bart.text_utils import normalize_command

# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

_state = BartState.IDLE


def _set_state(new_state: BartState):
    global _state
    _state = new_state
    print(f"  [{STATE_LABELS[new_state]}]")


# ---------------------------------------------------------------------------
# Core loop handlers
# ---------------------------------------------------------------------------

def _handle_input():
    """One full listen → think → speak cycle."""
    _set_state(BartState.LISTENING)
    user_speech = ears.listen_and_transcribe()

    if not user_speech or not user_speech.strip():
        _set_state(BartState.IDLE)
        voice.speak("I didn't catch that, Sir.")
        return

    print(f"\n  You: {user_speech}")

    # Check for shutdown commands before going to the brain
    if normalize_command(user_speech) in _SHUTDOWN_PHRASES:
        _shutdown()
        return

    _set_state(BartState.CONFIRMING if brain.is_confirming() else BartState.THINKING)
    reply = brain.ask_bart(user_speech)

    # After the brain replies, update state to reflect whether we are now
    # waiting for a confirmation or returning to idle.
    if brain.is_confirming():
        _set_state(BartState.CONFIRMING)
    else:
        _set_state(BartState.SPEAKING)

    interrupted = voice.speak(reply)

    if not interrupted:
        _set_state(BartState.IDLE)


def _shutdown(_event=None):
    global _running
    _running = False
    _set_state(BartState.SPEAKING)
    voice.speak_blocking("Logging off, Sir. Goodbye.")


# ---------------------------------------------------------------------------
# Shutdown phrases
# ---------------------------------------------------------------------------

_SHUTDOWN_PHRASES = {
    "quit", "exit", "goodbye", "goodbye bart",
    "log off", "sleep", "go to sleep",
    "shut down", "shutdown", "turn off",
    "turn off bart", "turn yourself off",
    "close", "close bart", "stop running",
}

# ---------------------------------------------------------------------------
# Start-up banner
# ---------------------------------------------------------------------------

print()
print("=" * 50)
print("  Bartholomew (Bart) — online.")
print("  Hold SPACE to speak · ESC to quit")
print("  Try: 'volume up', 'open Spotify',")
print("       'system stats', 'take a screenshot',")
print("       'add Discord to your apps as discord',")
print("       'remember my timezone is GMT'")
print("=" * 50)
print()

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

_running = True
keyboard.on_press_key("esc", _shutdown)

_set_state(BartState.IDLE)

try:
    while _running:
        if keyboard.is_pressed("space") and _state == BartState.IDLE:
            _handle_input()
        time.sleep(0.05)
except KeyboardInterrupt:
    _shutdown()
