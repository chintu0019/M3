// Single-pane M3. The Canvas owns everything: graph, chat, settings.
// All previous tabs have been removed — this view is the app.

import { useEffect, useState } from "react";
import UpdateBanner from "./components/UpdateBanner";
import Canvas from "./views/Canvas";
import { api } from "./api/client";

type Toast = { id: string; text: string; kind: "info" | "ok" | "err" };

export default function App() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  // Tauri's WebView-level drop interception is off (tauri.conf.json
  // dragDropEnabled=false) so HTML5 drop reaches React. Without a global
  // preventDefault, files dropped outside an explicit dropzone make the
  // WebView navigate to display the file (e.g. a PDF takes over the window
  // with no way back). Swallow drops everywhere and route them to ingest.
  // Drops inside [data-m3-dropzone] are left alone so that component handles
  // them without double-ingesting.
  useEffect(() => {
    const insideDropzone = (target: EventTarget | null) =>
      target instanceof Element && !!target.closest("[data-m3-dropzone]");

    const onDragOver = (e: DragEvent) => {
      if (e.dataTransfer?.types.includes("Files")) e.preventDefault();
    };

    const onDrop = (e: DragEvent) => {
      if (!e.dataTransfer?.types.includes("Files")) return;
      e.preventDefault();
      if (insideDropzone(e.target)) return;
      const files = Array.from(e.dataTransfer.files);
      if (files.length) void ingestDropped(files, setToasts);
    };

    window.addEventListener("dragover", onDragOver);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("drop", onDrop);
    };
  }, []);

  return (
    <div className="m3-root">
      <UpdateBanner />
      <Canvas />
      {toasts.length > 0 && (
        <div className="m3-toasts">
          {toasts.map(t => (
            <div key={t.id} className={`m3-toast m3-toast--${t.kind}`}>{t.text}</div>
          ))}
        </div>
      )}
    </div>
  );
}

async function ingestDropped(
  files: File[],
  setToasts: React.Dispatch<React.SetStateAction<Toast[]>>,
) {
  const push = (t: Toast, ttlMs = 4000) => {
    setToasts(xs => [...xs, t]);
    window.setTimeout(() => setToasts(xs => xs.filter(x => x.id !== t.id)), ttlMs);
  };
  for (const file of files) {
    const id = crypto.randomUUID();
    push({ id, text: `Ingesting ${file.name}…`, kind: "info" }, 60_000);
    try {
      const resp = await api.ingestFile(file, "drag_drop");
      setToasts(xs => xs.filter(x => x.id !== id));
      push({
        id: crypto.randomUUID(),
        text: `Ingested ${file.name} → ${resp.entities_touched.length} entities`,
        kind: "ok",
      });
    } catch (e) {
      setToasts(xs => xs.filter(x => x.id !== id));
      push({
        id: crypto.randomUUID(),
        text: `Failed to ingest ${file.name}: ${e instanceof Error ? e.message : String(e)}`,
        kind: "err",
      }, 8000);
    }
  }
}
