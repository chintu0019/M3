import { useCallback, useEffect, useState } from "react";

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

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    applyTheme(next);
    localStorage.setItem(STORAGE_KEY, next);
    broadcast(next);
  }, []);

  return { theme, setTheme };
}
