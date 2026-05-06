// Drive-like Files browser, surfaced from the canvas toolbar's folder icon.
//
// Two-pane layout: list on the left (with drag-drop upload), detail on the right
// (preview, extracted text, provenance, scoped chat). Mirrors the SettingsModal
// pattern — backdrop click + Esc closes, content owns its own scroll.

import { useCallback, useEffect, useState } from "react";
import type { ItemListEntry, IngestResponse } from "../../../api/client";
import { FileDetail } from "./FileDetail";
import { FilesList } from "./FilesList";
import { UploadDropzone } from "./UploadDropzone";

export interface FilesModalProps {
  open: boolean;
  onClose: () => void;
  /** Called whenever an upload completes; the canvas uses it to pulse touched nodes. */
  onIngest?: (resp: IngestResponse) => void;
  /** Called when the user clicks an entity chip in the provenance tab. The canvas
   *  closes the modal and pulses the matching node. */
  onFocusEntity?: (slug: string) => void;
}

export function FilesModal({ open, onClose, onIngest, onFocusEntity }: FilesModalProps) {
  const [selected, setSelected] = useState<ItemListEntry | null>(null);
  const [refreshTok, setRefreshTok] = useState(0);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // When the modal closes, drop selection so reopening starts fresh.
  useEffect(() => {
    if (!open) setSelected(null);
  }, [open]);

  const refresh = useCallback(() => setRefreshTok(v => v + 1), []);

  const handleIngest = useCallback(
    (resp: IngestResponse) => {
      onIngest?.(resp);
      refresh();
    },
    [onIngest, refresh],
  );

  const handleFocusEntity = useCallback(
    (slug: string) => {
      onFocusEntity?.(slug);
      onClose();
    },
    [onFocusEntity, onClose],
  );

  if (!open) return null;

  return (
    <div className="m3-modal-backdrop" onClick={onClose}>
      <div
        className="m3-modal m3-files-modal"
        onClick={e => e.stopPropagation()}
      >
        <button className="m3-modal__close" onClick={onClose} aria-label="Close">
          <svg width="14" height="14" viewBox="0 0 16 16">
            <path
              d="M3 3l10 10M13 3L3 13"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
        </button>
        <div className="m3-modal__body m3-files">
          <div className="m3-files__list-pane">
            <UploadDropzone onIngest={handleIngest} />
            <FilesList
              refreshToken={refreshTok}
              selectedId={selected?.id ?? null}
              onSelect={setSelected}
              onArchiveChanged={refresh}
            />
          </div>
          <div className="m3-files__detail-pane">
            {selected ? (
              <FileDetail
                key={selected.id}
                entry={selected}
                onFocusEntity={handleFocusEntity}
                onMutate={refresh}
                onClose={() => setSelected(null)}
              />
            ) : (
              <div className="m3-files__empty">
                <div className="m3-files__empty-title">No file selected</div>
                <div className="m3-files__empty-hint">
                  Drop files on the left, then click one to preview, see what it
                  contributed to your brain, or chat about its contents.
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
