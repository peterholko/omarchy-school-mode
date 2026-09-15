"""Recall practice, progressing from number bonds to familiar rational facts.

The same generator serves offline practice and the root-owned earning quiz.
Earning answers stay on the server until a question has been retired. Grade
bands are practice targets, not deadlines; earlier facts stay in rotation.
"""

from fractions import Fraction
import random
import re
import secrets
import time

GRADES = {
    "grade1": [("add10", 30), ("sub10", 25), ("bond10", 30), ("double5", 15)],
    "grade2": [("add20", 30), ("sub20", 25), ("bond20", 20), ("double10", 15), ("near_double", 10)],
    "grade3": [("add20", 15), ("sub20", 15), ("early_table", 35), ("early_div", 35)],
    "grade4": [("add20", 5), ("sub20", 5), ("table", 45), ("tablediv", 45)],
    "grade5": [("add20", 5), ("sub20", 5), ("hard_table", 35), ("hard_div", 35), ("fraction_decimal", 20)],
    "grade6": [("add20", 5), ("sub20", 5), ("table", 20), ("tablediv", 20),
               ("equivalent", 20), ("percent_of", 10), ("place_value", 10), ("divisibility", 10)],
    "grade7": [("add20", 5), ("sub20", 5), ("table", 10), ("tablediv", 10),
               ("extended_equivalent", 25), ("percent_of", 10), ("place_value", 5),
               ("divisibility", 5), ("signed_table", 15), ("signed_div", 10)],
}
FACT_KINDS = {kind for kinds in GRADES.values() for kind, _ in kinds}
CORE_FRACTIONS = ("1/100", "1/20", "1/10", "1/5", "1/4", "1/2", "3/4", "1")
EXTENDED_FRACTIONS = CORE_FRACTIONS + ("2/5", "3/5", "4/5", "1/8", "3/8", "5/8", "7/8")
THIRDS = (("1/3", "33 1/3%"), ("2/3", "66 2/3%"))
RULES = {
    2: "An even last digit.", 3: "The digit sum is a multiple of 3.",
    4: "The last two digits form a multiple of 4.", 5: "The last digit is 0 or 5.",
    6: "Divisible by both 2 and 3.", 8: "The last three digits form a multiple of 8.",
    9: "The digit sum is a multiple of 9.", 10: "The last digit is 0.",
}


def parse_number(value):
    """Exact, bounded input: integer, decimal, fraction, mixed number or yes/no.

    A percent sign scales the value by 100. No rounding, evaluation, exponents,
    thousands separators or stripping arbitrary characters into valid answers.
    """
    text = str(value).strip().lower().replace("−", "-")
    if len(text) > 40:
        raise ValueError("answer too long")
    if text in ("yes", "no"):
        return text
    percent = text.endswith("%")
    if percent:
        text = text[:-1].strip()
    mixed = re.fullmatch(r"([+-]?\d{1,7})\s+(\d{1,7})/(\d{1,7})", text)
    if mixed:
        whole, numerator, denominator = mixed.groups()
        number = abs(Fraction(whole)) + Fraction(int(numerator), int(denominator))
        if whole.startswith("-"):
            number = -number
    elif re.fullmatch(r"[+-]?(?:\d{1,7}(?:\.\d{0,7})?|\.\d{1,7}|\d{1,7}/\d{1,7})", text):
        number = Fraction(text)
    else:
        raise ValueError("invalid answer")
    return number / 100 if percent else number


def display_number(number):
    number = Fraction(number)
    if number.denominator == 1:
        return number.numerator
    denominator = number.denominator
    for prime in (2, 5):
        while denominator % prime == 0:
            denominator //= prime
    if denominator == 1:
        # All generated finite decimals have at most three decimal places.
        return format(float(number), ".7f").rstrip("0").rstrip(".")
    return str(number)


def _key(kind, text):
    return f"{kind}:{text}"


