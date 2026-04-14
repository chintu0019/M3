import { useCallback, useEffect, useState } from "react";
import { Routes, Route, NavLink } from "react-router-dom";
import { api } from "./api/client";
import Inbox from "./views/Inbox";
import Wiki from "./views/Wiki";
import Chat from "./views/Chat";
import Settings from "./views/Settings";

function Nav({ activeModel }: { activeModel: string | null }) {
  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `px-4 py-2 rounded-lg transition-colors ${
      isActive
        ? "bg-m3-accent text-white"
        : "text-m3-muted hover:text-m3-text hover:bg-m3-surface"
    }`;

  return (
    <nav className="flex items-center gap-2 px-6 py-3 border-b border-m3-border bg-m3-bg">
      <span className="font-bold text-lg mr-6">M3</span>
      <NavLink to="/" className={linkClass} end>
        Inbox
      </NavLink>
      <NavLink to="/wiki" className={linkClass}>
        Wiki
      </NavLink>
      <NavLink to="/chat" className={linkClass}>
        Chat
      </NavLink>
      <div className="flex-1" />
      {activeModel && (
        <NavLink
          to="/settings"
          className="text-xs text-m3-muted hover:text-m3-text px-3 py-1 rounded-lg hover:bg-m3-surface transition-colors"
        >
          {activeModel}
        </NavLink>
      )}
      <NavLink to="/settings" className={linkClass}>
        Settings
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
    // Re-check periodically in case user switches from Settings page
    const interval = setInterval(loadActiveModel, 10000);
    return () => clearInterval(interval);
  }, [loadActiveModel]);

  return (
    <div className="min-h-screen bg-m3-bg text-m3-text flex flex-col">
      <Nav activeModel={activeModel} />
      <main className="flex-1">
        <Routes>
          <Route path="/" element={<Inbox />} />
          <Route path="/wiki" element={<Wiki />} />
          <Route path="/wiki/:pageId" element={<Wiki />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}
