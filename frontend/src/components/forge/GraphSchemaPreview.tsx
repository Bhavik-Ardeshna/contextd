import { useEffect, useMemo, useRef, useState } from "react";
import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import Sigma from "sigma";
import {
  EdgeRectangleProgram,
  NodeCircleProgram,
  createEdgeArrowProgram,
  type EdgeLabelDrawingFunction,
  type NodeLabelDrawingFunction,
} from "sigma/rendering";
import { AlertTriangle, GitFork, Maximize2, Network, Sparkles } from "lucide-react";

import { useTheme } from "@/lib/theme-provider";
import { cn } from "@/lib/utils";

const ForgeArrowProgram = createEdgeArrowProgram({
  lengthToThicknessRatio: 3.4,
  widenessToThicknessRatio: 3,
});

export type ForgeGraphPreviewNode = {
  id: string;
  label: string;
  kind?: string;
  source_object?: string | null;
  status?: string;
  confidence?: number;
  x?: number;
  y?: number;
  metrics?: Record<string, unknown>;
  properties?: string[];
  badges?: string[];
};

export type ForgeGraphPreviewEdge = {
  id: string;
  source: string;
  target: string;
  label: string;
  kind?: string;
  status?: string;
  confidence?: number;
};

export type ForgeGraphPreview = {
  status: string;
  provider?: string | null;
  source_name?: string | null;
  generated_at: string;
  nodes: ForgeGraphPreviewNode[];
  edges: ForgeGraphPreviewEdge[];
  summary?: Record<string, unknown>;
  warnings?: string[];
};

type GraphSchemaPreviewProps = {
  preview?: ForgeGraphPreview | null;
  title?: string;
  subtitle?: string;
  compact?: boolean;
  className?: string;
  canvasClassName?: string;
};

const nodeColor = (kind?: string, isDark = false) => {
  if (kind === "source") return "#E45F1A";
  if (kind === "fact") return isDark ? "#60A5FA" : "#1F86CC";
  if (kind === "property") return isDark ? "#94A3B8" : "#64748B";
  return isDark ? "#34D399" : "#1F9D6A";
};

const nodeSize = (kind?: string, compact = false) => {
  const base = compact ? 10 : 16;
  if (kind === "source") return base + 8;
  if (kind === "fact") return base - 1;
  if (kind === "property") return base - 3;
  return base;
};

const edgeColor = (kind?: string, isDark = false) => {
  if (kind === "lineage") return isDark ? "#F97316" : "#D84A12";
  if (kind === "fact") return isDark ? "#38BDF8" : "#176EA8";
  if (kind === "foreign_key") return isDark ? "#34D399" : "#11845B";
  return isDark ? "#94A3B8" : "#475569";
};

const graphologyLayoutSeed = (index: number, count: number) => {
  const angle = (Math.PI * 2 * index) / Math.max(count, 1);
  const radius = count > 8 ? 10 : 7;
  return {
    x: Math.cos(angle) * radius,
    y: Math.sin(angle) * radius,
  };
};

const getGraphologyNodeLabel = (node: ForgeGraphPreviewNode) => {
  const label = node.label || node.source_object || node.id;
  return label.length > 24 ? `${label.slice(0, 21)}...` : label;
};

const getGraphologyDisplayLabel = (node: ForgeGraphPreviewNode) => {
  if (node.kind === "source") return "source";
  if (getNodeGroup(node) === "fact") return "";
  return getGraphologyNodeLabel(node);
};

const getEdgeWeight = (kind?: string) => {
  if (kind === "foreign_key") return 2.2;
  if (kind === "fact") return 1.7;
  if (kind === "lineage") return 0.75;
  return 1;
};

const getEdgeSize = (kind?: string, compact = false) => {
  const base = compact ? 1.6 : 2.35;
  if (kind === "foreign_key") return base + 1.1;
  if (kind === "fact") return base + 0.55;
  if (kind === "lineage") return base + 0.15;
  return base;
};

const getNodeGroup = (node: ForgeGraphPreviewNode) => {
  if (node.kind === "source") return "source";
  if (node.kind === "fact" || node.kind === "property") return "fact";
  return "entity";
};

const buildNeighborMap = (edges: ForgeGraphPreviewEdge[]) => {
  const map = new Map<string, Set<string>>();
  edges.forEach((edge) => {
    if (!edge.source || !edge.target) return;
    if (!map.has(edge.source)) map.set(edge.source, new Set());
    if (!map.has(edge.target)) map.set(edge.target, new Set());
    map.get(edge.source)?.add(edge.target);
    map.get(edge.target)?.add(edge.source);
  });
  return map;
};

