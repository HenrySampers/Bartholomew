import re


def normalize_command(text):
    normalized = text.strip().lower()
    normalized = re.sub(r"^[,.\s]*(bart|bartholomew)[,.\s]+", "", normalized)
    normalized = re.sub(r"[^a-z0-9 ]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized
