"""Questions that buy minutes, at a grade.

Two rules shape this file. The answer is never sent to the client, because the
client runs on the child's own machine and a text editor is not a challenge.
And the questions are weighted by what went wrong before, so the fact that is
actually missing comes back around instead of the one they already know.

Every grade practises facts for recall. Grades 1 to 4 include addition pairs
through 10 + 10 and their subtraction inverses. Grade 2 introduces the tables
of 2 to 5; grade 3 reaches 10 × 10; grade 4 reaches 12 × 12. Grades 5 and 6
practise only multiplication and division tables through 12 × 12. All facts
are remembered one by one, so a missed fact can come round again.
"""

import random
import secrets
import time

# kind -> weight, per grade; the roll picks a kind, then the operands.
GRADES = {
    "grade1": [("add20", 55), ("sub20", 45)],
    "grade2": [("add20", 40), ("sub20", 35), ("mulsmall", 25)],
    "grade3": [("add20", 25), ("sub20", 20), ("table", 30), ("tablediv", 25)],
    "grade4": [("add20", 20), ("sub20", 20), ("table", 30), ("tablediv", 30)],
    "grade5": [("table", 50), ("tablediv", 50)],
    "grade6": [("table", 50), ("tablediv", 50)],
}

# The kinds whose operands are few enough to be remembered one by one.
FACT_KINDS = {"add20", "sub20", "mulsmall", "table", "tablediv"}


def _key(kind, text):
    return f"{kind}:{text}"


class Question:
    __slots__ = ("id", "kind", "text", "answer", "key", "issued_at")

    def __init__(self, kind, text, answer, issued_at, fact=False):
        self.id = secrets.token_hex(8)
        self.kind = kind
        self.text = text
        self.answer = answer
        # Facts are remembered by their operands, the rest by their kind.
        self.key = _key(kind, text) if fact else kind
        self.issued_at = issued_at

    def public(self, reward_seconds, timeout_seconds):
        return {
            "id": self.id,
            "text": self.text,
            "kind": self.kind,
            "reward_seconds": reward_seconds,
            "timeout_seconds": timeout_seconds,
        }

    def choices(self):
        """Six unordered candidates; the answer stays unmarked on the server."""
        rng = secrets.SystemRandom()
        nearby = [n for n in range(max(0, self.answer - 12), min(144, self.answer + 12) + 1)
                  if n != self.answer]
        values = [self.answer, *rng.sample(nearby, 5)]
        rng.shuffle(values)
        return values


class Generator:
    """One question at a grade. Shared by the earning quiz and practice."""

    def __init__(self, rng=None):
        self.rng = rng or random.Random()

    def pick(self, lo, hi):
        """An operand in [lo, hi], including ten for number bonds and tables."""
        return self.rng.choice(range(lo, hi + 1))

    def make(self, kind, table_max=12):
        """(text, answer) for a kind. Every text is "a op b", plain."""
        p = self.pick
        if kind == "add20":
            a = p(2, 10); b = p(2, 10); return f"{a} + {b}", a + b
        if kind == "sub20":
            a = p(2, 10); b = p(2, 10); return f"{a + b} - {a}", b
        if kind == "mulsmall":
            a = p(2, 5); b = p(2, 10); return f"{a} × {b}", a * b
        if kind == "table":
            a = p(2, table_max); b = p(2, table_max); return f"{a} × {b}", a * b
        if kind == "tablediv":
            b = p(2, table_max); c = p(2, table_max); return f"{b * c} ÷ {b}", c
        raise ValueError(f"unknown kind {kind}")

    def question(self, level, now=None, weights=None):
        kinds = GRADES.get(level) or GRADES["grade5"]
        pool = [k for k, _ in kinds]
        base = [w for _, w in kinds]
        if weights:
            base = [b * weights.get(k, 1.0) for b, k in zip(base, pool)]
        kind = self.rng.choices(pool, weights=base, k=1)[0]
        text, answer = self.make(kind, table_max=10 if level == "grade3" else 12)
        return Question(kind, text, answer, now or time.time(), fact=kind in FACT_KINDS)


def practice(level, rng=None):
    """A question with its answer, for practice: checked by the app, recorded by nobody."""
    q = Generator(rng).question(level, 0)
    return {"text": q.text, "answer": q.answer, "kind": q.kind}


class Quiz:
    """Generates earning questions for one account and remembers how it went."""

    def __init__(self, earn_config, stats=None, rng=None):
        self.config = earn_config
        self.stats = stats if isinstance(stats, dict) else {}
        self.generator = Generator(rng)
        self.pending = None
        self.last_key = None

    def _weight(self, key):
        record = self.stats.get(key) or {}
        seen = max(0, int(record.get("seen", 0)))
        wrong = max(0, int(record.get("wrong", 0)))
        weight = 1.0
        if self.config.get("drill_weak") and seen:
            weight += 4.0 * (wrong / seen)
            if record.get("last_wrong") and time.time() - record["last_wrong"] < 86400:
                weight += 2.0
        return weight

    def next_question(self, now=None):
        now = now or time.time()
        level = self.config.get("level", "grade5")
        kind_weights = {k: self._weight(k) for k, _ in GRADES.get(level, GRADES["grade5"])}
        # A fact that went wrong comes back: the kind it belongs to is drawn
        # more often, and within the kind the fact itself is drawn again.
        question = None
        for _ in range(8):
            candidate = self.generator.question(level, now, kind_weights)
            if candidate.key == self.last_key:
                question = question or candidate
                continue
            question = candidate
            if not self.config.get("drill_weak") or self._weight(candidate.key) > 1.0:
                break
        self.pending = question
        self.last_key = question.key
        return question

    # answering ----------------------------------------------------------

    def answer(self, question_id, given, now=None):
        """Judge an answer. Returns a verdict dict; never leaks the answer of a
        question that is still open."""
        now = now or time.time()
        question = self.pending
        if not question or question.id != question_id:
            return {"ok": False, "error": "no_such_question"}

        elapsed = now - question.issued_at
        if elapsed > self.config["question_timeout_seconds"]:
            self.pending = None
            return {"ok": False, "error": "expired", "text": question.text}

        try:
            value = int(str(given).strip().replace(",", "").replace(" ", ""))
        except (TypeError, ValueError):
            return {"ok": False, "error": "not_a_number"}

        if elapsed < self.config["min_answer_seconds"]:
            return {"ok": False, "error": "too_fast",
                    "wait_seconds": round(self.config["min_answer_seconds"] - elapsed, 1)}

        correct = value == question.answer
        self._record(question, correct, now)
        self.pending = None
        return {
            "ok": True,
            "correct": correct,
            "text": question.text,
            "answer": question.answer,
            "given": value,
            "seconds_taken": round(elapsed, 1),
        }

    def _record(self, question, correct, now):
        record = self.stats.setdefault(question.key, {"seen": 0, "wrong": 0})
        record["seen"] = int(record.get("seen", 0)) + 1
        if not correct:
            record["wrong"] = int(record.get("wrong", 0)) + 1
            record["last_wrong"] = round(now, 1)

    def weakest(self, limit=5):
        """The facts and kinds worth practising, for the parent."""
        rows = []
        for key, record in self.stats.items():
            seen = int(record.get("seen", 0))
            wrong = int(record.get("wrong", 0))
            if seen >= 2 and wrong:
                text = key.split(":", 1)[1] if ":" in key else key
                rows.append({"text": text, "seen": seen, "wrong": wrong, "rate": round(wrong / seen, 2)})
        rows.sort(key=lambda row: (row["rate"], row["wrong"]), reverse=True)
        return rows[:limit]