const buildParentMap = (edges: ForgeGraphPreviewEdge[], nodes: ForgeGraphPreviewNode[]) => {
  const groups = new Map(nodes.map((node) => [node.id, getNodeGroup(node)]));
  const map = new Map<string, string>();
  edges.forEach((edge) => {
    const sourceGroup = groups.get(edge.source);
    const targetGroup = groups.get(edge.target);
    if (targetGroup === "fact" && sourceGroup === "entity") map.set(edge.target, edge.source);
    if (sourceGroup === "fact" && targetGroup === "entity") map.set(edge.source, edge.target);
  });
  return map;
};

const applySchemaLayout = (
  graph: Graph,
  nodes: ForgeGraphPreviewNode[],
  edges: ForgeGraphPreviewEdge[],
  compact: boolean
) => {
  const source = nodes.find((node) => getNodeGroup(node) === "source");
  const entityNodes = nodes.filter((node) => getNodeGroup(node) === "entity");
  const factNodes = nodes.filter((node) => getNodeGroup(node) === "fact");
  const parentMap = buildParentMap(edges, nodes);
  const factAngles = new Map<string, number>();
  const entityRadius = compact ? 7.2 : 9.5;
  const entityYScale = compact ? 0.74 : 0.68;

  if (source && graph.hasNode(source.id)) {
    graph.mergeNodeAttributes(source.id, { x: 0, y: 0, zIndex: 6 });
  }

  entityNodes.forEach((node, index) => {
    if (!graph.hasNode(node.id)) return;
    const angle = -Math.PI / 2 + (Math.PI * 2 * index) / Math.max(entityNodes.length, 1);
    graph.mergeNodeAttributes(node.id, {
      x: Math.cos(angle) * entityRadius,
      y: Math.sin(angle) * entityRadius * entityYScale,
      zIndex: 5,
    });
  });

  const factsByParent = new Map<string, ForgeGraphPreviewNode[]>();
  factNodes.forEach((node) => {
    const parent = parentMap.get(node.id);
    if (!parent) return;
    if (!factsByParent.has(parent)) factsByParent.set(parent, []);
    factsByParent.get(parent)?.push(node);
  });

  factNodes.forEach((node, index) => {
    if (!graph.hasNode(node.id)) return;
    const parentId = parentMap.get(node.id);
    const parentAttrs = parentId && graph.hasNode(parentId) ? graph.getNodeAttributes(parentId) : null;
    if (!parentAttrs) {
      const position = graphologyLayoutSeed(index, factNodes.length);
      graph.mergeNodeAttributes(node.id, { ...position, zIndex: 4 });
      return;
    }

    const siblings = factsByParent.get(parentId) || [node];
    const siblingIndex = Math.max(siblings.findIndex((candidate) => candidate.id === node.id), 0);
    const parentAngle = Math.atan2(Number(parentAttrs.y || 0), Number(parentAttrs.x || 0));
    const spread = siblings.length === 1 ? 0 : (siblingIndex - (siblings.length - 1) / 2) * 0.9;
    const angle = parentAngle + spread;
    const distance = compact ? 3.5 : 4.2;
    factAngles.set(node.id, angle);
    graph.mergeNodeAttributes(node.id, {
      x: Number(parentAttrs.x || 0) + Math.cos(angle) * distance,
      y: Number(parentAttrs.y || 0) + Math.sin(angle) * distance,
      zIndex: 4,
    });
  });

  if (graph.order > 2 && graph.order <= 80) {
    const inferred = forceAtlas2.inferSettings(graph);
    forceAtlas2.assign(graph, {
      iterations: compact ? 18 : 28,
      getEdgeWeight: "layoutWeight",
      settings: {
        ...inferred,
        adjustSizes: true,
        edgeWeightInfluence: 0.75,
        gravity: 5.5,
        scalingRatio: compact ? 0.85 : 1.1,
        slowDown: 12,
        strongGravityMode: true,
      },
    });
  }

  factNodes.forEach((node) => {
    const parentId = parentMap.get(node.id);
    if (!parentId || !graph.hasNode(parentId) || !graph.hasNode(node.id)) return;
    const parentAttrs = graph.getNodeAttributes(parentId);
    const attrs = graph.getNodeAttributes(node.id);
    const dx = Number(attrs.x || 0) - Number(parentAttrs.x || 0);
    const dy = Number(attrs.y || 0) - Number(parentAttrs.y || 0);
    const angle = factAngles.get(node.id) ?? Math.atan2(dy, dx);
    const targetDistance = compact ? 3.4 : 4.35;
    graph.mergeNodeAttributes(node.id, {
      x: Number(parentAttrs.x || 0) + Math.cos(angle) * targetDistance,
      y: Number(parentAttrs.y || 0) + Math.sin(angle) * targetDistance,
    });
  });
};

