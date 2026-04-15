"""
Bartholomew (Bart) — entry point.

Hold SPACE to speak, release to send.
Hold SPACE while Bart is speaking to interrupt.
Press ESC to quit.

Or set WAKE_WORD_ENABLED=true in .env and just say 'Bart' to activate.
"""
import os
import time

import keyboard
from dotenv import load_dotenv

load_dotenv()

from bart import brain, ears, voice
from bart import overlay, wakeword
from bart.skills import timer_tools
from bart.state import BartState, STATE_LABELS
from bart.text_utils import normalize_command

OVERLAY_ENABLED = os.getenv("OVERLAY_ENABLED", "true").lower() == "true"
WAKE_WORD_ENABLED = os.getenv("WAKE_WORD_ENABLED", "false").lower() == "true"

# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

_state = BartState.IDLE
_state_holder = [BartState.IDLE]   # shared with overlay thread


def _set_state(new_state: BartState) -> None:
    global _state
    _state = new_state
    _state_holder[0] = new_state
    print(f"  [{STATE_LABELS[new_state]}]")


# ---------------------------------------------------------------------------
# Core loop
# ---------------------------------------------------------------------------

def _handle_input() -> None:
    _set_state(BartState.LISTENING)
    user_speech = ears.listen_and_transcribe()

    if not user_speech or not user_speech.strip():
        _set_state(BartState.IDLE)
        voice.speak("didn't catch that bro, try again.")
        return

    print(f"\n  You: {user_speech}")

    if normalize_command(user_speech) in _SHUTDOWN_PHRASES:
        _shutdown()
        return

    _set_state(BartState.CONFIRMING if brain.is_confirming() else BartState.THINKING)
    reply = brain.ask_bart(user_speech)

    _set_state(BartState.CONFIRMING if brain.is_confirming() else BartState.SPEAKING)
    voice.speak(reply)
    _set_state(BartState.IDLE)


def _shutdown(_event=None) -> None:
    global _running
    _running = False
    _set_state(BartState.SPEAKING)
    voice.speak_blocking("later dude.")


_SHUTDOWN_PHRASES = {
    "quit", "exit", "goodbye", "goodbye bart", "later", "later bart",
    "peace", "peace out", "log off", "sleep", "go to sleep",
    "shut down", "shutdown", "turn off", "turn off bart",
    "turn yourself off", "close", "close bart", "stop running",
}

# ---------------------------------------------------------------------------
# Start-up
# ---------------------------------------------------------------------------

if OVERLAY_ENABLED:
    overlay.start(_state_holder)

if WAKE_WORD_ENABLED:
    wakeword.start()

print()
print("=" * 52)
print("  Bartholomew (Bart) — online.")
if WAKE_WORD_ENABLED:
    print("  Say 'Bart' to activate · ESC to quit")
else:
    print("  Hold SPACE to speak · ESC to quit")
print("  Try: 'what's the weather', 'set a timer for 5 minutes',")
print("       'what's playing', 'play Tame Impala',")
print("       'find my resume', 'volume up'")
print("=" * 52)
print()

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

_running = True
keyboard.on_press_key("esc", _shutdown)

_set_state(BartState.IDLE)

try:
    while _running:
        # Check for fired timers
        alert = timer_tools.get_alert()
        if alert and _state == BartState.IDLE:
            _set_state(BartState.SPEAKING)
            voice.speak(alert)
            _set_state(BartState.IDLE)

        # Activation
        if _state == BartState.IDLE:
            if WAKE_WORD_ENABLED:
                if wakeword.is_triggered():
                    wakeword.clear_trigger()
                    _handle_input()
                    wakeword.restart()
            else:
                if keyboard.is_pressed("space"):
                    _handle_input()

        time.sleep(0.05)

except KeyboardInterrupt:
    _shutdown()
