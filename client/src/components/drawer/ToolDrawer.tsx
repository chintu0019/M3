import { useEffect } from "react";
import Library from "../../views/Library";
import Entities from "../../views/Entities";
import Insights from "../../views/Insights";
import Settings from "../../views/Settings";

export type DrawerPane = "library" | "entities" | "insights" | "settings";

interface Props {
  open: DrawerPane | null;
  onClose: () => void;
}

const PANE_LABELS: Record<DrawerPane, string> = {
  library: "Library",
  entities: "Entities",
  insights: "Insights",
  settings: "Settings",
};

export default function ToolDrawer({ open, onClose }: Props) {
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <aside className="canvas-drawer" role="complementary" aria-label={PANE_LABELS[open]}>
      <header className="canvas-drawer__header">
        <span className="canvas-drawer__title">{PANE_LABELS[open]}</span>
        <button className="canvas-drawer__close" onClick={onClose} aria-label="Close drawer">
          ×
        </button>
      </header>
      <div className="canvas-drawer__body">
        {open === "library" && <Library />}
        {open === "entities" && <Entities />}
        {open === "insights" && <Insights />}
        {open === "settings" && <Settings />}
      </div>
    </aside>
  );
}
