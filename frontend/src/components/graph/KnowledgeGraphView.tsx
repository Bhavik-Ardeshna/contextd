import { type FormEvent, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import Sigma from "sigma";
import {
  EdgeRectangleProgram,
  NodeCircleProgram,
  createEdgeArrowProgram,
  type NodeLabelDrawingFunction,
} from "sigma/rendering";
import {
  Activity,
  ArrowRight,
  Boxes,
  CircleDot,
  Clock,
  Copy,
  Database,
  Download,
  Filter,
  GitFork,
  Hand,
  Layers3,
  Loader2,
  Maximize2,
  MousePointer,
  Network,
  RefreshCw,
  Route,
  Search,
  ShieldCheck,
  Sparkles,
  ZoomIn,
  ZoomOut,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiClient } from "@/lib/api";
import {
  fetchContextIntelligence,
  type ContextIntelligenceSummary,
} from "@/lib/contextIntelligenceApi";
import { useTheme } from "@/lib/theme-provider";
import { cn } from "@/lib/utils";

const ExplorerArrowProgram = createEdgeArrowProgram({
  lengthToThicknessRatio: 3.4,
  widenessToThicknessRatio: 3,
});

type GraphExplorerNode = {
  id: string;
  node_id: string;
  label: string;
  node_type: string;
  visual_kind: string;
  source?: string | null;
  collection_id?: string | null;
  properties: Record<string, any>;
  labels?: string[];
  degree?: number;
  depth?: number;
  is_seed?: boolean;
  is_selected?: boolean;
  created_at?: string | null;
  updated_at?: string | null;
};

type GraphExplorerEdge = {
  id: string;
  edge_id: string;
  source: string;
  target: string;
  source_node_id: string;
  target_node_id: string;
  relationship_type: string;
  label: string;
  visual_kind: string;
  properties: Record<string, any>;
  fact?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

type FacetItem = {
  value: string;
  count: number;
};

type GraphFact = {
  key: string;
  value: any;
  masked?: boolean;
  mask?: Record<string, any>;
};

type GraphInspector = {
  node: GraphExplorerNode;
  facts: GraphFact[];
  facts_total?: number;
  facts_sample_count?: number;
  facts_truncated?: boolean;
  top_edges: FacetItem[];
  relationships: Array<{
    edge_id: string;
    relationship_type: string;
    direction: "in" | "out";
    label: string;
    fact?: string;
    other_node_id: string;
    other_label: string;
    other_node_type: string;
  }>;
  relationship_count?: number;
  relationship_sample_count?: number;
  relationship_sample_limit?: number;
  neighbor_count?: number;
  raw_relationship_count?: number;
  relationships_truncated?: boolean;
  provenance: Record<string, any>;
  temporal: Record<string, any>;
  cohorts: string[];
  native?: {
    temporal_facts?: Array<Record<string, any>>;
    supersession_chain?: Array<Record<string, any>>;
    lineage_edges?: Array<Record<string, any>>;
    decisions?: Array<Record<string, any>>;
    drift_signals?: Array<Record<string, any>>;
    totals?: Record<string, number>;
    samples?: Record<string, number>;
    caps?: Record<string, number>;
    feedback?: Record<string, any>;
  };
  raw?: Record<string, any>;
};

type GraphEdgeInspector = {
  edge: GraphExplorerEdge;
  source: {
    node_id: string;
    node_type: string;
    label: string;
    properties: Record<string, any>;
  };
  target: {
    node_id: string;
    node_type: string;
    label: string;
    properties: Record<string, any>;
  };
  provenance: Record<string, any>;
  temporal: Record<string, any>;
  native?: {
    temporal_facts?: Array<Record<string, any>>;
    lineage_edges?: Array<Record<string, any>>;
    feedback?: Record<string, any>;
  };
  raw?: Record<string, any>;
};

type GraphExplorerResponse = {
  nodes: GraphExplorerNode[];
  edges: GraphExplorerEdge[];
  stats: {
    total_nodes: number;
    total_edges: number;
    visible_nodes: number;
    visible_edges: number;
    seed_count: number;
    depth: number;
  };
  facets: {
    node_types: FacetItem[];
    relationship_types: FacetItem[];
    sources: FacetItem[];
    collections: FacetItem[];
  };
  search: {
    query: string;
    mode: string;
    matched_nodes: Array<{
      node_id: string;
      label: string;
      node_type?: string;
      score?: number;
      source?: string;
    }>;
  };
  inspector?: GraphInspector | null;
  edge_inspector?: GraphEdgeInspector | null;
  filters: {
    collection_id?: string | null;
    node_type?: string | null;
    edge_type?: string | null;
  };
};

type InspectorTab = "details" | "lineage" | "temporal" | "feedback" | "raw";
type Node360Tab = "facts" | "edges" | "episodes" | "decisions" | "lineage" | "raw";

type Props = {
  organizationId: string;
  initialCollectionId?: string;
  lockCollection?: boolean;
  embedded?: boolean;
  title?: string;
  subtitle?: string;
  collectionOptions?: Array<{
    value: string;
    label: string;
    count?: number;
    status?: string;
  }>;
  onCollectionChange?: (collectionId: string) => void;
};

const kindStyles: Record<string, { color: string; label: string; size: number }> = {
  source_record: { color: "#64748B", label: "Source record", size: 13 },
  person: { color: "#E45F1A", label: "Person", size: 17 },
  organization: { color: "#11845B", label: "Organization", size: 18 },
  database_table: { color: "#1F86CC", label: "Database table", size: 16 },
  llm_extraction: { color: "#8B5CF6", label: "LLM extraction", size: 14 },
  temporal_event: { color: "#B7791F", label: "Temporal event", size: 14 },
  decision: { color: "#DC2626", label: "Decision", size: 15 },
  forge_fact: { color: "#2563EB", label: "Forge fact", size: 12 },
  entity: { color: "#1F9D6A", label: "Entity", size: 14 },
};

const edgeStyles: Record<string, { color: string; size: number; type: "arrow" | "line" }> = {
  confirmed: { color: "rgba(228,95,26,0.62)", size: 1.65, type: "arrow" },
  inferred: { color: "rgba(37,99,235,0.58)", size: 1.35, type: "line" },
  temporal: { color: "rgba(183,121,31,0.60)", size: 1.25, type: "line" },
  lineage: { color: "rgba(17,132,91,0.68)", size: 1.45, type: "arrow" },
  decision: { color: "rgba(220,38,38,0.72)", size: 1.55, type: "arrow" },
};

const depthOptions = [
  { value: 1, label: "1 hop", limit: 140 },
  { value: 2, label: "2 hops", limit: 220 },
  { value: 3, label: "3 hops", limit: 320 },
];

const formatNumber = (value?: number) => {
  const n = Number(value || 0);
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
};

const sampleText = (shown: number, total: number, noun: string) => {
  if (total <= shown) return `${formatNumber(total)} ${noun}`;
  return `showing ${formatNumber(shown)} of ${formatNumber(total)} ${noun}`;
};

const cleanType = (value?: string | null) => {
  if (!value) return "Unknown";
  return value
    .replace(/^DatabaseTableNode_/, "")
    .replace(/Entity$/, "")
    .replace(/Node$/, "")
    .replace(/_/g, " ");
};

const truncateMiddle = (value: string, limit = 38) => {
  if (!value || value.length <= limit) return value;
  const keep = Math.floor((limit - 3) / 2);
  return `${value.slice(0, keep)}...${value.slice(-keep)}`;
};

const MASKED_FIELDS_PROP = "_contextd_masked_fields";
const MASKING_POLICY_PROP = "_contextd_masking_policy";
const INTERNAL_FACT_PROPS = new Set(["id", "entity_type", "collection_id", "source_type", MASKED_FIELDS_PROP, MASKING_POLICY_PROP]);

const propertyFactsSafe = (node?: GraphExplorerNode | null) => {
  if (!node?.properties) return [];
  const maskedFields = typeof node.properties[MASKED_FIELDS_PROP] === "object" && node.properties[MASKED_FIELDS_PROP]
    ? node.properties[MASKED_FIELDS_PROP]
    : {};
  return Object.entries(node.properties)
    .filter(([key, value]) => !INTERNAL_FACT_PROPS.has(key) && value !== null)
    .filter(([, value]) => value !== undefined && value !== "")
    .map(([key, value]) => ({
      key,
      value,
      masked: Boolean((maskedFields as Record<string, unknown>)[key]),
      mask: (maskedFields as Record<string, any>)[key],
    }));
};

const nodeColor = (node: GraphExplorerNode) => {
  return kindStyles[node.visual_kind]?.color || kindStyles.entity.color;
};

const nodeSize = (node: GraphExplorerNode) => {
  const base = kindStyles[node.visual_kind]?.size || kindStyles.entity.size;
  const degreeBoost = Math.min(Math.sqrt(node.degree || 0), 8);
  return base + degreeBoost;
};

const edgeColor = (edge: GraphExplorerEdge) => {
  return edgeStyles[edge.visual_kind]?.color || edgeStyles.confirmed.color;
};

const edgeSize = (edge: GraphExplorerEdge) => {
  return edgeStyles[edge.visual_kind]?.size || edgeStyles.confirmed.size;
};

const createNodeLabelRenderer = (isDark: boolean): NodeLabelDrawingFunction => (context, data, settings) => {
  if (!data.label) return;
  const size = Math.max(settings.labelSize, 11);
  const label = String(data.label);
  context.font = `${settings.labelWeight || 600} ${size}px ${settings.labelFont}`;
  const textWidth = context.measureText(label).width;
  const x = data.x + data.size + 7;
  const y = data.y + size / 3;
  context.fillStyle = isDark ? "rgba(5,5,5,0.74)" : "rgba(255,255,255,0.84)";
  context.fillRect(x - 4, y - size + 1, textWidth + 8, size + 5);
  context.fillStyle = isDark ? "#F8FAFC" : "#111827";
  context.fillText(label, x, y);
};

const seedLayout = (index: number, count: number, inner = false) => {
  const angle = -Math.PI / 2 + (Math.PI * 2 * index) / Math.max(count, 1);
  const radius = inner ? 5.8 : 10.4;
  return {
    x: Math.cos(angle) * radius,
    y: Math.sin(angle) * radius * 0.72,
  };
};

const applyLayout = (graph: Graph) => {
  const nodes = graph.nodes();
  const seedNodes = nodes.filter((node) => graph.getNodeAttribute(node, "isSeed"));
  const otherNodes = nodes.filter((node) => !graph.getNodeAttribute(node, "isSeed"));

  seedNodes.forEach((node, index) => {
    graph.mergeNodeAttributes(node, { ...seedLayout(index, seedNodes.length, true), zIndex: 7 });
  });
  otherNodes.forEach((node, index) => {
    graph.mergeNodeAttributes(node, { ...seedLayout(index, otherNodes.length), zIndex: 4 });
  });

  if (graph.order > 2) {
    const inferred = forceAtlas2.inferSettings(graph);
    forceAtlas2.assign(graph, {
      iterations: graph.order > 180 ? 48 : 72,
      getEdgeWeight: "layoutWeight",
      settings: {
        ...inferred,
        adjustSizes: true,
        barnesHutOptimize: graph.order > 120,
        edgeWeightInfluence: 0.72,
        gravity: 4.6,
        scalingRatio: graph.order > 180 ? 2.1 : 1.65,
        slowDown: 10,
        strongGravityMode: true,
      },
    });
  }
};

const copyText = async (value: string) => {
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    // Clipboard failures are non-critical; the id remains visible.
  }
};

export function KnowledgeGraphView({
  organizationId,
  initialCollectionId,
  lockCollection = false,
  embedded = false,
  title = "ContextD graph",
  subtitle,
  collectionOptions,
  onCollectionChange,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const sigmaRef = useRef<Sigma | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const [graphData, setGraphData] = useState<GraphExplorerResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [focusNodeId, setFocusNodeId] = useState<string | null>(null);
  const [collectionFilter, setCollectionFilter] = useState<string>(initialCollectionId || "");
  const [nodeTypeFilter, setNodeTypeFilter] = useState<string>("");
  const [edgeTypeFilter, setEdgeTypeFilter] = useState<string>("");
  const [depth, setDepth] = useState(1);
  const [command, setCommand] = useState("@graph show neighborhood");
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("details");
  const [node360Tab, setNode360Tab] = useState<Node360Tab>("facts");
  const [intelligence, setIntelligence] = useState<ContextIntelligenceSummary | null>(null);
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const collectionSelectOptions = useMemo(
    () => {
      const baseOptions = collectionOptions?.length
        ? collectionOptions
        : (graphData?.facets.collections || []).map((item) => ({
            value: item.value,
            label: item.value,
            count: item.count,
          }));
      const activeCollection = collectionFilter || initialCollectionId || "";
      if (!activeCollection || baseOptions.some((item) => item.value === activeCollection)) {
        return baseOptions;
      }
      return [
        {
          value: activeCollection,
          label: activeCollection,
          status: isLoading ? "loading" : undefined,
        },
        ...baseOptions,
      ];
    },
    [collectionFilter, collectionOptions, graphData?.facets.collections, initialCollectionId, isLoading]
  );

  const loadGraph = useCallback(async (forceRefresh = false) => {
    setIsLoading(true);
    setError(null);
    try {
      const visibleLimit = depthOptions.find((option) => option.value === depth)?.limit || 140;
      const params: Record<string, string | number> = {
        limit: visibleLimit,
        depth,
      };
      if (activeQuery.trim()) params.q = activeQuery.trim();
      if (collectionFilter) params.collection_id = collectionFilter;
      if (nodeTypeFilter) params.node_type = nodeTypeFilter;
      if (edgeTypeFilter) params.edge_type = edgeTypeFilter;
      if (focusNodeId) params.selected_node_id = focusNodeId;
      if (selectedEdgeId) params.selected_edge_id = selectedEdgeId;

      const response = await apiClient.get(
        `/graph/organizations/${organizationId}/explorer`,
        params,
        { cache: !forceRefresh }
      );
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `Graph explorer failed: ${response.status}`);
      }

      const data: GraphExplorerResponse = await response.json();
      setGraphData(data);
      setSelectedNodeId((current) => {
        if (current && data.nodes.some((node) => node.node_id === current)) return current;
        const inspectorNodeId = data.inspector?.node?.node_id;
        return inspectorNodeId && data.nodes.some((node) => node.node_id === inspectorNodeId) ? inspectorNodeId : null;
      });
      setSelectedEdgeId((current) =>
        current && (data.edges.some((edge) => edge.edge_id === current) || data.edge_inspector?.edge?.edge_id === current)
          ? current
          : null
      );
    } catch (err) {
      console.error("[KnowledgeGraphView] explorer error", err);
      setError(err instanceof Error ? err.message : "Failed to load ContextD graph");
    } finally {
      setIsLoading(false);
    }
  }, [activeQuery, collectionFilter, depth, edgeTypeFilter, focusNodeId, nodeTypeFilter, organizationId, selectedEdgeId]);

  useEffect(() => {
    loadGraph();
  }, [loadGraph]);

  useEffect(() => {
    const scopedCollection = collectionFilter || initialCollectionId || "";
    if (!scopedCollection) {
      setIntelligence(null);
      return;
    }
    let cancelled = false;
    fetchContextIntelligence(scopedCollection)
      .then((summary) => {
        if (!cancelled) setIntelligence(summary);
      })
      .catch(() => {
        if (!cancelled) setIntelligence(null);
      });
    return () => {
      cancelled = true;
    };
  }, [collectionFilter, initialCollectionId]);

  useEffect(() => {
    if (!initialCollectionId) return;
    if (collectionFilter === initialCollectionId) return;
    setFocusNodeId(null);
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
    setCollectionFilter(initialCollectionId);
  }, [collectionFilter, initialCollectionId]);

  const selectedNode = useMemo(() => {
    if (!graphData || !selectedNodeId) return null;
    return graphData.nodes.find((node) => node.node_id === selectedNodeId) || null;
  }, [graphData, selectedNodeId]);

  const selectedEdgeRows = useMemo(() => {
    if (!graphData || !selectedNodeId) return [];
    return graphData.edges.filter((edge) => edge.source === selectedNodeId || edge.target === selectedNodeId);
  }, [graphData, selectedNodeId]);

  const selectedEdge = useMemo(() => {
    if (!graphData || !selectedEdgeId) return null;
    return graphData.edges.find((edge) => edge.edge_id === selectedEdgeId) || graphData.edge_inspector?.edge || null;
  }, [graphData, selectedEdgeId]);

  const selectedEdgeInspector = useMemo<GraphEdgeInspector | null>(() => {
    if (!selectedEdge) return graphData?.edge_inspector || null;
    if (graphData?.edge_inspector?.edge?.edge_id === selectedEdge.edge_id) return graphData.edge_inspector;
    const source = graphData?.nodes.find((node) => node.node_id === selectedEdge.source_node_id);
    const target = graphData?.nodes.find((node) => node.node_id === selectedEdge.target_node_id);
    return {
      edge: selectedEdge,
      source: {
        node_id: selectedEdge.source_node_id,
        node_type: source?.node_type || "Unknown",
        label: source?.label || selectedEdge.source_node_id,
        properties: source?.properties || {},
      },
      target: {
        node_id: selectedEdge.target_node_id,
        node_type: target?.node_type || "Unknown",
        label: target?.label || selectedEdge.target_node_id,
        properties: target?.properties || {},
      },
      provenance: {
        source: selectedEdge.properties?.source || selectedEdge.properties?.source_type || "graph",
        collection_id: selectedEdge.properties?.collection_id,
        extraction: selectedEdge.properties?.extraction_method || selectedEdge.properties?.relation_type || "visible neighborhood",
      },
      temporal: {
        valid_at: selectedEdge.created_at,
        last_seen: selectedEdge.updated_at,
        current: true,
      },
      native: {},
      raw: { edge: selectedEdge },
    };
  }, [graphData, selectedEdge]);

  const selectedInspector = useMemo<GraphInspector | null>(() => {
    if (!selectedNode) return graphData?.inspector || null;
    if (graphData?.inspector?.node?.node_id === selectedNode.node_id) return graphData.inspector;

    const relCounts = new Map<string, number>();
    const neighborIds = new Set<string>();
    const relationships = selectedEdgeRows.slice(0, 24).map((edge) => {
      const otherId = edge.source === selectedNode.node_id ? edge.target : edge.source;
      const other = graphData?.nodes.find((node) => node.node_id === otherId);
      neighborIds.add(otherId);
      relCounts.set(edge.relationship_type, (relCounts.get(edge.relationship_type) || 0) + 1);
      return {
        edge_id: edge.edge_id,
        relationship_type: edge.relationship_type,
        direction: edge.source === selectedNode.node_id ? "out" as const : "in" as const,
        label: edge.label || edge.relationship_type,
        fact: edge.fact || "",
        other_node_id: otherId,
        other_label: other?.label || otherId,
        other_node_type: other?.node_type || "Unknown",
      };
    });

    return {
      node: selectedNode,
      facts: propertyFactsSafe(selectedNode),
      top_edges: Array.from(relCounts.entries()).map(([value, count]) => ({ value, count })),
      relationships,
      relationship_count: selectedEdgeRows.length,
      neighbor_count: neighborIds.size,
      raw_relationship_count: selectedEdgeRows.length,
      relationships_truncated: selectedEdgeRows.length > relationships.length,
      provenance: {
        source: selectedNode.source || selectedNode.properties?.source_type || "graph",
        collection_id: selectedNode.collection_id || selectedNode.properties?.collection_id,
        entity_type: selectedNode.properties?.entity_type || selectedNode.node_type,
        extraction: "ContextD graph neighborhood",
      },
      temporal: {
        valid_at: selectedNode.properties?.created_at_field || selectedNode.created_at,
        last_seen: selectedNode.properties?.modified_at || selectedNode.updated_at,
        current: true,
      },
      cohorts: [selectedNode.source, selectedNode.collection_id, selectedNode.visual_kind].filter(Boolean) as string[],
    };
  }, [graphData, selectedEdgeRows, selectedNode]);

  const activeNeighborIds = useMemo(() => {
    const set = new Set<string>();
    if (!selectedNodeId || !graphData) return set;
    graphData.edges.forEach((edge) => {
      if (edge.source === selectedNodeId) set.add(edge.target);
      if (edge.target === selectedNodeId) set.add(edge.source);
    });
    return set;
  }, [graphData, selectedNodeId]);

  const kindCounts = useMemo(() => {
    const counts = new Map<string, number>();
    graphData?.nodes.forEach((node) => counts.set(node.visual_kind, (counts.get(node.visual_kind) || 0) + 1));
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
  }, [graphData]);

  useEffect(() => {
    if (!containerRef.current || !graphData) return undefined;

    sigmaRef.current?.kill();
    sigmaRef.current = null;
    graphRef.current = null;

    const graph = new Graph({ allowSelfLoops: false, multi: true, type: "directed" });
    const seenNodes = new Set<string>();
    graphData.nodes.forEach((node) => {
      if (!node.node_id || seenNodes.has(node.node_id)) return;
      graph.addNode(node.node_id, {
        label: node.label.length > 24 ? `${node.label.slice(0, 21)}...` : node.label,
        fullLabel: node.label,
        nodeType: node.node_type,
        visualKind: node.visual_kind,
        color: nodeColor(node),
        size: nodeSize(node),
        isSeed: Boolean(node.is_seed),
        zIndex: node.is_seed ? 7 : 4,
        x: 0,
        y: 0,
      });
      seenNodes.add(node.node_id);
    });

    graphData.edges.forEach((edge, index) => {
      if (!seenNodes.has(edge.source) || !seenNodes.has(edge.target)) return;
      const edgeId = edge.edge_id || `${edge.source}->${edge.target}:${index}`;
      if (graph.hasEdge(edgeId)) return;
      const style = edgeStyles[edge.visual_kind] || edgeStyles.confirmed;
      graph.addDirectedEdgeWithKey(edgeId, edge.source, edge.target, {
        label: edge.label,
        color: edgeColor(edge),
        size: edgeSize(edge),
        type: style.type,
        layoutWeight: edge.visual_kind === "confirmed" ? 2 : 0.8,
        relationshipType: edge.relationship_type,
        zIndex: edge.visual_kind === "confirmed" ? 3 : 1,
      });
    });

    applyLayout(graph);

    const renderer = new Sigma(graph, containerRef.current, {
      allowInvalidContainer: true,
      autoCenter: true,
      autoRescale: true,
      defaultDrawNodeLabel: createNodeLabelRenderer(isDark),
      defaultEdgeColor: isDark ? "#475569" : "#94A3B8",
      defaultEdgeType: "arrow",
      defaultNodeColor: "#64748B",
      defaultNodeType: "circle",
      edgeProgramClasses: {
        arrow: ExplorerArrowProgram,
        line: EdgeRectangleProgram,
      },
      itemSizesReference: "screen",
      labelColor: { attribute: "labelColor" },
      labelDensity: 0.18,
      labelFont: "Inter, system-ui, sans-serif",
      labelGridCellSize: 64,
      labelRenderedSizeThreshold: 7,
      labelSize: 11,
      labelWeight: "600",
      minCameraRatio: 0.32,
      minEdgeThickness: 1,
      nodeProgramClasses: {
        circle: NodeCircleProgram,
      },
      renderEdgeLabels: false,
      renderLabels: true,
      stagePadding: 20,
      zIndex: true,
    });

    graphRef.current = graph;
    sigmaRef.current = renderer;
    renderer.getCamera().animatedReset({ duration: 260 });

    renderer.on("clickNode", ({ node }: { node: string }) => {
      setSelectedNodeId(node);
      setSelectedEdgeId(null);
      setFocusNodeId(node);
      setInspectorTab("details");
      setNode360Tab("facts");
      if (containerRef.current) containerRef.current.style.cursor = "grab";
    });
    renderer.on("clickEdge", ({ edge }: { edge: string }) => {
      setSelectedEdgeId(edge);
      setSelectedNodeId(null);
      setInspectorTab("details");
      if (containerRef.current) containerRef.current.style.cursor = "grab";
    });
    renderer.on("clickStage", () => {
      setSelectedNodeId(null);
      setSelectedEdgeId(null);
    });
    renderer.on("enterNode", () => {
      if (containerRef.current) containerRef.current.style.cursor = "pointer";
    });
    renderer.on("leaveNode", () => {
      if (containerRef.current) containerRef.current.style.cursor = "grab";
    });
    if (containerRef.current) containerRef.current.style.cursor = "grab";

    return () => {
      renderer.kill();
      sigmaRef.current = null;
      graphRef.current = null;
    };
  }, [graphData, isDark]);

  useEffect(() => {
    const renderer = sigmaRef.current;
    const graph = graphRef.current;
    if (!renderer || !graph) return;

    renderer.setSettings({
      nodeReducer: (node, data) => {
        const selected = selectedNodeId === node;
        const neighbor = activeNeighborIds.has(node);
        const seed = Boolean(data.isSeed);
        if (!selectedNodeId || selected || neighbor) {
          return {
            ...data,
            forceLabel: selected || seed || neighbor,
            highlighted: selected,
            label: selected ? data.fullLabel || data.label : data.label,
            labelColor: selected ? "#E45F1A" : isDark ? "#F8FAFC" : "#111827",
            size: selected ? Number(data.size || 1) + 8 : neighbor ? Number(data.size || 1) + 3 : data.size,
            zIndex: selected ? 20 : neighbor ? 12 : data.zIndex,
          };
        }
        return {
          ...data,
          color: isDark ? "rgba(71,85,105,0.38)" : "rgba(100,116,139,0.42)",
          label: "",
          size: Math.max(Number(data.size || 1) * 0.66, 5),
          zIndex: 0,
        };
      },
      edgeReducer: (edge, data) => {
        if (selectedEdgeId === edge) {
          return {
            ...data,
            color: "#E45F1A",
            size: Number(data.size || 1) + 2.8,
            zIndex: 18,
          };
        }
        if (!selectedNodeId) return data;
        const extremities = graph.extremities(edge);
        const touchesSelected = extremities.includes(selectedNodeId);
        if (touchesSelected) {
          return {
            ...data,
            color: data.relationshipType === "RELATED_TO" ? "#E45F1A" : data.color,
            size: Number(data.size || 1) + 1.8,
            zIndex: 12,
          };
        }
        return {
          ...data,
          color: isDark ? "rgba(71,85,105,0.18)" : "rgba(100,116,139,0.22)",
          size: 0.9,
          zIndex: 0,
        };
      },
    });
    renderer.refresh({ skipIndexation: true });
  }, [activeNeighborIds, isDark, selectedEdgeId, selectedNodeId]);

  const zoomIn = () => {
    const camera = sigmaRef.current?.getCamera();
    if (!camera) return;
    camera.animate({ ratio: camera.getState().ratio / 1.45 }, { duration: 180 });
  };

  const zoomOut = () => {
    const camera = sigmaRef.current?.getCamera();
    if (!camera) return;
    camera.animate({ ratio: camera.getState().ratio * 1.45 }, { duration: 180 });
  };

  const fitGraph = () => {
    sigmaRef.current?.getCamera().animatedReset({ duration: 220 });
  };

  const submitSearch = (event?: FormEvent) => {
    event?.preventDefault();
    setFocusNodeId(null);
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
    setActiveQuery(searchInput.trim());
  };

  const submitCommand = (event?: FormEvent) => {
    event?.preventDefault();
    const next = command.replace(/^@graph\s*/i, "").trim();
    if (!next) return;
    setFocusNodeId(null);
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
    setSearchInput(next);
    setActiveQuery(next);
  };

  const expandSelection = () => {
    if (!selectedNodeId) return;
    setFocusNodeId(selectedNodeId);
    setDepth((value) => Math.min(value + 1, 3));
  };

  const changeDepth = (nextDepth: number) => {
    const boundedDepth = Math.max(1, Math.min(nextDepth, 3));
    if (selectedNodeId) setFocusNodeId(selectedNodeId);
    setSelectedEdgeId(null);
    setDepth(boundedDepth);
  };

  const changeCollection = (collectionId: string) => {
    setFocusNodeId(null);
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
    setCollectionFilter(collectionId);
    onCollectionChange?.(collectionId);
  };

  const resetFilters = () => {
    setSearchInput("");
    setActiveQuery("");
    setFocusNodeId(null);
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
    setCollectionFilter(lockCollection ? initialCollectionId || "" : "");
    setNodeTypeFilter("");
    setEdgeTypeFilter("");
    setDepth(1);
  };

  const stats = graphData?.stats;
  const facets = graphData?.facets;
  const countLabel = (value?: number) => (isLoading && !graphData ? "..." : formatNumber(value));
  const intelligenceTotals = intelligence?.totals || {};
  const driftSeverity = String(intelligence?.drift?.severity || "clean");
  const decisionAuditCount =
    Number(intelligenceTotals.decisions || 0) + Number(intelligenceTotals.query_traces || 0);
  const contextLaneItems = [
    { label: "Temporal", value: formatNumber(Number(intelligenceTotals.temporal_facts || 0)), icon: Clock },
    { label: "Lineage", value: formatNumber(Number(intelligenceTotals.lineage_edges || 0)), icon: Route },
    { label: "Decisions", value: formatNumber(decisionAuditCount), icon: ShieldCheck },
    { label: "Drift", value: driftSeverity, icon: Activity },
  ];

  return (
    <div className={cn("flex min-h-0 flex-col overflow-hidden bg-background", embedded ? "h-full" : "h-full")}>
      <div className="shrink-0 border-b border-border bg-background px-3 py-1.5 md:px-4">
        <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-md border border-primary/20 bg-primary/10 text-primary">
                <Network className="h-4 w-4" />
              </div>
              <div>
                <h1 className="text-lg font-semibold tracking-tight text-foreground">{title}</h1>
                <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                  <span>{subtitle || "ContextD graph workspace"}</span>
                  <span className="h-1 w-1 rounded-full bg-border" />
                  <span>{activeQuery ? "search neighborhood" : "central neighborhood"}</span>
                  <span className="h-1 w-1 rounded-full bg-border" />
                  <span className="font-mono text-foreground">{countLabel(stats?.visible_nodes)} visible nodes</span>
                </div>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-1.5 sm:flex sm:flex-wrap sm:items-center sm:justify-end">
            {[
              { label: "Nodes", value: formatNumber(stats?.total_nodes), icon: Boxes },
              { label: "Links", value: formatNumber(stats?.total_edges), icon: GitFork },
              { label: "Matches", value: formatNumber(stats?.seed_count), icon: Sparkles },
            ].map((item) => {
              const Icon = item.icon;
              return (
                <div key={item.label} className="min-w-0 rounded-md border border-border bg-card px-2 py-1 sm:min-w-[86px]">
                  <div className="flex items-center justify-between gap-2 text-[9px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                    <span className="truncate">{item.label}</span>
                    <Icon className="h-3.5 w-3.5 text-primary" />
                  </div>
                  <div className="font-mono text-sm font-semibold text-foreground">{isLoading && !graphData ? "..." : item.value}</div>
                </div>
              );
            })}
            <Button
              variant="outline"
              size="sm"
              className="col-span-3 h-7 gap-1.5 px-2.5 text-xs sm:col-span-1"
              onClick={() => {
                void loadGraph(true);
              }}
              disabled={isLoading}
            >
              {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              <span className="sm:inline">Refresh</span>
            </Button>
          </div>
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {contextLaneItems.map((item) => {
            const Icon = item.icon;
            return (
              <span
                key={item.label}
                className={cn(
                  "inline-flex h-5 items-center gap-1 rounded-md border px-1.5 text-[10px]",
                  item.label === "Drift" && item.value !== "clean"
                    ? "border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300"
                    : "border-border bg-background text-muted-foreground"
                )}
              >
                <Icon className="h-3 w-3 text-primary" />
                <span>{item.label}</span>
                <span className="font-mono text-foreground">{item.value}</span>
              </span>
            );
          })}
        </div>
      </div>

      <div className="grid min-h-0 flex-1 overflow-hidden xl:grid-cols-[minmax(0,1fr)_318px]">
        <main className="flex min-w-0 flex-col overflow-hidden border-r border-border">
          <div className="shrink-0 border-b border-border bg-card/60 px-3 py-1.5 md:px-4">
            <div className="grid gap-1.5 xl:grid-cols-[minmax(260px,0.95fr)_minmax(0,1.65fr)] xl:items-center">
              <form onSubmit={submitSearch} className="min-w-0">
                <div className="relative min-w-0 flex-1">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    value={searchInput}
                    onChange={(event) => setSearchInput(event.target.value)}
                    placeholder="Search entities, facts, or source records"
                    className="h-8 rounded-md border-border bg-background pl-9 font-mono text-sm"
                  />
                </div>
              </form>

              <div className="grid min-w-0 grid-cols-2 gap-1.5 md:grid-cols-[minmax(190px,1.15fr)_minmax(150px,0.85fr)_minmax(130px,0.72fr)]">
                {lockCollection ? (
                  <span className="inline-flex h-8 min-w-0 items-center rounded-md border border-primary/25 bg-primary/10 px-2.5 font-mono text-xs font-medium text-primary">
                    <Database className="mr-2 h-4 w-4 shrink-0" />
                    <span className="truncate">{collectionFilter || initialCollectionId || "Database scoped"}</span>
                  </span>
                ) : (
                  <select
                    value={collectionFilter}
                    onChange={(event) => {
                      changeCollection(event.target.value);
                    }}
                    className="h-8 min-w-0 rounded-md border border-border bg-background px-2.5 text-sm text-foreground"
                  >
                    <option value="" disabled={collectionSelectOptions.length > 0}>
                      {collectionSelectOptions.length ? "Select database" : "No databases"}
                    </option>
                    {collectionSelectOptions.map((item) => (
                      <option key={item.value} value={item.value}>
                        {item.label}
                        {typeof item.count === "number" ? ` (${formatNumber(item.count)})` : ""}
                        {item.status ? ` - ${item.status}` : ""}
                      </option>
                    ))}
                  </select>
                )}
                <select
                  value={nodeTypeFilter}
                  onChange={(event) => {
                    setFocusNodeId(null);
                    setSelectedNodeId(null);
                    setSelectedEdgeId(null);
                    setNodeTypeFilter(event.target.value);
                  }}
                  className="h-8 min-w-0 rounded-md border border-border bg-background px-2.5 text-sm text-foreground"
                >
                  <option value="">All entity types</option>
                  {(facets?.node_types || []).map((item) => (
                    <option key={item.value} value={item.value}>
                      {cleanType(item.value)}
                    </option>
                  ))}
                </select>
                <select
                  value={edgeTypeFilter}
                  onChange={(event) => {
                    setSelectedEdgeId(null);
                    setEdgeTypeFilter(event.target.value);
                  }}
                  className="h-8 min-w-0 rounded-md border border-border bg-background px-2.5 text-sm text-foreground"
                >
                  <option value="">All links</option>
                  {(facets?.relationship_types || []).map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.value.replace(/_/g, " ")}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              {(facets?.sources || []).slice(0, 6).map((item) => (
                <span key={item.value} className="rounded-md border border-border bg-background px-2 py-0.5 text-[11px] text-muted-foreground">
                  <span className="font-medium text-foreground">{item.value}</span>
                  <span className="ml-1 font-mono">{formatNumber(item.count)}</span>
                </span>
              ))}
              {activeQuery && (
                <span className="rounded-md border border-primary/25 bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
                  query: {activeQuery}
                </span>
              )}
              <div className="inline-flex h-7 items-center gap-0.5 rounded-md border border-border bg-background p-0.5">
                {depthOptions.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => changeDepth(option.value)}
                    className={cn(
                      "h-6 whitespace-nowrap rounded px-2 text-[11px] font-medium transition",
                      depth === option.value
                        ? "bg-primary text-primary-foreground"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground"
                    )}
                    aria-pressed={depth === option.value}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={resetFilters}>
                Reset
              </Button>
              <form
                onSubmit={submitCommand}
                className="ml-auto flex h-8 min-w-[280px] max-w-[520px] flex-1 basis-[360px] items-center gap-1.5 rounded-md border border-border bg-background px-1.5 shadow-sm"
              >
                <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded border border-primary/20 bg-primary/10 text-primary">
                  <Sparkles className="h-3.5 w-3.5" />
                </div>
                <Input
                  value={command}
                  onChange={(event) => setCommand(event.target.value)}
                  className="h-7 min-w-0 flex-1 border-0 bg-transparent px-1 font-mono text-xs text-foreground shadow-none placeholder:text-muted-foreground selection:bg-primary/20 focus-visible:ring-0"
                  placeholder="@graph show neighborhood"
                />
                <Button type="submit" size="sm" className="h-6 gap-1 bg-primary px-2.5 text-xs text-primary-foreground hover:bg-primary/90">
                  Run
                  <ArrowRight className="h-3.5 w-3.5" />
                </Button>
              </form>
            </div>
          </div>

          <section className="relative min-h-0 flex-1 overflow-hidden bg-background">
            <div className="absolute inset-0 opacity-[0.42] [background-image:linear-gradient(to_right,hsl(var(--border))_1px,transparent_1px),linear-gradient(to_bottom,hsl(var(--border))_1px,transparent_1px)] [background-size:36px_36px]" />
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_48%_42%,rgba(228,95,26,0.10),transparent_32%),radial-gradient(circle_at_66%_38%,rgba(31,134,204,0.10),transparent_30%),radial-gradient(circle_at_42%_62%,rgba(17,132,91,0.09),transparent_28%)]" />

            <aside className="absolute left-3 top-3 z-20 flex w-10 flex-col items-center gap-0.5 rounded-md border border-border bg-card/95 p-1 shadow-sm backdrop-blur">
              {[
                { icon: MousePointer, label: "Select" },
                { icon: Hand, label: "Pan" },
                { icon: Route, label: "Path" },
                { icon: Filter, label: "Filter" },
              ].map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.label}
                    type="button"
                    title={item.label}
                    className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground"
                  >
                    <Icon className="h-4 w-4" />
                  </button>
                );
              })}
              <div className="my-1 h-px w-6 bg-border" />
              <button type="button" title="Zoom in" onClick={zoomIn} className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground">
                <ZoomIn className="h-4 w-4" />
              </button>
              <button type="button" title="Zoom out" onClick={zoomOut} className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground">
                <ZoomOut className="h-4 w-4" />
              </button>
              <button type="button" title="Fit graph" onClick={fitGraph} className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground">
                <Maximize2 className="h-4 w-4" />
              </button>
            </aside>

            <div className="absolute left-16 top-3 z-20 flex max-w-[calc(100%-90px)] flex-wrap items-center gap-1.5 rounded-md border border-border bg-card/95 px-2 py-1 text-[11px] text-muted-foreground shadow-sm backdrop-blur">
              {kindCounts.slice(0, 7).map(([kind, count]) => (
                <span key={kind} className="flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: kindStyles[kind]?.color || kindStyles.entity.color }} />
                  <span>{kindStyles[kind]?.label || cleanType(kind)}</span>
                  <span className="font-mono text-foreground">{formatNumber(count)}</span>
                </span>
              ))}
            </div>

            <div ref={containerRef} className="relative h-full w-full" role="img" aria-label="ContextD knowledge graph explorer" />

            {isLoading && (
              <div className="absolute inset-0 z-30 flex items-center justify-center bg-background/70 backdrop-blur-sm">
                <div className="rounded-md border border-border bg-card px-4 py-3 shadow-sm">
                  <div className="flex items-center gap-3 text-sm text-foreground">
                    <Loader2 className="h-4 w-4 animate-spin text-primary" />
                    Loading ContextD graph
                  </div>
                </div>
              </div>
            )}

            {error && (
              <div className="absolute inset-0 z-30 flex items-center justify-center bg-background/75 p-8">
                <div className="max-w-lg rounded-md border border-destructive/25 bg-card p-5 text-center shadow-sm">
                  <Network className="mx-auto mb-3 h-8 w-8 text-destructive" />
                  <h3 className="text-base font-semibold text-foreground">ContextD graph could not load</h3>
                  <p className="mt-2 text-sm text-muted-foreground">{error}</p>
                  <Button className="mt-4 gap-2" onClick={loadGraph}>
                    <RefreshCw className="h-4 w-4" />
                    Try again
                  </Button>
                </div>
              </div>
            )}

            {!isLoading && !error && graphData?.nodes.length === 0 && (
              <div className="absolute inset-0 z-20 flex items-center justify-center">
                <div className="max-w-md rounded-md border border-border bg-card p-5 text-center shadow-sm">
                  <Database className="mx-auto mb-3 h-9 w-9 text-primary" />
                  <h3 className="text-base font-semibold text-foreground">No ContextD graph nodes in this scope</h3>
                  <p className="mt-2 text-sm text-muted-foreground">
                    Run a source sync or clear filters to inspect another ContextD neighborhood.
                  </p>
                </div>
              </div>
            )}

            <div className="absolute bottom-3 left-3 z-20 rounded-md border border-border bg-card/95 px-2.5 py-1.5 font-mono text-[11px] text-muted-foreground shadow-sm backdrop-blur">
              <span className="text-foreground">{countLabel(stats?.visible_nodes)}</span> of {countLabel(stats?.total_nodes)} nodes
              <span className="mx-2 text-border">/</span>
              <span className="text-foreground">{countLabel(stats?.visible_edges)}</span> of {countLabel(stats?.total_edges)} links
            </div>
          </section>

          <Node360Panel
            inspector={selectedInspector?.node ? selectedInspector : null}
            activeTab={node360Tab}
            onTabChange={setNode360Tab}
            depth={depth}
            driftSeverity={driftSeverity}
            onExpand={expandSelection}
            onAskGraph={(nodeId) => setCommand(`@graph show 360 ${nodeId}`)}
            onSelectNode={(nodeId) => {
              setSelectedEdgeId(null);
              setSelectedNodeId(nodeId);
              setFocusNodeId(nodeId);
              setInspectorTab("details");
              setNode360Tab("facts");
            }}
          />
        </main>

        <aside className="hidden min-w-0 flex-col overflow-hidden bg-card xl:flex">
          <div className="shrink-0 border-b border-border px-3 py-2.5">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-primary" />
                  <h2 className="text-base font-semibold text-foreground">Inspector</h2>
                </div>
                <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
                  {selectedEdgeInspector?.edge
                    ? "Edge context, temporal state, and provenance"
                    : selectedInspector?.node
                      ? "Entity context, relationships, and provenance"
                      : "Select a ContextD node or link"}
                </p>
              </div>
              {(selectedNodeId || selectedEdgeId) && (
                <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => {
                  setSelectedNodeId(null);
                  setSelectedEdgeId(null);
                }}>
                  <CircleDot className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {selectedEdgeInspector?.edge ? (
              <div className="space-y-3 p-3">
                <div className="rounded-md border border-border bg-background p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="rounded border border-primary/25 bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-primary">
                          link
                        </span>
                        <span className="rounded border border-border bg-muted px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                          {selectedEdgeInspector.edge.relationship_type}
                        </span>
                      </div>
                      <h3 className="mt-2 text-base font-semibold leading-tight text-foreground">
                        {selectedEdgeInspector.source.label} <ArrowRight className="inline h-4 w-4 text-primary" /> {selectedEdgeInspector.target.label}
                      </h3>
                      <button
                        type="button"
                        onClick={() => copyText(selectedEdgeInspector.edge.edge_id)}
                        className="mt-2 flex max-w-full items-center gap-1.5 text-left font-mono text-xs text-muted-foreground hover:text-foreground"
                      >
                        <span className="truncate">{truncateMiddle(selectedEdgeInspector.edge.edge_id, 44)}</span>
                        <Copy className="h-3.5 w-3.5 shrink-0" />
                      </button>
                    </div>
                    <div className="rounded-md border border-green-500/20 bg-green-500/10 px-2 py-1 text-right">
                      <div className="font-mono text-base font-semibold text-green-700 dark:text-green-300">
                        {selectedEdgeInspector.native?.feedback?.confidence ?? "1.0"}
                      </div>
                      <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">confidence</div>
                    </div>
                  </div>
                </div>

                <InspectorTabs activeTab={inspectorTab} onChange={setInspectorTab} />

                {inspectorTab === "details" && (
                  <>
                    <Panel title="Context link" icon={GitFork}>
                      <dl className="grid grid-cols-[96px_1fr] gap-y-2 text-sm">
                        <FragmentRow label="Source" value={`${selectedEdgeInspector.source.label} · ${cleanType(selectedEdgeInspector.source.node_type)}`} />
                        <FragmentRow label="Target" value={`${selectedEdgeInspector.target.label} · ${cleanType(selectedEdgeInspector.target.node_type)}`} />
                        <FragmentRow label="Type" value={selectedEdgeInspector.edge.relationship_type} />
                        <FragmentRow label="Fact" value={selectedEdgeInspector.edge.fact || selectedEdgeInspector.edge.label} />
                      </dl>
                    </Panel>
                    <Panel title="Provenance" icon={ShieldCheck}>
                      <dl className="grid grid-cols-[110px_1fr] gap-y-2 text-sm">
                        {Object.entries(selectedEdgeInspector.provenance || {}).map(([key, value]) => (
                          <FragmentRow key={key} label={key} value={value} />
                        ))}
                      </dl>
                    </Panel>
                  </>
                )}

                {inspectorTab === "lineage" && (
                  <Panel title="Lineage" icon={Route}>
                    <NativeList
                      empty="No lineage record is attached to this link yet."
                      items={selectedEdgeInspector.native?.lineage_edges || []}
                      render={(item) => (
                        <>
                          <div className="truncate font-medium text-foreground">{item.relationship_type || "lineage"}</div>
                          <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
                            {item.from_ref} → {item.to_ref}
                          </div>
                        </>
                      )}
                    />
                  </Panel>
                )}

                {inspectorTab === "temporal" && (
                  <Panel title="Temporal" icon={Clock}>
                    <NativeList
                      empty="No bitemporal fact row is attached to this link yet."
                      items={selectedEdgeInspector.native?.temporal_facts || []}
                      render={(item) => (
                        <>
                          <div className="flex items-center justify-between gap-2">
                            <span className="truncate font-medium text-foreground">{item.predicate || selectedEdgeInspector.edge.relationship_type}</span>
                            <span className="font-mono text-[10px] text-muted-foreground">{item.status}</span>
                          </div>
                          <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">{item.valid_at || item.created_at}</div>
                        </>
                      )}
                    />
                  </Panel>
                )}

                {inspectorTab === "feedback" && (
                  <Panel title="Quality signals" icon={Activity}>
                    <ConfidenceRows feedback={selectedEdgeInspector.native?.feedback || {}} />
                  </Panel>
                )}

                {inspectorTab === "raw" && (
                  <Panel title="Raw link packet" icon={Database}>
                    <JsonBlock value={selectedEdgeInspector.raw || selectedEdgeInspector.edge} />
                  </Panel>
                )}

                <div className="grid grid-cols-2 gap-2">
                  <Button variant="outline" className="gap-2" onClick={() => {
                    setSelectedEdgeId(null);
                    setSelectedNodeId(selectedEdgeInspector.source.node_id);
                    setFocusNodeId(selectedEdgeInspector.source.node_id);
                  }}>
                    <GitFork className="h-4 w-4" />
                    Source
                  </Button>
                  <Button className="gap-2 bg-primary text-primary-foreground hover:bg-primary/90" onClick={() => {
                    setSelectedEdgeId(null);
                    setSelectedNodeId(selectedEdgeInspector.target.node_id);
                    setFocusNodeId(selectedEdgeInspector.target.node_id);
                  }}>
                    <ArrowRight className="h-4 w-4" />
                    Target
                  </Button>
                </div>
              </div>
            ) : selectedInspector?.node ? (
              <div className="space-y-3 p-3">
                <div className="rounded-md border border-border bg-background p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="h-3 w-3 rounded-full" style={{ backgroundColor: nodeColor(selectedInspector.node) }} />
                        <span className="rounded border border-border bg-muted px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                          {cleanType(selectedInspector.node.node_type)}
                        </span>
                      </div>
                      <h3 className="mt-2 text-lg font-semibold leading-tight text-foreground">{selectedInspector.node.label}</h3>
                      <button
                        type="button"
                        onClick={() => copyText(selectedInspector.node.node_id)}
                        className="mt-2 flex max-w-full items-center gap-1.5 text-left font-mono text-xs text-muted-foreground hover:text-foreground"
                      >
                        <span className="truncate">{truncateMiddle(selectedInspector.node.node_id, 44)}</span>
                        <Copy className="h-3.5 w-3.5 shrink-0" />
                      </button>
                    </div>
                    <div className="rounded-md border border-primary/20 bg-primary/10 px-2 py-1 text-right">
                      <div className="font-mono text-base font-semibold text-primary">{formatNumber(selectedInspector.node.degree)}</div>
                      <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">links</div>
                    </div>
                  </div>

                  <div className="mt-3 grid grid-cols-2 gap-2">
                    <div className="rounded-md border border-border bg-card px-2.5 py-2">
                      <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">Source</div>
                      <div className="mt-1 truncate font-mono text-sm text-foreground">{selectedInspector.provenance?.source || "graph"}</div>
                    </div>
                    <div className="rounded-md border border-border bg-card px-2.5 py-2">
                      <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">Current</div>
                      <div className="mt-1 flex items-center gap-1.5 text-sm font-medium text-green-600">
                        <ShieldCheck className="h-3.5 w-3.5" />
                        active
                      </div>
                    </div>
                  </div>
                </div>

                <InspectorTabs activeTab={inspectorTab} onChange={setInspectorTab} />

                {inspectorTab === "details" && (
                  <>
                <div className="grid grid-cols-3 gap-1.5">
                  {[
                    { label: "Facts", value: formatNumber(selectedInspector.facts_total ?? selectedInspector.facts?.length), icon: Layers3 },
                    { label: "Links", value: formatNumber(selectedInspector.relationship_count ?? selectedInspector.relationships?.length), icon: GitFork },
                    { label: "Depth", value: String(depth), icon: Activity },
                  ].map((item) => {
                    const Icon = item.icon;
                    return (
                      <div key={item.label} className="rounded-md border border-border bg-background px-2.5 py-2">
                        <Icon className="mb-1.5 h-3.5 w-3.5 text-primary" />
                        <div className="font-mono text-base font-semibold text-foreground">{item.value}</div>
                        <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">{item.label}</div>
                      </div>
                    );
                  })}
                </div>

                <Panel title="Key facts" icon={Boxes}>
                  <div className="divide-y divide-border">
                    {(selectedInspector.facts?.length ? selectedInspector.facts : propertyFactsSafe(selectedInspector.node)).slice(0, 8).map((fact) => (
                      <div key={fact.key} className="grid grid-cols-[112px_1fr] gap-3 py-2 text-sm">
                        <dt className="truncate font-mono text-xs text-muted-foreground">{fact.key}</dt>
                        <dd className="min-w-0">
                          <FactValue fact={fact} />
                        </dd>
                      </div>
                    ))}
                    {selectedInspector.facts?.length === 0 && (
                      <div className="py-3 text-sm text-muted-foreground">No top-line facts are exposed for this node yet.</div>
                    )}
                  </div>
                </Panel>

                <Panel title="Linked context" icon={GitFork}>
                  <div className="space-y-2">
                    {selectedInspector.relationships.slice(0, 10).map((rel) => (
                      <button
                        key={rel.edge_id}
                        type="button"
                        onClick={() => {
                          setSelectedEdgeId(null);
                          setSelectedNodeId(rel.other_node_id);
                          setFocusNodeId(rel.other_node_id);
                          setInspectorTab("details");
                        }}
                        className="w-full rounded-md border border-border bg-background px-3 py-2 text-left transition hover:border-primary/30 hover:bg-primary/5"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate text-sm font-medium text-foreground">{rel.other_label}</span>
                          <span className="shrink-0 rounded border border-border bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{rel.direction}</span>
                        </div>
                        <div className="mt-1 flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground">
                          <span className="truncate">{rel.label}</span>
                          <ArrowRight className="h-3 w-3 shrink-0 text-primary" />
                          <span className="truncate">{cleanType(rel.other_node_type)}</span>
                        </div>
                      </button>
                    ))}
                    {selectedInspector.relationships.length === 0 && (
                      <div className="rounded-md border border-dashed border-border p-3 text-sm text-muted-foreground">
                        No visible relationships in this neighborhood. Expand the node to ask ContextD for a wider neighborhood.
                      </div>
                    )}
                  </div>
                </Panel>

                <Panel title="Provenance" icon={ShieldCheck}>
                  <dl className="grid grid-cols-[110px_1fr] gap-y-2 text-sm">
                    {Object.entries(selectedInspector.provenance || {}).map(([key, value]) => (
                      <FragmentRow key={key} label={key} value={value} />
                    ))}
                  </dl>
                </Panel>

                <Panel title="Temporal" icon={Clock}>
                  <dl className="grid grid-cols-[110px_1fr] gap-y-2 text-sm">
                    {Object.entries(selectedInspector.temporal || {}).map(([key, value]) => (
                      <FragmentRow key={key} label={key} value={value} />
                    ))}
                  </dl>
                </Panel>

                <Panel title="Context signals" icon={Sparkles}>
                  <dl className="grid grid-cols-[110px_1fr] gap-y-2 text-sm">
                    <FragmentRow label="Temporal" value={`${formatNumber(Number(intelligenceTotals.temporal_facts || 0))} facts`} />
                    <FragmentRow label="Lineage" value={`${formatNumber(Number(intelligenceTotals.lineage_edges || 0))} links`} />
                    <FragmentRow
                      label="Decisions"
                      value={`${formatNumber(Number(selectedInspector.native?.totals?.decisions ?? decisionAuditCount))} audit rows`}
                    />
                    <FragmentRow label="Drift" value={driftSeverity} />
                  </dl>
                </Panel>

                <div className="grid grid-cols-2 gap-2">
                  <Button variant="outline" className="gap-2" onClick={expandSelection} disabled={!selectedNodeId}>
                    <Route className="h-4 w-4" />
                    Expand
                  </Button>
                  <Button className="gap-2 bg-primary text-primary-foreground hover:bg-primary/90" onClick={() => setCommand(`@graph show neighborhood ${selectedInspector.node.node_id}`)}>
                    <Sparkles className="h-4 w-4" />
                    Ask ContextD
                  </Button>
                </div>
                  </>
                )}

                {inspectorTab === "lineage" && (
                  <>
                    <Panel title="Lineage records" icon={Route}>
                      <NativeList
                        empty="No source or graph-event lineage is attached to this node yet."
                        items={selectedInspector.native?.lineage_edges || []}
                        render={(item) => (
                          <>
                            <div className="flex items-center justify-between gap-2">
                              <span className="truncate font-medium text-foreground">{item.relationship_type || "lineage"}</span>
                              <span className="font-mono text-[10px] text-muted-foreground">{item.confidence ?? "1.0"}</span>
                            </div>
                            <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
                              {item.from_ref} → {item.to_ref}
                            </div>
                          </>
                        )}
                      />
                    </Panel>
                    <Panel title="Provenance" icon={ShieldCheck}>
                      <dl className="grid grid-cols-[110px_1fr] gap-y-2 text-sm">
                        {Object.entries(selectedInspector.provenance || {}).map(([key, value]) => (
                          <FragmentRow key={key} label={key} value={value} />
                        ))}
                      </dl>
                    </Panel>
                  </>
                )}

                {inspectorTab === "temporal" && (
                  <>
                    <Panel title="Supersession chain" icon={Clock}>
                      <NativeList
                        empty="No superseded versions have been recorded for this node yet."
                        items={selectedInspector.native?.supersession_chain || []}
                        render={(item) => (
                          <>
                            <div className="flex items-center justify-between gap-2">
                              <span className="truncate font-medium text-foreground">{item.predicate || item.primitive_type}</span>
                              <span className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">{item.status}</span>
                            </div>
                            <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
                              valid {item.valid_at || "-"} · expired {item.expired_at || "current"}
                            </div>
                          </>
                        )}
                      />
                    </Panel>
                    <Panel title="Current facts" icon={Layers3}>
                      <NativeList
                        empty="No current bitemporal fact rows are attached to this node."
                        items={selectedInspector.native?.temporal_facts || []}
                        render={(item) => (
                          <>
                            <div className="truncate font-medium text-foreground">{item.predicate || item.primitive_type}</div>
                            <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">{item.primitive_ref}</div>
                          </>
                        )}
                      />
                    </Panel>
                  </>
                )}

                {inspectorTab === "feedback" && (
                  <>
                    <Panel title="Quality signals" icon={Activity}>
                      <ConfidenceRows feedback={selectedInspector.native?.feedback || {}} />
                    </Panel>
                    <Panel title="Decisions and drift" icon={ShieldCheck}>
                      <div className="grid grid-cols-2 gap-2 text-xs">
                        <div className="rounded-md border border-border bg-card p-2">
                          <div className="text-muted-foreground">Decisions</div>
                          <div className="mt-1 font-mono text-base font-semibold text-foreground">
                            {formatNumber(Number(selectedInspector.native?.totals?.decisions ?? selectedInspector.native?.decisions?.length ?? 0))}
                          </div>
                        </div>
                        <div className="rounded-md border border-border bg-card p-2">
                          <div className="text-muted-foreground">Drift</div>
                          <div className="mt-1 font-mono text-base font-semibold text-foreground">
                            {formatNumber(Number(selectedInspector.native?.totals?.drift_signals ?? selectedInspector.native?.drift_signals?.length ?? 0))}
                          </div>
                        </div>
                      </div>
                    </Panel>
                  </>
                )}

                {inspectorTab === "raw" && (
                  <Panel title="Raw node packet" icon={Database}>
                    <JsonBlock value={selectedInspector.raw || { node: selectedInspector.node, properties: selectedInspector.node.properties }} />
                  </Panel>
                )}
              </div>
            ) : (
              <div className="space-y-3 p-3">
                <div className="rounded-md border border-dashed border-border bg-background p-4 text-center">
                  <Network className="mx-auto mb-3 h-9 w-9 text-primary" />
                  <h3 className="text-base font-semibold text-foreground">Select a ContextD node or link</h3>
                  <p className="mt-2 text-sm text-muted-foreground">
                    The inspector will show facts, lineage, temporal state, feedback, raw payloads, and provenance.
                  </p>
                </div>
                <Panel title="Matched context" icon={Search}>
                  <div className="space-y-2">
                    {(graphData?.search?.matched_nodes || []).slice(0, 8).map((match) => (
                      <button
                        key={match.node_id}
                        type="button"
                        onClick={() => {
                          setSelectedEdgeId(null);
                          setSelectedNodeId(match.node_id);
                          setFocusNodeId(match.node_id);
                          setInspectorTab("details");
                        }}
                        className="w-full rounded-md border border-border bg-background px-3 py-2 text-left transition hover:border-primary/30 hover:bg-primary/5"
                      >
                        <div className="truncate text-sm font-medium text-foreground">{match.label || match.node_id}</div>
                        <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">{cleanType(match.node_type)}</div>
                      </button>
                    ))}
                    {(graphData?.search?.matched_nodes || []).length === 0 && (
                      <div className="py-2 text-sm text-muted-foreground">Search the graph to seed a neighborhood.</div>
                    )}
                  </div>
                </Panel>
                <Panel title="Context signals" icon={Sparkles}>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    {contextLaneItems.map((item) => (
                      <div key={item.label} className="rounded-md border border-border bg-background p-2">
                        <div className="text-muted-foreground">{item.label}</div>
                        <div className="mt-1 font-mono text-sm text-foreground">{item.value}</div>
                      </div>
                    ))}
                  </div>
                </Panel>
              </div>
            )}
          </div>

          <div className="shrink-0 border-t border-border p-3">
            <Button variant="outline" size="sm" className="h-9 w-full gap-2" onClick={() => window.print()}>
              <Download className="h-4 w-4" />
              Export view
            </Button>
          </div>
        </aside>
      </div>
    </div>
  );
}

