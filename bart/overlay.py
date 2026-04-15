"""
Minimal always-on-top tkinter overlay showing Bart's current state.
Runs in a daemon thread. Toggle with OVERLAY_ENABLED=true in .env.
"""
import threading
import tkinter as tk

from .state import BartState

_STATE_STYLE = {
    BartState.IDLE:       ("#0d0d0d", "#4ecdc4", "BART  idle"),
    BartState.LISTENING:  ("#0d0d0d", "#ff6b6b", "BART  listening"),
    BartState.THINKING:   ("#0d0d0d", "#ffd93d", "BART  thinking"),
    BartState.SPEAKING:   ("#0d0d0d", "#6bcb77", "BART  speaking"),
    BartState.CONFIRMING: ("#0d0d0d", "#ff922b", "BART  confirm?"),
}


def start(state_holder: list) -> None:
    """
    state_holder is a single-element list so the overlay thread can read
    state updates written by the main thread without extra locking.
    """
    t = threading.Thread(target=_run, args=(state_holder,), daemon=True)
    t.start()


def _run(state_holder: list) -> None:
    root = tk.Tk()
    root.title("Bart")
    root.overrideredirect(True)      # no title bar / borders
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.88)

    w, h = 190, 34
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{sw - w - 12}+{sh - h - 52}")

    label = tk.Label(
        root,
        text="BART  idle",
        font=("Consolas", 10, "bold"),
        bg="#0d0d0d",
        fg="#4ecdc4",
        anchor="w",
        padx=12,
    )
    label.pack(fill="both", expand=True)

    def _tick():
        state = state_holder[0]
        bg, fg, text = _STATE_STYLE.get(state, ("#0d0d0d", "#ffffff", "BART"))
        label.config(text=text, bg=bg, fg=fg)
        root.configure(bg=bg)
        root.after(120, _tick)

    _tick()
    root.mainloop()
