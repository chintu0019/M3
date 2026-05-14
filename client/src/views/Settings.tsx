// Settings — lives inside the canvas's settings modal.
//
// Layout: agent picker is the primary surface (most users plug in a CLI
// they already have logged in). API providers — Anthropic, Ollama — sit
// below as a secondary fallback. The "Local agent" raw command/args fields
// are gone from the visible UI: they were a leaky abstraction (the picker
// already writes them), and showing them encouraged unnecessary edits.
// Power users can still set the env vars directly.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  LLMSettings,
  LocalAgentInfo,
  TelegramPairStart,
  TelegramStatus,
} from "../api/client";
import { useAutoUpdater } from "../hooks/useAutoUpdater";

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
  // App version (read once via Tauri's getVersion). Falls back to "?" outside
  // Tauri (e.g. `vite dev` in a plain browser).
  const [appVersion, setAppVersion] = useState<string>("?");
  const updater = useAutoUpdater();

  useEffect(() => {
    api.settings().then(setS).catch(e => setError(String(e)));
    api.listAgents().then(setAgents).catch(() => {
      // Detection failure is non-fatal — provider buttons still work.
    });
    // Lazy-import keeps the Tauri API out of the dev bundle when running
    // outside the desktop shell.
    import("@tauri-apps/api/app")
      .then(({ getVersion }) => getVersion())
      .then(setAppVersion)
      .catch(() => {
        // Outside Tauri or plugin unavailable — leave the placeholder.
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

      <TelegramSection />

      <section className="m3-settings__section">
        <header className="m3-settings__head">
          <h2>Canvas</h2>
          <span className="m3-settings__head-tag">{s.canvas_v2_enabled ? "v2 preview" : "v1"}</span>
        </header>
        <p className="m3-settings__hint">
          Canvas v2 replaces the radial-by-type layout with a topical force
          layout and concentric recency rings. Reload the canvas after
          toggling to see the change.
        </p>
        <label className="m3-settings__toggle-row">
          <input
            type="checkbox"
            checked={s.canvas_v2_enabled}
            onChange={e => save({ canvas_v2_enabled: e.target.checked })}
            disabled={saving}
          />
          <span>Canvas v2 (preview)</span>
        </label>
      </section>

      <section className="m3-settings__section">
        <header className="m3-settings__head">
          <h2>About</h2>
          <span className="m3-settings__head-tag">M3 v{appVersion}</span>
        </header>
        <p className="m3-settings__hint">
          Updates land automatically — M3 checks GitHub on launch, on window
          focus, and every few hours. The "Restart now" banner shows up at
          the top of the window when a new version is downloaded.
        </p>
        <div>
          <button
            className="m3-btn m3-btn--small"
            onClick={() => {
              void updater.checkNow();
            }}
            disabled={
              updater.stage.kind === "checking" ||
              updater.stage.kind === "downloading" ||
              updater.stage.kind === "ready"
            }
          >
            {updater.stage.kind === "checking" ? "Checking…" : "Check for updates"}
          </button>
        </div>
        <div className="m3-settings__hint" style={{ marginTop: 8 }}>
          {updaterStatusLine(updater.stage)}
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

// --- Telegram capture ---
//
// Three states for the card:
//   - not configured           : "Connect Telegram" CTA → opens the modal
//   - configured but not running: shows last_error, retry + disconnect
//   - running                  : shows @bot username + linked chats + Pair device / Disconnect
//
// The modal handles two sub-flows:
//   1. token entry (paste from BotFather)
//   2. QR pairing (server returns a data-URL PNG/SVG and a deeplink; we poll
//      every 2s until linked)
function TelegramSection() {
  const [s, setS] = useState<TelegramStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [modal, setModal] = useState<"closed" | "token" | "pair">("closed");

  const refresh = useCallback(async () => {
    try {
      setS(await api.telegramStatus());
    } catch (e) {
      setLoadError(String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function disconnect() {
    if (!confirm("Disconnect Telegram? The bot will stop receiving messages and the linked chat list will be cleared.")) return;
    setS(await api.telegramDisconnect());
  }

  return (
    <section className="m3-settings__section">
      <header className="m3-settings__head">
        <h2>Telegram capture</h2>
        {s?.running && (
          <span className="m3-settings__head-tag">Online · @{s.bot_username}</span>
        )}
        {s && s.configured && !s.running && (
          <span className="m3-settings__head-tag" style={{ color: "var(--m3-warn, #c0392b)" }}>Offline</span>
        )}
      </header>
      <p className="m3-settings__hint">
        Send anything to your personal Telegram bot — text, photos, voice notes, files —
        and M3 ingests it into your brain. One-time setup; the bot runs inside M3.
      </p>

      {loadError && (
        <div className="m3-settings__banner m3-settings__banner--warn">{loadError}</div>
      )}

      {!s?.configured && (
        <div>
          <button
            className="m3-btn m3-btn--small m3-btn--primary"
            onClick={() => setModal("token")}
          >
            Connect Telegram
          </button>
        </div>
      )}

      {s?.configured && (
        <div className="m3-field">
          <div className="m3-settings__hint">
            {s.running
              ? `Linked chats: ${s.allowed_chats.length === 0 ? "none yet — pair a device to start receiving" : s.allowed_chats.length}`
              : `Bot is offline${s.last_error ? ` — ${s.last_error}` : ""}.`}
          </div>
          <div className="m3-row" style={{ marginTop: 8 }}>
            {s.running && (
              <button
                className="m3-btn m3-btn--small m3-btn--primary"
                onClick={() => setModal("pair")}
              >
                Pair a device
              </button>
            )}
            {!s.running && (
              <button
                className="m3-btn m3-btn--small"
                onClick={() => setModal("token")}
              >
                Re-enter token
              </button>
            )}
            <button
              className="m3-btn m3-btn--small m3-btn--ghost"
              onClick={disconnect}
            >
              Disconnect
            </button>
          </div>
        </div>
      )}

      {modal !== "closed" && (
        <TelegramConnectModal
          initialStep={modal}
          onClose={() => {
            setModal("closed");
            void refresh();
          }}
        />
      )}
    </section>
  );
}

// Modal walks the user through the two manual steps Telegram requires:
// pasting a BotFather token, then scanning a QR to link the chat.
// `initialStep="pair"` lets the parent reopen straight into the QR
// when the bot's already online (e.g. user is adding a second device).
function TelegramConnectModal({
  initialStep,
  onClose,
}: {
  initialStep: "token" | "pair";
  onClose: () => void;
}) {
  const [step, setStep] = useState<"token" | "pair">(initialStep);
  const [token, setToken] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pair, setPair] = useState<TelegramPairStart | null>(null);
  const [pairStatus, setPairStatus] = useState<"pending" | "linked" | "expired">("pending");
  const [linkedTitle, setLinkedTitle] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  async function submitToken() {
    setSubmitting(true);
    setError(null);
    try {
      await api.telegramConnect(token.trim());
      setStep("pair");
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  }

  // Lazily start a pairing code the first time we enter the pair step.
  // Re-running on retry: call api.telegramPairStart() again to get a
  // fresh code + QR.
  const startPair = useCallback(async () => {
    setError(null);
    setPairStatus("pending");
    try {
      const p = await api.telegramPairStart();
      setPair(p);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    if (step !== "pair" || pair !== null) return;
    void startPair();
  }, [step, pair, startPair]);

  // Poll the pair endpoint every 2s while the QR is up. Stops on linked
  // or expired so we don't keep hitting the server after the modal's
  // done its job.
  useEffect(() => {
    if (step !== "pair" || pair === null || pairStatus !== "pending") return;
    const tick = async () => {
      try {
        const r = await api.telegramPairPoll(pair.code);
        setPairStatus(r.status);
        if (r.status === "linked") {
          setLinkedTitle(r.chat_title);
        }
      } catch {
        // Silent — next tick will retry. Showing a transient network blip
        // mid-pairing is noisier than just retrying.
      }
    };
    pollRef.current = window.setInterval(tick, 2000);
    return () => {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [step, pair, pairStatus]);

  return (
    <div className="m3-modal-backdrop" onClick={onClose}>
      <div className="m3-modal" onClick={e => e.stopPropagation()}>
        <header className="m3-modal__head">
          <h3>Connect Telegram</h3>
          <button className="m3-btn m3-btn--ghost m3-btn--small" onClick={onClose}>Close</button>
        </header>

        {step === "token" && (
          <div className="m3-modal__body">
            <ol className="m3-settings__hint" style={{ paddingLeft: 18, marginTop: 0 }}>
              <li>Open Telegram and message <a href="https://t.me/BotFather" target="_blank" rel="noreferrer">@BotFather</a>.</li>
              <li>Send <code>/newbot</code>, pick any name + username.</li>
              <li>BotFather replies with a token like <code>123456:ABC-DEF…</code> — paste it below.</li>
            </ol>
            <div className="m3-field">
              <label className="m3-field__label">Bot token</label>
              <input
                type="password"
                className="m3-input m3-input--mono"
                value={token}
                onChange={e => setToken(e.target.value)}
                placeholder="123456:ABC-DEF…"
                autoFocus
              />
            </div>
            {error && <div className="m3-settings__banner m3-settings__banner--warn">{error}</div>}
            <div className="m3-row" style={{ justifyContent: "flex-end" }}>
              <button
                className="m3-btn m3-btn--primary"
                disabled={submitting || !token.trim()}
                onClick={submitToken}
              >
                {submitting ? "Connecting…" : "Save & continue"}
              </button>
            </div>
          </div>
        )}

        {step === "pair" && (
          <div className="m3-modal__body">
            {pairStatus === "linked" ? (
              <div>
                <div className="m3-settings__banner m3-settings__banner--ok" style={{ marginBottom: 12 }}>
                  ✓ Linked{linkedTitle ? ` with ${linkedTitle}` : ""}. Send the bot a message any time.
                </div>
                <div className="m3-row" style={{ justifyContent: "flex-end" }}>
                  <button className="m3-btn m3-btn--primary" onClick={onClose}>Done</button>
                </div>
              </div>
            ) : pairStatus === "expired" ? (
              <div>
                <div className="m3-settings__banner m3-settings__banner--warn" style={{ marginBottom: 12 }}>
                  This pairing link expired. Generate a new one.
                </div>
                <div className="m3-row" style={{ justifyContent: "flex-end" }}>
                  <button
                    className="m3-btn m3-btn--primary"
                    onClick={() => { setPair(null); }}
                  >
                    New code
                  </button>
                </div>
              </div>
            ) : (
              <>
                <p className="m3-settings__hint">
                  Open Telegram on your phone, tap the camera/scan icon, and scan this QR.
                  Telegram will open your bot and link this chat to M3 automatically.
                </p>
                <div
                  className="m3-telegram-qr"
                  style={{
                    display: "flex",
                    justifyContent: "center",
                    padding: 16,
                    background: "white",
                    borderRadius: 8,
                  }}
                >
                  {pair ? (
                    <img
                      src={pair.qr_data_url}
                      alt="Telegram pairing QR code"
                      style={{ width: 240, height: 240 }}
                    />
                  ) : (
                    <div style={{ width: 240, height: 240, display: "grid", placeItems: "center", color: "#666" }}>
                      Generating QR…
                    </div>
                  )}
                </div>
                {pair && (
                  <div className="m3-settings__hint" style={{ marginTop: 8, textAlign: "center" }}>
                    Or open this link on the phone:{" "}
                    <a href={pair.deeplink} target="_blank" rel="noreferrer">{pair.deeplink}</a>
                  </div>
                )}
                {error && <div className="m3-settings__banner m3-settings__banner--warn">{error}</div>}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// Human-readable status line for the updater section. Kept outside the
// component so it doesn't capture stale closures from re-renders.
function updaterStatusLine(stage: ReturnType<typeof useAutoUpdater>["stage"]): string {
  switch (stage.kind) {
    case "idle":
      return "Not checked yet.";
    case "checking":
      return "Checking GitHub for a new release…";
    case "uptodate": {
      const ago = formatRelativeTime(Date.now() - stage.checkedAt);
      return `You're on the latest release. (Last checked ${ago}.)`;
    }
    case "downloading":
      return `Downloading update — ${Math.round(stage.progress * 100)}%.`;
    case "ready":
      return `M3 ${stage.version} is ready — click "Restart now" in the banner.`;
    case "error":
      return `Couldn't check: ${stage.message}`;
  }
}

function formatRelativeTime(ms: number): string {
  const sec = Math.round(ms / 1000);
  if (sec < 60) return "just now";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} min ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} h ago`;
  const day = Math.round(hr / 24);
  return `${day} d ago`;
}
