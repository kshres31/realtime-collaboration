import random

import pytest

from app import ot


def rand_op(rng, doc):
    n, op = ot.u16len(doc), []
    for _ in range(rng.randint(1, 3)):
        if n and rng.random() < 0.5:
            pos = rng.randint(0, n - 1)
            c = {"type": "delete", "pos": pos, "len": rng.randint(1, n - pos)}
        else:
            c = {"type": "insert", "pos": rng.randint(0, n), "text": rng.choice(["x", "yz", "é", "abc"])}
        op.append(c)
        doc = ot.apply(doc, [c])
        n = ot.u16len(doc)
    return op


def test_converges_randomized():
    rng = random.Random(1)
    for _ in range(5000):
        doc = "".join(rng.choice("abcdef") for _ in range(rng.randint(0, 12)))
        a, b = rand_op(rng, doc), rand_op(rng, doc)
        a2, b2 = ot.transform(a, b)
        assert ot.apply(ot.apply(doc, b), a2) == ot.apply(ot.apply(doc, a), b2), (doc, a, b)


def test_insert_tie_puts_committed_text_first():
    a2, _ = ot.transform([{"type": "insert", "pos": 0, "text": "A"}], [{"type": "insert", "pos": 0, "text": "B"}])
    assert ot.apply("B", a2) == "BA"


def test_delete_around_concurrent_insert_keeps_inserted_text():
    a = [{"type": "delete", "pos": 0, "len": 4}]
    b = [{"type": "insert", "pos": 2, "text": "XY"}]
    a2, _ = ot.transform(a, b)
    assert ot.apply(ot.apply("abcd", b), a2) == "XY"


def test_utf16_positions():
    assert ot.apply("😀b", [{"type": "insert", "pos": 2, "text": "a"}]) == "😀ab"
    with pytest.raises(ValueError):
        ot.apply("😀", [{"type": "insert", "pos": 1, "text": "a"}])
    with pytest.raises(ValueError):
        ot.apply("ab", [{"type": "delete", "pos": 1, "len": 5}])
