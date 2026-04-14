import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, type WikiPage, type WikiPageSummary, type SearchResult } from "../api/client";

export default function Wiki() {
  const { pageId } = useParams();
  const navigate = useNavigate();
  const [pages, setPages] = useState<WikiPageSummary[]>([]);
  const [activePage, setActivePage] = useState<WikiPage | null>(null);
  const [projects, setProjects] = useState<string[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null);
  const [selectedProject, setSelectedProject] = useState<string | null>(null);

  const loadPages = useCallback(async () => {
    try {
      const params: Record<string, string> = { per_page: "100" };
      if (selectedProject) params.category = selectedProject;
      const res = await api.wiki.pages(params);
      setPages(res.items);
    } catch {
      // not ready
    }
  }, [selectedProject]);

  const loadProjects = useCallback(async () => {
    try {
      setProjects(await api.wiki.projects());
    } catch {
      // not ready
    }
  }, []);

  useEffect(() => {
    loadPages();
    loadProjects();
  }, [loadPages, loadProjects]);

  useEffect(() => {
    if (pageId) {
      api.wiki.page(pageId).then(setActivePage).catch(() => setActivePage(null));
    } else {
      setActivePage(null);
    }
  }, [pageId]);

  const handleSearch = async () => {
    if (!searchQuery.trim()) {
      setSearchResults(null);
      return;
    }
    try {
      const results = await api.wiki.search(searchQuery);
      setSearchResults(results);
    } catch {
      setSearchResults([]);
    }
  };

  return (
    <div className="flex h-[calc(100vh-52px)]">
      {/* Sidebar */}
      <div className="w-72 border-r border-m3-border bg-m3-surface overflow-y-auto p-4 shrink-0">
        {/* Search */}
        <div className="mb-4">
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            placeholder="Search wiki..."
            className="w-full bg-m3-bg border border-m3-border rounded-lg px-3 py-2 text-sm"
          />
        </div>

        {/* Search results */}
        {searchResults && (
          <div className="mb-4">
            <h3 className="text-xs font-semibold text-m3-muted mb-2 uppercase">Results</h3>
            {searchResults.map((r) => (
              <button
                key={r.page_id}
                onClick={() => { navigate(`/wiki/${r.page_id}`); setSearchResults(null); setSearchQuery(""); }}
                className="w-full text-left p-2 rounded hover:bg-m3-bg text-sm mb-1"
              >
                <div className="font-medium">{r.title}</div>
                <div className="text-xs text-m3-muted truncate">{r.snippet}</div>
              </button>
            ))}
            {searchResults.length === 0 && <p className="text-xs text-m3-muted">No results</p>}
            <button onClick={() => setSearchResults(null)} className="text-xs text-m3-accent mt-1">
              Clear
            </button>
          </div>
        )}

        {/* Project filter */}
        <div className="mb-4">
          <h3 className="text-xs font-semibold text-m3-muted mb-2 uppercase">Categories</h3>
          <button
            onClick={() => setSelectedProject(null)}
            className={`block w-full text-left px-2 py-1 rounded text-sm ${!selectedProject ? "bg-m3-accent/20 text-m3-accent" : "hover:bg-m3-bg"}`}
          >
            All
          </button>
          {projects.map((p) => (
            <button
              key={p}
              onClick={() => setSelectedProject(p)}
              className={`block w-full text-left px-2 py-1 rounded text-sm ${selectedProject === p ? "bg-m3-accent/20 text-m3-accent" : "hover:bg-m3-bg"}`}
            >
              {p}
            </button>
          ))}
        </div>

        {/* Page list */}
        <div>
          <h3 className="text-xs font-semibold text-m3-muted mb-2 uppercase">Pages</h3>
          {pages.map((p) => (
            <button
              key={p.id}
              onClick={() => navigate(`/wiki/${p.id}`)}
              className={`block w-full text-left px-2 py-1.5 rounded text-sm mb-0.5 ${pageId === p.id ? "bg-m3-accent/20 text-m3-accent" : "hover:bg-m3-bg"}`}
            >
              {p.title}
            </button>
          ))}
          {pages.length === 0 && <p className="text-xs text-m3-muted">No pages yet</p>}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-8">
        {activePage ? (
          <div>
            <h1 className="text-3xl font-bold mb-2">{activePage.title}</h1>
            <div className="flex gap-2 mb-4 text-sm text-m3-muted">
              {activePage.category && <span className="bg-m3-surface px-2 py-0.5 rounded">{activePage.category}</span>}
              {activePage.tags.map((tag) => (
                <span key={tag} className="bg-m3-surface px-2 py-0.5 rounded">#{tag}</span>
              ))}
              <span>Updated {new Date(activePage.updated_at).toLocaleDateString()}</span>
            </div>
            <div className="prose max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{activePage.content}</ReactMarkdown>
            </div>
            {activePage.linked_pages.length > 0 && (
              <div className="mt-8 pt-4 border-t border-m3-border">
                <h3 className="text-sm font-semibold text-m3-muted mb-2">Linked Pages</h3>
                <div className="flex flex-wrap gap-2">
                  {activePage.linked_pages.map((lp) => (
                    <button
                      key={`${lp.id}-${lp.direction}`}
                      onClick={() => navigate(`/wiki/${lp.id}`)}
                      className="text-sm bg-m3-surface border border-m3-border rounded-lg px-3 py-1.5 hover:border-m3-accent transition-colors"
                    >
                      {lp.direction === "incoming" ? "\u2190" : "\u2192"} {lp.title}
                      <span className="text-xs text-m3-muted ml-1">({lp.link_type})</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="flex items-center justify-center h-full text-m3-muted">
            Select a page from the sidebar
          </div>
        )}
      </div>
    </div>
  );
}
