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
  user_tags: string[];
  user_project: string | null;
  status: string;
  error_message: string | null;
  created_at: string;
  processed_at: string | null;
}

export interface WikiPageSummary {
  id: string;
  title: string;
  category: string | null;
  page_type: string | null;
  tags: string[];
  confidence: number;
  created_at: string;
  updated_at: string;
}

export interface WikiPage extends WikiPageSummary {
  content: string;
  source_items: string[];
  metadata: Record<string, unknown>;
  linked_pages: { id: string; title: string; link_type: string; direction: string }[];
}

export interface SearchResult {
  page_id: string;
  title: string;
  snippet: string;
  score: number;
  category: string | null;
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

  wiki: {
    pages: (params?: Record<string, string>) =>
      request<Paginated<WikiPageSummary>>(
        `/api/v1/wiki/pages${params ? "?" + new URLSearchParams(params) : ""}`,
      ),
    page: (id: string) => request<WikiPage>(`/api/v1/wiki/pages/${id}`),
    search: (q: string) =>
      request<SearchResult[]>(`/api/v1/wiki/search?q=${encodeURIComponent(q)}`),
    projects: () => request<string[]>("/api/v1/wiki/projects"),
    tags: () => request<{ tag: string; count: number }[]>("/api/v1/wiki/tags"),
    graph: () =>
      request<{
        nodes: { id: string; title: string; category: string | null; connection_count: number }[];
        edges: { source_id: string; target_id: string; link_type: string; weight: number }[];
      }>("/api/v1/wiki/graph"),
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

  chat: async function* (message: string): AsyncGenerator<{ text?: string; citations?: { page_id: string; title: string }[] }> {
    const res = await fetch(`${BASE}/api/v1/chat`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${getApiKey()}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ message }),
    });

    if (!res.ok) throw new Error(`Chat error: ${res.status}`);
    if (!res.body) return;

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

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
  },
};
