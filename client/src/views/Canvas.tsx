import { useCallback, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Connection,
  NodeChange,
  applyNodeChanges,
  useReactFlow,
  ReactFlowProvider,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "../components/canvas/canvas.css";
import EntityNode from "../components/canvas/EntityNode";
import InsightNode from "../components/canvas/InsightNode";
import ThreadNode from "../components/canvas/ThreadNode";
import ChatDock from "../components/chat/ChatDock";
import NodeEditor from "../components/canvas/NodeEditor";
import LinkTypeMenu from "../components/canvas/LinkTypeMenu";
import NewNodeMenu from "../components/canvas/NewNodeMenu";
import CommandPalette, { PaletteAction } from "../components/palette/CommandPalette";
import ToolDrawer, { DrawerPane } from "../components/drawer/ToolDrawer";
import { useCanvasData, toFlowNode, toFlowEdge } from "../hooks/useCanvasData";
import { useHotkeys } from "../hooks/useHotkeys";
import { useTheme } from "../hooks/useTheme";
import { api } from "../api/client";

interface PendingLink {
  source: string;
  target: string;
  screenX: number;
  screenY: number;
}

interface PendingNewNode {
  flowX: number;
  flowY: number;
  screenX: number;
  screenY: number;
}

function CanvasInner() {
  const { setTheme } = useTheme();
  const {
    nodes,
    edges,
    loading,
    error,
    reload,
    queueLayout,
    setNodes,
    upsertNode,
    addEdge,
  } = useCanvasData();

  const { screenToFlowPosition, setCenter, getNode } = useReactFlow();

  const [editingEntityId, setEditingEntityId] = useState<string | null>(null);
  const [pendingLink, setPendingLink] = useState<PendingLink | null>(null);
  const [pendingNewNode, setPendingNewNode] = useState<PendingNewNode | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [drawerPane, setDrawerPane] = useState<DrawerPane | null>(null);

  const nodeTypes = useMemo(
    () => ({ entity: EntityNode, insight: InsightNode, thread: ThreadNode }),
    [],
  );

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      setNodes((prev) => {
        const next = applyNodeChanges(changes, prev);
        for (const ch of changes) {
          if (ch.type === "position" && ch.position && !ch.dragging) {
            queueLayout(ch.id, ch.position.x, ch.position.y);
          }
        }
        return next;
      });
    },
    [queueLayout, setNodes],
  );

  const onConnect = useCallback((c: Connection) => {
    if (!c.source || !c.target) return;
    const srcIsEntity = c.source.startsWith("entity:");
    const tgtIsEntity = c.target.startsWith("entity:");
    if (!srcIsEntity || !tgtIsEntity) return; // entity-to-entity links only for now
    // Anchor the menu at the middle of the target node.
    const tgt = getNode(c.target);
    const screenX = window.innerWidth / 2;
    const screenY = window.innerHeight / 2;
    setPendingLink({
      source: c.source,
      target: c.target,
      screenX: tgt ? screenX : screenX,
      screenY: tgt ? screenY : screenY,
    });
  }, [getNode]);

  const confirmLink = useCallback(
    async (linkType: string) => {
      if (!pendingLink) return;
      const sourceId = pendingLink.source.slice("entity:".length);
      const targetId = pendingLink.target.slice("entity:".length);
      try {
        const link = await api.entityLinks.create({
          source_entity_id: sourceId,
          target_entity_id: targetId,
          link_type: linkType,
        });
        addEdge(
          toFlowEdge({
            id: `link:${link.id}`,
            source: pendingLink.source,
            target: pendingLink.target,
            edge_type: link.link_type,
            weight: link.weight,
          }),
        );
      } catch (err) {
        console.error("link create failed", err);
      } finally {
        setPendingLink(null);
      }
    },
    [pendingLink, addEdge],
  );

  const onPaneDoubleClick = useCallback(
    (e: React.MouseEvent) => {
      // Ignore dblclicks on nodes, handles, or edges — those have their own handlers.
      const target = e.target as HTMLElement;
      if (target.closest(".react-flow__node") || target.closest(".react-flow__edge")) {
        return;
      }
      const pos = screenToFlowPosition({ x: e.clientX, y: e.clientY });
      setPendingNewNode({
        flowX: pos.x,
        flowY: pos.y,
        screenX: e.clientX,
        screenY: e.clientY,
      });
    },
    [screenToFlowPosition],
  );

  const confirmNewNode = useCallback(
    async (name: string, entityType: string) => {
      if (!pendingNewNode) return;
      try {
        const ent = await api.entities.create({
          canonical_name: name,
          entity_type: entityType,
        });
        const nodeId = `entity:${ent.id}`;
        upsertNode(
          toFlowNode(
            {
              id: nodeId,
              node_type: "entity",
              label: ent.canonical_name,
              data: {
                entity_type: ent.entity_type,
                has_page: !!ent.page_content,
                overview: ent.page_overview,
                facts_since_render: ent.facts_since_render ?? 0,
              },
              x: pendingNewNode.flowX,
              y: pendingNewNode.flowY,
              width: null,
              height: null,
            },
            0,
          ),
        );
        // Persist its spawn position.
        queueLayout(nodeId, pendingNewNode.flowX, pendingNewNode.flowY);
      } catch (err) {
        console.error("entity create failed", err);
      } finally {
        setPendingNewNode(null);
      }
    },
    [pendingNewNode, upsertNode, queueLayout],
  );

  const onNodeDoubleClick = useCallback((_e: React.MouseEvent, node: { id: string }) => {
    if (!node.id.startsWith("entity:")) return;
    setEditingEntityId(node.id.slice("entity:".length));
  }, []);

  const onPaletteAction = useCallback(
    (a: PaletteAction) => {
      setPaletteOpen(false);
      if (a.kind === "open-drawer") {
        setDrawerPane(a.pane);
        return;
      }
      if (a.kind === "set-theme") {
        void setTheme(a.theme);
        return;
      }
      if (a.kind === "focus-entity") {
        const nodeId = `entity:${a.id}`;
        const n = getNode(nodeId);
        if (n) {
          const w = n.measured?.width ?? 160;
          const h = n.measured?.height ?? 80;
          setCenter(n.position.x + w / 2, n.position.y + h / 2, {
            zoom: 1.2,
            duration: 500,
          });
        }
      }
    },
    [getNode, setCenter, setTheme],
  );

  const onCite = useCallback(
    (cite: { entity_id: string }) => {
      const nodeId = `entity:${cite.entity_id}`;
      const n = getNode(nodeId);
      if (!n) return;
      const w = n.measured?.width ?? 160;
      const h = n.measured?.height ?? 80;
      setCenter(n.position.x + w / 2, n.position.y + h / 2, {
        zoom: 1.1,
        duration: 600,
      });
      // Flag the node for a pulse by writing a cssVar-style hint via data. The
      // node component reads it and self-clears the class after the animation.
      setNodes((prev) =>
        prev.map((no) => {
          if (no.id !== nodeId) return no;
          return {
            ...no,
            data: { ...(no.data as object), _pulseAt: Date.now() },
          };
        }),
      );
    },
    [getNode, setCenter, setNodes],
  );

  const onThreadChanged = useCallback(() => {
    // Refetch so the new thread node (or the ended-state transition) shows up.
    void reload();
  }, [reload]);

  const hotkeys = useMemo(
    () => ({
      "cmd+k": (e: KeyboardEvent) => {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      },
      "ctrl+k": (e: KeyboardEvent) => {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      },
    }),
    [],
  );
  useHotkeys(hotkeys);

  if (loading && !nodes.length) {
    return <div className="p-6 text-m3-muted">Loading canvas…</div>;
  }
  if (error) {
    return <div className="p-6 text-red-500">Canvas error: {error}</div>;
  }

  return (
    <div className="canvas-surface">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onConnect={onConnect}
        onPaneClick={undefined}
        onPaneContextMenu={undefined}
        onDoubleClick={onPaneDoubleClick}
        onNodeDoubleClick={onNodeDoubleClick}
        fitView
        minZoom={0.1}
        maxZoom={2.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={32} size={1} />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable />
      </ReactFlow>

      {editingEntityId && (
        <NodeEditor
          entityId={editingEntityId}
          onClose={() => setEditingEntityId(null)}
          onSaved={(patch) => {
            const id = `entity:${editingEntityId}`;
            const existing = nodes.find((n) => n.id === id);
            if (existing) {
              const d = (existing.data as { label: string; data: Record<string, unknown> })
                .data;
              upsertNode({
                ...existing,
                data: {
                  ...(existing.data as object),
                  label: patch.canonical_name,
                  data: { ...d, has_page: !!patch.page_content },
                },
              });
            }
          }}
        />
      )}

      {pendingLink && (
        <LinkTypeMenu
          screenX={pendingLink.screenX}
          screenY={pendingLink.screenY}
          onConfirm={confirmLink}
          onCancel={() => setPendingLink(null)}
        />
      )}

      {pendingNewNode && (
        <NewNodeMenu
          screenX={pendingNewNode.screenX}
          screenY={pendingNewNode.screenY}
          onConfirm={confirmNewNode}
          onCancel={() => setPendingNewNode(null)}
        />
      )}

      {paletteOpen && (
        <CommandPalette
          onAction={onPaletteAction}
          onClose={() => setPaletteOpen(false)}
        />
      )}

      <ToolDrawer open={drawerPane} onClose={() => setDrawerPane(null)} />

      <ChatDock onCite={onCite} onThreadChanged={onThreadChanged} />
    </div>
  );
}

export default function Canvas() {
  return (
    <ReactFlowProvider>
      <CanvasInner />
    </ReactFlowProvider>
  );
}
