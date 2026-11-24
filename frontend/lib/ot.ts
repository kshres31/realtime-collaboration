// TypeScript port of backend/app/ot.py. Both sides must transform identically.
export type Component =
  | { type: "insert"; pos: number; text: string }
  | { type: "delete"; pos: number; len: number };
export type Op = Component[];

export function apply(doc: string, op: Op): string {
  for (const c of op) {
    if (c.type === "insert") {
      if (c.pos < 0 || c.pos > doc.length) throw new Error("insert out of range");
      doc = doc.slice(0, c.pos) + c.text + doc.slice(c.pos);
    } else {
      if (c.len < 0 || c.pos < 0 || c.pos + c.len > doc.length) throw new Error("delete out of range");
      doc = doc.slice(0, c.pos) + doc.slice(c.pos + c.len);
    }
  }
  return doc;
}

function one(p: Component, q: Component, pWinsTies: boolean): Op {
  if (p.type === "insert") {
    let pos = p.pos;
    if (q.type === "insert") {
      if (q.pos < pos || (q.pos === pos && !pWinsTies)) pos += q.text.length;
    } else if (pos >= q.pos + q.len) pos -= q.len;
    else if (pos > q.pos) pos = q.pos;
    return [{ ...p, pos }];
  }
  const ps = p.pos, pe = p.pos + p.len;
  if (q.type === "insert") {
    const ql = q.text.length;
    if (q.pos <= ps) return [{ ...p, pos: ps + ql }];
    if (q.pos >= pe) return [p];
    const first = q.pos - ps;
    return [
      { type: "delete", pos: ps, len: first },
      { type: "delete", pos: ps + ql, len: p.len - first },
    ];
  }
  const qs = q.pos, qe = q.pos + q.len;
  const shift = Math.max(0, Math.min(qe, ps) - qs);
  const overlap = Math.max(0, Math.min(pe, qe) - Math.max(ps, qs));
  const n = p.len - overlap;
  return n ? [{ type: "delete", pos: ps - shift, len: n }] : [];
}

/** Returns [a', b'] so that apply(apply(d, b), a') === apply(apply(d, a), b'). On insert ties b goes first. */
export function transform(a: Op, b: Op): [Op, Op] {
  if (!a.length || !b.length) return [a, b];
  if (a.length > 1) {
    const [a0, b1] = transform(a.slice(0, 1), b);
    const [rest, b2] = transform(a.slice(1), b1);
    return [[...a0, ...rest], b2];
  }
  if (b.length > 1) {
    const [a1, b0] = transform(a, b.slice(0, 1));
    const [a2, rest] = transform(a1, b.slice(1));
    return [a2, [...b0, ...rest]];
  }
  return [one(a[0], b[0], false), one(b[0], a[0], true)];
}

/** Move a caret index through an op (used to keep the local cursor in place on remote edits). */
export function transformIndex(i: number, op: Op): number {
  for (const c of op) {
    if (c.type === "insert") { if (c.pos < i) i += c.text.length; }
    else if (c.pos < i) i -= Math.min(c.len, i - c.pos);
  }
  return i;
}

/** The op that turns `before` into `after`, as one replaced range. */
export function diff(before: string, after: string): Op {
  let s = 0;
  while (s < before.length && s < after.length && before[s] === after[s]) s++;
  let e = 0;
  while (e < before.length - s && e < after.length - s &&
    before[before.length - 1 - e] === after[after.length - 1 - e]) e++;
  const op: Op = [];
  if (before.length - s - e > 0) op.push({ type: "delete", pos: s, len: before.length - s - e });
  if (after.length - s - e > 0) op.push({ type: "insert", pos: s, text: after.slice(s, after.length - e) });
  return op;
}
