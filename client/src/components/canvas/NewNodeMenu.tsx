import { useEffect, useRef, useState } from "react";

const PRESET_ENTITY_TYPES = ["person", "project", "place", "concept", "organization"];

interface Props {
  screenX: number;
  screenY: number;
  onConfirm: (canonical_name: string, entity_type: string) => void;
  onCancel: () => void;
}

export default function NewNodeMenu({ screenX, screenY, onConfirm, onCancel }: Props) {
  const [name, setName] = useState("");
  const [type, setType] = useState(PRESET_ENTITY_TYPES[0]);
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

  function submit() {
    const v = name.trim();
    if (v) onConfirm(v, type.trim().toLowerCase());
  }

  return (
    <div
      ref={ref}
      className="canvas-menu canvas-menu--wide"
      style={{ left: screenX, top: screenY }}
      role="dialog"
      aria-label="Create node"
    >
      <input
        autoFocus
        placeholder="Name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") submit();
        }}
      />
      <select value={type} onChange={(e) => setType(e.target.value)}>
        {PRESET_ENTITY_TYPES.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>
      <button onClick={submit} disabled={!name.trim()}>
        Create
      </button>
    </div>
  );
}
