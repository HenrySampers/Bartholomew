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
from ..logging_utils import log_event, log_process_snapshot, log_timing
from .. import wakeword

WAKE_WORD_ENABLED = os.getenv("WAKE_WORD_ENABLED", "false").lower() == "true"


class BartWorker(QThread):
    state_changed = pyqtSignal(object)        # BartState
    enabled_changed = pyqtSignal(bool)        # whether Bart accepts activation
    transcript_ready = pyqtSignal(str)        # user speech text
    reply_ready = pyqtSignal(str)             # Bart's reply text
    timer_alert = pyqtSignal(str)             # timer fired
    shutdown_complete = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True
        self._enabled = True
        self._interrupt_event = threading.Event()
        self._state = BartState.IDLE
        self._handle_lock = threading.Lock()  # prevent concurrent _handle_input calls
        self._wake_active = False

    # ------------------------------------------------------------------
    # Public API (called from UI thread)
    # ------------------------------------------------------------------

    def interrupt(self):
        """Stop Bart's current listen/think/speak cycle as quickly as possible."""
        self._interrupt_event.set()
        log_event("worker_interrupt", state=str(self._state))
        self._set_state(BartState.IDLE)
        # Kill winsound immediately
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass

    def request_shutdown(self):
        self._running = False
        self.interrupt()

    def set_enabled(self, enabled: bool):
        enabled = bool(enabled)
        if self._enabled == enabled:
            return
        self._enabled = enabled
        log_event("worker_enabled", enabled=self._enabled)
        if not enabled:
            self.interrupt()
            self._set_wake_listening(False)
        else:
            self._interrupt_event.clear()
            self._set_state(BartState.IDLE)
        self.enabled_changed.emit(self._enabled)

    def toggle_enabled(self):
        self.set_enabled(not self._enabled)

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self):
        # Short pause so the window is visible before we start polling keys
        time.sleep(0.5)
        self._set_state(BartState.IDLE)

        from ..skills import timer_tools

        while self._running:
            try:
                if not self._enabled:
                    time.sleep(0.05)
                    continue

                # --- Timer alerts ---
                alert = timer_tools.get_alert()
                if alert and self._state == BartState.IDLE:
                    self._speak(alert, log=True)

                # --- Wake word OR space bar ---
                if self._state == BartState.IDLE:
                    triggered = False
                    hold_space = True
                    if WAKE_WORD_ENABLED and wakeword.is_triggered():
                        wakeword.clear_trigger()
                        triggered = True
                        hold_space = False
                        log_event("activation", source=wakeword.activation_label())
                    elif keyboard.is_pressed("space"):
                        if WAKE_WORD_ENABLED:
                            wakeword.stop()
                        triggered = True
                        log_event("activation", source="space")

                    if triggered:
                        self._interrupt_event.clear()
                        if not self._handle_lock.acquire(blocking=False):
                            pass  # already handling
                        else:
                            try:
                                self._handle_input(hold_space=hold_space)
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

                time.sleep(0.05)

            except Exception as exc:
                import traceback
                traceback.print_exc()
                time.sleep(0.1)

        self._set_wake_listening(False)
        self.shutdown_complete.emit()

    # ------------------------------------------------------------------
    # Core input flow
    # ------------------------------------------------------------------

    def _handle_input(self, hold_space: bool = True):
        cycle_started = time.perf_counter()
        log_process_snapshot("cycle_start", hold_space=hold_space, state=str(self._state))
        self._set_state(BartState.LISTENING)

        stt_started = time.perf_counter()
        user_speech = ears.listen_and_transcribe(
            hold_space=hold_space,
            interrupt_event=self._interrupt_event,
        )
        log_timing("worker_listen_total", (time.perf_counter() - stt_started) * 1000, hold_space=hold_space)

        if self._interrupt_event.is_set():
            self._set_state(BartState.IDLE)
            return

        if not user_speech or not user_speech.strip():
            self._set_state(BartState.IDLE)
            self._speak("didn't catch that bro, try again.", log=False)
            return

        self.transcript_ready.emit(user_speech)
        log_event("transcript", text=user_speech[:200])
        log_process_snapshot("post_transcript", chars=len(user_speech))

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
        if not brain.is_confirming():
            self.reply_ready.emit("on it...")

        if self._interrupt_event.is_set():
            self._set_state(BartState.IDLE)
            return

        think_started = time.perf_counter()
        reply = self._ask_bart_interruptible(user_speech)
        log_timing("worker_think_total", (time.perf_counter() - think_started) * 1000)
        if reply is None:
            self._set_state(BartState.IDLE)
            return

        if self._interrupt_event.is_set():
            self._undo_last_exchange()
            self._set_state(BartState.IDLE)
            return

        self._speak(reply, log=False)  # already logged by brain
        log_timing("worker_cycle_total", (time.perf_counter() - cycle_started) * 1000, interrupted=False)
        log_process_snapshot("cycle_end")

    # ------------------------------------------------------------------
    # Speaking with interrupt awareness
    # ------------------------------------------------------------------

    def _speak(self, text: str, log: bool = True):
        """Speak text. Returns early (without saving) if interrupted."""
        if self._interrupt_event.is_set():
            return

        self._set_state(BartState.SPEAKING if not brain.is_confirming() else BartState.CONFIRMING)
        self.reply_ready.emit(text)
        log_event("reply", text=text[:200], confirmation=brain.is_confirming())

        # Wire our interrupt event into voice.py so it can stop mid-playback
        voice._ui_interrupt = self._interrupt_event
        try:
            speak_started = time.perf_counter()
            voice.speak(text, allow_interrupt=True)
            log_timing("worker_speak_total", (time.perf_counter() - speak_started) * 1000)
        finally:
            voice._ui_interrupt = None

        self._set_state(BartState.IDLE)

    def _ask_bart_interruptible(self, user_speech: str):
        state = {"done": False, "reply": None, "error": None}

        def worker():
            try:
                state["reply"] = brain.ask_bart(user_speech)
            except Exception as exc:
                state["error"] = exc
            finally:
                state["done"] = True

        task = threading.Thread(target=worker, daemon=True)
        task.start()

        while not state["done"]:
            if self._interrupt_event.is_set():
                def cleanup():
                    task.join()
                    if state["reply"] is not None:
                        self._undo_last_exchange()
                    log_event("thinking_cancelled")

                threading.Thread(target=cleanup, daemon=True).start()
                return None
            time.sleep(0.05)

        if state["error"] is not None:
            raise state["error"]
        return state["reply"]

    # ------------------------------------------------------------------
    # Undo last exchange from memory if interrupted
    # ------------------------------------------------------------------

    def _undo_last_exchange(self):
        """Remove the last user+assistant turns from history (not logged)."""
        try:
            from .. import brain as brain_module
            # Pop the last two entries from the in-memory deque
            history = brain_module._history
            if history and history[-1]["role"] == "assistant":
                history.pop()
            if history and history[-1]["role"] == "user":
                history.pop()
            # Remove from SQLite
            brain_module.memory.remove_last_turns(n=2)
        except Exception as exc:
            print(f"[worker] undo error (non-fatal): {exc}")

    # ------------------------------------------------------------------
    # State helper
    # ------------------------------------------------------------------

    def _set_state(self, state: BartState):
        self._state = state
        self._set_wake_listening(
            WAKE_WORD_ENABLED and self._enabled and state == BartState.IDLE
        )
        self.state_changed.emit(state)

    def _set_wake_listening(self, should_listen: bool):
        if not WAKE_WORD_ENABLED:
            return
        if should_listen and not self._wake_active:
            wakeword.start()
            self._wake_active = True
        elif not should_listen and self._wake_active:
            wakeword.stop()
            self._wake_active = False
