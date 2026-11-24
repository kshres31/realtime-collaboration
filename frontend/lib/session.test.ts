import { test } from "node:test";
import assert from "node:assert/strict";
import { apply, diff, transform, transformIndex, type Op } from "./ot.ts";
import { DocSession } from "./session.ts";

function rng(seed: number) {
  return () => ((seed = (seed * 1103515245 + 12345) % 2 ** 31) / 2 ** 31);
}

function randOp(r: () => number, doc: string): Op {
  if (doc.length && r() < 0.5) {
    const pos = Math.floor(r() * doc.length);
    return [{ type: "delete", pos, len: 1 + Math.floor(r() * (doc.length - pos)) }];
  }
  return [{ type: "insert", pos: Math.floor(r() * (doc.length + 1)), text: ["a", "bc", "é"][Math.floor(r() * 3)] }];
}

test("transform converges (same property as the Python suite)", () => {
  const r = rng(7);
  for (let i = 0; i < 3000; i++) {
    const doc = "abcdefgh".slice(0, Math.floor(r() * 9));
    const a = randOp(r, doc), b = randOp(r, doc);
    const [a2, b2] = transform(a, b);
    assert.equal(apply(apply(doc, b), a2), apply(apply(doc, a), b2));
  }
});

test("diff and transformIndex", () => {
  assert.deepEqual(diff("hello", "help"), [{ type: "delete", pos: 3, len: 2 }, { type: "insert", pos: 3, text: "p" }]);
  assert.equal(apply("hello", diff("hello", "jello!")), "jello!");
  assert.equal(transformIndex(3, [{ type: "insert", pos: 0, text: "xx" }]), 5);
  assert.equal(transformIndex(3, [{ type: "delete", pos: 1, len: 5 }]), 1);
});

// In-memory copy of the server's commit logic with a randomly delayed network.
test("three sessions with random latency converge", () => {
  for (let seed = 1; seed <= 30; seed++) {
    const r = rng(seed);
    let content = "start";
    const log: { op: Op; conn: string; id: string }[] = [];
    const queue: (() => void)[] = [];
    const sessions: DocSession[] = [];
    const deliver = (s: DocSession, m: any) => queue.push(() => s.receive(JSON.parse(JSON.stringify(m))));
    for (let i = 0; i < 3; i++) {
      const conn = `c${i}`;
      const s: DocSession = new DocSession(
        (msg: any) => queue.push(() => {
          let op: Op = msg.op;
          for (const prev of log.slice(msg.version)) [op] = transform(op, prev.op);
          content = apply(content, op);
          log.push({ op, conn, id: msg.client_op_id });
          const out = { type: "op", op, version: log.length, author: conn, conn, client_op_id: msg.client_op_id };
          sessions.forEach((t) => deliver(t, out));
        }),
        () => {},
        (e) => assert.fail(e),
      );
      sessions.push(s);
      s.receive({ type: "snapshot", title: "t", content, version: 0, you: conn, users: {} });
    }
    for (let step = 0; step < 300; step++) {
      if (r() < 0.4 || !queue.length) {
        const s = sessions[Math.floor(r() * 3)];
        s.edit(randOp(r, s.content));
      } else {
        queue.splice(Math.floor(r() * queue.length), 1)[0](); // random order = out-of-order delivery
      }
    }
    while (queue.length) queue.shift()!();
    for (const s of sessions) assert.equal(s.content, content, `seed ${seed}`);
  }
});
