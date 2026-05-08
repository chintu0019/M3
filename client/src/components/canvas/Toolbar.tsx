// Top-right toolbar floating over the canvas: variant toggle + zoom controls
// + a settings gear that opens the settings modal. The whole toolbar is
// uppercase JetBrains-Mono micro-text, very low-chrome.

import type { Variant } from "./NodeMark";

export interface ToolbarProps {
  variant: Variant;
  setVariant: (v: Variant) => void;
  onFit: () => void;
  zoom: number;
  setZoom: (k: number) => void;
  onSettings: () => void;
  onFiles: () => void;
  unconfigured: boolean;
  showAllSources: boolean;
  onToggleSources: () => void;
  showAllClaims: boolean;
  onToggleClaims: () => void;
}

export function Toolbar({
  variant, setVariant, onFit, zoom, setZoom, onSettings, onFiles, unconfigured,
  showAllSources, onToggleSources, showAllClaims, onToggleClaims,
}: ToolbarProps) {
  return (
    <div className="m3-toolbar">
      <div className="m3-toolbar__seg">
        <button className={variant === "cosmos" ? "on" : ""} onClick={() => setVariant("cosmos")}>
          Cosmos
        </button>
        <button className={variant === "blueprint" ? "on" : ""} onClick={() => setVariant("blueprint")}>
          Blueprint
        </button>
      </div>
      <div className="m3-toolbar__zoom">
        <button onClick={() => setZoom(zoom / 1.2)} aria-label="Zoom out">−</button>
        <span>{Math.round(zoom * 100)}%</span>
        <button onClick={() => setZoom(zoom * 1.2)} aria-label="Zoom in">+</button>
        <button onClick={onFit}>Fit</button>
      </div>
      <button
        className={`m3-toolbar__sources${showAllClaims ? " on" : ""}`}
        onClick={onToggleClaims}
        title={showAllClaims ? "Hide all atomic claims" : "Reveal all atomic claims"}
        aria-pressed={showAllClaims}
      >
        Claims
      </button>
      <button
        className={`m3-toolbar__sources${showAllSources ? " on" : ""}`}
        onClick={onToggleSources}
        title={showAllSources ? "Hide raw uploaded sources" : "Reveal raw uploaded sources"}
        aria-pressed={showAllSources}
      >
        Sources
      </button>
      <button
        className="m3-toolbar__gear"
        onClick={onFiles}
        title="Files"
        aria-label="Files"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
        </svg>
      </button>
      <button
        className="m3-toolbar__gear"
        onClick={onSettings}
        title={unconfigured ? "No AI agent — open Settings" : "Settings"}
        aria-label="Settings"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
        {unconfigured && <span className="m3-toolbar__gear-dot" />}
      </button>
    </div>
  );
}
