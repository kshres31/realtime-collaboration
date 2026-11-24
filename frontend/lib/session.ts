import { apply, transform, type Op } from "./ot.ts";

type ServerMsg =
  | { type: "snapshot"; title: string; content: string; version: number; you: string; users: Record<string, string> }
  | { type: "op"; op: Op; version: number; author: string; conn: string; client_op_id: string | null }
  | { type: "join"; id: string; name: string }
  | { type: "leave"; id: string }
  | { type: "error"; message: string; client_op_id: string | null };

/**
 * Client side of the OT protocol: one op in flight at a time, later local edits buffered,
 * remote ops transformed past both before they are applied. Transport-agnostic so it can be tested.
 */
export class DocSession {
  content = "";
  title = "";
  version = -1; // -1 until the snapshot arrives
  me = "";
  users: Record<string, string> = {};
  private inflight: { id: string; op: Op } | null = null;
  private buffer: Op[] = [];
  private early = new Map<number, Extract<ServerMsg, { type: "op" }>>();
  private seq = 0;

  private send: (msg: object) => void;
  private onChange: (remoteOp: Op | null) => void;
  private onError: (message: string) => void;

  constructor(send: (msg: object) => void, onChange: (remoteOp: Op | null) => void, onError: (message: string) => void) {
    this.send = send;
    this.onChange = onChange;
    this.onError = onError;
  }

  get ready() { return this.version >= 0; }

  edit(op: Op) {
    if (!op.length) return;
    this.content = apply(this.content, op);
    this.buffer.push(op);
    this.flush();
  }

  private flush() {
    if (this.inflight || !this.buffer.length) return;
    this.inflight = { id: `${this.me}-${++this.seq}`, op: this.buffer.shift()! };
    this.send({ type: "op", version: this.version, op: this.inflight.op, client_op_id: this.inflight.id });
  }

  receive(msg: ServerMsg) {
    switch (msg.type) {
      case "snapshot":
        Object.assign(this, { content: msg.content, title: msg.title, version: msg.version, me: msg.you, users: msg.users });
        this.drain();
        this.onChange(null);
        return;
      case "join": this.users = { ...this.users, [msg.id]: msg.name }; this.onChange(null); return;
      case "leave": { const { [msg.id]: _, ...rest } = this.users; this.users = rest; this.onChange(null); return; }
      case "error": this.onError(msg.message); return;
      case "op":
        // ops from different backend instances can arrive out of order, so apply strictly by version
        this.early.set(msg.version, msg);
        if (this.ready) this.drain();
    }
  }

  private drain() {
    for (const v of this.early.keys()) if (v <= this.version) this.early.delete(v);
    let m;
    while ((m = this.early.get(this.version + 1))) {
      this.early.delete(m.version);
      this.version = m.version;
      if (this.inflight && m.conn === this.me && m.client_op_id === this.inflight.id) {
        this.inflight = null;
        this.flush();
        continue;
      }
      let op = m.op;
      if (this.inflight) [this.inflight.op, op] = transform(this.inflight.op, op);
      this.buffer = this.buffer.map((b) => { const [b2, op2] = transform(b, op); op = op2; return b2; });
      this.content = apply(this.content, op);
      this.onChange(op);
    }
  }
}
