interface Props {
  userTags: string[];
  userProject: string | null;
}

export default function UserInputsCard({ userTags, userProject }: Props) {
  if (userTags.length === 0 && !userProject) return null;

  return (
    <div className="bg-m3-surface border border-m3-border rounded-xl p-4 space-y-3">
      <div className="text-xs uppercase tracking-wide text-m3-muted">Your inputs</div>
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
  );
}
