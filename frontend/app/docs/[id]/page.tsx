"use client";
import { use, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { WS_URL } from "@/lib/config.ts";
import { diff, transformIndex } from "@/lib/ot.ts";
import { DocSession } from "@/lib/session.ts";

function displayName() {
  try {
    let n = localStorage.getItem("name");
    if (!n) { n = `guest-${Math.floor(Math.random() * 1000)}`; localStorage.setItem("name", n); }
    return n;
  } catch { return "guest"; }
}

export default function Editor({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const box = useRef<HTMLTextAreaElement>(null);
  const session = useRef<DocSession | null>(null);
  const [, rerender] = useState(0);
  const [status, setStatus] = useState("Connecting…");

  useEffect(() => {
    let ws: WebSocket, timer: ReturnType<typeof setTimeout>, closed = false;
    const connect = () => {
      ws = new WebSocket(`${WS_URL}/ws/documents/${id}?name=${encodeURIComponent(displayName())}`);
      const s = new DocSession(
        (m) => ws.send(JSON.stringify(m)),
        (remoteOp) => {
          const el = box.current;
          if (el && remoteOp) {
            // keep the local caret where it was relative to the text
            const [a, b] = [transformIndex(el.selectionStart, remoteOp), transformIndex(el.selectionEnd, remoteOp)];
            el.value = s.content;
            el.setSelectionRange(a, b);
          } else if (el) el.value = s.content;
          rerender((x) => x + 1);
        },
        (message) => { setStatus(`Server rejected an edit (${message}), reloading…`); ws.close(); },
      );
      session.current = s;
      ws.onopen = () => setStatus("Connected");
      ws.onmessage = (e) => s.receive(JSON.parse(e.data));
      ws.onclose = (e) => {
        if (closed) return;
        if (e.code === 4404) return setStatus("Document not found.");
        // shortcut: edits not yet acknowledged are dropped on reconnect; queue and replay them if this matters
        setStatus("Disconnected, reconnecting…");
        session.current = null;
        rerender((x) => x + 1);
        timer = setTimeout(connect, 1000);
      };
    };
    connect();
    return () => { closed = true; clearTimeout(timer); ws.close(); };
  }, [id]);

  const s = session.current;
  return (
    <>
      <p><Link href="/">← All documents</Link></p>
      <h1>{s?.title || "…"}</h1>
      <p className="status" aria-live="polite">{status}{s?.ready ? ` · v${s.version}` : ""}</p>
      <div className="users" aria-label="People editing">
        {s && Object.entries(s.users).map(([cid, n]) => <span key={cid}>{n}{cid === s.me ? " (you)" : ""}</span>)}
      </div>
      <textarea
        ref={box}
        aria-label="Document text"
        disabled={!s?.ready}
        defaultValue=""
        onChange={(e) => s?.edit(diff(s.content, e.target.value))}
      />
    </>
  );
}
