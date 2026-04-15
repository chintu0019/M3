import { type RawItem } from "../../api/client";
import FileCard from "./FileCard";
import FileRow from "./FileRow";

export default function FileList({
  items,
  mode,
  selected,
  onToggleSelect,
  selectMode,
}: {
  items: RawItem[];
  mode: "list" | "grid";
  selected: Set<string>;
  onToggleSelect: (id: string) => void;
  selectMode: boolean;
}) {
  if (items.length === 0) {
    return (
      <p className="text-m3-muted text-center py-12">
        No items in this view.
      </p>
    );
  }
  if (mode === "grid") {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        {items.map((item) => (
          <FileCard
            key={item.id}
            item={item}
            selected={selected.has(item.id)}
            onToggleSelect={onToggleSelect}
            selectMode={selectMode}
          />
        ))}
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {items.map((item) => (
        <FileRow
          key={item.id}
          item={item}
          selected={selected.has(item.id)}
          onToggleSelect={onToggleSelect}
          selectMode={selectMode}
        />
      ))}
    </div>
  );
}
