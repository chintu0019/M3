import { useSearchParams } from "react-router-dom";
import { useCallback, useMemo } from "react";

export type SidebarFilter =
  | { kind: "view"; value: "all" | "recent" | "pending" | "processing" | "done" | "error" }
  | { kind: "project"; value: string }
  | { kind: "type"; value: string }
  | { kind: "source"; value: string };

export type LibraryFilters = {
  filter: SidebarFilter;
  q: string;
  mode: "list" | "grid";
  sort: "date_desc" | "date_asc" | "name_asc" | "status";
};

export function useLibraryFilters() {
  const [params, setParams] = useSearchParams();

  const filters = useMemo<LibraryFilters>(() => {
    // Sidebar filter: exactly one of view/project/type/source
    const view = params.get("view");
    const project = params.get("project");
    const type = params.get("type");
    const source = params.get("source");

    let filter: SidebarFilter = { kind: "view", value: "all" };
    if (project) filter = { kind: "project", value: project };
    else if (type) filter = { kind: "type", value: type };
    else if (source) filter = { kind: "source", value: source };
    else if (view === "recent" || view === "pending" || view === "processing" || view === "done" || view === "error") {
      filter = { kind: "view", value: view };
    }

    return {
      filter,
      q: params.get("q") ?? "",
      mode: params.get("mode") === "grid" ? "grid" : "list",
      sort: (params.get("sort") as LibraryFilters["sort"]) ?? "date_desc",
    };
  }, [params]);

  const setFilter = useCallback(
    (next: SidebarFilter) => {
      const p = new URLSearchParams(params);
      // Clear other dimensions
      p.delete("view");
      p.delete("project");
      p.delete("type");
      p.delete("source");
      if (next.kind === "view") {
        if (next.value !== "all") p.set("view", next.value);
      } else {
        p.set(next.kind, next.value);
      }
      setParams(p, { replace: false });
    },
    [params, setParams],
  );

  const setField = useCallback(
    (key: "q" | "mode" | "sort", value: string) => {
      const p = new URLSearchParams(params);
      if (value) p.set(key, value);
      else p.delete(key);
      setParams(p, { replace: true });
    },
    [params, setParams],
  );

  return { filters, setFilter, setField };
}
