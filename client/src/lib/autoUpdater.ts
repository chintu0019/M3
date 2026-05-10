// Module-level updater store.
//
// Lives outside React so multiple components (the top-of-window UpdateBanner
// AND the "Check for updates" button in Settings) can share a single update
// flow. Without this, a manual check kicked off from Settings would race the
// banner's automatic polling and we'd see two parallel downloads.
//
// Lifecycle:
//   - startAutoUpdater() boots the focus + interval pollers. Idempotent;
//     calling it twice from React's strict-mode double-mount is fine.
//   - runCheck({ manual }) is the single entry point for an updater check.
//     The auto poller calls it without `manual`, the Settings button calls
//     it with `manual: true` (which bypasses the MIN_GAP_MS rate limit and
//     surfaces "uptodate" / "error" so the UI can tell the user something
//     happened).
//   - subscribe(listener) returns an unsubscribe function. React components
//     wire this up via useSyncExternalStore-style hooks; everything else
//     just calls getStage() ad-hoc.
//
// In dev (running outside Tauri, or if the updater plugin isn't reachable)
// every call no-ops gracefully.

export type Stage =
  | { kind: "idle" }
  | { kind: "checking" }
  | { kind: "uptodate"; checkedAt: number }
  | { kind: "downloading"; progress: number }
  | { kind: "ready"; version: string }
  | { kind: "error"; message: string };

// Periodic recheck cadence. 6h is the compromise: long enough that an always-
// open M3 doesn't hammer GitHub, short enough that a release shipped in the
// morning lands by lunch without a manual quit/relaunch.
const UPDATE_INTERVAL_MS = 6 * 60 * 60 * 1000;

// Minimum gap between two automatic checks. Window-focus events fire on every
// alt-tab; without this guard, a focus dance would hammer the updater
// endpoint. Manual "Check for updates" from Settings ignores this gap.
const MIN_GAP_MS = 30 * 60 * 1000;

let _stage: Stage = { kind: "idle" };
let _dismissed = false;
let _lastAutoCheckAt = 0;
let _started = false;
const _listeners = new Set<() => void>();

const insideTauri = () =>
  typeof window !== "undefined" &&
  // Tauri 2 sets either of these depending on how the app was launched.
  (("__TAURI_INTERNALS__" in window) || ("__TAURI__" in window));

const notify = () => _listeners.forEach((l) => l());

const setStage = (s: Stage) => {
  _stage = s;
  notify();
};

export const getStage = (): Stage => _stage;
export const getDismissed = (): boolean => _dismissed;

export const setDismissed = (d: boolean) => {
  _dismissed = d;
  notify();
};

export const subscribe = (listener: () => void): (() => void) => {
  _listeners.add(listener);
  return () => {
    _listeners.delete(listener);
  };
};

export const runCheck = async (opts: { manual?: boolean } = {}): Promise<void> => {
  if (!insideTauri()) return;
  // Don't start a new flow if one is already in progress / a banner is up.
  const k = _stage.kind;
  if (k === "checking" || k === "downloading" || k === "ready") return;
  if (!opts.manual && Date.now() - _lastAutoCheckAt < MIN_GAP_MS) return;

  if (!opts.manual) _lastAutoCheckAt = Date.now();
  setStage({ kind: "checking" });

  try {
    const { check } = await import("@tauri-apps/plugin-updater");
    const update = await check();
    if (!update) {
      setStage({ kind: "uptodate", checkedAt: Date.now() });
      return;
    }

    let total = 0;
    let downloaded = 0;
    setStage({ kind: "downloading", progress: 0 });

    await update.downloadAndInstall((event) => {
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
    // No endpoint configured, offline, signature mismatch — all land here.
    // We surface the message via stage so Settings can show it; we ALSO
    // console.warn for live-debugging from DevTools.
    const msg = err instanceof Error ? err.message : String(err);
    setStage({ kind: "error", message: msg });
    console.warn("updater check failed:", err);
  }
};

export const startAutoUpdater = (): void => {
  if (_started) return;
  _started = true;
  if (!insideTauri()) return;

  // Initial check on app launch.
  void runCheck();

  // Periodic check while the app stays open.
  window.setInterval(() => {
    void runCheck();
  }, UPDATE_INTERVAL_MS);

  // Re-check when the user alt-tabs back to M3. Cheap, MIN_GAP_MS gates it.
  window.addEventListener("focus", () => {
    void runCheck();
  });
};