class Question:
    __slots__ = ("id", "kind", "text", "answer", "key", "issued_at", "hint")

    def __init__(self, kind, text, answer, issued_at, fact=False, hint=""):
        self.id = secrets.token_hex(8)
        self.kind = kind
        self.text = text
        self.answer = answer
        self.key = _key(kind, text) if fact else kind
        self.issued_at = issued_at
        self.hint = hint

    def public(self, reward_seconds, timeout_seconds):
        return {"id": self.id, "text": self.text, "kind": self.kind, **({"hint": self.hint} if self.hint else {}),
                "reward_seconds": reward_seconds, "timeout_seconds": timeout_seconds}

    def choices(self):
        """Unmarked choices, with two candidates for a yes/no fact."""
        rng = secrets.SystemRandom()
        answer = parse_number(self.answer)
        if isinstance(answer, str):
            values = ["yes", "no"]
        elif answer.denominator == 1 and 0 <= answer <= 144:
            nearby = [n for n in range(max(0, int(answer) - 12), min(144, int(answer) + 12) + 1) if n != answer]
            values = [self.answer, *rng.sample(nearby, 5)]
        else:
            step = Fraction(1, answer.denominator)
            offsets = rng.sample([n for n in range(-9, 10) if n], 5)
            values = [self.answer, *(display_number(answer + n * step) for n in offsets)]
        rng.shuffle(values)
        return values


