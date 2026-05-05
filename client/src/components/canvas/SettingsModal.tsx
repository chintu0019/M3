// Modal wrapper around the existing Settings view, surfaced from the
// canvas toolbar's gear icon. The view itself isn't redesigned for v1 —
// it's the BYO-AI-agent picker shipped with the chintu0019/M3 server work,
// just in a centered overlay instead of a full page.
//
// Keeping the existing component intact keeps this PR scoped: the canvas
// + force-graph + chat rail + visuals are the redesign; settings stays
// functional and gets a visual pass later.

import { useEffect } from "react";
import Settings from "../../views/Settings";

export interface SettingsModalProps {
  open: boolean;
  onClose: () => void;
}

export function SettingsModal({ open, onClose }: SettingsModalProps) {
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
    <div className="m3-modal-backdrop" onClick={onClose}>
      <div className="m3-modal" onClick={e => e.stopPropagation()}>
        <button className="m3-modal__close" onClick={onClose} aria-label="Close">
          <svg width="14" height="14" viewBox="0 0 16 16">
            <path d="M3 3l10 10M13 3L3 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
        <div className="m3-modal__body">
          <Settings />
        </div>
      </div>
    </div>
  );
}
