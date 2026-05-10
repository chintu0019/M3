// Top-of-window update banner.
//
// All updater state lives in the autoUpdater module + useAutoUpdater hook.
// This component is now a pure renderer: it shows the download progress while
// a bundle is fetching, flips to a "Restart now" prompt when it's ready, and
// stays invisible otherwise (idle / checking / uptodate / error). The
// Settings page consumes the same hook to drive its "Check for updates"
// button; both share one stage so we never run two checks in parallel.

import { useAutoUpdater } from "../hooks/useAutoUpdater";

export default function UpdateBanner() {
  const { stage, dismissed, dismiss } = useAutoUpdater();

  if (dismissed) return null;
  // idle / checking / uptodate / error: no banner. Settings is where those
  // states surface as text.
  if (
    stage.kind === "idle" ||
    stage.kind === "checking" ||
    stage.kind === "uptodate" ||
    stage.kind === "error"
  ) {
    return null;
  }

  if (stage.kind === "downloading") {
    return (
      <div className="px-4 py-2 bg-m3-surface border-b border-m3-border text-sm flex items-center gap-3">
        <span className="text-m3-muted">Downloading update…</span>
        <div className="flex-1 h-1.5 rounded-full bg-m3-border overflow-hidden max-w-xs">
          <div
            className="h-full bg-m3-accent transition-[width] duration-200"
            style={{ width: `${Math.round(stage.progress * 100)}%` }}
          />
        </div>
        <span className="tabular-nums text-m3-muted text-xs">
          {Math.round(stage.progress * 100)}%
        </span>
      </div>
    );
  }

  // stage.kind === "ready"
  return (
    <div className="px-4 py-2 bg-m3-accent text-white text-sm flex items-center gap-3">
      <span>
        M3 <strong>{stage.version}</strong> is ready to install.
      </span>
      <div className="flex-1" />
      <button
        onClick={async () => {
          const { relaunch } = await import("@tauri-apps/plugin-process");
          await relaunch();
        }}
        className="px-3 py-1 rounded-md bg-white/15 hover:bg-white/25 text-sm font-medium"
      >
        Restart now
      </button>
      <button
        onClick={dismiss}
        className="px-2 py-1 rounded-md hover:bg-white/15 text-sm"
        aria-label="Dismiss"
      >
        ✕
      </button>
    </div>
  );
}
