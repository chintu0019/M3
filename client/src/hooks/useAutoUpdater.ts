// React-side adapter for the autoUpdater module.
//
// useSyncExternalStore would be more idiomatic, but a plain useState +
// subscribe in useEffect is easier to read and handles every case we care
// about (no concurrent rendering subtleties — there's exactly one writer
// per stage transition and we never tear during render).

import { useEffect, useState } from "react";
import {
  getDismissed,
  getStage,
  runCheck,
  setDismissed as moduleSetDismissed,
  Stage,
  startAutoUpdater,
  subscribe,
} from "../lib/autoUpdater";

export interface AutoUpdaterApi {
  stage: Stage;
  dismissed: boolean;
  dismiss: () => void;
  /** Manual "Check for updates" — bypasses the 30-min focus-debounce. */
  checkNow: () => Promise<void>;
}

export function useAutoUpdater(): AutoUpdaterApi {
  // Boot the auto-poller on first mount of any consumer. Idempotent.
  useEffect(() => {
    startAutoUpdater();
  }, []);

  const [stage, setStage] = useState<Stage>(getStage);
  const [dismissed, setDismissedState] = useState<boolean>(getDismissed);

  useEffect(() => {
    const unsubscribe = subscribe(() => {
      setStage(getStage());
      setDismissedState(getDismissed());
    });
    return unsubscribe;
  }, []);

  return {
    stage,
    dismissed,
    dismiss: () => moduleSetDismissed(true),
    checkNow: () => runCheck({ manual: true }),
  };
}
