// Generic overflow menu used by chat rows and folder rows in the sidebar.
// Caller provides items + handlers. Closes on outside click, Escape, or
// item activation.

import { useEffect, useRef } from "react";

export interface RowMenuItem {
  label: string;
  /** Optional submenu items - when present, hovering shows a child menu. */
  children?: RowMenuItem[];
  onClick?: () => void;
  destructive?: boolean;
  divider?: boolean;
}

export interface RowMenuProps {
  items: RowMenuItem[];
  onClose: () => void;
  /** Anchor coordinates (page x, y), caller computes from a DOM rect or click event. */
  x: number;
  y: number;
}

export function RowMenu({ items, onClose, x, y }: RowMenuProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!ref.current) return;
      if (!ref.current.contains(e.target as Node)) onClose();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="m3-row-menu"
      style={{ position: "fixed", left: x, top: y }}
      role="menu"
    >
      {items.map((it, i) =>
        it.divider ? (
          <div key={i} className="m3-row-menu__divider" />
        ) : it.children ? (
          <div key={i} className="m3-row-menu__item m3-row-menu__item--has-children" role="menuitem">
            <span>{it.label}</span>
            <span className="m3-row-menu__chevron">▸</span>
            <div className="m3-row-menu__submenu">
              {it.children.map((c, j) => (
                <button
                  key={j}
                  className={`m3-row-menu__item${c.destructive ? " m3-row-menu__item--danger" : ""}`}
                  role="menuitem"
                  onClick={() => { c.onClick?.(); onClose(); }}
                >
                  {c.label}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <button
            key={i}
            className={`m3-row-menu__item${it.destructive ? " m3-row-menu__item--danger" : ""}`}
            role="menuitem"
            onClick={() => { it.onClick?.(); onClose(); }}
          >
            {it.label}
          </button>
        )
      )}
    </div>
  );
}
