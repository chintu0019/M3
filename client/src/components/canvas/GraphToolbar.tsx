import type { CanvasVariant } from "./GraphCanvas";

export interface GraphToolbarProps {
  variant: CanvasVariant;
  setVariant: (v: CanvasVariant) => void;
  zoom: number;
  setZoom: (k: number) => void;
  onFit: () => void;
}

export default function GraphToolbar({
  variant,
  setVariant,
  zoom,
  setZoom,
  onFit,
}: GraphToolbarProps) {
  return (
    <div className="m3-toolbar">
      <div className="m3-toolbar__seg">
        <button
          className={variant === "cosmos" ? "on" : ""}
          onClick={() => setVariant("cosmos")}
        >
          Cosmos
        </button>
        <button
          className={variant === "blueprint" ? "on" : ""}
          onClick={() => setVariant("blueprint")}
        >
          Blueprint
        </button>
      </div>
      <div className="m3-toolbar__zoom">
        <button onClick={() => setZoom(zoom / 1.2)} aria-label="Zoom out">
          −
        </button>
        <span>{Math.round(zoom * 100)}%</span>
        <button onClick={() => setZoom(zoom * 1.2)} aria-label="Zoom in">
          +
        </button>
        <button onClick={onFit}>Fit</button>
      </div>
    </div>
  );
}
