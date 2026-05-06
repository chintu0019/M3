// API client for M3 local server.
// Defaults to same-origin; override with VITE_API_URL for `npm run dev` against a running server.
// Auth: if localStorage.M3_API_KEY is set (user paired the client with a
// running server that has auth enabled), attach Authorization: Bearer. If
// not set, no header is sent — which is fine when the server runs in default
// local-only mode (loopback = security boundary).

const BASE = import.meta.env.VITE_API_URL || "";

function authHeaders(): HeadersInit {
  const k = typeof localStorage !== "undefined" ? localStorage.getItem("M3_API_KEY") : null;
  return k ? { Authorization: `Bearer ${k}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status} ${res.statusText}: ${body.slice(0, 300)}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// --- types ---

export interface RetrieveHit {
  item_id: string;
  score: number;
  kind: string;
  when_iso: string | null;
  snippet: string;
  excerpt: string;
  reasons: string[];
}

export interface IngestResponse {
  item_id: string;
  kind: string;
  confidence: number;
  self_touched: string[];
  entities_touched: string[];
  questions_raised: number;
}

export interface EntitySummary {
  slug: string;
  canonical_name: string;
  entity_type: string;
  aliases: string[];
  description: string | null;
  related: string[];
  signal_mentions: number;
  summary_external: string | null;
  body: string;
}

export interface SelfResponse {
  slots: Record<string, string>;
}

export interface OpenQuestion {
  question: string;
}

export interface ItemMeta {
  id: string;
  kind: string;
  source: string;
  created_at: string;
  original_filename: string | null;
  extracted_text: string;
  when_iso: string | null;
  when_source: string;
  hooks: Record<string, unknown>;
  confidence: number;
  archived?: boolean;
}

export interface ItemListEntry {
  id: string;
  kind: string;
  content_kind: string;
  source: string;
  original_filename: string | null;
  created_at: string;
  when_iso: string | null;
  confidence: number;
  snippet: string;
  entity_count: number;
  has_original: boolean;
  has_thumbnail: boolean;
  extension: string | null;
  archived: boolean;
}

export interface ItemListPage {
  items: ItemListEntry[];
  next_cursor: string | null;
  total: number;
}

export interface ProvenanceEntity {
  slug: string;
  canonical_name: string;
  entity_type: string | null;
  role: string;
}

export interface ProvenanceFact {
  text: string;
  source: string;
}

export interface ProvenanceResponse {
  item_id: string;
  entities_touched: ProvenanceEntity[];
  facts: ProvenanceFact[];
  questions: string[];
  signal: Record<string, unknown> | null;
  record: Record<string, unknown> | null;
}

export interface ItemListQuery {
  kind?: string[];
  content_kind?: string[];
  q?: string;
  since_iso?: string;
  until_iso?: string;
  cursor?: string;
  limit?: number;
  include_archived?: boolean;
}

export interface ChatSessionSummary {
  id: string;
  title: string;
  title_locked: boolean;
  message_count: number;
  last_ts: string;
  pinned: boolean;
  folder_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChatFolder {
  id: string;
  name: string;
  sort_order: number;
}

export interface ChatSessionTurn {
  ts: string;
  role: string;
  content: string;
  events: unknown[];
}

export interface ClusterNode {
  id: string;
  type: "query" | "item" | "entity";
  label: string;
  score: number;
  kind: string | null;
  entity_type: string | null;
  when_iso: string | null;
  excerpt: string | null;
  item_id: string | null;
  entity_slug: string | null;
}

export interface ClusterEdge {
  source: string;
  target: string;
  kind: "matched" | "hooks" | "related";
}

export interface ClusterResponse {
  nodes: ClusterNode[];
  edges: ClusterEdge[];
}

export interface LLMSettings {
  provider: string;
  ollama_host: string;
  ollama_model: string;
  anthropic_model: string;
  anthropic_api_key_present: boolean;
  // local_agent: subprocess to a user-installed AI CLI (claude, codex, gemini,
  // aider, mods, llm, or a custom command). Empty means "use defaults".
  local_agent_command: string;
  local_agent_args: string[];
  // False when the active provider can't be built (no key, missing CLI, etc.).
  // Settings + Chat render an empty-state CTA when this is false.
  configured: boolean;
  unconfigured_reason: string | null;
  env_overrides: string[];
}

export interface LocalAgentInfo {
  id: string;
  command: string;
  label: string;
  default_args: string[];
  available: boolean;
  path: string | null;
}

// --- methods ---

interface ChatStreamOptions {
  history?: unknown[];
  session_id?: string;
  scope_item_id?: string;
}

async function* chatStream(message: string, optsOrHistory?: ChatStreamOptions | unknown[], session_id?: string) {
  // Backwards-compatible: callers used to pass (message, history, session_id).
  // New callers can pass an options bag for scope_item_id support.
  let history: unknown[] | undefined;
  let sid: string | undefined = session_id;
  let scope_item_id: string | undefined;
  if (Array.isArray(optsOrHistory)) {
    history = optsOrHistory;
  } else if (optsOrHistory && typeof optsOrHistory === "object") {
    history = optsOrHistory.history;
    sid = optsOrHistory.session_id ?? sid;
    scope_item_id = optsOrHistory.scope_item_id;
  }
  const res = await fetch(`${BASE}/api/v1/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ message, history, session_id: sid, scope_item_id }),
  });
  if (!res.ok || !res.body) throw new Error(`chat ${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const line = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      if (line.startsWith("data: ")) {
        const payload = line.slice(6);
        if (payload === "[DONE]") return;
        yield JSON.parse(payload);
      }
    }
  }
}

export const api = {
  status: () => request<{ ok: boolean; brain_root: string }>("/api/v1/status"),

  retrieve: (q: string, k = 10, since?: string, until?: string) => {
    const params = new URLSearchParams({ q, k: String(k) });
    if (since) params.set("since", since);
    if (until) params.set("until", until);
    return request<{ hits: RetrieveHit[] }>(`/api/v1/retrieve?${params}`);
  },

  ingestText: (text: string, source = "web") =>
    request<IngestResponse>("/api/v1/ingest/text", {
      method: "POST",
      body: JSON.stringify({ text, source }),
    }),

  ingestFile: async (file: File, source = "web"): Promise<IngestResponse> => {
    const form = new FormData();
    form.append("file", file);
    form.append("source", source);
    const res = await fetch(`${BASE}/api/v1/ingest/file`, {
      method: "POST",
      headers: authHeaders(),
      body: form,
    });
    if (!res.ok) throw new Error(`ingest file ${res.status}`);
    return res.json();
  },

  self: () => request<SelfResponse>("/api/v1/self"),

  updateSelfSection: (slot: string, new_content: string) =>
    request<{ slot: string; new_body: string }>(
      `/api/v1/self/${encodeURIComponent(slot)}`,
      { method: "PUT", body: JSON.stringify({ slot, new_content }) },
    ),

  entities: () => request<{ entities: EntitySummary[] }>("/api/v1/entities"),

  entity: (slug: string) => request<EntitySummary>(`/api/v1/entities/${encodeURIComponent(slug)}`),

  openQuestions: () => request<{ questions: OpenQuestion[] }>("/api/v1/open-questions"),

  resolveQuestion: (question_text: string, answer: string) =>
    request<{ resolved: boolean }>("/api/v1/open-questions/resolve", {
      method: "POST",
      body: JSON.stringify({ question_text, answer }),
    }),

  item: (id: string) => request<ItemMeta>(`/api/v1/items/${id}`),

  itemOriginalUrl: (id: string) => `${BASE}/api/v1/items/${id}/original`,

  itemThumbnailUrl: (id: string) => `${BASE}/api/v1/items/${id}/thumbnail`,

  listItems: (params: ItemListQuery = {}) => {
    const sp = new URLSearchParams();
    for (const k of params.kind || []) sp.append("kind", k);
    for (const ck of params.content_kind || []) sp.append("content_kind", ck);
    if (params.q) sp.set("q", params.q);
    if (params.since_iso) sp.set("since_iso", params.since_iso);
    if (params.until_iso) sp.set("until_iso", params.until_iso);
    if (params.cursor) sp.set("cursor", params.cursor);
    if (params.limit != null) sp.set("limit", String(params.limit));
    if (params.include_archived) sp.set("include_archived", "true");
    const qs = sp.toString();
    return request<ItemListPage>(`/api/v1/items${qs ? `?${qs}` : ""}`);
  },

  itemText: (id: string, max_chars = 20000) =>
    request<{ extracted_text: string; truncated: boolean }>(
      `/api/v1/items/${id}/text?max_chars=${max_chars}`,
    ),

  itemProvenance: (id: string) =>
    request<ProvenanceResponse>(`/api/v1/items/${id}/provenance`),

  archiveItem: (id: string, archived: boolean) =>
    request<{ ok: boolean; archived: boolean }>(`/api/v1/items/${id}/archive`, {
      method: "POST",
      body: JSON.stringify({ archived }),
    }),

  reingestItem: (id: string) =>
    request<IngestResponse>(`/api/v1/items/${id}/reingest`, { method: "POST" }),

  settings: () => request<LLMSettings>("/api/v1/settings"),

  updateSettings: (
    update: Partial<LLMSettings> & {
      anthropic_api_key?: string;
      clear_anthropic_api_key?: boolean;
    },
  ) =>
    request<LLMSettings>("/api/v1/settings", {
      method: "PUT",
      body: JSON.stringify(update),
    }),

  listAgents: () => request<LocalAgentInfo[]>("/api/v1/settings/agents"),

  cluster: (q: string, k = 15) =>
    request<ClusterResponse>(`/api/v1/cluster?q=${encodeURIComponent(q)}&k=${k}`),

  /** Whole-brain graph: every item + entity with persisted edges. */
  clusterAll: () => request<ClusterResponse>("/api/v1/cluster/all"),

  chat: chatStream,

  listChats: () => request<ChatSessionSummary[]>("/api/v1/chats"),

  newChat: () => request<{ id: string }>("/api/v1/chats", { method: "POST" }),

  getChat: (sid: string) =>
    request<{ id: string; turns: ChatSessionTurn[] }>(
      `/api/v1/chats/${encodeURIComponent(sid)}`,
    ),

  patchChat: (
    sid: string,
    fields: { title?: string; pinned?: boolean; folder_id?: string | null },
  ) =>
    request<ChatSessionSummary>(`/api/v1/chats/${encodeURIComponent(sid)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    }),

  deleteChat: (sid: string) =>
    request<void>(`/api/v1/chats/${encodeURIComponent(sid)}`, { method: "DELETE" }),

  listFolders: () => request<ChatFolder[]>("/api/v1/folders"),

  createFolder: (name: string) =>
    request<ChatFolder>("/api/v1/folders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),

  patchFolder: (fid: string, fields: { name?: string; sort_order?: number }) =>
    request<ChatFolder>(`/api/v1/folders/${encodeURIComponent(fid)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    }),

  deleteFolder: (fid: string) =>
    request<void>(`/api/v1/folders/${encodeURIComponent(fid)}`, { method: "DELETE" }),
};
