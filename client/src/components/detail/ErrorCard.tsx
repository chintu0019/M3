export default function ErrorCard({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="bg-red-950/40 border border-red-900 rounded-xl p-4">
      <div className="text-xs uppercase tracking-wide text-red-400 mb-2">Processing Failed</div>
      <pre className="whitespace-pre-wrap text-sm text-red-200 mb-3">{message}</pre>
      <button onClick={onRetry} className="bg-red-900/40 border border-red-800 hover:border-red-500 text-red-200 px-3 py-1.5 rounded text-sm">
        ↻ Retry
      </button>
    </div>
  );
}
