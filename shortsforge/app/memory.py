"""
memory.py - the assistant's notebook ("remember that I like the blur layout").

WHY it exists:
    A good assistant remembers what you told it. You can say "remember that my channel is about
    cooking" and the assistant will keep that in mind in every later chat, even after restarting.

HOW it works:
    - Notes are saved in Documents/ShortsForge/_memory.json (a short list of sentences).
    - When the AI answers, the notes are added to its instructions as DATA (not as commands).
    - You can see and clear them in Settings, or by chat: "what do you remember", "forget everything".

HOW TO IMPROVE:
    - Let the AI propose notes itself (with your approval).
    - Group notes by topic, and drop ones that are old and never used.
"""

import json
import time
from pathlib import Path

MAX_NOTES = 40
MAX_NOTE_LENGTH = 300


class Memory:
    def __init__(self, path):
        self.path = Path(path)

    def all(self) -> list:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return [n for n in data if isinstance(n, dict) and n.get("text")]
        except (OSError, ValueError):
            return []

    def add(self, text: str) -> str:
        """Save a note. Returns the cleaned note, or raises ValueError."""
        text = " ".join(str(text or "").split())[:MAX_NOTE_LENGTH]
        if len(text) < 3:
            raise ValueError("Tell me what to remember.")
        notes = [n for n in self.all() if n["text"].lower() != text.lower()]
        notes.append({"text": text, "time": time.time()})
        self._save(notes[-MAX_NOTES:])
        return text

    def clear(self) -> None:
        self._save([])

    def texts(self) -> list:
        return [n["text"] for n in self.all()]

    def _save(self, notes: list) -> None:
        try:
            self.path.write_text(json.dumps(notes, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass                                      # memory is a convenience, never fatal
