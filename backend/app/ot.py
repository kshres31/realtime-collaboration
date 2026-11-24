"""Operational transform for plain text.

An operation is a list of components applied in order:
  {"type": "insert", "pos": int, "text": str}
  {"type": "delete", "pos": int, "len": int}
Positions and lengths count UTF-16 code units so they match JavaScript strings in the browser.
"""


def u16len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def apply(doc: str, op: list[dict]) -> str:
    b = doc.encode("utf-16-le")
    for c in op:
        pos = c["pos"]
        if c["type"] == "insert":
            if not 0 <= pos <= len(b) // 2:
                raise ValueError("insert out of range")
            b = b[: pos * 2] + c["text"].encode("utf-16-le") + b[pos * 2 :]
        elif c["type"] == "delete":
            if c["len"] < 0 or not 0 <= pos <= pos + c["len"] <= len(b) // 2:
                raise ValueError("delete out of range")
            b = b[: pos * 2] + b[(pos + c["len"]) * 2 :]
        else:
            raise ValueError("unknown component type")
    try:
        return b.decode("utf-16-le")
    except UnicodeDecodeError as e:  # an edit split a surrogate pair
        raise ValueError("edit splits a character") from e


def _one(p: dict, q: dict, p_wins_ties: bool) -> list[dict]:
    """Rewrite component p so it applies after component q."""
    if p["type"] == "insert":
        pos = p["pos"]
        if q["type"] == "insert":
            if q["pos"] < pos or (q["pos"] == pos and not p_wins_ties):
                pos += u16len(q["text"])
        else:
            qs, qe = q["pos"], q["pos"] + q["len"]
            if pos >= qe:
                pos -= q["len"]
            elif pos > qs:
                pos = qs
        return [{**p, "pos": pos}]

    ps, pe = p["pos"], p["pos"] + p["len"]
    if q["type"] == "insert":
        qp, ql = q["pos"], u16len(q["text"])
        if qp <= ps:
            return [{**p, "pos": ps + ql}]
        if qp >= pe:
            return [p]
        # insert landed inside the deleted range: delete around it, keep the inserted text
        first = qp - ps
        return [{"type": "delete", "pos": ps, "len": first},
                {"type": "delete", "pos": ps + ql, "len": p["len"] - first}]
    qs, qe = q["pos"], q["pos"] + q["len"]
    shift = max(0, min(qe, ps) - qs)
    overlap = max(0, min(pe, qe) - max(ps, qs))
    n = p["len"] - overlap
    return [{"type": "delete", "pos": ps - shift, "len": n}] if n else []


def transform(a: list[dict], b: list[dict]) -> tuple[list[dict], list[dict]]:
    """Given ops a and b on the same document, return (a', b') with
    apply(apply(d, b), a') == apply(apply(d, a), b').
    On an insert tie at the same position, b's text goes first."""
    if not a or not b:
        return a, b
    if len(a) > 1:
        a0, b1 = transform(a[:1], b)
        rest, b2 = transform(a[1:], b1)
        return a0 + rest, b2
    if len(b) > 1:
        a1, b0 = transform(a, b[:1])
        a2, rest = transform(a1, b[1:])
        return a2, b0 + rest
    return _one(a[0], b[0], False), _one(b[0], a[0], True)
