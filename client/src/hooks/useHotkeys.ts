import { useEffect } from "react";

export type HotkeyMap = Record<string, (e: KeyboardEvent) => void>;

function matches(e: KeyboardEvent, combo: string): boolean {
  const parts = combo.toLowerCase().split("+").map((p) => p.trim());
  const want = new Set(parts);
  const wantKey = parts[parts.length - 1];

  const modsOk =
    (want.has("cmd") ? e.metaKey : !e.metaKey) &&
    (want.has("ctrl") ? e.ctrlKey : !e.ctrlKey) &&
    (want.has("alt") ? e.altKey : !e.altKey) &&
    (want.has("shift") ? e.shiftKey : !e.shiftKey);
  return modsOk && e.key.toLowerCase() === wantKey;
}

export function useHotkeys(map: HotkeyMap) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      for (const combo of Object.keys(map)) {
        if (matches(e, combo)) {
          map[combo](e);
          return;
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [map]);
}
