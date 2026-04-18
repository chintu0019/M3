import { Command } from "cmdk";
import { useEffect, useState } from "react";
import { api, EntitySummary } from "../../api/client";
import { THEMES, Theme } from "../../hooks/useTheme";

export type PaletteAction =
  | { kind: "focus-entity"; id: string; label: string }
  | { kind: "open-drawer"; pane: "library" | "entities" | "insights" | "settings" }
  | { kind: "set-theme"; theme: Theme };

interface Props {
  onAction: (a: PaletteAction) => void;
  onClose: () => void;
}

export default function CommandPalette({ onAction, onClose }: Props) {
  const [q, setQ] = useState("");
  const [entities, setEntities] = useState<EntitySummary[]>([]);

  useEffect(() => {
    let cancelled = false;
    const params = q ? { search: q } : undefined;
    api.entities
      .list(params)
      .then((res) => {
        if (!cancelled) setEntities(res.items.slice(0, 20));
      })
      .catch(() => {
        if (!cancelled) setEntities([]);
      });
    return () => {
      cancelled = true;
    };
  }, [q]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="canvas-palette-backdrop" onClick={onClose}>
      <div className="canvas-palette" onClick={(e) => e.stopPropagation()}>
        <Command label="Command palette">
          <Command.Input
            autoFocus
            value={q}
            onValueChange={setQ}
            placeholder="Search entities, open tools…"
          />
          <Command.List>
            <Command.Empty>No results.</Command.Empty>

            <Command.Group heading="Tools">
              <Command.Item
                onSelect={() => onAction({ kind: "open-drawer", pane: "library" })}
              >
                Open Library
              </Command.Item>
              <Command.Item
                onSelect={() => onAction({ kind: "open-drawer", pane: "entities" })}
              >
                Open Entities
              </Command.Item>
              <Command.Item
                onSelect={() => onAction({ kind: "open-drawer", pane: "insights" })}
              >
                Open Insights
              </Command.Item>
              <Command.Item
                onSelect={() => onAction({ kind: "open-drawer", pane: "settings" })}
              >
                Open Settings
              </Command.Item>
            </Command.Group>

            <Command.Group heading="Theme">
              {THEMES.map((t) => (
                <Command.Item
                  key={t}
                  onSelect={() => onAction({ kind: "set-theme", theme: t })}
                >
                  Switch theme: {t}
                </Command.Item>
              ))}
            </Command.Group>

            {entities.length > 0 && (
              <Command.Group heading="Entities">
                {entities.map((e) => (
                  <Command.Item
                    key={e.id}
                    onSelect={() =>
                      onAction({ kind: "focus-entity", id: e.id, label: e.canonical_name })
                    }
                  >
                    {e.canonical_name}{" "}
                    <span className="canvas-palette__meta">{e.entity_type}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
          </Command.List>
        </Command>
      </div>
    </div>
  );
}
