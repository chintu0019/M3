import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";

export const THEMES = ["document", "notebook", "observatory"] as const;
export type Theme = (typeof THEMES)[number];

const STORAGE_KEY = "m3_theme";
const CHANGE_EVENT = "m3:theme-changed";

function applyTheme(theme: Theme) {
  document.documentElement.setAttribute("data-theme", theme);
}

function readLocal(): Theme {
  const t = localStorage.getItem(STORAGE_KEY);
  return THEMES.includes(t as Theme) ? (t as Theme) : "document";
}

function broadcast(theme: Theme) {
  window.dispatchEvent(new CustomEvent<Theme>(CHANGE_EVENT, { detail: theme }));
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(() => {
    const t = readLocal();
    applyTheme(t);
    return t;
  });

  // Tracks whether this hook instance has applied a user-driven change. If so,
  // a late server reconcile must not clobber it.
  const userOverrodeRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    api.settings
      .getTheme()
      .then((res) => {
        if (cancelled || userOverrodeRef.current) return;
        const t = (THEMES.includes(res.theme as Theme)
          ? res.theme
          : "document") as Theme;
        if (t !== readLocal()) {
          setThemeState(t);
          applyTheme(t);
          localStorage.setItem(STORAGE_KEY, t);
          broadcast(t);
        } else if (t !== theme) {
          setThemeState(t);
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

  // Cross-instance sync: when any other hook (palette, settings) changes the
  // theme, every mounted instance picks up the new value.
  useEffect(() => {
    function onChange(e: Event) {
      const next = (e as CustomEvent<Theme>).detail;
      if (THEMES.includes(next)) setThemeState(next);
    }
    window.addEventListener(CHANGE_EVENT, onChange);
    return () => window.removeEventListener(CHANGE_EVENT, onChange);
  }, []);

  const setTheme = useCallback(async (next: Theme) => {
    userOverrodeRef.current = true;
    setThemeState(next);
    applyTheme(next);
    localStorage.setItem(STORAGE_KEY, next);
    broadcast(next);
    try {
      await api.settings.setTheme(next);
    } catch (err) {
      console.error("theme persist failed", err);
      // Don't revert the visual — local stays authoritative.
    }
  }, []);

  return { theme, setTheme };
}
