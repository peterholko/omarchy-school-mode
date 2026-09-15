"""Arithmetic challenge verification for previously installed clients."""
import secrets
from ..core.game_service import GameService


class Service(GameService):
    module = "grove"

    def challenge(self, message):
        grade = message.get("grade", 5)
        if type(grade) is not int or not 1 <= grade <= 6:
            raise ValueError("grade")
        rng = secrets.SystemRandom()
        operations = ["+", "−"] if grade == 1 else ["+", "−", "×"] if grade == 2 else ["+", "−", "×", "÷"] if grade < 5 else ["×", "÷"]
        operation = rng.choice(operations)
        maximum = 10 if grade == 3 else 12
        if operation in ("+", "−"):
            a, b = rng.randint(2, 10), rng.randint(2, 10)
            if operation == "+":
                answer = a + b
            else:
                a += b; answer = a - b
        elif operation == "×":
            a, b = rng.randint(2, 5 if grade == 2 else maximum), rng.randint(2, 10 if grade == 2 else maximum)
            answer = a * b
        else:
            b, answer = rng.randint(2, maximum), rng.randint(2, maximum); a = b * answer
        alternatives = [n for n in range(max(0, answer - 12), min(144, answer + 12) + 1) if n != answer]
        choices = [answer, *rng.sample(alternatives, 5)]; rng.shuffle(choices)
        return {"text": f"{a} {operation} {b}", "answer": answer, "choices": choices, "grade": grade}

    def public_challenge(self, pending):
        return {"question": {key: pending[key] for key in ("id", "text", "choices")},
            "level": "grade" + str(pending["grade"]), "questions_per_set": 10}

    def verify(self, pending, message, elapsed):
        value = message.get("answer")
        if type(value) is not int or value not in pending["choices"]:
            return {"ok": False, "error": "invalid_answer"}
        return {"ok": True, "correct": value == pending["answer"], "answer": pending["answer"]}
