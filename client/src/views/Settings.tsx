import { useCallback, useEffect, useState } from "react";
import { api, type LLMSettings, type ProviderInfo } from "../api/client";

// --- Presets for quick-adding popular providers ---

const PRESETS: {
  name: string;
  label: string;
  type: string;
  model: string;
  base_url: string;
  description: string;
}[] = [
  {
    name: "minimax",
    label: "MiniMax",
    type: "openai_compatible",
    model: "MiniMax-M1",
    base_url: "https://api.minimaxi.chat/v1",
    description: "Fast, affordable, great for most tasks",
  },
  {
    name: "openrouter",
    label: "OpenRouter",
    type: "openai_compatible",
    model: "anthropic/claude-sonnet-4",
    base_url: "https://openrouter.ai/api/v1",
    description: "200+ models through one API key",
  },
  {
    name: "groq",
    label: "Groq",
    type: "openai_compatible",
    model: "llama-3.3-70b-versatile",
    base_url: "https://api.groq.com/openai/v1",
    description: "Blazing fast inference for open models",
  },
  {
    name: "together",
    label: "Together AI",
    type: "openai_compatible",
    model: "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    base_url: "https://api.together.xyz/v1",
    description: "Wide selection of open models",
  },
  {
    name: "ollama",
    label: "Ollama (local)",
    type: "openai_compatible",
    model: "llama3.1:70b",
    base_url: "http://localhost:11434/v1",
    description: "Fully local, no API key needed",
  },
  {
    name: "claude",
    label: "Anthropic Claude",
    type: "anthropic",
    model: "claude-sonnet-4-20250514",
    base_url: "",
    description: "Best reasoning, requires Anthropic API key",
  },
];

// --- Provider form (used for both add and edit) ---

