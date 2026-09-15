"""Issued typing deliveries, with bounded game-only input verification."""
import json
from pathlib import Path
import secrets
from ..core.game_service import GameService

BANK = json.loads(Path(__file__).with_name("lessons.json").read_text())


class Service(GameService):
    module = "typing"

    def challenge(self, message):
        lesson = message.get("lesson", "words")
        if not isinstance(lesson, str) or lesson not in BANK:
            raise ValueError("lesson")
        text = secrets.choice(BANK[lesson])
        # Combine short words into a complete practice delivery.
        while len(text) < 12:
            text += " " + secrets.choice(BANK[lesson])
        return {"text": text, "lesson": lesson}

    def public_challenge(self, pending):
        return {"id": pending["id"], "text": pending["text"], "lesson": pending["lesson"]}

    def verify(self, pending, message, elapsed):
        events = message.get("events")
        if not isinstance(events, list) or not 1 <= len(events) <= 512:
            return {"ok": False, "error": "invalid_input"}
        typed, attempts, correct, previous = "", 0, 0, -1
        for event in events:
            if not isinstance(event, dict) or set(event) != {"key", "ms"}:
                return {"ok": False, "error": "invalid_input"}
            key, stamp = event["key"], event["ms"]
            if type(stamp) is not int or not previous <= stamp <= elapsed * 1000 + 1000 or stamp < 0:
                return {"ok": False, "error": "invalid_timing"}
            previous = stamp
            if key == "Backspace":
                typed = typed[:-1]
            elif isinstance(key, str) and len(key) == 1 and 32 <= ord(key) <= 126:
                attempts += 1
                if len(typed) < len(pending["text"]) and key == pending["text"][len(typed)]:
                    correct += 1
                if len(typed) < len(pending["text"]):
                    typed += key
            else:
                return {"ok": False, "error": "invalid_input"}
        if typed != pending["text"]:
            return {"ok": False, "error": "incomplete_delivery"}
        if elapsed < 2 or previous < max(1500, len(typed) * 50):
            return {"ok": False, "error": "too_fast"}
        # Record accuracy without granting or removing screen time.
        return {"ok": True, "correct": attempts > 0 and correct / attempts >= 0.85,
            "accuracy": round(100 * correct / max(1, attempts))}
