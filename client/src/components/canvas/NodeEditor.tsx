import { useEffect, useState } from "react";
import { api } from "../../api/client";

interface Props {
  entityId: string;
  onClose: () => void;
  onSaved: (patch: { canonical_name: string; page_content: string | null }) => void;
}

export default function NodeEditor({ entityId, onClose, onSaved }: Props) {
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.entities
      .get(entityId)
      .then((e) => {
        if (cancelled) return;
        setName(e.canonical_name);
        setContent(e.page_content ?? "");
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [entityId]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api.entities.patch(entityId, {
        canonical_name: name,
        page_content: content,
      });
      onSaved({ canonical_name: name, page_content: content });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="canvas-editor" role="dialog" aria-label="Edit entity">
      <header className="canvas-editor__header">
        <input
          className="canvas-editor__title"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Name"
          disabled={loading || saving}
        />
        <button className="canvas-editor__close" onClick={onClose} aria-label="Close">
          ×
        </button>
      </header>
      {loading ? (
        <div className="canvas-editor__body">Loading…</div>
      ) : (
        <textarea
          className="canvas-editor__body"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Markdown page content"
          disabled={saving}
        />
      )}
      <footer className="canvas-editor__footer">
        {error && <span className="canvas-editor__error">{error}</span>}
        <button className="canvas-editor__cancel" onClick={onClose} disabled={saving}>
          Cancel
        </button>
        <button className="canvas-editor__save" onClick={save} disabled={saving || loading}>
          {saving ? "Saving…" : "Save"}
        </button>
      </footer>
    </div>
  );
}
