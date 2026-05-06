// One row in the sidebar listing a chat session. Props are deliberately
// dumb: all mutating actions are passed in by the parent so the parent
// owns the optimistic-update + revert logic.

import { useEffect, useRef, useState } from "react";
import type { ChatFolder, ChatSessionSummary } from "../../../api/client";
import { RowMenu, type RowMenuItem } from "./RowMenu";

export interface ChatRowProps {
  chat: ChatSessionSummary;
  folders: ChatFolder[];
  active: boolean;
  onSelect: () => void;
  onRename: (title: string) => void;
  onTogglePin: () => void;
  onMoveToFolder: (folderId: string | null) => void;
  onDelete: () => void;
  onDragStart?: (e: React.DragEvent) => void;
}

export function ChatRow({
  chat, folders, active, onSelect, onRename, onTogglePin, onMoveToFolder,
  onDelete, onDragStart,
}: ChatRowProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(chat.title);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  function commit() {
    const trimmed = draft.trim();
    if (trimmed && trimmed !== chat.title) onRename(trimmed);
    setEditing(false);
  }

  const moveItems: RowMenuItem[] = [
    {
      label: "No folder",
      onClick: () => onMoveToFolder(null),
    },
    ...folders.map(f => ({ label: f.name, onClick: () => onMoveToFolder(f.id) })),
  ];

  const items: RowMenuItem[] = [
    { label: chat.pinned ? "Unpin" : "Pin", onClick: onTogglePin },
    { label: "Move to…", children: moveItems },
    { label: "Rename", onClick: () => setEditing(true) },
    { divider: true, label: "" },
    {
      label: "Delete",
      destructive: true,
      onClick: () => {
        if (window.confirm(`Delete "${chat.title}"? This cannot be undone.`)) onDelete();
      },
    },
  ];

  return (
    <div
      className={`m3-chat-row${active ? " m3-chat-row--active" : ""}`}
      onClick={() => !editing && onSelect()}
      onContextMenu={e => {
        e.preventDefault();
        setMenu({ x: e.clientX, y: e.clientY });
      }}
      onDoubleClick={e => { e.stopPropagation(); setEditing(true); }}
      draggable={!editing}
      onDragStart={onDragStart}
      role="button"
      tabIndex={0}
    >
      {editing ? (
        <input
          ref={inputRef}
          className="m3-chat-row__rename"
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={e => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") { setDraft(chat.title); setEditing(false); }
          }}
          onClick={e => e.stopPropagation()}
        />
      ) : (
        <span className="m3-chat-row__title">{chat.title}</span>
      )}

      <div className="m3-chat-row__actions" onClick={e => e.stopPropagation()}>
        <button
          className={`m3-chat-row__pin${chat.pinned ? " m3-chat-row__pin--on" : ""}`}
          onClick={onTogglePin}
          title={chat.pinned ? "Unpin" : "Pin"}
          aria-label={chat.pinned ? "Unpin" : "Pin"}
        >
          ★
        </button>
        <button
          className="m3-chat-row__menu"
          onClick={e => setMenu({ x: e.clientX, y: e.clientY })}
          aria-label="More actions"
        >
          ⋯
        </button>
      </div>

      {menu && <RowMenu items={items} x={menu.x} y={menu.y} onClose={() => setMenu(null)} />}
    </div>
  );
}
