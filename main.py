from bart import ears, brain, voice
import keyboard
import time
from bart.text_utils import normalize_command

is_running = True


def handle_space_press():
    try:
        print("\n[Listening...]")
        # 1. Listen
        user_speech = ears.listen_and_transcribe()
        print(f"You: {user_speech}")

        # Ignore empty input
        if not user_speech or user_speech.strip() == "":
            return voice.speak("I didn't catch that, Sir.")

        normalized_speech = normalize_command(user_speech)
        if normalized_speech in {
            "quit",
            "exit",
            "goodbye",
            "goodbye bart",
            "log off",
            "sleep",
            "go to sleep",
            "shut down",
            "shutdown",
            "turn off",
            "turn off bart",
            "turn yourself off",
            "close",
            "close bart",
            "stop running",
        }:
            quit_program()
            return False

        # 2. Think
        print("[Bart is thinking...]")
        bart_reply = brain.ask_bart(user_speech)

        # 3. Speak
        return voice.speak(bart_reply)

    except Exception as e:
        print(f"Critical Error: {e}")
        return voice.speak("My apologies, Sir. An unexpected error occurred.")

# --- Quit Handler ---
def quit_program(event=None):
    global is_running
    is_running = False
    voice.speak_blocking("Logging off, Sir. Goodbye.")

print("========================================")
print("Bartholomew (Bart) Online. Ready to serve, Sir.")
print("Hold SPACEBAR to speak, release to send. Press SPACE while Bart talks to interrupt.")
print("Press ESC to quit.")
print("Try: 'remember my favourite editor is VS Code', 'open notepad', or 'search Python pyttsx3'.")
print("========================================")

keyboard.on_press_key("esc", quit_program)

try:
    while is_running:
        if keyboard.is_pressed("space"):
            interrupted = handle_space_press()
            if not interrupted:
                time.sleep(0.25)
        time.sleep(0.05)
except KeyboardInterrupt:
    quit_program()
