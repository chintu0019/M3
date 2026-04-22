import { Link } from "react-router-dom";
import { RetrieveHit } from "../api/client";

export default function ResultCard({ hit }: { hit: RetrieveHit }) {
  return (
    <div className="border border-m3-border rounded-lg p-4 hover:border-m3-accent transition-colors">
      <div className="flex items-center gap-2 text-xs text-m3-muted mb-2">
        <span className="px-2 py-0.5 rounded bg-m3-surface">{hit.kind}</span>
        {hit.when_iso && <span>{hit.when_iso}</span>}
        <span className="flex-1" />
        <span>score {hit.score.toFixed(2)}</span>
      </div>
      <p className="text-sm mb-3">{hit.excerpt || hit.snippet || "(no excerpt)"}</p>
      <ul className="text-xs text-m3-muted space-y-0.5">
        {hit.reasons.map((r, i) => (
          <li key={i}>· {r}</li>
        ))}
      </ul>
      <Link
        to={`/items/${hit.item_id}`}
        className="text-xs text-m3-accent hover:text-m3-accent-hover mt-2 inline-block"
      >
        open →
      </Link>
    </div>
  );
}
