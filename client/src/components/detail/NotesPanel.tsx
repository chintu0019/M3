import { useState } from "react";
import { api, type ItemNote } from "../../api/client";

interface Props {
  itemId: string;
  notes: ItemNote[];
  onRefresh: () => void;
  onReprocess: () => void;
  canReprocess: boolean;
}

function timeAgo(iso: string): string {
  const d = new Date(iso).getTime();
  const secs = Math.round((Date.now() - d) / 1000);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

export default function NotesPanel({ itemId, notes, onRefresh, onReprocess, canReprocess }: Props) {
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");

  const addNote = async () => {
    if (!draft.trim()) return;
    setSaving(true);
    try {
      await api.library.notes.create(itemId, draft.trim());
      setDraft("");
      onRefresh();
    } catch (err) {
      alert(`Failed to add note: ${err}`);
    }
    setSaving(false);
  };

  const saveEdit = async (noteId: string) => {
    if (!editDraft.trim()) return;
    try {
      await api.library.notes.update(itemId, noteId, editDraft.trim());
      setEditingId(null);
      setEditDraft("");
      onRefresh();
    } catch (err) {
      alert(`Failed to save note: ${err}`);
    }
  };

  const deleteNote = async (noteId: string) => {
    if (!confirm("Delete this note?")) return;
    try {
      await api.library.notes.delete(itemId, noteId);
      onRefresh();
    } catch (err) {
      alert(`Failed to delete: ${err}`);
    }
  };

  return (
    <div className="bg-m3-surface border border-m3-border rounded-xl p-4">
      <div className="text-xs uppercase tracking-wide text-m3-muted mb-3">Notes</div>

      {notes.length === 0 && <p className="text-sm text-m3-muted mb-3">No notes yet.</p>}

      <div className="space-y-2 mb-3">
        {notes.map((note) => (
          <div key={note.id} className="bg-m3-bg border border-m3-border rounded-lg p-3 text-sm">
            {editingId === note.id ? (
              <div>
                <textarea
                  value={editDraft}
                  onChange={(e) => setEditDraft(e.target.value)}
                  rows={3}
                  className="w-full bg-m3-surface border border-m3-border rounded p-2 text-sm"
                />
                <div className="flex gap-2 mt-2 justify-end">
                  <button onClick={() => { setEditingId(null); setEditDraft(""); }} className="text-xs text-m3-muted hover:text-m3-text">
                    Cancel
                  </button>
                  <button onClick={() => saveEdit(note.id)} className="text-xs px-2 py-1 bg-m3-accent text-white rounded">
                    Save
                  </button>
                </div>
              </div>
            ) : (
              <div className="group">
                <div className="whitespace-pre-wrap">{note.content}</div>
                <div className="flex items-center justify-between mt-2 text-xs text-m3-muted">
                  <span>{timeAgo(note.created_at)}</span>
                  <div className="opacity-0 group-hover:opacity-100 flex gap-2 transition-opacity">
                    <button onClick={() => { setEditingId(note.id); setEditDraft(note.content); }} className="hover:text-m3-text">Edit</button>
                    <button onClick={() => deleteNote(note.id)} className="hover:text-red-400">Delete</button>
                  </div>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        rows={3}
        placeholder="Add a note..."
        className="w-full bg-m3-bg border border-m3-border rounded p-2 text-sm"
      />
      <div className="flex justify-between items-center mt-2">
        <button
          onClick={onReprocess}
          disabled={!canReprocess || notes.length === 0}
          className="text-sm px-3 py-1.5 bg-m3-bg border border-m3-border rounded hover:border-m3-muted disabled:opacity-40 disabled:cursor-not-allowed"
          title={notes.length === 0 ? "Add a note first" : !canReprocess ? "Already processing" : ""}
        >
          ↻ Reprocess with notes
        </button>
        <button
          onClick={addNote}
          disabled={saving || !draft.trim()}
          className="text-sm px-3 py-1.5 bg-m3-accent text-white rounded hover:bg-m3-accent-hover disabled:opacity-50"
        >
          {saving ? "Saving..." : "Add note"}
        </button>
      </div>
    </div>
  );
}
