import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";

export const THEMES = ["document", "notebook", "observatory"] as const;
export type Theme = (typeof THEMES)[number];

const STORAGE_KEY = "m3_theme";

function applyTheme(theme: Theme) {
  document.documentElement.setAttribute("data-theme", theme);
}

function readLocal(): Theme {
  const t = localStorage.getItem(STORAGE_KEY);
  return THEMES.includes(t as Theme) ? (t as Theme) : "document";
}

export function useTheme() {
  // Apply the locally-cached theme synchronously on first render so the
  // canvas doesn't flash the default theme while the GET round-trips.
  const [theme, setThemeState] = useState<Theme>(() => {
    const t = readLocal();
    applyTheme(t);
    return t;
  });

  useEffect(() => {
    let cancelled = false;
    api.settings
      .getTheme()
      .then((res) => {
        if (cancelled) return;
        const t = (THEMES.includes(res.theme as Theme) ? res.theme : "document") as Theme;
        if (t !== theme) {
          setThemeState(t);
          applyTheme(t);
          localStorage.setItem(STORAGE_KEY, t);
        }
      })
      .catch(() => {
        // Server unreachable — local cache is authoritative for this session.
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setTheme = useCallback(async (next: Theme) => {
    if (!THEMES.includes(next)) return;
    // Optimistic apply so the UI feels instant.
    setThemeState(next);
    applyTheme(next);
    localStorage.setItem(STORAGE_KEY, next);
    try {
      await api.settings.setTheme(next);
    } catch (err) {
      console.error("theme persist failed", err);
      // Don't revert the visual — local applies anyway, server can catch up
      // on next change. A noisy toast would be more helpful than a flicker.
    }
  }, []);

  return { theme, setTheme };
}
