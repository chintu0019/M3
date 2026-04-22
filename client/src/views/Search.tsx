import { useEffect, useState } from "react";
import { api, RetrieveHit } from "../api/client";
import ResultCard from "../components/ResultCard";

export default function Search() {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<RetrieveHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!query.trim()) {
      setHits([]);
      return;
    }
    const handle = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await api.retrieve(query);
        setHits(res.hits);
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
      }
    }, 200);
    return () => clearTimeout(handle);
  }, [query]);

  return (
    <div className="max-w-3xl mx-auto p-6">
      <input
        type="text"
        autoFocus
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="A fragment of something you're trying to remember…"
        className="w-full bg-m3-surface border border-m3-border rounded-lg px-4 py-3 text-m3-text placeholder-m3-muted focus:outline-none focus:border-m3-accent"
      />
      <div className="mt-4 space-y-3">
        {loading && <div className="text-m3-muted text-sm">searching…</div>}
        {error && <div className="text-red-400 text-sm">{error}</div>}
        {!loading && !error && query && hits.length === 0 && (
          <div className="text-m3-muted text-sm">no hits</div>
        )}
        {hits.map((h) => (
          <ResultCard key={h.item_id} hit={h} />
        ))}
      </div>
    </div>
  );
}
