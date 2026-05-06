# Chat history sidebar — design

**Date:** 2026-05-06
**Status:** Approved, ready for implementation plan

## Problem

The chat rail today persists a single conversation. Server-side every turn is already written to `~/brain/chats/<sid>.jsonl` and there are `newChat` / `getChat` endpoints, but the client only knows about one session id (in `localStorage["m3-session-id"]`). When the user hits "+", the previous conversation's `.jsonl` remains on disk but there is no way to find or resume it.

Users want a **collapsable left sidebar** that lists every past conversation, supports manual organization (pinning + folders), and persists chats indefinitely until they are explicitly deleted.

## Goals

- Browse and resume any past conversation.
- Group conversations into user-named folders.
- Auto-name conversations using the configured agent; user can override.
- Pin important conversations so they always surface at the top.
- Delete is manual only — never auto-archive, never auto-expire.
- Existing single-session behavior keeps working through the upgrade (no migration required for users with prior `.jsonl` files).

## Non-goals

- Full-text search across chats. Out of scope for this iteration; the sidebar is purely structural navigation.
- Persisting the per-file scoped `FileChat` rendered inside `FilesModal`. Stays ephemeral.
- Reconstructing per-citation offsets when rehydrating an old chat. Same call as today — citations only re-appear if the user re-asks within the conversation.
- Multi-select bulk operations on chats. One-at-a-time actions only.
- Tags or multi-folder membership. A chat is in zero or one folder.

## Architecture

Three-pane layout:

```
+-------------------+----------------+--------------------------+
| ChatHistorySidebar|   ChatRail     |         Canvas           |
| (new, collapsable)| (existing)     |       (existing)         |
+-------------------+----------------+--------------------------+
```

The active session id moves up from `ChatRail` local state into `Canvas`. `Canvas` becomes the single source of truth for "which chat is active" and passes the id down to both the sidebar (for highlighting the active row) and the rail (for hydration and turn appending).

When the user clicks a session in the sidebar, `Canvas` updates the active id, which causes `ChatRail` to refetch and rehydrate.

The collapsed-state of the sidebar lives in `localStorage["m3-sidebar-collapsed"]`. Collapsed = ~44px strip with an expand button and a "new chat" icon visible. Expanded default width: 260px.

## Storage model

Existing `.jsonl` turn files are untouched. We add a sidecar metadata file per session and a single folders file:

```
~/brain/chats/
  2026-05-06-abc123.jsonl       ← turns (existing, append-only)
  2026-05-06-abc123.meta.json   ← NEW: session metadata
  folders.json                  ← NEW: folder definitions
```

### Session meta sidecar (`<sid>.meta.json`)

```json
{
  "id": "2026-05-06-abc123",
  "title": "Refactor force-graph layout",
  "title_locked": false,
  "pinned": false,
  "folder_id": null,
  "created_at": "2026-05-06T13:07:25Z",
  "updated_at": "2026-05-06T14:02:11Z"
}
```

