/**
 * ContextGraph - Graph visualization for chat context
 * 
 * Displays the knowledge graph subgraph that was retrieved
 * to provide context for an AI response. Uses Sigma.js for
 * interactive visualization with the same styling as KnowledgeGraphView.
 */
import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import Graph from 'graphology';
import Sigma from 'sigma';
import { 
  ZoomIn, ZoomOut, RefreshCw, Loader2, 
  Maximize2, Network
} from 'lucide-react';
import { useTheme } from '@/lib/theme-provider';
import { 
  getNodeColor, 
  getNodeSize, 
  getHighlightColors,
} from '@/lib/graph-colors';

// Subgraph data structure from backend
interface SubgraphNode {
  id: string;
  labels: string[];
  properties: Record<string, unknown>;
}

interface SubgraphEdge {
  id?: string;
  source: string;
  target: string;
  type: string;
  properties?: Record<string, unknown>;
}

interface SubgraphData {
  nodes: SubgraphNode[];
  edges: SubgraphEdge[];
  stats?: {
    nodes_count?: number;
    edges_count?: number;
  };
}

interface ContextGraphProps {
  subgraphJson: string | null;
  height?: string;
  onExpand?: () => void;
  className?: string;
}

export function ContextGraph({ 
  subgraphJson, 
  height = '200px',
  onExpand,
  className = ''
}: ContextGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const sigmaRef = useRef<Sigma | null>(null);
  const graphRef = useRef<Graph | null>(null);
  
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [graphLoaded, setGraphLoaded] = useState(false);
  const [nodeCount, setNodeCount] = useState(0);
  const [edgeCount, setEdgeCount] = useState(0);
  
  // Highlighting state - same as KnowledgeGraphView
  const [selectedNode, setSelectedNode] = useState<SubgraphNode | null>(null);
  const [highlightedNode, setHighlightedNode] = useState<string | null>(null);
  const [highlightedNeighbors, setHighlightedNeighbors] = useState<Set<string>>(new Set());
  
  // Theme
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === 'dark';
  const highlightColors = useMemo(() => getHighlightColors(isDark), [isDark]);

  // Helper to get display label from node
  const getNodeDisplayLabel = useCallback((node: SubgraphNode): string => {
    const props = node.properties as Record<string, unknown>;
    return String(
      props?.name || 
      props?.title || 
      props?.label || 
      node.id?.substring(0, 15) ||
      'Unknown'
    ).substring(0, 25) + (String(props?.name || props?.title || '').length > 25 ? '...' : '');
  }, []);

  // Apply circular layout
  const layoutGraph = useCallback((graph: Graph) => {
    const nodes = graph.nodes();
    const count = nodes.length;
    
    if (count === 0) return;
    
    nodes.forEach((node, index) => {
      const angle = (2 * Math.PI * index) / count;
      const radius = 80 + Math.random() * 40;
      graph.setNodeAttribute(node, 'x', Math.cos(angle) * radius);
      graph.setNodeAttribute(node, 'y', Math.sin(angle) * radius);
    });
  }, []);

  // Load graph data
  const loadGraph = useCallback(() => {
    if (!graphRef.current || !sigmaRef.current || !subgraphJson) return;
    
    setIsLoading(true);
    setError(null);

    try {
      let data: SubgraphData;
      try {
        data = JSON.parse(subgraphJson);
      } catch {
        setError('Invalid graph data format');
        setIsLoading(false);
        return;
      }

      const graph = graphRef.current;
      graph.clear();

      if (!data.nodes || data.nodes.length === 0) {
        setGraphLoaded(false);
        setIsLoading(false);
        setNodeCount(0);
        setEdgeCount(0);
        return;
      }

      const addedNodeIds = new Set<string>();

      // Add nodes (skip nodes with undefined/null IDs)
      data.nodes.forEach((node) => {
        // Skip nodes without valid IDs
        if (!node.id || node.id === 'undefined' || node.id === 'null') {
          return;
        }
        
        // Skip if node already added
        if (addedNodeIds.has(node.id)) {
          return;
        }
        
        const nodeType = node.labels?.[0] || 'Unknown';
        const color = getNodeColor(nodeType);
        const size = getNodeSize(nodeType);
        const displayLabel = getNodeDisplayLabel(node);

        try {
          graph.addNode(node.id, {
            x: Math.random() * 100 - 50,
            y: Math.random() * 100 - 50,
            size,
            color,
            label: displayLabel,
            nodeType,
            nodeData: node,
          });
          addedNodeIds.add(node.id);
        } catch (err) {
          // Skip duplicate nodes silently
          console.warn(`Skipping duplicate node: ${node.id}`);
        }
      });

      // Add edges
      let edgeIdx = 0;
      data.edges?.forEach((edge) => {
        if (addedNodeIds.has(edge.source) && addedNodeIds.has(edge.target)) {
          const edgeId = edge.id || `edge-${edgeIdx++}`;
          if (!graph.hasEdge(edgeId) && !graph.hasEdge(edge.source, edge.target)) {
            try {
              graph.addEdge(edge.source, edge.target, {
                id: edgeId,
                edgeType: edge.type,
                label: edge.type?.replace(/_/g, ' '),
                color: '#9ca3af',
                size: 1.2,
              });
            } catch {
              // Skip duplicate edges
            }
          }
        }
      });

      // Apply layout
      layoutGraph(graph);
      
      // Update counts
      setNodeCount(graph.order);
      setEdgeCount(graph.size);

      // Refresh sigma
      sigmaRef.current?.refresh();
      setGraphLoaded(graph.order > 0);
      setIsLoading(false);

    } catch (err) {
      console.error('Error loading graph:', err);
      setError('Failed to load graph');
      setIsLoading(false);
    }
  }, [subgraphJson, getNodeDisplayLabel, layoutGraph]);

  // Initialize Sigma - same pattern as KnowledgeGraphView
  useEffect(() => {
    if (sigmaRef.current) return;
    if (!containerRef.current) return;

    const container = containerRef.current;

    // Create new graph
    const graph = new Graph();
    graphRef.current = graph;

    // Create Sigma instance with same settings as KnowledgeGraphView
    try {
      const sigma = new Sigma(graph, container, {
        renderLabels: true,
        renderEdgeLabels: false,
        labelRenderedSizeThreshold: 6,
        labelDensity: 0.1,
        labelGridCellSize: 50,
        labelFont: 'Inter, system-ui, sans-serif',
        labelWeight: '500',
        labelSize: 10,
        labelColor: { 
          attribute: 'labelColor',
        },
        zIndex: true,
        defaultNodeColor: '#6b7280',
        defaultEdgeColor: '#9ca3af',
        allowInvalidContainer: true,
      });

      sigmaRef.current = sigma;
      
      // Load data if available
      if (subgraphJson) {
        loadGraph();
      }
    } catch (err) {
      console.error('Failed to initialize Sigma:', err);
      setError('Failed to initialize graph');
    }

    return () => {
      sigmaRef.current?.kill();
      sigmaRef.current = null;
      graphRef.current = null;
    };
  }, []);

  // Reload graph when subgraphJson changes
  useEffect(() => {
    if (sigmaRef.current && graphRef.current && subgraphJson) {
      loadGraph();
    }
  }, [subgraphJson, loadGraph]);

  // Setup highlighting reducers - same as KnowledgeGraphView
  useEffect(() => {
    const sigma = sigmaRef.current;
    const graph = graphRef.current;
    if (!sigma || !graph) return;

    // Node reducer for highlighting
    sigma.setSetting('nodeReducer', (node, data) => {
      const res = { ...data };
      
      // Default label color
      res.labelColor = highlightColors.labelDefault;
      
      if (highlightedNode) {
        if (node === highlightedNode) {
          // The clicked node - emphasized
          res.highlighted = true;
          res.size = (data.size || 8) * 1.6;
          res.zIndex = 2;
          res.color = data.color;
          res.labelColor = highlightColors.labelHighlighted;
        } else if (highlightedNeighbors.has(node)) {
          // Neighbor nodes
          res.size = (data.size || 8) * 1.25;
          res.zIndex = 1;
          res.color = data.color;
          res.labelColor = highlightColors.labelNeighbor;
        } else {
          // Non-connected nodes - dimmed
          res.color = highlightColors.dimmedNode;
          res.size = (data.size || 8) * 0.6;
          res.zIndex = 0;
          res.label = '';
        }
      }
      
      return res;
    });

    // Edge reducer for highlighting
    sigma.setSetting('edgeReducer', (edge, data) => {
      const res = { ...data };
      
      if (highlightedNode && graph.hasEdge(edge)) {
        const source = graph.source(edge);
        const target = graph.target(edge);
        
        if (source === highlightedNode || target === highlightedNode) {
          // Connected edge - highlighted
          res.color = highlightColors.primary;
          res.size = 2.5;
          res.zIndex = 1;
        } else {
          // Non-connected edge - hidden
          res.color = highlightColors.dimmedEdge;
          res.hidden = true;
        }
      }
      
      return res;
    });

    sigma.refresh();
  }, [highlightedNode, highlightedNeighbors, highlightColors]);

  // Setup click handlers for highlighting
  useEffect(() => {
    const sigma = sigmaRef.current;
    const graph = graphRef.current;
    if (!sigma || !graph) return;

    // Click handler for highlighting
    const handleClickNode = ({ node }: { node: string }) => {
      const nodeData = graph.getNodeAttributes(node);
      
      // Set selected node for details
      setSelectedNode(nodeData.nodeData as SubgraphNode || null);
      
      // Toggle highlight
      setHighlightedNode(prev => {
        if (prev === node) {
          setHighlightedNeighbors(new Set());
          setSelectedNode(null);
          return null;
        } else {
          const neighbors = new Set<string>();
          graph.forEachNeighbor(node, (neighbor) => {
            neighbors.add(neighbor);
          });
          setHighlightedNeighbors(neighbors);
          return node;
        }
      });
    };

    const handleClickStage = () => {
      setSelectedNode(null);
      setHighlightedNode(null);
      setHighlightedNeighbors(new Set());
    };

    sigma.on('clickNode', handleClickNode);
    sigma.on('clickStage', handleClickStage);

    return () => {
      sigma.off('clickNode', handleClickNode);
      sigma.off('clickStage', handleClickStage);
    };
  }, []);

  // Zoom controls
  const handleZoomIn = () => {
    const sigma = sigmaRef.current;
    if (sigma) {
      const camera = sigma.getCamera();
      const currentRatio = camera.getState().ratio;
      camera.animate({ ratio: currentRatio / 1.5 }, { duration: 200 });
    }
  };

  const handleZoomOut = () => {
    const sigma = sigmaRef.current;
    if (sigma) {
      const camera = sigma.getCamera();
      const currentRatio = camera.getState().ratio;
      camera.animate({ ratio: currentRatio * 1.5 }, { duration: 200 });
    }
  };

  const handleResetZoom = () => {
    const sigma = sigmaRef.current;
    if (sigma) {
      const camera = sigma.getCamera();
      camera.animate({ x: 0.5, y: 0.5, ratio: 1, angle: 0 }, { duration: 200 });
    }
  };

  // Empty state
  if (!subgraphJson) {
    return (
      <div 
        className={`flex items-center justify-center bg-muted/30 rounded-lg ${className}`}
        style={{ height }}
      >
        <div className="text-center p-4">
          <Network className="w-8 h-8 text-muted-foreground/40 mx-auto mb-2" />
          <p className="text-xs text-muted-foreground">No graph context</p>
        </div>
      </div>
    );
  }

  return (
    <div className={`relative rounded-lg overflow-hidden bg-graph border border-border ${className}`} style={{ height }}>
      {/* Graph container */}
      <div 
        ref={containerRef}
        className="w-full h-full"
      />
      
      {/* Loading overlay */}
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/80">
          <Loader2 className="w-6 h-6 animate-spin text-primary" />
        </div>
      )}
      
      {/* Error state */}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/80">
          <div className="text-center p-4">
            <p className="text-xs text-destructive">{error}</p>
            <button 
              onClick={loadGraph}
              className="text-xs text-primary hover:underline mt-1"
            >
              Retry
            </button>
          </div>
        </div>
      )}
      
      {/* Empty graph state */}
      {!graphLoaded && !isLoading && !error && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="text-center">
            <Network className="w-6 h-6 text-muted-foreground/30 mx-auto mb-1" />
            <p className="text-xs text-muted-foreground">No nodes in context</p>
          </div>
        </div>
      )}
      
      {/* Controls overlay */}
      {graphLoaded && (
        <div className="absolute top-2 right-2 flex items-center gap-1">
          <button
            onClick={loadGraph}
            className="p-1.5 rounded bg-background/80 hover:bg-background border border-border text-muted-foreground hover:text-foreground transition-colors"
            title="Refresh layout"
          >
            <RefreshCw className="w-3 h-3" />
          </button>
          <button
            onClick={handleZoomIn}
            className="p-1.5 rounded bg-background/80 hover:bg-background border border-border text-muted-foreground hover:text-foreground transition-colors"
            title="Zoom in"
          >
            <ZoomIn className="w-3 h-3" />
          </button>
          <button
            onClick={handleZoomOut}
            className="p-1.5 rounded bg-background/80 hover:bg-background border border-border text-muted-foreground hover:text-foreground transition-colors"
            title="Zoom out"
          >
            <ZoomOut className="w-3 h-3" />
          </button>
          <button
            onClick={handleResetZoom}
            className="p-1.5 rounded bg-background/80 hover:bg-background border border-border text-muted-foreground hover:text-foreground transition-colors"
            title="Reset view"
          >
            <Maximize2 className="w-3 h-3" />
          </button>
          {onExpand && (
            <button
              onClick={onExpand}
              className="p-1.5 rounded bg-primary/10 hover:bg-primary/20 border border-primary/20 text-primary transition-colors"
              title="Expand graph"
            >
              <Maximize2 className="w-3 h-3" />
            </button>
          )}
        </div>
      )}
      
      {/* Stats badge */}
      {graphLoaded && (
        <div className="absolute bottom-2 left-2 px-2 py-1 rounded bg-background/80 border border-border">
          <span className="text-[10px] text-muted-foreground">
            {nodeCount} nodes · {edgeCount} edges
          </span>
        </div>
      )}
      
      {/* Selected node details */}
      {selectedNode && (
        <div className="absolute bottom-2 right-2 max-w-[180px] p-2 rounded bg-background/95 border border-border shadow-lg">
          <p className="text-xs font-medium text-foreground truncate">
            {getNodeDisplayLabel(selectedNode)}
          </p>
          <p className="text-[10px] text-muted-foreground">
            {selectedNode.labels?.[0]?.replace(/Entity$/, '') || 'Unknown'}
          </p>
          {highlightedNeighbors.size > 0 && (
            <p className="text-[10px] text-primary mt-1">
              {highlightedNeighbors.size} connection{highlightedNeighbors.size !== 1 ? 's' : ''}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export default ContextGraph;
