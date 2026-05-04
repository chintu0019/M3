import { useCallback, useEffect, useState } from "react";
import { Navigate, Route, Routes, NavLink } from "react-router-dom";
import { api } from "./api/client";
import Library from "./views/Library";
import LibraryDetail from "./views/LibraryDetail";
import Settings from "./views/Settings";
import Workspace from "./views/Workspace";

function Nav({ activeModel }: { activeModel: string | null }) {
  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `px-4 py-2 rounded-lg text-sm transition-colors ${
      isActive
        ? "bg-m3-accent text-white"
        : "text-m3-muted hover:text-m3-text hover:bg-m3-surface"
    }`;

  return (
    <nav className="flex items-center gap-2 px-4 py-3 border-b border-m3-border bg-m3-bg">
      <span className="font-bold text-lg mr-4">M3</span>
      <NavLink to="/documents" className={linkClass}>
        Documents
      </NavLink>
      <NavLink to="/workspace" className={linkClass}>
        Workspace
      </NavLink>
      <div className="flex-1" />
      {activeModel && (
        <span className="hidden sm:inline text-xs text-m3-muted px-2">{activeModel}</span>
      )}
      <NavLink
        to="/settings"
        title="Settings"
        className={({ isActive }) =>
          `w-9 h-9 flex items-center justify-center rounded-lg transition-colors ${
            isActive ? "bg-m3-accent text-white" : "text-m3-muted hover:text-m3-text hover:bg-m3-surface"
          }`
        }
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      </NavLink>
    </nav>
  );
}

export default function App() {
  const [activeModel, setActiveModel] = useState<string | null>(null);

  const loadActiveModel = useCallback(async () => {
    try {
      const res = await api.settings.getLLM();
      const active = res.providers.find((p) => p.active);
      if (active) setActiveModel(active.model);
    } catch {
      // not connected
    }
  }, []);

  useEffect(() => {
    loadActiveModel();
    const interval = setInterval(loadActiveModel, 10000);
    return () => clearInterval(interval);
  }, [loadActiveModel]);

  return (
    <div className="h-screen overflow-hidden bg-m3-bg text-m3-text flex flex-col">
      <Nav activeModel={activeModel} />
      <main className="flex-1 min-h-0">
        <Routes>
          <Route path="/" element={<Navigate to="/documents" replace />} />
          <Route path="/documents" element={<Library />} />
          <Route path="/documents/:id" element={<LibraryDetail />} />
          <Route path="/workspace" element={<Workspace />} />
          <Route path="/settings" element={<Settings />} />
          {/* Legacy redirects so deep links keep working. */}
          <Route path="/library" element={<Navigate to="/documents" replace />} />
          <Route path="/library/:id" element={<LegacyLibraryRedirect />} />
          <Route path="/canvas" element={<Navigate to="/workspace" replace />} />
          <Route path="/entities/*" element={<Navigate to="/workspace" replace />} />
          <Route path="/insights" element={<Navigate to="/workspace" replace />} />
        </Routes>
      </main>
    </div>
  );
}

function LegacyLibraryRedirect() {
  const path = window.location.pathname.replace(/^\/library/, "/documents");
  return <Navigate to={path} replace />;
}