const applyViewportPadding = (renderer: Sigma, graph: Graph, compact: boolean) => {
  if (graph.order === 0) return;
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  graph.forEachNode((_node, attrs) => {
    const x = Number(attrs.x || 0);
    const y = Number(attrs.y || 0);
    minX = Math.min(minX, x);
    maxX = Math.max(maxX, x);
    minY = Math.min(minY, y);
    maxY = Math.max(maxY, y);
  });
  const width = Math.max(maxX - minX, 1);
  const height = Math.max(maxY - minY, 1);
  const paddingRatio = compact ? 0.28 : 0.14;
  renderer.setCustomBBox({
    x: [minX - width * paddingRatio, maxX + width * paddingRatio],
    y: [minY - height * paddingRatio, maxY + height * paddingRatio],
  });
};

const createNodeLabelRenderer = (isDark: boolean): NodeLabelDrawingFunction => (context, data, settings) => {
  if (!data.label) return;
  const size = Math.max(settings.labelSize, 11);
  const label = String(data.label);
  context.font = `${settings.labelWeight || 600} ${size}px ${settings.labelFont}`;
  const textWidth = context.measureText(label).width;
  const x = data.x + data.size + 6;
  const y = data.y + size / 3;
  context.fillStyle = isDark ? "rgba(5,5,5,0.72)" : "rgba(255,255,255,0.78)";
  context.fillRect(x - 3, y - size + 1, textWidth + 6, size + 4);
  context.fillStyle = isDark ? "#F8FAFC" : "#111827";
  context.fillText(label, x, y);
};

const createEdgeLabelRenderer = (isDark: boolean): EdgeLabelDrawingFunction => (context, edgeData, sourceData, targetData, settings) => {
  if (!edgeData.label) return;
  const label = String(edgeData.label);
  const x = (sourceData.x + targetData.x) / 2;
  const y = (sourceData.y + targetData.y) / 2;
  const size = Math.max(settings.edgeLabelSize, 9);
  context.font = `${settings.edgeLabelWeight || 500} ${size}px ${settings.edgeLabelFont}`;
  const textWidth = context.measureText(label).width;
  context.fillStyle = isDark ? "rgba(5,5,5,0.68)" : "rgba(255,255,255,0.72)";
  context.fillRect(x - textWidth / 2 - 3, y - size + 1, textWidth + 6, size + 3);
  context.fillStyle = isDark ? "#CBD5E1" : "#475569";
  context.fillText(label, x - textWidth / 2, y);
};

