import { useState } from "react";
import { api } from "../api/client";

export default function IngestDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submitText() {
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.ingestText(text.trim(), "web");
      setResult(`ingested ${res.item_id.slice(0, 8)} (${res.kind}, conf ${res.confidence.toFixed(2)})`);
      setText("");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function submitFile(f: File) {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.ingestFile(f, "web");
      setResult(`ingested ${res.item_id.slice(0, 8)} (${res.kind}, conf ${res.confidence.toFixed(2)})`);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;
  return (
    <div className="fixed inset-0 bg-black/50 z-50" onClick={onClose}>
      <div
        className="absolute right-0 top-0 h-full w-full max-w-md bg-m3-bg border-l border-m3-border p-6 overflow-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center mb-4">
          <h2 className="text-lg font-bold flex-1">Ingest</h2>
          <button onClick={onClose} className="text-m3-muted hover:text-m3-text">✕</button>
        </div>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Paste text, thought, note…"
          rows={8}
          className="w-full bg-m3-surface border border-m3-border rounded-lg p-3 text-sm focus:outline-none focus:border-m3-accent"
        />
        <button
          disabled={busy || !text.trim()}
          onClick={submitText}
          className="mt-2 w-full px-4 py-2 rounded bg-m3-accent hover:bg-m3-accent-hover disabled:opacity-50"
        >
          {busy ? "working…" : "ingest text"}
        </button>
        <div className="mt-4 text-sm text-m3-muted">Or drop a file:</div>
        <input
          type="file"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) submitFile(f);
          }}
          className="mt-2 w-full text-sm"
        />
        {result && <div className="mt-4 text-sm text-green-400">{result}</div>}
        {error && <div className="mt-4 text-sm text-red-400">{error}</div>}
      </div>
    </div>
  );
}
