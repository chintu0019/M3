import { useEffect, useMemo, useState } from "react";
import { api, LLMSettings, LocalAgentInfo } from "../api/client";

const PROVIDERS: { id: string; label: string }[] = [
  { id: "ollama", label: "ollama" },
  { id: "anthropic", label: "anthropic" },
  { id: "local_agent", label: "local agent" },
];

export default function Settings() {
  const [s, setS] = useState<LLMSettings | null>(null);
  const [agents, setAgents] = useState<LocalAgentInfo[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  // The custom-command escape hatch -- lets users wrap any AI CLI not in
  // KNOWN_AGENTS by typing the binary name and a space-separated arg list.
  const [customCommand, setCustomCommand] = useState("");
  const [customArgs, setCustomArgs] = useState("-p");

  useEffect(() => {
    api.settings().then(setS).catch((e) => setError(String(e)));
    api.listAgents().then(setAgents).catch(() => {
      // Detection failure is non-fatal; the provider buttons still work.
    });
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

  function pickAgent(agent: LocalAgentInfo) {
    void save({
      provider: "local_agent",
      local_agent_command: agent.command,
      local_agent_args: agent.default_args,
    });
  }

  function pickCustom() {
    const cmd = customCommand.trim();
    if (!cmd) return;
    const args = customArgs
      .split(/\s+/)
      .map((p) => p.trim())
      .filter(Boolean);
    void save({
      provider: "local_agent",
      local_agent_command: cmd,
      local_agent_args: args,
    });
  }

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>

      {/* Empty state when the configured provider can't be built. */}
      {!s.configured && (
        <div className="border border-yellow-600/50 bg-yellow-900/20 text-yellow-100 p-4 rounded">
          <div className="font-semibold mb-1">Pick an AI agent to get started</div>
          <div className="text-sm">
            M3 is running but no LLM is wired up
            {s.unconfigured_reason ? ` (${s.unconfigured_reason})` : ""}.
            Choose an installed agent below or paste an Anthropic API key.
            Chat is disabled until you do.
          </div>
        </div>
      )}

      {s.env_overrides.length > 0 && (
        <div className="border border-amber-500/40 bg-amber-500/10 p-3 rounded text-sm">
          <strong>Env overrides active:</strong> {s.env_overrides.join(", ")}.
          These take precedence over anything you set here. Unset them in your
          shell/launchd for these settings to apply.
        </div>
      )}

      <section className="space-y-2">
        <label className="block text-sm font-semibold">LLM provider</label>
        <div className="flex gap-2 flex-wrap">
          {PROVIDERS.map((p) => (
            <button
              key={p.id}
              onClick={() => save({ provider: p.id })}
              disabled={saving}
              className={`px-4 py-2 rounded border ${
                s.provider === p.id
                  ? "bg-m3-accent border-m3-accent text-white"
                  : "border-m3-border text-m3-muted hover:text-m3-text"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </section>

      <UseInstalledAgent
        agents={agents}
        active={s.provider === "local_agent" ? s.local_agent_command : null}
        saving={saving}
        onPick={pickAgent}
        customCommand={customCommand}
        customArgs={customArgs}
        onCustomCommandChange={setCustomCommand}
        onCustomArgsChange={setCustomArgs}
        onPickCustom={pickCustom}
      />

      <section className="space-y-2">
        <h2 className="text-sm font-semibold">Local agent</h2>
        <p className="text-xs text-m3-muted">
          Wraps any installed AI CLI. Picking one above writes these fields;
          edit by hand to use a custom binary.
        </p>
        <label className="block text-xs text-m3-muted">Command</label>
        <input
          defaultValue={s.local_agent_command}
          onBlur={(e) => save({ local_agent_command: e.target.value })}
          placeholder="claude"
          className="w-full bg-m3-surface border border-m3-border rounded px-3 py-1.5 text-sm"
        />
        <label className="block text-xs text-m3-muted mt-3">
          Args (space-separated, prepended before the prompt)
        </label>
        <input
          defaultValue={s.local_agent_args.join(" ")}
          onBlur={(e) =>
            save({
              local_agent_args: e.target.value
                .split(/\s+/)
                .map((p) => p.trim())
                .filter(Boolean),
            })
          }
          placeholder="-p"
          className="w-full bg-m3-surface border border-m3-border rounded px-3 py-1.5 text-sm"
        />
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

function UseInstalledAgent({
  agents,
  active,
  saving,
  onPick,
  customCommand,
  customArgs,
  onCustomCommandChange,
  onCustomArgsChange,
  onPickCustom,
}: {
  agents: LocalAgentInfo[];
  active: string | null;
  saving: boolean;
  onPick: (agent: LocalAgentInfo) => void;
  customCommand: string;
  customArgs: string;
  onCustomCommandChange: (v: string) => void;
  onCustomArgsChange: (v: string) => void;
  onPickCustom: () => void;
}) {
  // Sort detected agents to the top so users see what they can use
  // immediately. Unavailable rows still render with an install hint so
  // users know what M3 supports.
  const sorted = useMemo(
    () => [...agents].sort((a, b) => Number(b.available) - Number(a.available)),
    [agents],
  );

  if (agents.length === 0) return null;

  return (
    <section className="space-y-2">
      <h2 className="text-sm font-semibold">Use my installed AI agent</h2>
      <p className="text-xs text-m3-muted">
        M3 can drive any AI CLI you already have logged in. No M3-managed key —
        it reuses your existing CLI subscription.
      </p>
      <div className="space-y-2">
        {sorted.map((a) => (
          <div
            key={a.id}
            className={`flex items-center justify-between gap-3 border rounded px-3 py-2 ${
              a.available ? "border-m3-border" : "border-m3-border/40 opacity-60"
            }`}
          >
            <div className="min-w-0">
              <div className="text-sm font-medium">{a.label}</div>
              <div className="text-xs text-m3-muted truncate">
                {a.available
                  ? `${a.path}${a.default_args.length ? "  " + a.default_args.join(" ") : ""}`
                  : `\`${a.command}\` not on PATH — install it to enable.`}
              </div>
            </div>
            <button
              disabled={!a.available || saving}
              onClick={() => onPick(a)}
              className={`px-3 py-1.5 text-sm rounded border ${
                active === a.command
                  ? "bg-m3-accent border-m3-accent text-white"
                  : "bg-m3-bg border-m3-border hover:border-m3-muted"
              } disabled:opacity-40 disabled:cursor-not-allowed`}
            >
              {active === a.command ? "in use" : "Use this"}
            </button>
          </div>
        ))}

        <div className="border border-dashed border-m3-border/60 rounded px-3 py-2 space-y-2">
          <div className="text-xs text-m3-muted">
            Custom command — wrap any AI CLI we don't list above.
          </div>
          <div className="flex gap-2">
            <input
              value={customCommand}
              onChange={(e) => onCustomCommandChange(e.target.value)}
              placeholder="binary name (e.g. my-agent)"
              className="flex-1 bg-m3-surface border border-m3-border rounded px-3 py-1.5 text-sm"
            />
            <input
              value={customArgs}
              onChange={(e) => onCustomArgsChange(e.target.value)}
              placeholder="args (space-separated)"
              className="flex-1 bg-m3-surface border border-m3-border rounded px-3 py-1.5 text-sm"
            />
            <button
              onClick={onPickCustom}
              disabled={saving || !customCommand.trim()}
              className="px-3 py-1.5 text-sm rounded border border-m3-border bg-m3-bg hover:border-m3-muted disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Use this
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