class Generator:
    """One recall fact at a grade, with a cue for unfamiliar answer formats."""

    def __init__(self, rng=None):
        self.rng = rng or random.Random()

    def pick(self, lo, hi):
        return self.rng.choice(range(lo, hi + 1))

    def make(self, kind, table_max=10):
        p, choose = self.pick, self.rng.choice
        if kind in ("add10", "sub10", "bond10", "add20", "sub20", "bond20"):
            limit = 10 if kind.endswith("10") else 20
            if kind.startswith("bond"):
                total = choose((5, 10)) if limit == 10 else choose((10, 20))
                a = p(0, min(10, total)); b = total - a
                return choose(((f"{a} + ? = {total}", b), (f"? + {b} = {total}", a),
                               (f"{total} − ? = {a}", b)))
            a = p(0, 10); b = p(0, min(10, limit - a))
            if kind.startswith("add"):
                return f"{a} + {b}", a + b
            return f"{a + b} - {a}", b
        if kind in ("double5", "double10", "near_double"):
            a = p(0, 9 if kind == "near_double" else 5 if kind == "double5" else 10)
            b = a + 1 if kind == "near_double" else a
            return f"{a} + {b}", a + b
        if kind in ("table", "tablediv", "early_table", "early_div", "hard_table", "hard_div",
                    "signed_table", "signed_div"):
            # Core recall stops at 10 × 10. The harder families occur more
            # often in Grade 5, while zero, one and the easier tables remain.
            family = p(0, 10)
            if kind.startswith("early"):
                family = choose((0, 1, 2, 5, 10))
            if kind.startswith("hard") and self.rng.random() < .75:
                family = choose((3, 4, 6, 7, 8, 9))
            other = p(0, 10)
            division = kind.endswith("div")
            if division and family == 0:
                family = choose((1, 2, 5, 10)) if kind.startswith("early") else p(1, 10)
            if kind.startswith("signed"):
                family *= choose((-1, 1)); other *= choose((-1, 1))
            if division:
                return f"{family * other} ÷ {family}", other
            return f"{family} × {other}", family * other
        if kind in ("fraction_decimal", "equivalent", "extended_equivalent"):
            if kind == "extended_equivalent" and self.rng.random() < .2:
                fraction, percent = choose(THIRDS)
                # An exact fraction answer avoids teaching a rounded decimal
                # as equal to a third. Mixed-number percent inputs also work.
                return f"{percent} = ? (fraction)", fraction
            fraction = choose(EXTENDED_FRACTIONS if kind == "extended_equivalent" else CORE_FRACTIONS)
            value = Fraction(fraction)
            decimal = display_number(value)
            forms = [(fraction, "fraction"), (str(decimal), "decimal")]
            if kind != "fraction_decimal":
                forms.append((f"{display_number(value * 100)}%", "percent"))
            source, target = self.rng.sample(forms, 2)
            return f"{source[0]} = ? ({target[1]})", target[0]
        if kind == "percent_of":
            percent = choose((1, 5, 10, 20, 25, 50, 75))
            whole = choose((20, 40, 60, 80, 100, 200))
            return f"{percent}% of {whole}", display_number(Fraction(percent * whole, 100))
        if kind == "place_value":
            number = choose((1, 2, 5, 10, 12, 25, 50, 100))
            power = choose((10, 100, 1000))
            if choose((True, False)):
                return f"{number} × {power}", number * power
            return f"{number} ÷ {power}", display_number(Fraction(number, power))
        if kind == "divisibility":
            divisor = choose(tuple(RULES))
            number = choose((12, 24, 30, 45, 80, 114, 123, 145, 146, 230, 316, 729, 1024))
            return f"Is {number} divisible by {divisor}?", "yes" if number % divisor == 0 else "no"
        raise ValueError(f"unknown kind {kind}")

    def question(self, level, now=None, weights=None, game=False):
        kinds = GRADES.get(level) or GRADES["grade5"]
        if game:
            # Number Grove's seed tiles hold whole numbers from 0 to 144.
            # Retain its existing table-only reward rounds in the upper grades.
            allowed = {"add10", "sub10", "bond10", "double5", "add20", "sub20", "bond20", "double10", "near_double", "early_table", "early_div", "table", "tablediv", "hard_table", "hard_div"}
            if level in ("grade5", "grade6", "grade7"):
                allowed = {"table", "tablediv", "hard_table", "hard_div"}
            kinds = [(kind, weight) for kind, weight in kinds if kind in allowed]
        pool = [kind for kind, _ in kinds]
        base = [weight * (weights or {}).get(kind, 1.0) for kind, weight in kinds]
        kind = self.rng.choices(pool, weights=base, k=1)[0]
        text, answer = self.make(kind)
        hint = ""
        if "bond" in kind:
            hint = "Fill in the missing number."
        elif kind == "divisibility":
            hint = "Answer yes or no. " + RULES[int(re.search(r"by (\d+)", text)[1])]
        elif kind in ("fraction_decimal", "equivalent", "extended_equivalent"):
            hint = "Use / for fractions and % for percentages. Equivalent exact answers work too."
        elif kind in ("percent_of", "place_value"):
            hint = "A decimal or fraction is fine."
        elif kind.startswith("signed"):
            hint = "Remember the sign: use − for a negative answer."
        return Question(kind, text, answer, time.time() if now is None else now, fact=True, hint=hint)


def practice(level, rng=None):
    """Practice is offline and unrecorded; only earning withholds answers."""
    q = Generator(rng).question(level, 0)
    return {"text": q.text, "answer": q.answer, "kind": q.kind, "hint": q.hint}


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

    def next_question(self, now=None, game=False):
        now = now or time.time()
        level = self.config.get("level", "grade5")
        kind_weights = {k: self._weight(k) for k, _ in GRADES.get(level, GRADES["grade5"])}
        # A fact that went wrong comes back: the kind it belongs to is drawn
        # more often, and within the kind the fact itself is drawn again.
        question = None
        for _ in range(8):
            candidate = self.generator.question(level, now, kind_weights, game=game)
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
            value = parse_number(given)
        except (TypeError, ValueError, ZeroDivisionError):
            return {"ok": False, "error": "not_a_number"}

        if elapsed < self.config["min_answer_seconds"]:
            return {"ok": False, "error": "too_fast",
                    "wait_seconds": round(self.config["min_answer_seconds"] - elapsed, 1)}

        correct = value == parse_number(question.answer)
        self._record(question, correct, now)
        self.pending = None
        return {
            "ok": True,
            "correct": correct,
            "text": question.text,
            "answer": question.answer,
            "given": str(given).strip(),
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
