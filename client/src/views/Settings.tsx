// Settings — lives inside the canvas's settings modal.
//
// Layout: agent picker is the primary surface (most users plug in a CLI
// they already have logged in). API providers — Anthropic, Ollama — sit
// below as a secondary fallback. The "Local agent" raw command/args fields
// are gone from the visible UI: they were a leaky abstraction (the picker
// already writes them), and showing them encouraged unnecessary edits.
// Power users can still set the env vars directly.

import { useEffect, useMemo, useState } from "react";
import { api, LLMSettings, LocalAgentInfo } from "../api/client";

type Provider = "ollama" | "anthropic" | "local_agent";

export default function Settings() {
  const [s, setS] = useState<LLMSettings | null>(null);
  const [agents, setAgents] = useState<LocalAgentInfo[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [customCommand, setCustomCommand] = useState("");
  const [customArgs, setCustomArgs] = useState("-p");

  useEffect(() => {
    api.settings().then(setS).catch(e => setError(String(e)));
    api.listAgents().then(setAgents).catch(() => {
      // Detection failure is non-fatal — provider buttons still work.
    });
  }, []);

  // ALL hooks must be called before any conditional return — otherwise the
  // hook count differs between the loading render and the loaded render and
  // React throws #310 ("Rendered more hooks than during the previous render").
  const sortedAgents = useMemo(
    () => [...agents].sort((a, b) => Number(b.available) - Number(a.available)),
    [agents],
  );

  if (error && !s) {
    return (
      <div className="m3-settings">
        <div className="m3-settings__banner m3-settings__banner--warn">{error}</div>
      </div>
    );
  }
  if (!s) {
    return <div className="m3-settings"><div className="m3-settings__hint">loading…</div></div>;
  }

  async function save(update: Parameters<typeof api.updateSettings>[0]) {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const next = await api.updateSettings(update);
      setS(next);
      setApiKey("");
      setMessage("saved");
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
    const args = customArgs.split(/\s+/).map(p => p.trim()).filter(Boolean);
    void save({
      provider: "local_agent",
      local_agent_command: cmd,
      local_agent_args: args,
    });
  }

  const isAgentActive = (cmd: string) =>
    s.provider === "local_agent" && s.local_agent_command === cmd;

  return (
    <div className="m3-settings">
      <h1 className="m3-settings__title">Settings</h1>

      {!s.configured && (
        <div className="m3-settings__banner m3-settings__banner--warn">
          <div className="m3-settings__banner-title">Pick an AI agent to get started</div>
          <div>
            M3 is running but no LLM is wired up
            {s.unconfigured_reason ? ` (${s.unconfigured_reason})` : ""}.
            Pick an installed agent below or paste an Anthropic API key. Chat is disabled until you do.
          </div>
        </div>
      )}

      {s.env_overrides.length > 0 && (
        <div className="m3-settings__banner m3-settings__banner--info">
          <div className="m3-settings__banner-title">Env overrides active</div>
          <div>
            These take precedence over anything you set here:{" "}
            <code>{s.env_overrides.join(", ")}</code>. Unset them in your shell or launchd for these settings to apply.
          </div>
        </div>
      )}

      {/* PRIMARY: agent picker */}
      <section className="m3-settings__section">
        <header className="m3-settings__head">
          <h2>AI agent</h2>
          {s.provider === "local_agent" && s.local_agent_command && (
            <span className="m3-settings__head-tag">Active · {s.local_agent_command}</span>
          )}
        </header>
        <p className="m3-settings__hint">
          M3 drives any AI CLI you already have logged in. Reuses your existing CLI
          subscription — no M3-managed API key required.
        </p>

        <div className="m3-agent-list">
          {sortedAgents.map(a => (
            <div
              key={a.id}
              className="m3-agent-row"
              data-unavailable={!a.available}
              data-active={isAgentActive(a.command)}
            >
              <div className="m3-agent-row__main">
                <div className="m3-agent-row__label">{a.label}</div>
                <div className="m3-agent-row__path">
                  {a.available
                    ? `${a.path}${a.default_args.length ? "  " + a.default_args.join(" ") : ""}`
                    : `\`${a.command}\` not on PATH — install it to enable.`}
                </div>
              </div>
              <button
                disabled={!a.available || saving}
                onClick={() => pickAgent(a)}
                className={`m3-btn m3-btn--small ${isAgentActive(a.command) ? "m3-btn--accent" : ""}`}
              >
                {isAgentActive(a.command) ? "In use" : "Use this"}
              </button>
            </div>
          ))}
          {sortedAgents.length === 0 && (
            <div className="m3-settings__hint">
              Detection unavailable. Use the custom command form below or pick an API provider.
            </div>
          )}

          <div className="m3-agent-custom">
            <div className="m3-settings__hint">Custom command — wrap any AI CLI we don't list above.</div>
            <div className="m3-agent-custom__row">
              <input
                className="m3-input m3-input--mono"
                value={customCommand}
                onChange={e => setCustomCommand(e.target.value)}
                placeholder="binary name (e.g. my-agent)"
              />
              <input
                className="m3-input m3-input--mono"
                value={customArgs}
                onChange={e => setCustomArgs(e.target.value)}
                placeholder="args (space-separated)"
              />
              <button
                onClick={pickCustom}
                disabled={saving || !customCommand.trim()}
                className="m3-btn m3-btn--small"
              >
                Use this
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* SECONDARY: API providers */}
      <section className="m3-settings__section">
        <header className="m3-settings__head">
          <h2>Anthropic API</h2>
          {s.provider === "anthropic" && (
            <span className="m3-settings__head-tag">Active · {s.anthropic_model}</span>
          )}
        </header>
        <p className="m3-settings__hint">
          Direct API access. Best response quality + native tool use, but requires Anthropic billing.
        </p>
        <div className="m3-field">
          <label className="m3-field__label">Model</label>
          <input
            className="m3-input m3-input--mono"
            defaultValue={s.anthropic_model}
            onBlur={e => save({ anthropic_model: e.target.value })}
          />
        </div>
        <div className="m3-field">
          <label className="m3-field__label">
            API key
            {s.anthropic_api_key_present && <span className="m3-field__label-tag">· set</span>}
          </label>
          <div className="m3-row">
            <input
              type="password"
              className="m3-input m3-input--mono"
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              placeholder="sk-ant-…"
            />
            <button
              className="m3-btn m3-btn--small m3-btn--primary"
              onClick={() => save({ anthropic_api_key: apiKey, provider: "anthropic" as Provider })}
              disabled={saving || !apiKey}
            >
              Save & switch
            </button>
            {s.anthropic_api_key_present && (
              <button
                className="m3-btn m3-btn--small m3-btn--ghost"
                onClick={() => save({ clear_anthropic_api_key: true })}
                disabled={saving}
              >
                Clear
              </button>
            )}
          </div>
        </div>
      </section>

      <section className="m3-settings__section">
        <header className="m3-settings__head">
          <h2>Ollama</h2>
          {s.provider === "ollama" && (
            <span className="m3-settings__head-tag">Active · {s.ollama_model}</span>
          )}
        </header>
        <p className="m3-settings__hint">
          Local instance. Fully offline; quality depends on the model you pull.
        </p>
        <div className="m3-field">
          <label className="m3-field__label">Host</label>
          <input
            className="m3-input m3-input--mono"
            defaultValue={s.ollama_host}
            onBlur={e => save({ ollama_host: e.target.value })}
          />
        </div>
        <div className="m3-field">
          <label className="m3-field__label">Model</label>
          <input
            className="m3-input m3-input--mono"
            defaultValue={s.ollama_model}
            onBlur={e => save({ ollama_model: e.target.value })}
          />
        </div>
        <div>
          <button
            className="m3-btn m3-btn--small"
            onClick={() => save({ provider: "ollama" as Provider })}
            disabled={saving || s.provider === "ollama"}
          >
            {s.provider === "ollama" ? "In use" : "Use Ollama"}
          </button>
        </div>
      </section>

      <div
        className={
          "m3-settings__status " +
          (saving
            ? "m3-settings__status--saving"
            : error
            ? "m3-settings__status--error"
            : message
            ? "m3-settings__status--ok"
            : "")
        }
      >
        {saving ? "saving…" : error ? error : message || ""}
      </div>
    </div>
  );
}