function Node360Panel({
  inspector,
  activeTab,
  onTabChange,
  depth,
  driftSeverity,
  onExpand,
  onAskGraph,
  onSelectNode,
}: {
  inspector: GraphInspector | null;
  activeTab: Node360Tab;
  onTabChange: (tab: Node360Tab) => void;
  depth: number;
  driftSeverity: string;
  onExpand: () => void;
  onAskGraph: (nodeId: string) => void;
  onSelectNode: (nodeId: string) => void;
}) {
  if (!inspector?.node) {
    return (
    <section className="shrink-0 border-t border-border bg-card px-3 py-2">
      <div className="flex items-center justify-between gap-3 rounded-md border border-dashed border-border bg-background px-4 py-3">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-primary/20 bg-primary/10 text-primary">
              <CircleDot className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-foreground">Context 360</h3>
              <p className="truncate text-xs text-muted-foreground">
                Select any node to review facts, linked data, temporal episodes, decisions, lineage, and the raw context packet.
              </p>
            </div>
          </div>
          <span className="hidden rounded-md border border-border bg-card px-2.5 py-1 font-mono text-xs text-muted-foreground md:inline-flex">
            waiting for selection
          </span>
        </div>
      </section>
    );
  }

  const node = inspector.node;
  const facts = inspector.facts?.length ? inspector.facts : propertyFactsSafe(node);
  const nativeFacts = inspector.native?.temporal_facts || [];
  const supersession = inspector.native?.supersession_chain || [];
  const lineage = inspector.native?.lineage_edges || [];
  const decisions = inspector.native?.decisions || [];
  const nativeTotals = inspector.native?.totals || {};
  const nativeSamples = inspector.native?.samples || {};
  const factsTotal = Number(inspector.facts_total ?? facts.length);
  const factsSampleCount = Number(inspector.facts_sample_count ?? facts.length);
  const relationshipCount = inspector.relationship_count ?? inspector.relationships.length;
  const relationshipSampleCount = inspector.relationship_sample_count ?? inspector.relationships.length;
  const neighborCount =
    inspector.neighbor_count ??
    new Set(inspector.relationships.map((relationship) => relationship.other_node_id)).size;
  const rawRelationshipCount = inspector.raw_relationship_count ?? relationshipCount;
  const source = String(inspector.provenance?.source || node.source || node.properties?.source_type || "graph");
  const extraction = String(inspector.provenance?.extraction || node.properties?.extraction_method || "ContextD graph");
  const confidence = percentLabel(inspector.native?.feedback?.confidence ?? node.properties?.confidence, "86%");
  const validAt = String(inspector.temporal?.valid_at || node.created_at || "current");
  const episodes = [
    ...nativeFacts.map((item) => ({ ...item, _episode: "fact" })),
    ...supersession.map((item) => ({ ...item, _episode: "superseded" })),
  ];
  const episodeTotal =
    Number(nativeTotals.current_temporal_facts ?? nativeTotals.temporal_facts ?? nativeFacts.length) +
    Number(nativeTotals.supersession_chain ?? supersession.length);
  const episodeSampleCount =
    Number(nativeSamples.temporal_facts ?? nativeFacts.length) +
    Number(nativeSamples.supersession_chain ?? supersession.length);
  const decisionRows = decisions.map((item) => ({ ...item, _kind: "decision" }));
  const decisionTotal = Number(nativeTotals.decisions ?? decisionRows.length);
  const decisionSampleCount = Number(nativeSamples.decisions ?? decisionRows.length);
  const lineageTotal = Number(nativeTotals.lineage_edges ?? lineage.length);
  const lineageSampleCount = Number(nativeSamples.lineage_edges ?? lineage.length);
  const tabs: Array<{ id: Node360Tab; label: string; count?: number }> = [
    { id: "facts", label: "Facts", count: factsTotal },
    { id: "edges", label: "Links", count: relationshipCount },
    { id: "episodes", label: "Episodes", count: episodeTotal },
    { id: "decisions", label: "Decisions", count: decisionTotal },
    { id: "lineage", label: "Lineage", count: lineageTotal },
    { id: "raw", label: "Raw" },
  ];

  return (
    <section className="h-[clamp(220px,27vh,310px)] shrink-0 overflow-hidden border-t border-border bg-card">
      <div className="flex h-full min-h-0 flex-col">
        <div className="grid shrink-0 gap-1.5 border-b border-border px-3 py-1.5 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-center">
          <div className="flex min-w-0 items-center gap-2.5">
            <div
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border text-white shadow-sm"
              style={{ backgroundColor: nodeColor(node), borderColor: `${nodeColor(node)}44` }}
            >
              <CircleDot className="h-3.5 w-3.5" />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <h3 className="truncate text-sm font-semibold text-foreground">{node.label}</h3>
                <span className="rounded border border-border bg-background px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  {cleanType(node.node_type)}
                </span>
                <span className="rounded border border-primary/25 bg-primary/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-primary">
                  360
                </span>
              </div>
              <div className="mt-0.5 flex min-w-0 flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                <span className="max-w-[260px] truncate font-mono">{truncateMiddle(node.node_id, 46)}</span>
                <span className="h-1 w-1 rounded-full bg-border" />
                <span className="truncate">{source}</span>
                <span className="h-1 w-1 rounded-full bg-border" />
                <span>depth {depth}</span>
              </div>
            </div>
          </div>

          <div className="flex min-w-0 flex-wrap items-center gap-1 text-xs xl:justify-end">
            {[
              { label: "facts", value: factsTotal },
              { label: "links", value: relationshipCount },
              { label: "neighbors", value: neighborCount },
              { label: "drift", value: driftSeverity },
            ].map((item) => (
              <div key={item.label} className="inline-flex h-6 items-center gap-1.5 rounded-md border border-border bg-background px-2">
                <span className="font-mono text-xs font-semibold text-foreground">{String(item.value)}</span>
                <span className="text-[9px] uppercase tracking-[0.12em] text-muted-foreground">{item.label}</span>
              </div>
            ))}
            <Button
              variant="outline"
              size="sm"
              className="hidden h-6 gap-1.5 px-2.5 text-xs xl:inline-flex"
              onClick={onExpand}
              disabled={depth >= 3}
            >
              <Route className="h-3.5 w-3.5" />
              {depth >= 3 ? "Max depth" : `Expand to ${depth + 1} hops`}
            </Button>
            <Button size="sm" className="hidden h-6 gap-1.5 bg-primary px-2.5 text-xs text-primary-foreground hover:bg-primary/90 xl:inline-flex" onClick={() => onAskGraph(node.node_id)}>
              <Sparkles className="h-3.5 w-3.5" />
              Ask 360
            </Button>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1 overflow-x-auto border-b border-border bg-background px-3 py-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => onTabChange(tab.id)}
              className={cn(
                "inline-flex h-6 shrink-0 items-center gap-1.5 rounded px-2 text-[11px] font-medium transition",
                activeTab === tab.id
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              {tab.label}
              {tab.count !== undefined && (
                <span className="inline-flex h-4 min-w-4 items-center justify-center rounded border border-border bg-card px-1 font-mono text-[9px] text-foreground">
                  {formatNumber(tab.count)}
                </span>
              )}
            </button>
          ))}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden overscroll-contain p-2.5 pb-5 [scrollbar-gutter:stable] [&::-webkit-scrollbar]:w-2 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-border [&::-webkit-scrollbar-track]:bg-transparent">
          {activeTab === "facts" && (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-background px-3 py-1.5">
                <div>
                  <div className="text-sm font-semibold text-foreground">Current facts</div>
                  <div className="text-xs text-muted-foreground">
                    {sampleText(factsSampleCount, factsTotal, "fields")} · {sampleText(nativeFacts.length, Number(nativeTotals.current_temporal_facts ?? nativeFacts.length), "temporal rows")}
                  </div>
                </div>
                <span className="rounded border border-primary/20 bg-primary/10 px-2 py-1 font-mono text-xs text-primary">
                  {confidence} confidence
                </span>
              </div>

              <div className="grid min-h-full gap-2 xl:grid-cols-[minmax(0,1fr)_260px]">
                <div className="overflow-hidden rounded-md border border-border bg-background">
                  <div className="grid grid-cols-[1.1fr_1.5fr_0.9fr_1fr_0.7fr_0.9fr] gap-3 border-b border-border bg-muted/40 px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                    <span>Predicate</span>
                    <span>Value</span>
                    <span>Source</span>
                    <span>Extraction</span>
                    <span>Confidence</span>
                    <span>Valid at</span>
                  </div>
                  <div className="divide-y divide-border">
                    {facts.map((fact, index) => {
                      const temporalFact = nativeFacts[index];
                      return (
                        <div
                          key={`${fact.key}-${index}`}
                          className="grid grid-cols-[1.1fr_1.5fr_0.9fr_1fr_0.7fr_0.9fr] gap-3 px-3 py-2 text-xs"
                        >
                          <span className="truncate font-mono text-muted-foreground">{fact.key}</span>
                          <span className="min-w-0 truncate font-medium text-foreground">
                            <FactValue fact={fact} />
                          </span>
                          <span className="truncate text-muted-foreground">{String(temporalFact?.source || source)}</span>
                          <span className="truncate text-muted-foreground">{String(temporalFact?.extraction || extraction)}</span>
                          <span className="font-mono text-primary">{percentLabel(temporalFact?.confidence, confidence)}</span>
                          <span className="truncate font-mono text-muted-foreground">{String(temporalFact?.valid_at || validAt)}</span>
                        </div>
                      );
                    })}
                    {facts.length === 0 && (
                      <div className="px-3 py-5 text-sm text-muted-foreground">No facts are attached to this node yet.</div>
                    )}
                  </div>
                </div>

                <div className="grid min-h-0 gap-3">
                  <Mini360Card title={`Supersession · ${sampleText(supersession.length, Number(nativeTotals.supersession_chain ?? supersession.length), "rows")}`} icon={Clock}>
                    <CompactRecordList
                      items={supersession}
                      empty="No superseded facts"
                      render={(item) => (
                        <>
                          <div className="truncate font-medium text-foreground">{displayScalar(item.predicate || item.primitive_type || "version")}</div>
                          <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
                            {displayScalar(item.valid_at || item.created_at)} → {displayScalar(item.expired_at || "current")}
                          </div>
                        </>
                      )}
                    />
                  </Mini360Card>
                  <Mini360Card title={`Nearest links · ${sampleText(Math.min(relationshipSampleCount, 8), relationshipCount, "links")}`} icon={GitFork}>
                    <CompactRecordList
                      items={inspector.relationships}
                      empty="No linked data in this scope"
                      render={(item) => (
                        <button
                          type="button"
                          onClick={() => onSelectNode(item.other_node_id)}
                          className="block w-full text-left"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="truncate font-medium text-foreground">{item.other_label}</span>
                            <span className="shrink-0 rounded border border-border bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{item.direction}</span>
                          </div>
                          <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">{item.relationship_type}</div>
                        </button>
                      )}
                    />
                  </Mini360Card>
                </div>
              </div>
            </div>
          )}

          {activeTab === "edges" && (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-background px-3 py-2">
                <div>
                  <div className="text-sm font-semibold text-foreground">Linked data</div>
                  <div className="text-xs text-muted-foreground">
                    {sampleText(relationshipSampleCount, relationshipCount, "logical links")}
                    {rawRelationshipCount > relationshipCount
                      ? ` · ${formatNumber(rawRelationshipCount)} raw rows deduped by relation identity`
                      : " · one row per ContextD link"}
                  </div>
                </div>
                {inspector.relationships_truncated && (
                  <span className="rounded border border-amber-500/25 bg-amber-500/10 px-2 py-1 font-mono text-xs text-amber-700 dark:text-amber-300">
                    sampled
                  </span>
                )}
              </div>
              <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                {inspector.relationships.map((rel) => (
                  <button
                    key={rel.edge_id}
                    type="button"
                    onClick={() => onSelectNode(rel.other_node_id)}
                    className="rounded-md border border-border bg-background p-3 text-left transition hover:border-primary/30 hover:bg-primary/5"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-semibold text-foreground">{rel.other_label}</span>
                      <span className="rounded border border-border bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{rel.direction}</span>
                    </div>
                    <div className="mt-2 flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
                      <GitFork className="h-3.5 w-3.5 shrink-0 text-primary" />
                      <span className="truncate font-mono">{rel.relationship_type}</span>
                      <ArrowRight className="h-3.5 w-3.5 shrink-0" />
                      <span className="truncate">{cleanType(rel.other_node_type)}</span>
                    </div>
                    {rel.fact && <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">{rel.fact}</p>}
                  </button>
                ))}
                {inspector.relationships.length === 0 && (
                  <div className="rounded-md border border-dashed border-border bg-background p-5 text-sm text-muted-foreground">
                    No links are visible for this node. Expand the neighborhood to pull more linked data.
                  </div>
                )}
              </div>
            </div>
          )}

          {activeTab === "episodes" && (
            <div className="space-y-2">
              <SectionSummary
                title="Temporal episodes"
                detail={`${sampleText(episodeSampleCount, episodeTotal, "episodes")} · current facts plus supersession history`}
              />
              <CompactTimeline
                items={episodes}
                total={episodeTotal}
                empty="No temporal episodes are attached to this node yet."
                renderTitle={(item) => displayScalar(item.predicate || item.primitive_type || item._episode)}
                renderMeta={(item) =>
                  `${displayScalar(item.valid_at || item.created_at || "valid now")} · ${displayScalar(item.status || item._episode)}`
                }
              />
            </div>
          )}

          {activeTab === "decisions" && (
            <DecisionAuditList items={decisionRows} total={decisionTotal} sampleCount={decisionSampleCount} nodeId={node.node_id} />
          )}

          {activeTab === "lineage" && (
            <div className="space-y-2">
              <SectionSummary
                title="Lineage"
                detail={`${sampleText(lineageSampleCount, lineageTotal, "lineage edges")} · source records, graph events, and derived context`}
              />
              <LineageList
                items={lineage}
                total={lineageTotal}
                empty="No lineage links are attached to this node yet."
              />
            </div>
          )}

          {activeTab === "raw" && (
            <div className="space-y-2">
              <SectionSummary
                title="Raw context packet"
                detail="Exact inspector payload, including sample metadata used by this view."
              />
              <JsonBlock
                value={{
                  summary: {
                    facts_total: factsTotal,
                    facts_sample_count: factsSampleCount,
                    relationship_count: relationshipCount,
                    relationship_sample_count: relationshipSampleCount,
                    raw_relationship_count: rawRelationshipCount,
                    native_totals: nativeTotals,
                    native_samples: nativeSamples,
                  },
                  ...(inspector.raw || { node, facts, relationships: inspector.relationships, provenance: inspector.provenance, native: inspector.native }),
                }}
              />
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function Panel({
  title,
  icon: Icon,
  children,
  className,
}: {
  title: string;
  icon: any;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("overflow-hidden rounded-md border border-border bg-background", className)}>
      <div className="flex items-center gap-2 border-b border-border bg-card px-2.5 py-1.5">
        <Icon className="h-3.5 w-3.5 text-primary" />
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      </div>
      <div className="p-2.5">{children}</div>
    </section>
  );
}

function Mini360Card({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon: any;
  children: ReactNode;
}) {
  return (
    <section className="min-h-0 overflow-hidden rounded-md border border-border bg-background">
      <div className="flex items-center gap-2 border-b border-border bg-card px-2.5 py-1.5">
        <Icon className="h-3.5 w-3.5 text-primary" />
        <h4 className="text-xs font-semibold text-foreground">{title}</h4>
      </div>
      <div className="max-h-[104px] overflow-auto p-2">{children}</div>
    </section>
  );
}

function SectionSummary({
  title,
  detail,
}: {
  title: string;
  detail: string;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-background px-3 py-1.5">
      <div>
        <div className="text-sm font-semibold text-foreground">{title}</div>
        <div className="text-xs text-muted-foreground">{detail}</div>
      </div>
    </div>
  );
}

function CompactRecordList({
  items,
  empty,
  render,
}: {
  items: Array<Record<string, any>>;
  empty: string;
  render: (item: Record<string, any>) => ReactNode;
}) {
  if (!items.length) {
    return <div className="rounded-md border border-dashed border-border p-3 text-xs text-muted-foreground">{empty}</div>;
  }
  return (
    <div className="space-y-1.5">
      {items.slice(0, 8).map((item, index) => (
        <div key={`${String(item.id || item.edge_id || item.primitive_ref || "record")}-${index}`} className="rounded-md border border-border bg-card px-2.5 py-2 text-xs">
          {render(item)}
        </div>
      ))}
    </div>
  );
}

function CompactTimeline({
  items,
  total,
  empty,
  renderTitle,
  renderMeta,
}: {
  items: Array<Record<string, any>>;
  total?: number;
  empty: string;
  renderTitle: (item: Record<string, any>) => string;
  renderMeta: (item: Record<string, any>) => string;
}) {
  if (!items.length) {
    return <div className="rounded-md border border-dashed border-border bg-background p-5 text-sm text-muted-foreground">{empty}</div>;
  }
  return (
    <div className="space-y-2">
      {Number(total || 0) > items.length && (
        <div className="rounded-md border border-border bg-background px-3 py-2 text-xs text-muted-foreground">
          {sampleText(items.length, Number(total || 0), "records")} are shown in this panel.
        </div>
      )}
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
      {items.slice(0, 18).map((item, index) => (
        <div key={`${String(item.id || item.primitive_ref || item.from_ref || "timeline")}-${index}`} className="rounded-md border border-border bg-background p-3">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 shrink-0 rounded-full bg-primary" />
            <span className="truncate text-sm font-semibold text-foreground">{renderTitle(item)}</span>
          </div>
          <div className="mt-2 truncate font-mono text-xs text-muted-foreground">{renderMeta(item)}</div>
        </div>
      ))}
      </div>
    </div>
  );
}

function LineageList({
  items,
  total,
  empty,
}: {
  items: Array<Record<string, any>>;
  total: number;
  empty: string;
}) {
  if (!items.length) {
    return <div className="rounded-md border border-dashed border-border bg-background p-5 text-sm text-muted-foreground">{empty}</div>;
  }
  return (
    <div className="space-y-2">
      {total > items.length && (
        <div className="rounded-md border border-border bg-background px-3 py-2 text-xs text-muted-foreground">
          {sampleText(items.length, total, "lineage records")} are shown. The raw packet keeps the sample metadata.
        </div>
      )}
      <div className="grid gap-2 lg:grid-cols-2">
        {items.map((item, index) => {
          const evidence = item.evidence && typeof item.evidence === "object" ? item.evidence : {};
          return (
            <section key={`${String(item.id || item.from_ref || "lineage")}-${index}`} className="rounded-md border border-border bg-background p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="h-2 w-2 shrink-0 rounded-full bg-primary" />
                    <span className="truncate text-sm font-semibold text-foreground">{displayScalar(item.relationship_type || "lineage")}</span>
                  </div>
                  <div className="mt-2 grid gap-1 font-mono text-[11px] text-muted-foreground">
                    <span className="truncate">{displayScalar(item.from_ref || "source")}</span>
                    <span className="text-primary">→</span>
                    <span className="truncate">{displayScalar(item.to_ref || "target")}</span>
                  </div>
                </div>
                <span className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                  {percentLabel(item.confidence, "100%")}
                </span>
              </div>
              {(item.valid_at || item.created_at || evidence.source_field || evidence.table) && (
                <div className="mt-3 grid gap-1 border-t border-border pt-2 text-xs text-muted-foreground">
                  {item.valid_at && <span className="truncate">valid {displayScalar(item.valid_at)}</span>}
                  {item.created_at && <span className="truncate">recorded {displayScalar(item.created_at)}</span>}
                  {(evidence.source_field || evidence.table) && (
                    <span className="truncate">
                      {displayScalar(evidence.table || "source")} · {displayScalar(evidence.source_field || "field")}
                    </span>
                  )}
                </div>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}

function traceDuration(value: any) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return null;
  if (numeric >= 1000) return `${(numeric / 1000).toFixed(1)}s`;
  return `${Math.round(numeric)}ms`;
}

function traceStepSummary(step: Record<string, any>) {
  const output = step.output && typeof step.output === "object" ? step.output : {};
  const outputCount = Number(step.output_count);
  const selected = [
    output.seed_count !== undefined ? `${formatNumber(Number(output.seed_count))} seeds` : null,
    output.node_count !== undefined ? `${formatNumber(Number(output.node_count))} nodes` : null,
    output.edge_count !== undefined ? `${formatNumber(Number(output.edge_count))} links` : null,
    output.current_facts !== undefined ? `${formatNumber(Number(output.current_facts))} facts` : null,
    output.decision_count !== undefined ? `${formatNumber(Number(output.decision_count))} audits` : null,
    output.severity ? `drift ${output.severity}` : null,
    output.token_estimate !== undefined ? `${formatNumber(Number(output.token_estimate))} tokens` : null,
  ].filter(Boolean);
  if (selected.length) return selected.join(" · ");
  if (Number.isFinite(outputCount) && outputCount > 0) return `${formatNumber(outputCount)} output`;
  return displayScalar(step.status || "recorded");
}

function DecisionAuditList({
  items,
  total,
  sampleCount,
  nodeId,
}: {
  items: Array<Record<string, any>>;
  total: number;
  sampleCount: number;
  nodeId: string;
}) {
  if (!items.length) {
    return (
      <div className="rounded-md border border-dashed border-border bg-background p-5 text-sm text-muted-foreground">
        No decision traces are attached to this node yet. Run a query that retrieves this node, then the response trace will appear here.
      </div>
    );
  }

  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-background px-3 py-2">
        <div>
          <div className="text-sm font-semibold text-foreground">Decision trace for this node</div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            {sampleText(sampleCount, total, "query audits and first-class decisions")} that referenced{" "}
            <span className="font-mono text-foreground">{truncateMiddle(nodeId, 42)}</span>.
          </div>
        </div>
        <span className="rounded-md border border-primary/20 bg-primary/10 px-2.5 py-1 font-mono text-xs text-primary">
          {formatNumber(total)} audit{total === 1 ? "" : "s"}
        </span>
      </div>

      <div className="grid gap-2 xl:grid-cols-2">
        {items.map((item, index) => {
          const isQueryTrace = item.trace_kind === "query_decision_trace";
          const steps = Array.isArray(item.steps) ? item.steps : [];
          const latency = traceDuration(item.latency_ms);
          const drift = displayScalar(item.drift_severity || item.metrics?.drift_severity || "clean");
          return (
            <section
              key={`${String(item.id || item.decision_key || "decision")}-${index}`}
              className="overflow-hidden rounded-md border border-border bg-background"
            >
              <div className="border-b border-border bg-muted/25 px-3 py-2">
                <div className="flex min-w-0 items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="h-2 w-2 shrink-0 rounded-full bg-primary" />
                      <h4 className="truncate text-sm font-semibold text-foreground">
                        {isQueryTrace ? "Query decision trace" : displayScalar(item.decision_type || "Decision audit")}
                      </h4>
                      <span className="rounded border border-border bg-card px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                        {displayScalar(item.outcome || item.status || "recorded")}
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                      {displayScalar(item.query || item.subject || item.justification || "ContextD decision audit")}
                    </p>
                  </div>
                  <span className="shrink-0 rounded-md border border-primary/20 bg-primary/10 px-2 py-1 font-mono text-[10px] text-primary">
                    {displayScalar(item.recipe || item.policy_ref || "audit")}
                  </span>
                </div>
              </div>

              <div className="space-y-2 p-3">
                <div className="grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
                  {[
                    { label: "route", value: item.path_used || item.justification || item.policy_ref },
                    { label: "latency", value: latency || "-" },
                    { label: "nodes", value: formatNumber(Number(item.retrieved_node_count || item.affected_refs?.length || 0)) },
                    { label: "drift", value: drift },
                  ].map((meta) => (
                    <div key={meta.label} className="rounded-md border border-border bg-card px-2.5 py-2">
                      <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">{meta.label}</div>
                      <div className="mt-1 truncate font-mono text-xs font-semibold text-foreground">{displayScalar(meta.value)}</div>
                    </div>
                  ))}
                </div>

                {steps.length ? (
                  <div className="rounded-md border border-border">
                    <div className="border-b border-border px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                      Trace steps
                    </div>
                    <div className="divide-y divide-border">
                      {steps.map((step: Record<string, any>, stepIndex: number) => (
                        <div key={`${displayScalar(step.key)}-${stepIndex}`} className="grid gap-2 px-2.5 py-2 text-xs md:grid-cols-[140px_minmax(0,1fr)_64px]">
                          <div className="flex min-w-0 items-center gap-1.5">
                            <span className={cn(
                              "h-2 w-2 shrink-0 rounded-full",
                              step.status === "warn" ? "bg-amber-500" : step.status === "skipped" ? "bg-muted-foreground/45" : "bg-emerald-500"
                            )} />
                            <span className="truncate font-medium text-foreground">{displayScalar(step.label)}</span>
                          </div>
                          <span className="truncate font-mono text-[11px] text-muted-foreground">{traceStepSummary(step)}</span>
                          <span className="text-right font-mono text-[11px] text-muted-foreground">{displayScalar(step.status)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="rounded-md border border-border bg-card px-3 py-2 text-xs text-muted-foreground">
                    {displayScalar(item.justification || item.reason || "Audit was recorded without a step packet.")}
                  </div>
                )}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}

function InspectorTabs({
  activeTab,
  onChange,
}: {
  activeTab: InspectorTab;
  onChange: (tab: InspectorTab) => void;
}) {
  const tabs: Array<{ id: InspectorTab; label: string }> = [
    { id: "details", label: "Details" },
    { id: "lineage", label: "Lineage" },
    { id: "temporal", label: "Temporal" },
    { id: "feedback", label: "Quality" },
    { id: "raw", label: "Raw" },
  ];
  return (
    <div className="flex flex-wrap gap-1 rounded-md border border-border bg-background p-1">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          onClick={() => onChange(tab.id)}
          className={cn(
            "rounded px-2 py-1 text-[11px] font-medium transition",
            activeTab === tab.id
              ? "bg-primary/10 text-primary"
              : "text-muted-foreground hover:bg-muted hover:text-foreground"
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

function NativeList({
  items,
  empty,
  render,
}: {
  items: Array<Record<string, any>>;
  empty: string;
  render: (item: Record<string, any>) => ReactNode;
}) {
  if (!items.length) {
    return <div className="rounded-md border border-dashed border-border p-3 text-sm text-muted-foreground">{empty}</div>;
  }
  return (
    <div className="space-y-2">
      {items.slice(0, 12).map((item, index) => (
        <div key={`${String(item.id || item.edge_id || "native")}-${index}`} className="rounded-md border border-border bg-card px-3 py-2 text-sm">
          {render(item)}
        </div>
      ))}
    </div>
  );
}

function ConfidenceRows({ feedback }: { feedback: Record<string, any> }) {
  const confidence = Number(feedback.confidence ?? 0);
  const weight = Number(feedback.feedback_weight ?? 0);
  const rows = [
    { label: "Confidence", value: feedback.confidence ?? "-", percent: confidence ? Math.round(confidence * 100) : 0 },
    { label: "Memory weight", value: feedback.feedback_weight ?? "-", percent: weight ? Math.min(100, Math.round(weight * 100)) : 0 },
    { label: "Facts", value: feedback.facts ?? 0, percent: 0 },
    { label: "Lineage links", value: feedback.lineage_edges ?? 0, percent: 0 },
  ];
  return (
    <div className="space-y-3">
      {rows.map((row) => (
        <div key={row.label}>
          <div className="mb-1 flex items-center justify-between gap-2 text-xs">
            <span className="text-muted-foreground">{row.label}</span>
            <span className="font-mono text-foreground">{String(row.value)}</span>
          </div>
          {row.percent > 0 && (
            <div className="h-1.5 rounded-full bg-muted">
              <div className="h-1.5 rounded-full bg-primary" style={{ width: `${row.percent}%` }} />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function JsonBlock({ value }: { value: any }) {
  return (
    <pre className="max-h-[380px] overflow-auto rounded-md bg-zinc-950 p-3 font-mono text-[11px] leading-relaxed text-zinc-100" style={{ color: '#F8FAFC' }}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function displayScalar(value: any) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function FactValue({ fact }: { fact: GraphFact }) {
  const label = displayScalar(fact.value);
  if (!fact.masked) {
    return <span className="inline-block max-w-full truncate align-bottom text-foreground">{label}</span>;
  }
  const maskLabels = Array.isArray(fact.mask?.labels) ? fact.mask.labels.join(", ") : "PII";
  return (
    <span className="inline-flex max-w-full items-center gap-1.5 truncate rounded-md border border-amber-500/25 bg-amber-500/10 px-1.5 py-0.5 text-amber-700 dark:text-amber-200">
      <span className="truncate font-mono">{label}</span>
      <span className="shrink-0 rounded border border-amber-500/25 bg-background/70 px-1 text-[10px] uppercase tracking-[0.12em]">
        masked {maskLabels}
      </span>
    </span>
  );
}

function percentLabel(value: any, fallback = "-") {
  const numeric = Number(value);
  if (Number.isFinite(numeric) && numeric > 0) {
    const percent = numeric <= 1 ? numeric * 100 : numeric;
    return `${Math.round(percent)}%`;
  }
  return fallback;
}

function FragmentRow({ label, value }: { label: string; value: any }) {
  return (
    <>
      <dt className="truncate font-mono text-xs text-muted-foreground">{label}</dt>
      <dd className="min-w-0 truncate text-foreground">
        {typeof value === "object" ? JSON.stringify(value) : String(value ?? "-")}
      </dd>
    </>
  );
}
