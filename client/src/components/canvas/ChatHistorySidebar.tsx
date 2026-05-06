// Left-of-ChatRail sidebar: lists every persisted chat session, grouped
// into Pinned, Folders, and recency buckets. Owned by Canvas which passes
// the active session id and a callback to change it.
//
// Data is fetched from the server on mount and after any mutation (we
// keep the last `refreshKey` to force a refetch). Folder expand-state is
// local-only and persisted to localStorage per folder id.
//
// Drag-and-drop: a chat row sets `application/x-chat-id` on its
// dataTransfer. FolderRow handles drop-onto-folder. The "Chats" section
// header acts as a drop target meaning "remove from folder".

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type ChatFolder, type ChatSessionSummary } from "../../api/client";
import { BUCKET_LABEL, BUCKET_ORDER, bucketFor, type RecencyBucket } from "../../lib/recency";
import { ChatRow } from "./sidebar/ChatRow";
import { FolderRow } from "./sidebar/FolderRow";

export interface ChatHistorySidebarProps {
  activeSessionId: string | null;
  onSelectSession: (sid: string) => void;
  onNewChat: () => void;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  /** Bumped by parent (Canvas) after sending a message so titles/timestamps refresh. */
  refreshKey: number;
}

export function ChatHistorySidebar({
  activeSessionId, onSelectSession, onNewChat, collapsed, onToggleCollapsed,
  refreshKey,
}: ChatHistorySidebarProps) {
  const [chats, setChats] = useState<ChatSessionSummary[]>([]);
  const [folders, setFolders] = useState<ChatFolder[]>([]);
  const [folderExpanded, setFolderExpanded] = useState<Record<string, boolean>>(() => {
    if (typeof window === "undefined") return {};
    try { return JSON.parse(localStorage.getItem("m3-folder-expanded") || "{}"); }
    catch { return {}; }
  });
  const [creatingFolder, setCreatingFolder] = useState(false);
  const [folderDraft, setFolderDraft] = useState("");

  const refetch = useCallback(async () => {
    try {
      const [c, f] = await Promise.all([api.listChats(), api.listFolders()]);
      setChats(c);
      setFolders(f);
    } catch {
      // Empty/error: keep last successful snapshot.
    }
  }, []);

  useEffect(() => { refetch(); }, [refetch, refreshKey]);

  useEffect(() => {
    localStorage.setItem("m3-folder-expanded", JSON.stringify(folderExpanded));
  }, [folderExpanded]);

  // Patch helpers: optimistic update, revert on failure.
  const patchChat = useCallback(async (
    sid: string,
    fields: Parameters<typeof api.patchChat>[1],
  ) => {
    setChats(prev => prev.map(c => c.id === sid ? { ...c, ...fields } as ChatSessionSummary : c));
    try { await api.patchChat(sid, fields); }
    catch { refetch(); }
  }, [refetch]);

  const deleteChat = useCallback(async (sid: string) => {
    setChats(prev => prev.filter(c => c.id !== sid));
    try { await api.deleteChat(sid); }
    catch { refetch(); }
  }, [refetch]);

  const createFolder = useCallback(async (name: string) => {
    try {
      const f = await api.createFolder(name);
      setFolders(prev => [...prev, f]);
      setFolderExpanded(s => ({ ...s, [f.id]: true }));
    } catch { refetch(); }
  }, [refetch]);

  const renameFolder = useCallback(async (fid: string, name: string) => {
    setFolders(prev => prev.map(f => f.id === fid ? { ...f, name } : f));
    try { await api.patchFolder(fid, { name }); }
    catch { refetch(); }
  }, [refetch]);

  const deleteFolder = useCallback(async (fid: string) => {
    setFolders(prev => prev.filter(f => f.id !== fid));
    setChats(prev => prev.map(c => c.folder_id === fid ? { ...c, folder_id: null } : c));
    try { await api.deleteFolder(fid); }
    catch { refetch(); }
  }, [refetch]);

  // Sectioning.
  const pinned = useMemo(() => chats.filter(c => c.pinned), [chats]);
  const byFolder = useMemo(() => {
    const m = new Map<string, ChatSessionSummary[]>();
    for (const f of folders) m.set(f.id, []);
    for (const c of chats) {
      if (c.folder_id && m.has(c.folder_id)) m.get(c.folder_id)!.push(c);
    }
    return m;
  }, [chats, folders]);

  const unfoldered = useMemo(() => chats.filter(c => !c.folder_id), [chats]);
  const recency = useMemo(() => {
    const m: Record<RecencyBucket, ChatSessionSummary[]> = {
      today: [], yesterday: [], previous7: [], previous30: [], older: [],
    };
    for (const c of unfoldered) m[bucketFor(c.updated_at)].push(c);
    return m;
  }, [unfoldered]);

  // Drag-source for chat rows: pass the chat id. The 'application/x-chat-id'
  // payload is the contract between this component and FolderRow.
  function chatDragStart(sid: string) {
    return (e: React.DragEvent) => {
      e.dataTransfer.setData("application/x-chat-id", sid);
      e.dataTransfer.effectAllowed = "move";
    };
  }

  if (collapsed) {
    return (
      <aside className="m3-sidebar m3-sidebar--collapsed">
        <button className="m3-sidebar__expand" onClick={onToggleCollapsed} aria-label="Expand">›</button>
        <button className="m3-sidebar__newchat" onClick={onNewChat} title="New chat" aria-label="New chat">＋</button>
      </aside>
    );
  }

  function renderChat(c: ChatSessionSummary) {
    return (
      <ChatRow
        key={c.id}
        chat={c}
        folders={folders}
        active={c.id === activeSessionId}
        onSelect={() => onSelectSession(c.id)}
        onRename={title => patchChat(c.id, { title })}
        onTogglePin={() => patchChat(c.id, { pinned: !c.pinned })}
        onMoveToFolder={fid => patchChat(c.id, { folder_id: fid })}
        onDelete={() => deleteChat(c.id)}
        onDragStart={chatDragStart(c.id)}
      />
    );
  }

  return (
    <aside className="m3-sidebar">
      <header className="m3-sidebar__head">
        <button className="m3-sidebar__collapse" onClick={onToggleCollapsed} aria-label="Collapse">‹</button>
        <span className="m3-sidebar__title">Chats</span>
        <button className="m3-sidebar__newchat" onClick={onNewChat} title="New chat">＋</button>
      </header>

      <div className="m3-sidebar__scroll">
        {chats.length === 0 && (
          <div className="m3-sidebar__empty">Start a conversation to see it here.</div>
        )}

        {pinned.length > 0 && (
          <section className="m3-sidebar__section">
            <h4 className="m3-sidebar__section-title">Pinned</h4>
            {pinned.map(renderChat)}
          </section>
        )}

        <section className="m3-sidebar__section">
          <header className="m3-sidebar__section-head">
            <h4 className="m3-sidebar__section-title">Folders</h4>
            <button
              className="m3-sidebar__add-folder"
              onClick={() => { setCreatingFolder(true); setFolderDraft(""); }}
              aria-label="New folder"
              title="New folder"
            >＋</button>
          </header>
          {creatingFolder && (
            <input
              autoFocus
              className="m3-sidebar__new-folder-input"
              value={folderDraft}
              onChange={e => setFolderDraft(e.target.value)}
              placeholder="Folder name"
              onBlur={() => {
                // Single commit site: Enter routes here via .blur() below so
                // we don't double-fire createFolder.
                const v = folderDraft.trim();
                if (v) createFolder(v);
                setCreatingFolder(false);
                setFolderDraft("");
              }}
              onKeyDown={e => {
                if (e.key === "Enter") e.currentTarget.blur();
                if (e.key === "Escape") {
                  setFolderDraft("");
                  setCreatingFolder(false);
                }
              }}
            />
          )}
          {folders.map(f => {
            const expanded = folderExpanded[f.id] !== false; // default expanded
            const items = byFolder.get(f.id) || [];
            return (
              <div key={f.id}>
                <FolderRow
                  folder={f}
                  childCount={items.length}
                  expanded={expanded}
                  onToggle={() => setFolderExpanded(s => ({ ...s, [f.id]: !expanded }))}
                  onRename={name => renameFolder(f.id, name)}
                  onDelete={() => deleteFolder(f.id)}
                  onDropChat={cid => patchChat(cid, { folder_id: f.id })}
                />
                {expanded && (
                  <div className="m3-sidebar__folder-children">
                    {items.length === 0
                      ? <div className="m3-sidebar__folder-empty">Drag chats here to organize.</div>
                      : items.map(renderChat)}
                  </div>
                )}
              </div>
            );
          })}
        </section>

        <section
          className="m3-sidebar__section"
          onDragOver={e => e.preventDefault()}
          onDrop={e => {
            e.preventDefault();
            const cid = e.dataTransfer.getData("application/x-chat-id");
            if (cid) patchChat(cid, { folder_id: null });
          }}
        >
          <h4 className="m3-sidebar__section-title">Chats</h4>
          {BUCKET_ORDER.map(b => recency[b].length > 0 && (
            <div key={b}>
              <h5 className="m3-sidebar__bucket-label">{BUCKET_LABEL[b]}</h5>
              {recency[b].map(renderChat)}
            </div>
          ))}
        </section>
      </div>
    </aside>
  );
}
