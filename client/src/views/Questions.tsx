import { useState } from "react";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";

function QuestionRow({ q, onResolve }: { q: string; onResolve: (text: string, answer: string) => Promise<void> }) {
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);

  // The question text from the backend has the full checklist suffix "(created ..., item: ...)".
  // Extract just the question part for the submit payload.
  const questionText = q.split(" (created ")[0].split(" — ")[0];

  return (
    <li className="border border-m3-border rounded-lg p-4 mb-3">
      <div className="mb-3">{q}</div>
      <div className="flex gap-2">
        <input
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          placeholder="Answer…"
          className="flex-1 bg-m3-surface border border-m3-border rounded px-3 py-1.5 text-sm focus:outline-none focus:border-m3-accent"
        />
        <button
          disabled={!answer.trim() || busy}
          onClick={async () => {
            setBusy(true);
            await onResolve(questionText, answer);
            setBusy(false);
          }}
          className="px-3 py-1.5 rounded text-sm bg-m3-accent hover:bg-m3-accent-hover disabled:opacity-50"
        >
          resolve
        </button>
      </div>
    </li>
  );
}

export default function Questions() {
  const { data, error, loading, refetch } = useApi(() => api.openQuestions());

  async function handleResolve(text: string, answer: string) {
    await api.resolveQuestion(text, answer);
    refetch();
  }

  if (loading) return <div className="p-6 text-m3-muted">loading…</div>;
  if (error) return <div className="p-6 text-red-400">{error}</div>;
  if (!data || data.questions.length === 0) {
    return <div className="p-6 text-m3-muted">No open questions — you're caught up.</div>;
  }
  return (
    <div className="max-w-3xl mx-auto p-6">
      <h1 className="text-2xl font-bold mb-6">Open questions</h1>
      <ul>
        {data.questions.map((entry, i) => (
          <QuestionRow key={i} q={entry.question} onResolve={handleResolve} />
        ))}
      </ul>
    </div>
  );
}
