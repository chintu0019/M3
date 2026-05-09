// Background update flow.
//
// On mount, on window focus, and every UPDATE_INTERVAL_MS we ask Tauri's updater
// plugin whether a new release is available. If yes, the bundle is downloaded
// silently (with a progress bar) and a "Restart now" banner appears. The user
// keeps working — the next click of the button calls process.relaunch().
//
// Polling guards:
//   - MIN_GAP_MS prevents back-to-back checks (focus events fire often).
//   - We skip new checks once a download is in flight or a "ready" banner is
//     already showing — no point starting a second flow.
//   - All errors land in console.warn (offline, sig mismatch, no endpoint).
//
// In dev (running outside Tauri, or if the updater plugin isn't reachable) every
// call no-ops gracefully — the banner just never shows.

import { useEffect, useRef, useState } from "react";

type Stage =
  | { kind: "idle" }
  | { kind: "downloading"; progress: number }
  | { kind: "ready"; version: string }
  | { kind: "error"; message: string };

// Periodic recheck cadence. 6h is a sensible compromise: long enough that an
// always-open M3 doesn't hammer GitHub, short enough that a release shipped in
// the morning lands by lunch without a manual quit/relaunch.
const UPDATE_INTERVAL_MS = 6 * 60 * 60 * 1000;

// Minimum gap between two consecutive checks. Window focus events fire on
// every alt-tab; without this guard a rapid focus dance would hammer the
// updater endpoint and waste GitHub's CDN budget.
const MIN_GAP_MS = 30 * 60 * 1000;

const insideTauri = () =>
  typeof window !== "undefined" &&
  // Tauri 2 sets either of these depending on how the app was launched.
  (("__TAURI_INTERNALS__" in window) || ("__TAURI__" in window));

export default function UpdateBanner() {
  const [stage, setStage] = useState<Stage>({ kind: "idle" });
  const [dismissed, setDismissed] = useState(false);

  // Refs so the polling closure inside the mount-only useEffect can read
  // current state without resubscribing intervals/listeners on every render.
  const stageRef = useRef(stage);
  useEffect(() => {
    stageRef.current = stage;
  }, [stage]);

  useEffect(() => {
    if (!insideTauri()) return;

    let cancelled = false;
    let lastCheckAt = 0;

    const runCheck = async () => {
      if (cancelled) return;
      // Already mid-flow? leave it alone.
      const k = stageRef.current.kind;
      if (k === "downloading" || k === "ready") return;
      if (Date.now() - lastCheckAt < MIN_GAP_MS) return;
      lastCheckAt = Date.now();

      try {
        const { check } = await import("@tauri-apps/plugin-updater");
        const update = await check();
        if (cancelled || !update) return;

        let total = 0;
        let downloaded = 0;

        await update.downloadAndInstall((event) => {
          if (cancelled) return;
          switch (event.event) {
            case "Started":
              total = event.data.contentLength ?? 0;
              setStage({ kind: "downloading", progress: 0 });
              break;
            case "Progress":
              downloaded += event.data.chunkLength;
              setStage({
                kind: "downloading",
                progress: total > 0 ? downloaded / total : 0,
              });
              break;
            case "Finished":
              setStage({ kind: "ready", version: update.version });
              break;
          }
        });
      } catch (err) {
        if (cancelled) return;
        // No endpoint configured, offline, signature mismatch — all land here.
        // Silent in production; surfaced in console for debugging.
        console.warn("updater check failed:", err);
      }
    };

    // Initial check on mount.
    void runCheck();

    // Periodic check every UPDATE_INTERVAL_MS while the app stays open.
    const intervalId = window.setInterval(() => {
      void runCheck();
    }, UPDATE_INTERVAL_MS);

    // Focus-driven check: regaining focus after switching apps is a natural
    // moment to recheck. MIN_GAP_MS keeps it from firing on rapid alt-tabs.
    const onFocus = () => {
      void runCheck();
    };
    window.addEventListener("focus", onFocus);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
      window.removeEventListener("focus", onFocus);
    };
  }, []);

  if (dismissed) return null;
  if (stage.kind === "idle" || stage.kind === "error") return null;

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
        onClick={() => setDismissed(true)}
        className="px-2 py-1 rounded-md hover:bg-white/15 text-sm"
        aria-label="Dismiss"
      >
        ✕
      </button>
    </div>
  );
}
