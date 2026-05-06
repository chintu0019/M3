// Right pane of the Files modal. Tabs:
//   Preview         — image/PDF/audio inline, or a fallback link.
//   Extracted text  — what the LLM saw at ingest time.
//   Provenance      — entities + facts + open questions this file produced.
//   Chat            — scoped chat (pin + filter) over this single file.
//
// Header has a small action row: Archive / Unarchive, Re-extract.

import { useEffect, useState } from "react";
import { api, type ItemListEntry, type ProvenanceResponse } from "../../../api/client";
import { FileChat } from "./FileChat";

type Tab = "preview" | "text" | "provenance" | "chat";

export interface FileDetailProps {
  entry: ItemListEntry;
  onFocusEntity: (slug: string) => void;
  onMutate: () => void;
  onClose: () => void;
}

export function FileDetail({ entry, onFocusEntity, onMutate, onClose }: FileDetailProps) {
  const [tab, setTab] = useState<Tab>(entry.has_original ? "preview" : "text");
  const [text, setText] = useState<{ extracted_text: string; truncated: boolean } | null>(null);
  const [provenance, setProvenance] = useState<ProvenanceResponse | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reingestWarned, setReingestWarned] = useState(false);

  // Lazy-load text + provenance on first tab switch into them. Both are cheap
  // but no point fetching what the user never opens.
  useEffect(() => {
    if (tab === "text" && !text) {
      api.itemText(entry.id).then(setText).catch(e => setError(String(e)));
    }
    if (tab === "provenance" && !provenance) {
      api.itemProvenance(entry.id).then(setProvenance).catch(e => setError(String(e)));
    }
  }, [tab, entry.id, text, provenance]);

  async function archive() {
    setBusy("archive");
    try {
      await api.archiveItem(entry.id, !entry.archived);
      onMutate();
      onClose();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function reingest() {
    if (!reingestWarned) {
      const ok = window.confirm(
        "Re-extraction may duplicate facts the LLM already merged. Proceed?",
      );
      if (!ok) return;
      setReingestWarned(true);
    }
    setBusy("reingest");
    try {
      await api.reingestItem(entry.id);
      // Refresh derived data so the user sees the new provenance immediately.
      const [t, p] = await Promise.all([
        api.itemText(entry.id),
        api.itemProvenance(entry.id),
      ]);
      setText(t);
      setProvenance(p);
      onMutate();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="m3-files__detail">
      <header className="m3-files__detail-head">
        <div className="m3-files__detail-title">
          {entry.original_filename || `(${entry.content_kind} item)`}
        </div>
        <div className="m3-files__detail-actions">
          <button
            className="m3-btn-ghost"
            onClick={archive}
            disabled={busy !== null}
          >
            {busy === "archive" ? "…" : entry.archived ? "Unarchive" : "Archive"}
          </button>
          <button
            className="m3-btn-ghost"
            onClick={reingest}
            disabled={busy !== null}
            title="Run the ingest LLM again on this file"
          >
            {busy === "reingest" ? "Re-extracting…" : "Re-extract"}
          </button>
          <a
            className="m3-btn-ghost"
            href={api.itemOriginalUrl(entry.id)}
            target="_blank"
            rel="noreferrer"
            style={{ display: entry.has_original ? "inline-flex" : "none" }}
          >
            Download
          </a>
        </div>
      </header>

      {error && <div className="m3-files__error">{error}</div>}

      <nav className="m3-files__tabs">
        {(["preview", "text", "provenance", "chat"] as const).map(t => (
          <button
            key={t}
            className={`m3-files__tab${tab === t ? " m3-files__tab--on" : ""}`}
            onClick={() => setTab(t)}
            disabled={t === "preview" && !entry.has_original}
          >
            {t === "preview"
              ? "Preview"
              : t === "text"
              ? "Extracted text"
              : t === "provenance"
              ? "Provenance"
              : "Chat"}
          </button>
        ))}
      </nav>

      <div className="m3-files__detail-body">
        {tab === "preview" && entry.has_original && <Preview entry={entry} />}
        {tab === "text" && (
          <pre className="m3-files__text">
            {text ? (
              <>
                {text.extracted_text || "(no extracted text)"}
                {text.truncated && (
                  <em className="m3-files__truncated"> [truncated]</em>
                )}
              </>
            ) : (
              "Loading…"
            )}
          </pre>
        )}
        {tab === "provenance" && (
          <Provenance prov={provenance} onFocusEntity={onFocusEntity} />
        )}
        {tab === "chat" && (
          <FileChat itemId={entry.id} filename={entry.original_filename} />
        )}
      </div>
    </div>
  );
}

function Preview({ entry }: { entry: ItemListEntry }) {
  const url = api.itemOriginalUrl(entry.id);
  if (entry.content_kind === "image") {
    return <img src={url} alt={entry.original_filename || ""} className="m3-files__img" />;
  }
  if (entry.content_kind === "pdf") {
    return <iframe src={url} title={entry.original_filename || "PDF"} className="m3-files__pdf" />;
  }
  if (entry.content_kind === "audio") {
    return <audio src={url} controls className="m3-files__audio" />;
  }
  if (entry.content_kind === "video") {
    return <video src={url} controls className="m3-files__video" />;
  }
  return (
    <div className="m3-files__nopreview">
      No inline preview for this file type.{" "}
      <a href={url} target="_blank" rel="noreferrer">
        Open
      </a>{" "}
      in a new tab.
    </div>
  );
}

function Provenance({
  prov, onFocusEntity,
}: {
  prov: ProvenanceResponse | null;
  onFocusEntity: (slug: string) => void;
}) {
  if (!prov) return <div>Loading…</div>;
  return (
    <div className="m3-files__prov">
      <section>
        <h4>Entities touched</h4>
        {prov.entities_touched.length === 0 ? (
          <p className="m3-files__muted">None — this file didn't update any entity pages.</p>
        ) : (
          <ul className="m3-files__entities">
            {prov.entities_touched.map(e => (
              <li key={e.slug}>
                <button className="m3-files__entity-chip" onClick={() => onFocusEntity(e.slug)}>
                  {e.canonical_name}
                  {e.entity_type ? <span className="m3-files__entity-type"> · {e.entity_type}</span> : null}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section>
        <h4>Facts contributed</h4>
        {prov.facts.length === 0 ? (
          <p className="m3-files__muted">No new facts were extracted.</p>
        ) : (
          <ul className="m3-files__facts">
            {prov.facts.map((f, i) => (
              <li key={i}>
                <span className="m3-files__fact-source">{f.source}</span>
                <span>{f.text}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      {prov.questions.length > 0 && (
        <section>
          <h4>Open questions raised</h4>
          <ul className="m3-files__questions">
            {prov.questions.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
