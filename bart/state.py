from enum import Enum, auto


class BartState(Enum):
    IDLE = auto()
    LISTENING = auto()
    THINKING = auto()
    SPEAKING = auto()
    CONFIRMING = auto()


STATE_LABELS = {
    BartState.IDLE: "Idle — hold SPACE to speak.",
    BartState.LISTENING: "Listening...",
    BartState.THINKING: "Thinking...",
    BartState.SPEAKING: "Speaking — hold SPACE to interrupt.",
    BartState.CONFIRMING: "Waiting for confirmation (yes/no).",
}
