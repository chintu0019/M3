const BASE = import.meta.env.VITE_API_URL || "";

function getApiKey(): string {
  return localStorage.getItem("m3_api_key") || "";
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${getApiKey()}`,
      ...options?.headers,
    },
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

// --- Types ---

export interface RawItem {
  id: string;
  content_text: string | null;
  content_type: string | null;
  source_channel: string | null;
  file_path: string | null;
  file_url: string | null;
  user_tags: string[];
  user_project: string | null;
  status: string;
  error_message: string | null;
  created_at: string;
  processing_started_at: string | null;
  processed_at: string | null;
}

export interface ItemNote {
  id: string;
  item_id: string;
  content: string;
  created_at: string;
  updated_at: string;
}

export interface ItemDetail extends RawItem {
  file_url: string | null;
  notes: ItemNote[];
}

export interface CountItem {
  key: string;
  count: number;
}

export interface LibraryStats {
  totals: {
    all: number;
    recent: number;
    pending: number;
    processing: number;
    done: number;
    error: number;
  };
  projects: CountItem[];
  types: CountItem[];
  sources: CountItem[];
}

export interface BulkOpError {
  id: string;
  error: string;
}

export interface BulkOpResult {
  succeeded: string[];
  failed: BulkOpError[];
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
}

export interface ProviderInfo {
  name: string;
  type: string;
  model: string;
  base_url: string | null;
  has_api_key: boolean;
  active: boolean;
}

export interface LLMSettings {
  active_provider: string;
  providers: ProviderInfo[];
}

// --- Entities (Phase 5) ---

export interface EntitySummary {
  id: string;
  canonical_name: string;
  entity_type: string;
  aliases: string[];
  updated_at: string;
  has_page: boolean;
  facts_since_render: number;
}

export interface RelatedEntity {
  id: string;
  canonical_name: string;
  entity_type: string;
  link_type: string;
  weight: number;
}

export interface InsightSummary {
  id: string;
  insight_type: string;
  title: string;
  description: string;
  related_entity_ids: string[];
  related_item_ids: string[];
  status: string;
  created_at: string;
}

export interface EntityDetail extends EntitySummary {
  description: string | null;
  page_content: string | null;
  page_overview: string | null;
  page_dirty: boolean;
  created_at: string;
  related: RelatedEntity[];
  insights: InsightSummary[];
}

export interface EntityGraphNode {
  id: string;
  canonical_name: string;
  entity_type: string;
  fact_count: number;
}

export interface EntityGraphEdge {
  source_id: string;
  target_id: string;
  link_type: string;
  weight: number;
}

export interface EntityGraph {
  nodes: EntityGraphNode[];
  edges: EntityGraphEdge[];
}

export interface EntityCreateBody {
  canonical_name: string;
  entity_type: string;
  description?: string | null;
}

export interface EntityPatchBody {
  canonical_name?: string;
  page_content?: string | null;
  description?: string | null;
}

export interface EntityLinkCreateBody {
  source_entity_id: string;
  target_entity_id: string;
  link_type?: string;
  weight?: number;
}

export interface EntityLinkResponse {
  id: string;
  source_entity_id: string;
  target_entity_id: string;
  link_type: string;
  weight: number;
}

// --- Canvas ---

export interface CanvasNodeData {
  entity_type?: string;
  has_page?: boolean;
  overview?: string | null;
  facts_since_render?: number;
  insight_type?: string;
  description?: string;
  status?: string;
  created_at?: string;
  ended_at?: string | null;
}

export interface CanvasNode {
  id: string;
  node_type: "entity" | "insight" | "thread";
  label: string;
  data: CanvasNodeData;
  x: number | null;
  y: number | null;
  width: number | null;
  height: number | null;
}

// --- Chat threads (Phase C) ---

export interface ChatThreadSummary {
  id: string;
  title: string | null;
  summary: string | null;
  status: string;
  created_at: string;
  ended_at: string | null;
  message_count: number;
}

export interface ChatMessage {
  id: string;
  role: string;
  content: string;
  created_at: string;
}

export interface ChatThreadDetail extends ChatThreadSummary {
  messages: ChatMessage[];
  cited_entity_ids: string[];
}

export interface ChatCite {
  entity_id: string;
  name: string;
  entity_type: string;
}

export interface CanvasEdge {
  id: string;
  source: string;
  target: string;
  edge_type: string;
  weight: number;
}

export interface CanvasResponse {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
}

export interface CanvasLayoutUpdate {
  node_type: string;
  node_id: string;
  x: number;
  y: number;
  width?: number | null;
  height?: number | null;
  z_index?: number;
}

// --- API ---

export const api = {
  status: () => request<{ status: string; version: string }>("/api/v1/status"),

  ingest: {
    list: (params?: Record<string, string>) =>
      request<Paginated<RawItem>>(
        `/api/v1/ingest${params ? "?" + new URLSearchParams(params) : ""}`,
      ),
    create: async (text: string, tags?: string, project?: string) => {
      const form = new FormData();
      form.append("content_text", text);
      if (tags) form.append("tags", tags);
      if (project) form.append("project", project);
      return request<{ id: string; status: string }>("/api/v1/ingest", {
        method: "POST",
        body: form,
      });
    },
    upload: async (file: File, tags?: string, project?: string) => {
      const form = new FormData();
      form.append("file", file);
      if (tags) form.append("tags", tags);
      if (project) form.append("project", project);
      return request<{ id: string; status: string }>("/api/v1/ingest", {
        method: "POST",
        body: form,
      });
    },
  },

  library: {
    get: (id: string) => request<ItemDetail>(`/api/v1/ingest/${id}`),
    patch: (id: string, data: { filename?: string; user_tags?: string[]; user_project?: string | null }) =>
      request<ItemDetail>(`/api/v1/ingest/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    delete: (id: string) =>
      fetch(`${BASE}/api/v1/ingest/${id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${localStorage.getItem("m3_api_key") || ""}` },
      }).then((r) => {
        if (!r.ok) throw new Error(`Delete failed: ${r.status}`);
      }),
    retry: (id: string) =>
      request<ItemDetail>(`/api/v1/ingest/${id}/retry`, { method: "POST" }),
    notes: {
      create: (id: string, content: string) =>
        request<ItemNote>(`/api/v1/ingest/${id}/notes`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content }),
        }),
      update: (id: string, noteId: string, content: string) =>
        request<ItemNote>(`/api/v1/ingest/${id}/notes/${noteId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content }),
        }),
      delete: (id: string, noteId: string) =>
        fetch(`${BASE}/api/v1/ingest/${id}/notes/${noteId}`, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${localStorage.getItem("m3_api_key") || ""}` },
        }).then((r) => {
          if (!r.ok) throw new Error(`Delete note failed: ${r.status}`);
        }),
    },
    bulkRetry: (ids: string[]) =>
      request<BulkOpResult>(`/api/v1/ingest/bulk/retry`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids }),
      }),
    bulkDelete: (ids: string[]) =>
      request<BulkOpResult>(`/api/v1/ingest/bulk/delete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids }),
      }),
    stats: () => request<LibraryStats>(`/api/v1/ingest/library/stats`),
  },

  entities: {
    list: (params?: Record<string, string>) =>
      request<Paginated<EntitySummary>>(
        `/api/v1/entities${params ? "?" + new URLSearchParams(params) : ""}`,
      ),
    get: (id: string) => request<EntityDetail>(`/api/v1/entities/${id}`),
    graph: (params?: Record<string, string>) =>
      request<EntityGraph>(
        `/api/v1/entities/graph${params ? "?" + new URLSearchParams(params) : ""}`,
      ),
    create: (body: EntityCreateBody) =>
      request<EntityDetail>(`/api/v1/entities`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    patch: (id: string, body: EntityPatchBody) =>
      request<EntityDetail>(`/api/v1/entities/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
  },

  entityLinks: {
    create: (body: EntityLinkCreateBody) =>
      request<EntityLinkResponse>(`/api/v1/entity-links`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    delete: (id: string) =>
      fetch(`${BASE}/api/v1/entity-links/${id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${localStorage.getItem("m3_api_key") || ""}` },
      }).then((r) => {
        if (!r.ok) throw new Error(`Delete link failed: ${r.status}`);
      }),
  },

  threads: {
    list: (params?: Record<string, string>) =>
      request<Paginated<ChatThreadSummary>>(
        `/api/v1/chat/threads${params ? "?" + new URLSearchParams(params) : ""}`,
      ),
    create: (title?: string) =>
      request<ChatThreadSummary>(`/api/v1/chat/threads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: title ?? null }),
      }),
    get: (id: string) => request<ChatThreadDetail>(`/api/v1/chat/threads/${id}`),
    end: (id: string) =>
      request<ChatThreadSummary>(`/api/v1/chat/threads/${id}/end`, { method: "POST" }),
  },

  insights: {
    list: (params?: Record<string, string>) =>
      request<Paginated<InsightSummary>>(
        `/api/v1/insights${params ? "?" + new URLSearchParams(params) : ""}`,
      ),
    patch: (id: string, status: string) =>
      request<InsightSummary>(`/api/v1/insights/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      }),
  },

  canvas: {
    get: (params?: Record<string, string>) =>
      request<CanvasResponse>(
        `/api/v1/canvas${params ? "?" + new URLSearchParams(params) : ""}`,
      ),
    patchLayout: (updates: CanvasLayoutUpdate[]) =>
      request<{ written: number }>(`/api/v1/canvas/layout`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ updates }),
      }),
  },

  settings: {
    getLLM: () => request<LLMSettings>("/api/v1/settings/llm"),
    switchProvider: (provider: string) =>
      request<LLMSettings>("/api/v1/settings/llm/switch", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider }),
      }),
    addProvider: (data: {
      name: string;
      type: string;
      model: string;
      api_key?: string;
      base_url?: string;
    }) =>
      request<LLMSettings>("/api/v1/settings/llm/providers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    updateProvider: (name: string, data: { model?: string; api_key?: string; base_url?: string }) =>
      request<LLMSettings>(`/api/v1/settings/llm/providers/${encodeURIComponent(name)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    deleteProvider: (name: string) =>
      request<LLMSettings>(`/api/v1/settings/llm/providers/${encodeURIComponent(name)}`, {
        method: "DELETE",
      }),
  },

  chat: async function* (
    message: string,
    thread_id?: string,
  ): AsyncGenerator<{ text?: string; cite?: ChatCite }> {
    const res = await fetch(`${BASE}/api/v1/chat`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${getApiKey()}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ message, thread_id }),
    });

    if (!res.ok) throw new Error(`Chat error: ${res.status}`);
    if (!res.body) return;

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const data = line.slice(6).trim();
            if (data === "[DONE]") return;
            try {
              yield JSON.parse(data);
            } catch {
              // skip malformed
            }
          }
        }
      }
    } finally {
      // Release the connection if the consumer breaks out early (component
      // unmount, dock collapse mid-stream, thrown error downstream).
      try {
        await reader.cancel();
      } catch {
        // reader may already be closed
      }
    }
  },
};
