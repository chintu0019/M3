// Drag-and-drop upload zone. Accepts any file; routes through api.ingestFile()
// which the backend already MIME-detects (text/pdf/image/audio/video/other).
//
// Per-upload progress: each file gets its own row in a transient list with
// pending → ingesting → done | error states. Done rows show the entity-touch
// badge built from IngestResponse so the user immediately sees how the file
// connected to their brain.

import { useCallback, useRef, useState } from "react";
import { api, type IngestResponse } from "../../../api/client";

interface PendingUpload {
  id: string;
  filename: string;
  status: "uploading" | "done" | "error";
  result?: IngestResponse;
  error?: string;
}

export interface UploadDropzoneProps {
  onIngest: (resp: IngestResponse) => void;
}

export function UploadDropzone({ onIngest }: UploadDropzoneProps) {
  const [hover, setHover] = useState(false);
  const [pending, setPending] = useState<PendingUpload[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const upload = useCallback(
    async (files: File[]) => {
      for (const file of files) {
        const id = crypto.randomUUID();
        setPending(p => [...p, { id, filename: file.name, status: "uploading" }]);
        try {
          const resp = await api.ingestFile(file, "drag_drop");
          setPending(p =>
            p.map(x => (x.id === id ? { ...x, status: "done", result: resp } : x)),
          );
          onIngest(resp);
          // Auto-clear successful uploads after a few seconds so the dropzone
          // doesn't grow forever.
          window.setTimeout(() => {
            setPending(p => p.filter(x => x.id !== id));
          }, 6000);
        } catch (e) {
          setPending(p =>
            p.map(x =>
              x.id === id
                ? { ...x, status: "error", error: e instanceof Error ? e.message : String(e) }
                : x,
            ),
          );
        }
      }
    },
    [onIngest],
  );

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setHover(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length) upload(files);
  }

  function onPicker(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files || []);
    if (files.length) upload(files);
    e.target.value = "";
  }

  return (
    <div
      className={`m3-files__dropzone${hover ? " m3-files__dropzone--hover" : ""}`}
      onDragOver={e => {
        e.preventDefault();
        setHover(true);
      }}
      onDragLeave={() => setHover(false)}
      onDrop={onDrop}
    >
      <div className="m3-files__dz-label">
        Drop files here, or{" "}
        <button
          type="button"
          className="m3-files__dz-link"
          onClick={() => inputRef.current?.click()}
        >
          browse
        </button>
      </div>
      <input
        ref={inputRef}
        type="file"
        multiple
        style={{ display: "none" }}
        onChange={onPicker}
      />
      {pending.length > 0 && (
        <ul className="m3-files__dz-list">
          {pending.map(p => (
            <li key={p.id} className={`m3-files__dz-row m3-files__dz-row--${p.status}`}>
              <span className="m3-files__dz-name">{p.filename}</span>
              {p.status === "uploading" && (
                <span className="m3-files__dz-status">ingesting…</span>
              )}
              {p.status === "done" && p.result && (
                <span className="m3-files__dz-status">
                  ✓ {p.result.entities_touched.length} entities
                  {p.result.questions_raised > 0
                    ? `, ${p.result.questions_raised} questions`
                    : ""}
                </span>
              )}
              {p.status === "error" && (
                <span className="m3-files__dz-status m3-files__dz-status--err">
                  failed: {p.error}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
