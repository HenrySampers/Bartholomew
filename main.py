"""
Bartholomew (Bart) — entry point.

Hold SPACE to speak, release to send.
Hold SPACE while Bart is speaking to interrupt.
Press ESC to quit.

Or set WAKE_WORD_ENABLED=true in .env and use the configured wake model.
"""
import os
import time

import keyboard
from dotenv import load_dotenv

load_dotenv()

from bart.logging_utils import setup_console_logging
from bart.logging_utils import log_event, log_process_snapshot, log_timing

setup_console_logging("bart_cli")

from bart import brain, ears, voice
from bart import overlay, wakeword
from bart.skills import timer_tools
from bart.state import BartState, STATE_LABELS
from bart.text_utils import is_shutdown_command

OVERLAY_ENABLED = os.getenv("OVERLAY_ENABLED", "true").lower() == "true"
WAKE_WORD_ENABLED = os.getenv("WAKE_WORD_ENABLED", "false").lower() == "true"
WAKE_WORD_LABEL = wakeword.activation_label()

# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

_state = BartState.IDLE
_state_holder = [BartState.IDLE]   # shared with overlay thread
_wake_active = False


def _set_state(new_state: BartState) -> None:
    global _state
    _state = new_state
    _state_holder[0] = new_state
    _set_wake_listening(WAKE_WORD_ENABLED and new_state == BartState.IDLE)
    print(f"  [{STATE_LABELS[new_state]}]")


def _set_wake_listening(should_listen: bool) -> None:
    global _wake_active
    if not WAKE_WORD_ENABLED:
        return
    if should_listen and not _wake_active:
        wakeword.start()
        _wake_active = True
    elif not should_listen and _wake_active:
        wakeword.stop()
        _wake_active = False


# ---------------------------------------------------------------------------
# Core loop
# ---------------------------------------------------------------------------

def _handle_input(hold_space: bool = True) -> None:
    cycle_started = time.perf_counter()
    log_process_snapshot("cli_cycle_start", hold_space=hold_space)
    _set_state(BartState.LISTENING)
    listen_started = time.perf_counter()
    user_speech = ears.listen_and_transcribe(hold_space=hold_space)
    log_timing("cli_listen_total", (time.perf_counter() - listen_started) * 1000, hold_space=hold_space)

    if not user_speech or not user_speech.strip():
        _set_state(BartState.IDLE)
        voice.speak("didn't catch that bro, try again.")
        return

    print(f"\n  You: {user_speech}")
    log_event("cli_transcript", text=user_speech[:200])

    if is_shutdown_command(user_speech):
        _shutdown()
        return

    _set_state(BartState.CONFIRMING if brain.is_confirming() else BartState.THINKING)
    think_started = time.perf_counter()
    reply = brain.ask_bart(user_speech)
    log_timing("cli_think_total", (time.perf_counter() - think_started) * 1000)

    _set_state(BartState.CONFIRMING if brain.is_confirming() else BartState.SPEAKING)
    speak_started = time.perf_counter()
    voice.speak(reply)
    log_timing("cli_speak_total", (time.perf_counter() - speak_started) * 1000)
    _set_state(BartState.IDLE)
    log_timing("cli_cycle_total", (time.perf_counter() - cycle_started) * 1000)
    log_process_snapshot("cli_cycle_end")


def _shutdown(_event=None) -> None:
    global _running
    _running = False
    _set_state(BartState.SPEAKING)
    voice.speak_blocking("later dude.")


# ---------------------------------------------------------------------------
# Start-up
# ---------------------------------------------------------------------------

if OVERLAY_ENABLED:
    overlay.start(_state_holder)

print()
print("=" * 52)
print("  Bartholomew (Bart) — online.")
if WAKE_WORD_ENABLED:
    if WAKE_WORD_LABEL == "double clap":
        print("  Double clap to activate · ESC to quit")
    else:
        print(f"  Say '{WAKE_WORD_LABEL}' to activate · ESC to quit")
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
                    _handle_input(hold_space=False)
            else:
                if keyboard.is_pressed("space"):
                    _handle_input()

        time.sleep(0.05)

except KeyboardInterrupt:
    _shutdown()
