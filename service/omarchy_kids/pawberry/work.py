"""Expected column work, independently checked by the Pawberry verifier.

Parity tests compare this with WorkSteps.js across borrowing through zeros,
carry rows, long multiplication and exact division facts.
"""
import secrets


def generate(problem):
    operation = problem["operation"]
    rng = secrets.SystemRandom()
    if operation == "divide":
        pairs = [(a * b, b) for a in range(2, 10) for b in range(2, 10) if a * b >= 10]
        a, b = rng.choice(pairs)
    else:
        size = max(len(str(problem["a"])), len(str(problem["b"])))
        low = 10 ** (size - 1)
        a, b = rng.randrange(low, low * 10), rng.randrange(low, low * 10)
        if operation == "subtract":
            a, b = max(a, b), min(a, b)
    return {"a": a, "b": b, "operation": operation}


def expected_steps(problem):
    a, b, operation = problem["a"], problem["b"], problem["operation"]
    steps = []
    def add(kind, value):
        steps.append({"kind": kind, "value": value})
    def digit(value, place):
        return value // 10 ** place % 10
    def rows(values):
        carry = 0
        for place in range(max(len(str(value)) for value in values)):
            total = sum(digit(value, place) for value in values) + carry
            add("add-column", total)
            carry = total // 10
            if carry:
                add("add-carry", carry)
    if operation == "add":
        rows([a, b]); answer = a + b
    elif operation == "subtract":
        top = [digit(a, place) for place in range(5)]
        for place in range(max(len(str(a)), len(str(b)))):
            if top[place] < digit(b, place):
                donor = place + 1
                while top[donor] == 0:
                    donor += 1
                top[donor] -= 1; add("borrow-give", top[donor])
                for target in range(donor - 1, place - 1, -1):
                    top[target] += 10; add("borrow-receive", top[target])
                    if target > place:
                        top[target] -= 1; add("borrow-pass", top[target])
            add("subtract-column", top[place] - digit(b, place))
        answer = a - b
    elif operation == "multiply":
        partials = []
        for row in range(len(str(b))):
            multiplier, carry = digit(b, row), 0
            partials.append(a * multiplier * 10 ** row)
            for _ in range(row):
                add("placeholder", 0)
            for place in range(len(str(a))):
                total = digit(a, place) * multiplier + carry
                add("multiply-column", total)
                carry = total // 10
                if carry:
                    add("multiply-carry", carry)
            add("partial-product", partials[-1])
        rows(partials); answer = a * b
    else:
        answer = a // b
        add("divide-groups", answer); add("divide-product", a); add("divide-remainder", 0)
    add("final", answer)
    return steps


def verified(problem, supplied):
    if not isinstance(supplied, list) or len(supplied) > 100:
        return False
    if any(not isinstance(step, dict) or set(step) != {"kind", "value"} or type(step["value"]) is not int for step in supplied):
        return False
    return supplied == expected_steps(problem)
