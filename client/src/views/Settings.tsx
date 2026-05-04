import { useEffect, useState } from "react";
import { api, LLMSettings } from "../api/client";

export default function Settings() {
  const [s, setS] = useState<LLMSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");

  useEffect(() => {
    api.settings().then(setS).catch((e) => setError(String(e)));
  }, []);

  if (error) return <div className="p-6 text-red-400">{error}</div>;
  if (!s) return <div className="p-6 text-m3-muted">loading…</div>;

  async function save(update: Parameters<typeof api.updateSettings>[0]) {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const next = await api.updateSettings(update);
      setS(next);
      setApiKey("");
      setMessage("saved. next request will use the new setting.");
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>

      {s.env_overrides.length > 0 && (
        <div className="border border-amber-500/40 bg-amber-500/10 p-3 rounded text-sm">
          <strong>Env overrides active:</strong> {s.env_overrides.join(", ")}.
          These take precedence over anything you set here. Unset them in your
          shell/launchd for these settings to apply.
        </div>
      )}

      <section className="space-y-2">
        <label className="block text-sm font-semibold">LLM provider</label>
        <div className="flex gap-2">
          {["ollama", "anthropic"].map((p) => (
            <button
              key={p}
              onClick={() => save({ provider: p })}
              disabled={saving}
              className={`px-4 py-2 rounded border ${
                s.provider === p
                  ? "bg-m3-accent border-m3-accent text-white"
                  : "border-m3-border text-m3-muted hover:text-m3-text"
              }`}
            >
              {p}
            </button>
          ))}
        </div>
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold">Ollama</h2>
        <label className="block text-xs text-m3-muted">Host</label>
        <input
          defaultValue={s.ollama_host}
          onBlur={(e) => save({ ollama_host: e.target.value })}
          className="w-full bg-m3-surface border border-m3-border rounded px-3 py-1.5 text-sm"
        />
        <label className="block text-xs text-m3-muted mt-3">Model</label>
        <input
          defaultValue={s.ollama_model}
          onBlur={(e) => save({ ollama_model: e.target.value })}
          className="w-full bg-m3-surface border border-m3-border rounded px-3 py-1.5 text-sm"
        />
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold">Anthropic</h2>
        <label className="block text-xs text-m3-muted">Model</label>
        <input
          defaultValue={s.anthropic_model}
          onBlur={(e) => save({ anthropic_model: e.target.value })}
          className="w-full bg-m3-surface border border-m3-border rounded px-3 py-1.5 text-sm"
        />
        <label className="block text-xs text-m3-muted mt-3">
          API key {s.anthropic_api_key_present && <span className="text-green-400">· set</span>}
        </label>
        <div className="flex gap-2">
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="sk-ant-..."
            className="flex-1 bg-m3-surface border border-m3-border rounded px-3 py-1.5 text-sm"
          />
          <button
            onClick={() => save({ anthropic_api_key: apiKey })}
            disabled={saving || !apiKey}
            className="px-3 py-1.5 rounded bg-m3-accent disabled:opacity-50"
          >
            save
          </button>
          {s.anthropic_api_key_present && (
            <button
              onClick={() => save({ clear_anthropic_api_key: true })}
              disabled={saving}
              className="px-3 py-1.5 rounded border border-m3-border text-sm"
            >
              clear
            </button>
          )}
        </div>
      </section>

      {saving && <div className="text-m3-muted text-sm">saving…</div>}
      {message && <div className="text-green-400 text-sm">{message}</div>}
    </div>
  );
}
