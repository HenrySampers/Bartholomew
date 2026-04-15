"""
BartWorker — QThread that runs Bart's main loop.

Signals emitted to the UI:
  state_changed(BartState)   — new state to render
  transcript_ready(str)      — what the user said
  reply_ready(str)           — what Bart said
  shutdown_complete()        — quit signal for the app

Interrupt button:
  Call worker.interrupt() from the UI thread.
  This sets _interrupt_event which:
    1. Stops winsound audio mid-playback (via PlaySound(None, SND_PURGE)).
    2. Signals voice.py to return early (checked in the speaking loop).
    3. Discards the current exchange — NO _log_turn() call.
  The interrupted exchange never touches memory.
"""
import os
import threading
import time
import winsound

import keyboard
from PyQt6.QtCore import QThread, pyqtSignal

from ..state import BartState
from .. import brain, ears, voice
from .. import wakeword

WAKE_WORD_ENABLED = os.getenv("WAKE_WORD_ENABLED", "false").lower() == "true"


class BartWorker(QThread):
    state_changed = pyqtSignal(object)        # BartState
    transcript_ready = pyqtSignal(str)        # user speech text
    reply_ready = pyqtSignal(str)             # Bart's reply text
    timer_alert = pyqtSignal(str)             # timer fired
    shutdown_complete = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True
        self._interrupt_event = threading.Event()
        self._state = BartState.IDLE
        self._handle_lock = threading.Lock()  # prevent concurrent _handle_input calls

    # ------------------------------------------------------------------
    # Public API (called from UI thread)
    # ------------------------------------------------------------------

    def interrupt(self):
        """Stop Bart mid-sentence. Does NOT save the interrupted exchange."""
        self._interrupt_event.set()
        # Kill winsound immediately
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass

    def request_shutdown(self):
        self._running = False
        self.interrupt()

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self):
        if WAKE_WORD_ENABLED:
            wakeword.start()

        # Short pause so the window is visible before we start polling keys
        time.sleep(0.5)
        self._set_state(BartState.IDLE)

        from ..skills import timer_tools

        while self._running:
            try:
                # --- Timer alerts ---
                alert = timer_tools.get_alert()
                if alert and self._state == BartState.IDLE:
                    self._speak(alert, log=True)

                # --- Wake word OR space bar ---
                if self._state == BartState.IDLE:
                    triggered = False
                    if WAKE_WORD_ENABLED and wakeword.is_triggered():
                        wakeword.clear_trigger()
                        triggered = True
                    elif keyboard.is_pressed("space"):
                        if WAKE_WORD_ENABLED:
                            wakeword.stop()
                        triggered = True

                    if triggered:
                        self._interrupt_event.clear()
                        if not self._handle_lock.acquire(blocking=False):
                            pass  # already handling
                        else:
                            try:
                                self._handle_input()
                            except Exception as exc:
                                import traceback
                                traceback.print_exc()
                                self._set_state(BartState.IDLE)
                                try:
                                    self.reply_ready.emit("yo something went sideways, try again bro.")
                                except Exception:
                                    pass
                            finally:
                                self._handle_lock.release()
                                if WAKE_WORD_ENABLED:
                                    wakeword.restart()

                time.sleep(0.05)

            except Exception as exc:
                import traceback
                traceback.print_exc()
                time.sleep(0.1)

        if WAKE_WORD_ENABLED:
            wakeword.stop()
        self.shutdown_complete.emit()

    # ------------------------------------------------------------------
    # Core input flow
    # ------------------------------------------------------------------

    def _handle_input(self):
        self._set_state(BartState.LISTENING)

        user_speech = ears.listen_and_transcribe()

        if not user_speech or not user_speech.strip():
            self._set_state(BartState.IDLE)
            self._speak("didn't catch that bro, try again.", log=False)
            return

        self.transcript_ready.emit(user_speech)

        from ..text_utils import is_shutdown_command
        if is_shutdown_command(user_speech):
            self._running = False
            self._set_state(BartState.SPEAKING)
            voice.speak_blocking("later dude.")
            # Mine in background — don't block the shutdown
            threading.Thread(
                target=brain.mine_session_to_palace, daemon=True
            ).start()
            self.shutdown_complete.emit()
            return

        self._set_state(BartState.CONFIRMING if brain.is_confirming() else BartState.THINKING)

        if self._interrupt_event.is_set():
            self._set_state(BartState.IDLE)
            return

        reply = brain.ask_bart(user_speech)

        if self._interrupt_event.is_set():
            self._undo_last_exchange()
            self._set_state(BartState.IDLE)
            return

        self._speak(reply, log=False)  # already logged by brain

    # ------------------------------------------------------------------
    # Speaking with interrupt awareness
    # ------------------------------------------------------------------

    def _speak(self, text: str, log: bool = True):
        """Speak text. Returns early (without saving) if interrupted."""
        if self._interrupt_event.is_set():
            return

        self._set_state(BartState.SPEAKING if not brain.is_confirming() else BartState.CONFIRMING)
        self.reply_ready.emit(text)

        # Wire our interrupt event into voice.py so it can stop mid-playback
        voice._ui_interrupt = self._interrupt_event
        try:
            voice.speak(text, allow_interrupt=True)
        finally:
            voice._ui_interrupt = None

        self._set_state(BartState.IDLE)

    # ------------------------------------------------------------------
    # Undo last exchange from memory if interrupted
    # ------------------------------------------------------------------

    def _undo_last_exchange(self):
        """Remove the last user+assistant turns from history (not logged)."""
        try:
            from .. import memory as mem_module
            from .. import brain as brain_module
            # Pop the last two entries from the in-memory deque
            history = brain_module._history
            if history and history[-1]["role"] == "assistant":
                history.pop()
            if history and history[-1]["role"] == "user":
                history.pop()
            # Remove from SQLite
            mem_module.memory.remove_last_turns(n=2)
        except Exception as exc:
            print(f"[worker] undo error (non-fatal): {exc}")

    # ------------------------------------------------------------------
    # State helper
    # ------------------------------------------------------------------

    def _set_state(self, state: BartState):
        self._state = state
        self.state_changed.emit(state)