export const GraphSchemaPreview = ({
  preview,
  title = "Forge schema preview",
  subtitle,
  compact = false,
  className,
  canvasClassName,
}: GraphSchemaPreviewProps) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const sigmaRef = useRef<Sigma | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const nodes = preview?.nodes || [];
  const edges = preview?.edges || [];
  const warnings = preview?.warnings || [];
  const activeNodeId = selectedNodeId || hoveredNodeId;
  const neighborMap = useMemo(() => buildNeighborMap(edges), [edges]);
  const graphStats = useMemo(() => {
    const entityCount = nodes.filter((node) => getNodeGroup(node) === "entity").length;
    const factCount = nodes.filter((node) => getNodeGroup(node) === "fact").length;
    const foreignKeyCount = edges.filter((edge) => edge.kind === "foreign_key").length;
    const factEdgeCount = edges.filter((edge) => edge.kind === "fact").length;
    return { entityCount, factCount, foreignKeyCount, factEdgeCount };
  }, [edges, nodes]);
  const activeNode = useMemo(
    () => nodes.find((node) => node.id === activeNodeId) || null,
    [activeNodeId, nodes]
  );

  useEffect(() => {
    if (!containerRef.current || nodes.length === 0) return undefined;

    const graph = new Graph({ allowSelfLoops: false, multi: true, type: "directed" });
    const seenNodes = new Set<string>();
    nodes.forEach((node, index) => {
      if (!node.id || seenNodes.has(node.id)) return;
      const position = graphologyLayoutSeed(index, nodes.length);
      graph.addNode(node.id, {
        ...position,
        label: getGraphologyDisplayLabel(node),
        previewLabel: getGraphologyNodeLabel(node),
        labelColor: isDark ? "#F8FAFC" : "#111827",
        color: nodeColor(node.kind, isDark),
        size: nodeSize(node.kind, compact),
        kind: node.kind || "entity",
        group: getNodeGroup(node),
        sourceObject: node.source_object,
        confidence: node.confidence,
        originalLabel: node.label,
        zIndex: node.kind === "source" ? 6 : node.kind === "fact" ? 4 : 5,
      });
      seenNodes.add(node.id);
    });

    edges.forEach((edge, index) => {
      if (!seenNodes.has(edge.source) || !seenNodes.has(edge.target)) return;
      const edgeId = edge.id || `${edge.source}->${edge.target}:${index}`;
      if (graph.hasEdge(edgeId)) return;
      graph.addDirectedEdgeWithKey(edgeId, edge.source, edge.target, {
        label: edge.label?.replace(/_/g, " ") || "relates to",
        color: edgeColor(edge.kind, isDark),
        size: getEdgeSize(edge.kind, compact),
        type: edge.kind === "lineage" ? "line" : "arrow",
        weight: edge.confidence || 1,
        layoutWeight: getEdgeWeight(edge.kind),
        kind: edge.kind || "relationship",
        zIndex: edge.kind === "foreign_key" ? 3 : edge.kind === "fact" ? 2 : 1,
      });
    });

    applySchemaLayout(graph, nodes, edges, compact);

    graphRef.current = graph;
    const renderer = new Sigma(graph, containerRef.current, {
      allowInvalidContainer: true,
      autoCenter: true,
      autoRescale: true,
      defaultEdgeColor: edgeColor(undefined, isDark),
      defaultEdgeType: "arrow",
      defaultNodeColor: nodeColor(undefined, isDark),
      defaultNodeType: "circle",
      defaultDrawEdgeLabel: createEdgeLabelRenderer(isDark),
      defaultDrawNodeLabel: createNodeLabelRenderer(isDark),
      edgeProgramClasses: {
        arrow: ForgeArrowProgram,
        line: EdgeRectangleProgram,
      },
      edgeLabelColor: { color: isDark ? "#CBD5E1" : "#475569" },
      edgeLabelFont: "JetBrains Mono, ui-monospace, SFMono-Regular, monospace",
      edgeLabelSize: 9,
      enableEdgeEvents: true,
      itemSizesReference: "screen",
      labelColor: { attribute: "labelColor" },
      labelDensity: compact ? 0.16 : 0.3,
      labelFont: "Inter, system-ui, sans-serif",
      labelGridCellSize: compact ? 76 : 54,
      labelRenderedSizeThreshold: compact ? 8 : 5,
      labelSize: compact ? 10 : 11,
      labelWeight: "600",
      minCameraRatio: 0.55,
      minEdgeThickness: compact ? 1 : 1.25,
      nodeProgramClasses: {
        circle: NodeCircleProgram,
      },
      renderEdgeLabels: false,
      renderLabels: true,
      stagePadding: compact ? 8 : 14,
      zIndex: true,
    });
    sigmaRef.current = renderer;
    applyViewportPadding(renderer, graph, compact);

    renderer.on("enterNode", ({ node }: { node: string }) => {
      setHoveredNodeId(node);
      if (containerRef.current) containerRef.current.style.cursor = "pointer";
    });
    renderer.on("leaveNode", () => {
      setHoveredNodeId(null);
      if (containerRef.current) containerRef.current.style.cursor = "grab";
    });
    renderer.on("clickNode", ({ node }: { node: string }) => setSelectedNodeId((previous) => (previous === node ? null : node)));
    renderer.on("clickStage", () => setSelectedNodeId(null));
    renderer.getCamera().animatedReset({ duration: 260 });
    if (containerRef.current) containerRef.current.style.cursor = "grab";

    return () => {
      renderer.kill();
      sigmaRef.current = null;
      graphRef.current = null;
      setHoveredNodeId(null);
      setSelectedNodeId(null);
    };
  }, [compact, edges, isDark, nodes]);

  useEffect(() => {
    const renderer = sigmaRef.current;
    const graph = graphRef.current;
    if (!renderer || !graph) return;

    renderer.setSettings({
      nodeReducer: (node, data) => {
        const activeNeighbors = activeNodeId ? neighborMap.get(activeNodeId) : null;
        const isActive = activeNodeId === node;
        const isNeighbor = Boolean(activeNeighbors?.has(node));
        if (!activeNodeId || isActive || isNeighbor) {
          return {
            ...data,
            label: activeNodeId ? data.previewLabel || data.label : data.label,
            forceLabel: Boolean(activeNodeId && (isActive || isNeighbor)),
            highlighted: isActive,
            size: isActive ? Number(data.size || 0) + 5 : data.size,
            zIndex: isActive ? 10 : data.zIndex,
          };
        }
        return {
          ...data,
          color: isDark ? "rgba(71,85,105,0.34)" : "rgba(148,163,184,0.34)",
          label: "",
          zIndex: 0,
        };
      },
      edgeReducer: (edge, data) => {
        if (!activeNodeId) return data;
        const extremities = graph.extremities(edge);
        const touchesActive = extremities.includes(activeNodeId);
        if (touchesActive) {
          return {
            ...data,
            forceLabel: true,
            size: Number(data.size || 1) + 1.2,
            label: data.label,
            zIndex: 8,
          };
        }
        return {
          ...data,
          color: isDark ? "rgba(71,85,105,0.16)" : "rgba(148,163,184,0.18)",
          label: "",
          size: Math.max(Number(data.size || 1) - 0.5, 0.7),
          zIndex: 0,
        };
      },
      renderEdgeLabels: Boolean(activeNodeId) && !compact,
    });
    renderer.refresh({ skipIndexation: true });
  }, [activeNodeId, compact, isDark, neighborMap]);

  const resetCamera = () => {
    sigmaRef.current?.getCamera().animatedReset({ duration: 220 });
  };

  return (
    <div className={cn("overflow-hidden rounded-lg border border-border bg-card", className)}>
      <div className="border-b border-border bg-gradient-to-r from-primary/5 via-card to-card px-4 py-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-primary/20 bg-primary/10 text-primary">
              <Sparkles className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <h3 className="truncate text-sm font-semibold text-foreground">{title}</h3>
                {preview?.status && (
                  <span className="rounded border border-primary/25 bg-background/80 px-2 py-0.5 text-[10px] font-medium text-primary">
                    {preview.status.replace(/_/g, " ")}
                  </span>
                )}
              </div>
              <div className="mt-1 flex min-w-0 flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                <span className="truncate">{subtitle || (preview ? "Forge schema draft" : "Run discovery to generate the schema.")}</span>
                {preview && (
                  <>
                    <span className="h-1 w-1 rounded-full bg-border" />
                    <span className="font-mono text-foreground">{nodes.length} nodes</span>
                    <span className="h-1 w-1 rounded-full bg-border" />
                    <span className="font-mono text-foreground">{edges.length} relations</span>
                  </>
                )}
              </div>
            </div>
          </div>
          {preview && (
            <div className="flex shrink-0 items-center gap-1.5 text-[10px] text-muted-foreground">
              <span className="rounded border border-border bg-background/80 px-2 py-1 font-mono">
                {graphStats.entityCount} entities
              </span>
              <span className="rounded border border-border bg-background/80 px-2 py-1 font-mono">
                {graphStats.foreignKeyCount} FK
              </span>
            </div>
          )}
        </div>
      </div>

      <div className={cn("relative overflow-hidden bg-background", canvasClassName || (compact ? "h-[180px]" : "h-[320px]"))}>
        {nodes.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center px-8 text-center text-sm text-muted-foreground">
            <GitFork className="mb-3 h-8 w-8 text-primary" />
            Forge will draw entities, relationships, and derived facts here after discovery.
          </div>
        ) : (
          <>
            <div className="absolute inset-0 opacity-[0.42] [background-image:linear-gradient(to_right,hsl(var(--border))_1px,transparent_1px),linear-gradient(to_bottom,hsl(var(--border))_1px,transparent_1px)] [background-size:36px_36px]" />
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_48%_46%,rgba(228,95,26,0.12),transparent_34%),radial-gradient(circle_at_62%_36%,rgba(31,134,204,0.11),transparent_30%),radial-gradient(circle_at_44%_62%,rgba(17,132,91,0.10),transparent_28%)]" />
            <div className="absolute left-1/2 top-1/2 h-72 w-72 -translate-x-1/2 -translate-y-1/2 rounded-full border border-primary/10" />
            <div className="absolute left-1/2 top-1/2 h-44 w-44 -translate-x-1/2 -translate-y-1/2 rounded-full border border-emerald-500/10" />
            <div ref={containerRef} className="relative h-full w-full" role="img" aria-label="Context Forge graph schema preview" />
            {!compact && (
              <div className="pointer-events-none absolute left-3 top-3 flex max-w-[calc(100%-104px)] flex-wrap items-center gap-1.5 rounded-md border border-border bg-background/95 px-2.5 py-1.5 text-[10px] text-muted-foreground shadow-sm backdrop-blur">
                <span className="flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-full bg-[#E45F1A]" />
                  source
                </span>
                <span className="h-px w-5 rounded-full bg-[#11845B]" />
                <span className="flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-full bg-[#1F9D6A]" />
                  {graphStats.entityCount} entities
                </span>
                <span className="h-px w-5 rounded-full bg-[#176EA8]" />
                <span className="flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-full bg-[#1F86CC]" />
                  {graphStats.factCount} facts
                </span>
              </div>
            )}
            {!compact && (
              <div className="pointer-events-none absolute bottom-3 left-3 flex flex-wrap items-center gap-2 rounded-md border border-border bg-background/95 px-2.5 py-1.5 text-[10px] text-muted-foreground shadow-sm backdrop-blur">
                <span className="flex items-center gap-1.5 font-mono">
                  <span className="h-0.5 w-6 rounded-full bg-[#11845B]" />
                  {graphStats.foreignKeyCount} FK
                </span>
                <span className="flex items-center gap-1.5 font-mono">
                  <span className="h-0.5 w-6 rounded-full bg-[#176EA8]" />
                  {graphStats.factEdgeCount} fact edges
                </span>
                <span className="h-1 w-1 rounded-full bg-border" />
                <span>{selectedNodeId ? "click canvas to release" : "hover or click node"}</span>
              </div>
            )}
            {compact && (
              <div className="pointer-events-none absolute bottom-3 left-3 flex items-center gap-2 rounded-md border border-border bg-background/95 px-2.5 py-1 text-[10px] text-muted-foreground shadow-sm">
                <span className="font-mono">{nodes.length} nodes · {edges.length} edges</span>
              </div>
            )}
            {!compact && !activeNode && (
              <div className="pointer-events-none absolute right-3 bottom-3 hidden max-w-[178px] rounded-md border border-border bg-background/95 p-2 text-[10px] text-muted-foreground shadow-sm backdrop-blur sm:block">
                <div className="mb-1 font-medium text-foreground">Relation fabric</div>
                <div className="flex items-center gap-2">
                  <span className="h-0.5 w-8 rounded-full bg-[#11845B]" />
                  <span>keys and joins</span>
                </div>
                <div className="mt-1 flex items-center gap-2">
                  <span className="h-0.5 w-8 rounded-full bg-[#176EA8]" />
                  <span>derived facts</span>
                </div>
                <div className="mt-1 flex items-center gap-2">
                  <span className="h-0.5 w-8 rounded-full bg-[#D84A12]" />
                  <span>source lineage</span>
                </div>
              </div>
            )}
            {!compact && (
              <button
                type="button"
                onClick={resetCamera}
                className="absolute right-3 top-3 inline-flex h-7 items-center gap-1.5 rounded-md border border-border bg-background/90 px-2 text-[11px] font-medium text-muted-foreground shadow-sm transition hover:text-foreground"
              >
                <Maximize2 className="h-3.5 w-3.5" />
                Fit
              </button>
            )}
            {activeNode && (
              <div className="absolute bottom-3 right-3 max-w-[240px] rounded-md border border-border bg-background/95 p-3 shadow-md">
                <div className="flex items-center gap-2">
                  <Network className="h-3.5 w-3.5 text-primary" />
                  <p className="truncate text-xs font-semibold text-foreground">{activeNode.label}</p>
                </div>
                <p className="mt-1 truncate font-mono text-[10px] text-muted-foreground">
                  {activeNode.kind || "entity"}{activeNode.source_object ? ` · ${activeNode.source_object}` : ""}
                </p>
                {activeNode.metrics && Object.keys(activeNode.metrics).length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {Object.entries(activeNode.metrics).slice(0, 2).map(([key, value]) => (
                      <span key={key} className="rounded border border-border bg-muted/40 px-1.5 py-0.5 font-mono text-[9px] text-muted-foreground">
                        {key}: {String(value)}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>

      {warnings.length > 0 && (
        <div className="border-t border-border px-4 py-3">
          <div className="flex items-start gap-2 text-xs text-amber-600 dark:text-amber-400">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>{warnings.slice(0, 2).join(" · ")}</span>
          </div>
        </div>
      )}
    </div>
  );
};
