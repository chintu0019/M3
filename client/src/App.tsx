import { useState } from "react";
import { NavLink, Route, Routes, Navigate } from "react-router-dom";

import Search from "./views/Search";
import Self from "./views/Self";
import Entities from "./views/Entities";
import EntityDetail from "./views/EntityDetail";
import Questions from "./views/Questions";
import Chat from "./views/Chat";
import Settings from "./views/Settings";
import IngestDrawer from "./components/IngestDrawer";

const tabs = [
  { to: "/search", label: "Search" },
  { to: "/chat", label: "Chat" },
  { to: "/self", label: "Self" },
  { to: "/entities", label: "Entities" },
  { to: "/questions", label: "Open questions" },
  { to: "/settings", label: "Settings" },
];

export default function App() {
  const [ingestOpen, setIngestOpen] = useState(false);

  return (
    <div className="h-screen flex flex-col bg-m3-bg text-m3-text">
      <nav className="flex items-center gap-2 px-6 py-3 border-b border-m3-border">
        <span className="font-bold text-lg mr-6">M3</span>
        {tabs.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            className={({ isActive }) =>
              `px-3 py-1.5 rounded-md text-sm ${
                isActive ? "bg-m3-accent text-white" : "text-m3-muted hover:text-m3-text hover:bg-m3-surface"
              }`
            }
          >
            {t.label}
          </NavLink>
        ))}
        <div className="flex-1" />
        <button
          onClick={() => setIngestOpen(true)}
          className="px-3 py-1.5 rounded-md text-sm bg-m3-surface hover:bg-m3-border"
        >
          + Ingest
        </button>
      </nav>

      <main className="flex-1 min-h-0 overflow-auto">
        <Routes>
          <Route path="/" element={<Navigate to="/search" replace />} />
          <Route path="/search" element={<Search />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/self" element={<Self />} />
          <Route path="/entities" element={<Entities />} />
          <Route path="/entities/:slug" element={<EntityDetail />} />
          <Route path="/questions" element={<Questions />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/search" replace />} />
        </Routes>
      </main>

      <IngestDrawer open={ingestOpen} onClose={() => setIngestOpen(false)} />
    </div>
  );
}
