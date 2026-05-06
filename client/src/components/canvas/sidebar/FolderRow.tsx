// Folder row: header (expand toggle + name + count + actions). Children
// (the foldered chats) are rendered by the parent. This component only
// owns the header and exposes drop-target behavior for moving chats in.

import { useEffect, useRef, useState } from "react";
import type { ChatFolder } from "../../../api/client";
import { RowMenu, type RowMenuItem } from "./RowMenu";

export interface FolderRowProps {
  folder: ChatFolder;
  childCount: number;
  expanded: boolean;
  onToggle: () => void;
  onRename: (name: string) => void;
  onDelete: () => void;
  onDropChat: (chatId: string) => void;
}

export function FolderRow({
  folder, childCount, expanded, onToggle, onRename, onDelete, onDropChat,
}: FolderRowProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(folder.name);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  function commit() {
    const trimmed = draft.trim();
    if (trimmed && trimmed !== folder.name) onRename(trimmed);
    setEditing(false);
  }

  const items: RowMenuItem[] = [
    { label: "Rename", onClick: () => setEditing(true) },
    { divider: true, label: "" },
    {
      label: "Delete folder",
      destructive: true,
      onClick: () => {
        const msg = childCount > 0
          ? `Delete "${folder.name}"? ${childCount} chat${childCount === 1 ? "" : "s"} will move out of the folder (not deleted).`
          : `Delete "${folder.name}"?`;
        if (window.confirm(msg)) onDelete();
      },
    },
  ];

  return (
    <div
      className={`m3-folder-row${dragOver ? " m3-folder-row--drop" : ""}`}
      onContextMenu={e => { e.preventDefault(); setMenu({ x: e.clientX, y: e.clientY }); }}
      onDragOver={e => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={e => {
        e.preventDefault();
        setDragOver(false);
        const cid = e.dataTransfer.getData("application/x-chat-id");
        if (cid) onDropChat(cid);
      }}
    >
      <button className="m3-folder-row__toggle" onClick={onToggle} aria-label={expanded ? "Collapse" : "Expand"}>
        {expanded ? "▾" : "▸"}
      </button>

      {editing ? (
        <input
          ref={inputRef}
          className="m3-folder-row__rename"
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={e => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") { setDraft(folder.name); setEditing(false); }
          }}
        />
      ) : (
        <span className="m3-folder-row__name" onDoubleClick={() => setEditing(true)}>
          {folder.name}
        </span>
      )}

      {childCount > 0 && <span className="m3-folder-row__count">{childCount}</span>}

      <button
        className="m3-folder-row__menu"
        onClick={e => setMenu({ x: e.clientX, y: e.clientY })}
        aria-label="More actions"
      >⋯</button>

      {menu && <RowMenu items={items} x={menu.x} y={menu.y} onClose={() => setMenu(null)} />}
    </div>
  );
}
