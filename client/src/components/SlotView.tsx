import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { api } from "../api/client";

export default function SlotView({
  name,
  content,
  onSaved,
}: {
  name: string;
  content: string;
  onSaved?: () => void;
}) {
  const isEmpty = content.trim() === "_(empty)_" || content.trim() === "";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function startEdit() {
    setDraft(isEmpty ? "" : content);
    setEditing(true);
    setErr(null);
  }

  async function save() {
    setSaving(true);
    setErr(null);
    try {
      await api.updateSelfSection(name, draft);
      setEditing(false);
      onSaved?.();
    } catch (e) {
      setErr(String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="mb-8">
      <div className="flex items-center gap-3 mb-2">
        <h2 className="text-lg font-semibold">{name}</h2>
        {!editing && (
          <button
            onClick={startEdit}
            className="text-xs text-m3-muted hover:text-m3-text px-2 py-0.5 rounded hover:bg-m3-surface"
          >
            edit
          </button>
        )}
      </div>

      {editing ? (
        <div>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="w-full h-40 bg-m3-surface border border-m3-border rounded p-3 text-sm font-mono"
            placeholder="(empty — save to clear)"
          />
          <div className="mt-2 flex gap-2 items-center">
            <button
              onClick={save}
              disabled={saving}
              className="px-3 py-1 rounded bg-m3-accent text-white text-sm hover:bg-m3-accent-hover disabled:opacity-50"
            >
              {saving ? "saving…" : "save"}
            </button>
            <button
              onClick={() => setEditing(false)}
              disabled={saving}
              className="px-3 py-1 rounded bg-m3-surface text-m3-text text-sm hover:bg-m3-border"
            >
              cancel
            </button>
            {err && <span className="text-red-400 text-sm">{err}</span>}
          </div>
        </div>
      ) : isEmpty ? (
        <p className="text-m3-muted text-sm italic">(empty)</p>
      ) : (
        <div className="text-sm leading-relaxed text-m3-text">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        </div>
      )}
    </section>
  );
}