function ProviderForm({
  initial,
  onSubmit,
  onCancel,
  submitLabel,
}: {
  initial?: { name?: string; type?: string; model?: string; api_key?: string; base_url?: string };
  onSubmit: (data: { name: string; type: string; model: string; api_key: string; base_url: string }) => void;
  onCancel: () => void;
  submitLabel: string;
}) {
  const [name, setName] = useState(initial?.name || "");
  const [type, setType] = useState(initial?.type || "openai_compatible");
  const [model, setModel] = useState(initial?.model || "");
  const [apiKey, setApiKey] = useState(initial?.api_key || "");
  const [baseUrl, setBaseUrl] = useState(initial?.base_url || "");
  const isEdit = !!initial?.name;

  const applyPreset = (preset: (typeof PRESETS)[number]) => {
    if (!isEdit) setName(preset.name);
    setType(preset.type);
    setModel(preset.model);
    setBaseUrl(preset.base_url);
  };

  return (
    <div className="bg-m3-bg border border-m3-border rounded-xl p-5 space-y-4">
      {/* Presets */}
      {!isEdit && (
        <div>
          <label className="block text-xs text-m3-muted mb-2 uppercase tracking-wide">Quick setup</label>
          <div className="flex flex-wrap gap-2">
            {PRESETS.map((p) => (
              <button
                key={p.name}
                onClick={() => applyPreset(p)}
                className="text-xs px-3 py-1.5 bg-m3-surface border border-m3-border rounded-lg hover:border-m3-muted transition-colors"
                title={p.description}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs text-m3-muted mb-1">Name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="my-provider"
            disabled={isEdit}
            className="w-full bg-m3-surface border border-m3-border rounded-lg px-3 py-2 text-sm disabled:opacity-50"
          />
        </div>
        <div>
          <label className="block text-xs text-m3-muted mb-1">Type</label>
          <select
            value={type}
            onChange={(e) => setType(e.target.value)}
            className="w-full bg-m3-surface border border-m3-border rounded-lg px-3 py-2 text-sm"
          >
            <option value="openai_compatible">OpenAI Compatible</option>
            <option value="anthropic">Anthropic</option>
          </select>
        </div>
      </div>

      <div>
        <label className="block text-xs text-m3-muted mb-1">Model</label>
        <input
          value={model}
          onChange={(e) => setModel(e.target.value)}
          placeholder="e.g. MiniMax-M1, claude-sonnet-4-20250514"
          className="w-full bg-m3-surface border border-m3-border rounded-lg px-3 py-2 text-sm"
        />
      </div>

      {type === "openai_compatible" && (
        <div>
          <label className="block text-xs text-m3-muted mb-1">Base URL</label>
          <input
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://api.minimaxi.chat/v1"
            className="w-full bg-m3-surface border border-m3-border rounded-lg px-3 py-2 text-sm"
          />
        </div>
      )}

      <div>
        <label className="block text-xs text-m3-muted mb-1">
          API Key {isEdit && <span className="text-m3-muted">(leave blank to keep current)</span>}
        </label>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={isEdit ? "unchanged" : "sk-..."}
          className="w-full bg-m3-surface border border-m3-border rounded-lg px-3 py-2 text-sm"
        />
      </div>

      <div className="flex gap-2 justify-end pt-1">
        <button
          onClick={onCancel}
          className="px-4 py-2 text-sm text-m3-muted hover:text-m3-text transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={() => onSubmit({ name, type, model, api_key: apiKey, base_url: baseUrl })}
          disabled={!name || !model}
          className="px-4 py-2 bg-m3-accent text-white rounded-lg text-sm hover:bg-m3-accent-hover transition-colors disabled:opacity-50"
        >
          {submitLabel}
        </button>
      </div>
    </div>
  );
}

// --- Provider card ---

function ProviderCard({
  provider,
  onSwitch,
  onEdit,
  onDelete,
  switching,
}: {
  provider: ProviderInfo;
  onSwitch: (name: string) => void;
  onEdit: (name: string) => void;
  onDelete: (name: string) => void;
  switching: boolean;
}) {
  const isLocal =
    provider.base_url?.includes("localhost") || provider.base_url?.includes("127.0.0.1");
  const needsKey = !provider.has_api_key && !isLocal;

  return (
    <div
      className={`border rounded-xl p-4 transition-all ${
        provider.active
          ? "border-m3-accent bg-m3-accent/5"
          : needsKey
            ? "border-m3-border/50 opacity-60"
            : "border-m3-border hover:border-m3-muted"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="font-semibold">{provider.name}</span>
            {provider.active && (
              <span className="text-xs bg-m3-accent/20 text-m3-accent px-2 py-0.5 rounded-full">
                Active
              </span>
            )}
            {needsKey && (
              <span className="text-xs bg-yellow-900/30 text-yellow-400 px-2 py-0.5 rounded-full">
                No API key
              </span>
            )}
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-m3-muted">
            <span>
              Model: <span className="text-m3-text">{provider.model}</span>
            </span>
            <span>
              Type: <span className="text-m3-text">{provider.type}</span>
            </span>
            {provider.base_url && (
              <span>
                Endpoint:{" "}
                <span className="text-m3-text">
                  {(() => {
                    try {
                      return new URL(provider.base_url).host;
                    } catch {
                      return provider.base_url;
                    }
                  })()}
                </span>
              </span>
            )}
          </div>
        </div>
        <div className="flex gap-2 shrink-0">
          <button
            onClick={() => onEdit(provider.name)}
            className="px-3 py-1.5 text-xs text-m3-muted hover:text-m3-text hover:bg-m3-surface border border-transparent hover:border-m3-border rounded-lg transition-all"
          >
            Edit
          </button>
          {!provider.active && (
            <>
              <button
                onClick={() => onDelete(provider.name)}
                className="px-3 py-1.5 text-xs text-red-400/60 hover:text-red-400 hover:bg-red-900/20 border border-transparent hover:border-red-900/50 rounded-lg transition-all"
              >
                Delete
              </button>
              <button
                onClick={() => onSwitch(provider.name)}
                disabled={switching || needsKey}
                className="px-4 py-1.5 bg-m3-surface border border-m3-border rounded-lg text-sm hover:bg-m3-border hover:border-m3-muted transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {switching ? "..." : "Use this"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// --- Main Settings page ---

export default function Settings() {
  const [apiKey, setApiKey] = useState(localStorage.getItem("m3_api_key") || "");
  const [status, setStatus] = useState<{ status: string; version: string } | null>(null);
  const [connError, setConnError] = useState("");
  const [llmSettings, setLlmSettings] = useState<LLMSettings | null>(null);
  const [switching, setSwitching] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: "ok" | "err" } | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [editingProvider, setEditingProvider] = useState<string | null>(null);

  const flash = (text: string, type: "ok" | "err" = "ok") => {
    setMessage({ text, type });
    setTimeout(() => setMessage(null), 3000);
  };

  const checkConnection = async () => {
    try {
      const res = await api.status();
      setStatus(res);
      setConnError("");
    } catch (err) {
      setStatus(null);
      setConnError(`${err}`);
    }
  };

  const loadLLM = useCallback(async () => {
    try {
      setLlmSettings(await api.settings.getLLM());
    } catch {
      /* not connected */
    }
  }, []);

  useEffect(() => {
    if (apiKey) {
      checkConnection();
      loadLLM();
    }
  }, [loadLLM]);

  const handleSaveKey = () => {
    localStorage.setItem("m3_api_key", apiKey);
    checkConnection();
    loadLLM();
  };

  const handleSwitch = async (provider: string) => {
    setSwitching(true);
    try {
      setLlmSettings(await api.settings.switchProvider(provider));
      flash(`Switched to ${provider}`);
    } catch (err) {
      flash(`${err}`, "err");
    }
    setSwitching(false);
  };

  const handleAdd = async (data: {
    name: string;
    type: string;
    model: string;
    api_key: string;
    base_url: string;
  }) => {
    try {
      setLlmSettings(
        await api.settings.addProvider({
          name: data.name,
          type: data.type,
          model: data.model,
          api_key: data.api_key || undefined,
          base_url: data.base_url || undefined,
        }),
      );
      setShowAddForm(false);
      flash(`Added ${data.name}`);
    } catch (err) {
      flash(`${err}`, "err");
    }
  };

  const handleEdit = async (data: {
    name: string;
    type: string;
    model: string;
    api_key: string;
    base_url: string;
  }) => {
    try {
      const update: { model?: string; api_key?: string; base_url?: string } = {};
      if (data.model) update.model = data.model;
      if (data.api_key) update.api_key = data.api_key;
      if (data.base_url !== undefined) update.base_url = data.base_url;
      setLlmSettings(await api.settings.updateProvider(data.name, update));
      setEditingProvider(null);
      flash(`Updated ${data.name}`);
    } catch (err) {
      flash(`${err}`, "err");
    }
  };

  const handleDelete = async (name: string) => {
    if (!confirm(`Delete provider "${name}"?`)) return;
    try {
      setLlmSettings(await api.settings.deleteProvider(name));
      flash(`Deleted ${name}`);
    } catch (err) {
      flash(`${err}`, "err");
    }
  };

  const editingProviderData = editingProvider
    ? llmSettings?.providers.find((p) => p.name === editingProvider)
    : null;

  return (
    <div className="max-w-2xl mx-auto p-6">
      <h1 className="text-2xl font-bold mb-6">Settings</h1>

      {/* Connection */}
      <div className="bg-m3-surface border border-m3-border rounded-xl p-6 mb-6">
        <h2 className="text-lg font-semibold mb-4">API Connection</h2>
        <div className="mb-4">
          <label className="block text-xs text-m3-muted mb-1">M3 API Key</label>
          <div className="flex gap-2">
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Enter your M3 API key"
              className="flex-1 bg-m3-bg border border-m3-border rounded-lg px-3 py-2 text-sm"
            />
            <button
              onClick={handleSaveKey}
              className="px-4 py-2 bg-m3-accent text-white rounded-lg text-sm hover:bg-m3-accent-hover transition-colors"
            >
              Save
            </button>
          </div>
        </div>
        {status && (
          <div className="p-3 bg-green-900/20 border border-green-800 rounded-lg text-sm text-green-300">
            Connected -- M3 v{status.version}
          </div>
        )}
        {connError && (
          <div className="p-3 bg-red-900/20 border border-red-800 rounded-lg text-sm text-red-300">
            {connError}
          </div>
        )}
      </div>

      {/* LLM Providers */}
      {llmSettings && (
        <div className="bg-m3-surface border border-m3-border rounded-xl p-6 mb-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">LLM Providers</h2>
            {message && (
              <span
                className={`text-sm ${message.type === "err" ? "text-red-400" : "text-green-400"}`}
              >
                {message.text}
              </span>
            )}
          </div>

          {/* Provider list */}
          <div className="space-y-3 mb-4">
            {llmSettings.providers.map((p) =>
              editingProvider === p.name ? (
                <ProviderForm
                  key={p.name}
                  initial={{
                    name: p.name,
                    type: p.type,
                    model: p.model,
                    base_url: p.base_url || "",
                  }}
                  onSubmit={handleEdit}
                  onCancel={() => setEditingProvider(null)}
                  submitLabel="Save"
                />
              ) : (
                <ProviderCard
                  key={p.name}
                  provider={p}
                  onSwitch={handleSwitch}
                  onEdit={setEditingProvider}
                  onDelete={handleDelete}
                  switching={switching}
                />
              ),
            )}
          </div>

          {/* Add form or button */}
          {showAddForm ? (
            <ProviderForm
              onSubmit={handleAdd}
              onCancel={() => setShowAddForm(false)}
              submitLabel="Add Provider"
            />
          ) : (
            <button
              onClick={() => setShowAddForm(true)}
              className="w-full py-3 border-2 border-dashed border-m3-border rounded-xl text-sm text-m3-muted hover:text-m3-text hover:border-m3-muted transition-colors"
            >
              + Add provider
            </button>
          )}
        </div>
      )}

      {/* About */}
      <div className="bg-m3-surface border border-m3-border rounded-xl p-6">
        <h2 className="text-lg font-semibold mb-2">About</h2>
        <p className="text-sm text-m3-muted">
          M3 -- Personal Knowledge Operating System. Self-hosted, single-user, fully private.
        </p>
      </div>
    </div>
  );
}
