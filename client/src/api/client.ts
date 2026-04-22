// API client for M3 local server (brain-backed, no auth).
// Defaults to same-origin; override with VITE_API_URL for `npm run dev` against a running server.

const BASE = import.meta.env.VITE_API_URL || "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status} ${res.statusText}: ${body.slice(0, 300)}`);
  }
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
}

// --- methods ---

async function* chatStream(message: string, history?: unknown[]) {
  const res = await fetch(`${BASE}/api/v1/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history }),
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
    const res = await fetch(`${BASE}/api/v1/ingest/file`, { method: "POST", body: form });
    if (!res.ok) throw new Error(`ingest file ${res.status}`);
    return res.json();
  },

  self: () => request<SelfResponse>("/api/v1/self"),

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

  chat: chatStream,
};
