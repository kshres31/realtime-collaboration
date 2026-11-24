"use client";
import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { API_URL } from "@/lib/config.ts";

type Doc = { id: string; title: string; version: number; updated_at: string };

export default function Home() {
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");

  const load = () =>
    fetch(`${API_URL}/documents`).then((r) => r.json()).then(setDocs).catch(() => setError("Could not reach the API."));
  useEffect(() => { load(); }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    const r = await fetch(`${API_URL}/documents`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }),
    });
    if (!r.ok) return setError("Could not create the document.");
    setTitle("");
    load();
  }

  return (
    <>
      <h1>Documents</h1>
      <form onSubmit={create} style={{ display: "flex", gap: 8 }}>
        <input aria-label="New document title" placeholder="New document title" value={title}
          onChange={(e) => setTitle(e.target.value)} required maxLength={200} style={{ flex: 1 }} />
        <button>Create</button>
      </form>
      {error && <p role="alert">{error}</p>}
      {docs === null ? <p className="status">Loading…</p> : (
        <ul className="docs">
          {docs.map((d) => (
            <li key={d.id}>
              <Link href={`/docs/${d.id}`}>{d.title}</Link>{" "}
              <span className="status">v{d.version} · {new Date(d.updated_at).toLocaleString()}</span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
