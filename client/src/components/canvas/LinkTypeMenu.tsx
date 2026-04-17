import { useEffect, useRef, useState } from "react";

const PRESET_LINK_TYPES = ["related", "part_of", "mentions", "blocks", "supports"];

interface Props {
  screenX: number;
  screenY: number;
  onConfirm: (linkType: string) => void;
  onCancel: () => void;
}

export default function LinkTypeMenu({ screenX, screenY, onConfirm, onCancel }: Props) {
  const [custom, setCustom] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onCancel();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCancel();
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [onCancel]);

  return (
    <div
      ref={ref}
      className="canvas-menu"
      style={{ left: screenX, top: screenY }}
      role="menu"
    >
      {PRESET_LINK_TYPES.map((t) => (
        <button key={t} className="canvas-menu__item" onClick={() => onConfirm(t)}>
          {t}
        </button>
      ))}
      <form
        className="canvas-menu__custom"
        onSubmit={(e) => {
          e.preventDefault();
          const v = custom.trim();
          if (v) onConfirm(v);
        }}
      >
        <input
          autoFocus={false}
          value={custom}
          onChange={(e) => setCustom(e.target.value)}
          placeholder="custom…"
        />
      </form>
    </div>
  );
}
