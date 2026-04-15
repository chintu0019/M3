import { type LinkedWikiPage } from "../../api/client";

interface Props {
  linkedPages: LinkedWikiPage[];
  userTags: string[];
  userProject: string | null;
}

export default function ClassificationCard({ linkedPages, userTags, userProject }: Props) {
  // Merge tags from all linked wiki pages (AI-assigned) and dedupe
  const aiTagSet = new Set<string>();
  for (const p of linkedPages) {
    for (const t of p.tags) aiTagSet.add(t);
  }
  const aiTags = Array.from(aiTagSet);
  const primary = linkedPages[0];

  // If nothing to show, skip the card
  if (!primary && aiTags.length === 0 && userTags.length === 0 && !userProject) return null;

  return (
    <div className="bg-m3-surface border border-m3-border rounded-xl p-4 space-y-3">
      <div className="text-xs uppercase tracking-wide text-m3-muted">AI Classification</div>

      {primary && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {primary.category && (
            <span className="bg-m3-bg border border-m3-border rounded px-2 py-0.5">
              {primary.category}
            </span>
          )}
          {primary.page_type && (
            <span className="text-m3-muted">· {primary.page_type}</span>
          )}
          <span className="text-m3-muted">· confidence {(primary.confidence * 100).toFixed(0)}%</span>
        </div>
      )}

      {aiTags.length > 0 && (
        <div>
          <div className="text-xs text-m3-muted mb-1">AI tags</div>
          <div className="flex flex-wrap gap-1">
            {aiTags.map((t) => (
              <span key={t} className="text-xs bg-m3-bg border border-m3-border rounded-full px-2 py-0.5">
                #{t}
              </span>
            ))}
          </div>
        </div>
      )}

      {(userTags.length > 0 || userProject) && (
        <div>
          <div className="text-xs text-m3-muted mb-1">Your inputs</div>
          <div className="flex flex-wrap gap-1 items-center">
            {userProject && (
              <span className="text-xs bg-m3-accent/20 text-m3-accent rounded-full px-2 py-0.5">
                project: {userProject}
              </span>
            )}
            {userTags.map((t) => (
              <span key={t} className="text-xs bg-m3-bg border border-m3-border rounded-full px-2 py-0.5">
                #{t}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