- `title_locked` is set to `true` when the user manually renames; the auto-title pass never overwrites a locked title.
- `updated_at` is set when a turn is appended OR when meta itself changes (rename, pin, move).
- Missing sidecar = treat as defaults (`title` derived from first user message, `pinned: false`, `folder_id: null`, timestamps from the `.jsonl`'s mtime). This makes existing chats appear in the sidebar with zero migration step.

### Folders file (`folders.json`)

```json
{
  "folders": [
    { "id": "f_a8b3c2", "name": "Work", "sort_order": 0 },
    { "id": "f_d1e4f5", "name": "Side projects", "sort_order": 1 }
  ]
}
```

### Trade-off vs single index file

A single `index.json` for everything was considered. Per-session sidecars win on:

- **Git friendliness:** renaming one chat touches one small file, not a rolling diff over the whole index.
- **Concurrent safety:** no global lock; turn-append writers and metadata writers don't contend.
- **Symmetric delete:** delete a chat = delete its two files. No need to mutate a global registry.

The cost is one extra file per session, negligible at expected scale.

## Auto-naming flow

After the first assistant turn completes on a session whose meta has no title (or default-derived title) and `title_locked == false`:

1. Chat route enqueues a follow-up agent call asynchronously (does not block the streamed response).
2. Prompt to the agent: a fixed template asking for a 3-6 word title summarizing the first user message and the first assistant reply.
3. On success, write the title to meta and bump `updated_at`.
4. On any failure, leave the derived title in place. Never retries.

User-triggered rename (via inline edit or row menu) sets `title_locked: true`, so future auto-title runs skip the session.

## API surface

All additions live under the existing `/api/v1` prefix in [server/m3/api/chats.py](server/m3/api/chats.py). No existing endpoints change shape; only the list response gains optional fields.

| Verb   | Path                       | Purpose                                                               |
|--------|----------------------------|-----------------------------------------------------------------------|
| GET    | `/api/v1/chats`            | List sessions. Response items extended with `pinned`, `folder_id`, `updated_at`. Pagination unchanged. |
| POST   | `/api/v1/chats`            | Existing — mints a new session id.                                    |
| GET    | `/api/v1/chats/{sid}`      | Existing — load turns for a session.                                  |
| PATCH  | `/api/v1/chats/{sid}`      | Body: `{ title?, pinned?, folder_id? }`. Setting `title` sets `title_locked: true`. |
| DELETE | `/api/v1/chats/{sid}`      | Removes both `.jsonl` and `.meta.json`. Idempotent. Manual only.      |
| GET    | `/api/v1/folders`          | List folders.                                                         |
| POST   | `/api/v1/folders`          | Body: `{ name }`. Creates folder, returns id.                         |
| PATCH  | `/api/v1/folders/{fid}`    | Body: `{ name?, sort_order? }`.                                       |
| DELETE | `/api/v1/folders/{fid}`    | Deletes folder. Chats with that `folder_id` are reset to `null`.      |

Auto-title firing is internal to the chat route — no public endpoint.

## UI behaviors

### Sidebar sections (top → bottom)

1. **Header:** logo + "New chat" button + collapse toggle.
2. **Pinned** (only rendered if any chats are pinned): pinned chats listed flat, newest first. A pinned chat ALSO appears in its folder or recency bucket below.
3. **Folders** (only rendered if any folders exist): each folder is an expandable row. Default state: expanded. Collapsed-state per folder lives in `localStorage["m3-folder-expanded"]` keyed by folder id. Inside each folder, chats are sorted newest-first.
4. **Chats** — un-foldered chats grouped by recency:
   - Today
   - Yesterday
   - Previous 7 Days
   - Previous 30 Days
   - Older

### Row interactions

- Click row → make active. `Canvas` updates active session id.
- Hover row → reveal pin icon and overflow (`⋯`) icon on the right side.
- Right-click row → context menu: Pin / Unpin, Move to… (folder picker submenu including "No folder"), Rename, Delete.
- Double-click title → inline rename input. Enter commits, Escape cancels. Commit calls PATCH with `title` set.
- Drag row onto a folder header → move into that folder.
- Drag row onto "Chats" header → unset folder (move out of folder).

### Folder operations

- "+" button next to "Folders" section header → inline-create new folder (input field appears, Enter commits).
- Right-click folder header → Rename, Delete.
- Delete folder confirms with a small dialog ("Move N chats out of folder?"). Chats are not deleted, just orphaned back to the recency list.

### Collapsed state

Width ~44px. Renders only:
- Expand-toggle button (top).
- "New chat" button (below it).
- Active-session indicator dot (small, just visible).

### Empty states

- No chats yet: "Start a conversation to see it here." Plus the "+ New chat" button.
- One folder, empty: "Drag chats here to organize."

## Frontend changes

### New files

- `client/src/components/canvas/ChatHistorySidebar.tsx` — the sidebar component.
- `client/src/components/canvas/ChatRow.tsx` — single row rendering, inline rename, hover reveal.
- `client/src/components/canvas/FolderRow.tsx` — folder row with expand toggle.
- `client/src/lib/recency.ts` — helper for "Today / Yesterday / 7d / 30d / Older" bucketing of timestamps.

### Modified files

- `client/src/views/Canvas.tsx` — owns `activeSessionId`, renders the sidebar, passes id to `ChatRail`.
- `client/src/components/canvas/ChatRail.tsx` — accepts `sessionId` prop instead of owning its own state. The internal `useState` for sessionId becomes a controlled-from-parent value. localStorage write moves into `Canvas`. Mounting/unmounting on session change drives rehydration via prop change.
- `client/src/api/client.ts` — new methods: `listChats`, `patchChat`, `deleteChat`, `listFolders`, `createFolder`, `patchFolder`, `deleteFolder`. Existing `newChat` / `getChat` unchanged.

### CSS

- `client/src/index.css` — styles for sidebar, rows, sections, drag-target highlight, collapsed strip. Follows the existing canvas aesthetic (matches `m3-chat-rail__*` classes).

## Backend changes

### New files

- `server/m3/brain/folders.py` — read/write `folders.json`, CRUD helpers.

### Modified files

- `server/m3/brain/chats.py` — extend with:
  - `read_meta(root, sid) -> dict` (returns derived defaults if sidecar missing)
  - `write_meta(root, sid, **fields)` (atomic write via tempfile + rename)
  - `delete_session(root, sid)` (removes both files; safe if either is missing)
  - `list_sessions` extended to return the new fields. Existing limit semantics unchanged.
  - `auto_title(root, sid, agent_call)` — async-callable that produces and persists the title.
- `server/m3/api/chats.py` — add the new routes listed above.
- `server/m3/api/chat.py` — after `append_turn` for the first assistant turn of a session, schedule the auto-title task. Best-effort; never blocks the response.

## Error handling

- **Missing meta sidecar on read:** return derived defaults; do not error.
- **Auto-title failure:** logged, swallowed. Derived title remains.
- **Folder id pointing to a deleted folder:** treat as `folder_id: null` on read; lazy-repair the meta on next write.
- **Concurrent write to same meta:** atomic rename; last writer wins. Acceptable — single-user app.
- **Network failure on PATCH from the client:** revert the optimistic UI state and surface a small toast. (Toast infra: reuse whatever pattern `FilesModal` uses; if none, console.error and a passive failure are acceptable for this iteration.)

## Testing

Backend unit tests in `server/tests/`:

1. `read_meta` returns defaults when sidecar is missing, parsed values when present.
2. `write_meta` is atomic (write fails midway → original file unchanged). Verified by injecting a failure between tempfile write and rename.
3. `delete_session` removes both files; idempotent; safe with one file missing.
4. `list_sessions` includes new fields; sessions without sidecars still appear.
5. PATCH `/chats/{sid}` with `title` sets `title_locked: true`.
6. DELETE `/folders/{fid}` orphans member chats to `folder_id: null`.
7. Auto-title pass: stub agent returns a string, verify it lands in meta with `title_locked: false`.
8. Auto-title pass: when `title_locked: true`, agent is not called.

Frontend smoke tests are out of scope for this iteration (existing project doesn't have a frontend test harness).

End-to-end manual verification:
- Start with no chats → sidebar shows empty state.
- Send a message → row appears with auto-named title within a few seconds.
- Reload → row persists, click → conversation rehydrates.
- Pin → moves to Pinned section.
- Create folder, drag chat in → chat appears under folder, disappears from recency list.
- Rename via double-click → title sticks across reload, agent never overwrites.
- Delete chat → row gone, files gone from `~/brain/chats/`.
- Collapse sidebar → strip shows; expand restores width.

## Build sequence (for the implementation plan)

1. Backend: extend `chats.py` with meta read/write/delete; add `folders.py`; add API routes; tests.
2. Backend: wire auto-title hook into the chat route.
3. Frontend: lift `sessionId` to `Canvas`; convert `ChatRail` to accept it as a prop.
4. Frontend: build `ChatHistorySidebar` with sections, rows, recency bucketing — read-only first.
5. Frontend: rename / pin / delete / move row interactions.
6. Frontend: folder create / rename / delete / drag-drop.
7. Frontend: collapsed state and persistence.
8. Manual end-to-end pass against the verification list.
