export default function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: "bg-yellow-900/50 text-yellow-300",
    processing: "bg-blue-900/50 text-blue-300",
    done: "bg-green-900/50 text-green-300",
    error: "bg-red-900/50 text-red-300",
  };
  return (
    <span
      className={`text-xs px-2 py-0.5 rounded-full ${
        colors[status] || "bg-m3-surface text-m3-muted"
      }`}
    >
      {status}
    </span>
  );
}
