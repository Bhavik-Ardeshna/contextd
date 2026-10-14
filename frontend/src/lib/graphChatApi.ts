/**
 * Graph Chat API client
 * 
 * Provides chat functionality with graph-augmented context,
 * returning AI responses informed by the knowledge graph.
 */

import { apiClient } from './api';

// ============================================================================
// Types
// ============================================================================

/**
 * Entity reference from chat response
 */
export interface EntityReference {
  entity_id: string;
  node_id: string;
  name: string;
  entity_type: string;
  source: string;
  url: string | null;
  score: number | null;
  properties: Record<string, any>;
}

/**
 * Subgraph node for visualization (frontend format)
 */
export interface SubgraphNode {
  id: string;
  name: string;
  entity_type: string;
  source?: string;
  depth?: number;
  is_primary?: boolean;
  properties: Record<string, any>;
}

/**
 * Subgraph edge for visualization (frontend format)
 */
export interface SubgraphEdge {
  source: string;
  target: string;
  relationship_type: string;
  label?: string;
  properties: Record<string, any>;
}

/**
 * Subgraph data for visualization
 */
export interface Subgraph {
  nodes: SubgraphNode[];
  edges: SubgraphEdge[];
  center_node_ids?: string[];
}

/**
 * Raw subgraph node from backend API
 */
interface RawSubgraphNode {
  node_id: string;
  node_type: string;
  name: string;
  source?: string;
  depth?: number;
  is_primary?: boolean;
  properties: Record<string, any>;
}

/**
 * Raw subgraph edge from backend API
 */
interface RawSubgraphEdge {
  from_node_id: string;
  to_node_id: string;
  relationship_type: string;
  label?: string;
}

/**
 * Raw subgraph from backend API
 */
interface RawSubgraph {
  nodes: RawSubgraphNode[];
  edges: RawSubgraphEdge[];
  center_node_ids?: string[];
}

/**
 * Transform raw backend subgraph to frontend format
 */
function transformSubgraph(raw: RawSubgraph | null): Subgraph | null {
  if (!raw) return null;
  
  return {
    nodes: raw.nodes
      .filter(n => n.node_id && n.node_id !== 'undefined' && n.node_id !== 'null')
      .map(n => ({
        id: n.node_id,
        name: n.name || n.node_id,
        entity_type: n.node_type || 'Unknown',
        source: n.source,
        depth: n.depth,
        is_primary: n.is_primary,
        properties: n.properties || {},
      })),
    edges: raw.edges
      .filter(e => e.from_node_id && e.to_node_id && 
                   e.from_node_id !== 'undefined' && e.to_node_id !== 'undefined')
      .map(e => ({
        source: e.from_node_id,
        target: e.to_node_id,
        relationship_type: e.relationship_type || 'RELATED_TO',
        label: e.label,
        properties: {},
      })),
    center_node_ids: raw.center_node_ids,
  };
}

/**
 * Context metadata from chat response
 */
export interface ContextMetadata {
  node_count: number;
  edge_count: number;
  search_result_count: number;
  token_estimate: number;
  token_limit?: number;
  token_remaining?: number;
  token_used_percent?: number;
  phase_timings_ms?: Record<string, number>;
  max_depth: number;
  // Execution trace for the Decision Trace sidebar (all optional for back-compat)
  query_id?: string | null;
  latency_ms?: number | null;
  temporal_mode?: string;
  lineage_edge_count?: number;
  decision_count?: number;
  native_decision_count?: number;
  query_trace_count?: number;
  drift_severity?: string;
  context_tools?: Record<string, any>;
  path_used?: 'graph_search' | 'glm_deterministic' | 'glm_non_deterministic';
  queries?: Array<{ cypher: string; row_count: number; error?: string | null }>;
  total_rows?: number;
  collection_id?: string | null;
  collection_name?: string | null;
  source_types?: string[];
  mention_unresolved?: string | null;
}

/**
 * Search result from chat
 */
export interface ChatSearchResult {
  id: string;
  node_id: string;
  score: number;
  payload: Record<string, any>;
  source: string;
  graph_context: Record<string, any>;
  relationships: Array<any>;
}

/**
 * Chat request parameters
 */
export interface GraphChatRequest {
  message: string;
  history?: Array<{ role: string; content: string }>;
  max_depth?: number;
  search_limit?: number;
  max_context_tokens?: number;
  include_subgraph?: boolean;
  include_lineage?: boolean;
  context_tools?: string[];
  temporal_mode?: 'current' | 'historical' | 'knowledge' | 'audit';
}

/**
 * Plot image from P-Agent for display in chat
 */
export interface PlotImage {
  description: string;
  image_base64: string;
}

/**
 * Chart spec from P-Agent (JSON Bridge) for frontend to render with Recharts
 */
export interface ChartSpec {
  type: 'chart';
  chart_type: 'pie' | 'bar' | 'line' | 'histogram' | 'area' | 'scatter' | 'radar' | 'radialBar';
  title: string;
  data: Array<({ label?: string; name?: string; value?: number; x?: number; y?: number } & Record<string, unknown>)>;
  config?: { xAxis?: string; yAxis?: string; [k: string]: unknown };
}

/**
 * Chat response from API
 */
export interface GraphChatResponse {
  message: string;
  entity_references: EntityReference[];
  subgraph: Subgraph | null;
  /** Plots from P-Agent (graphs to display in chat window) */
  plot_images?: PlotImage[];
  /** Chart specs from P-Agent for interactive Recharts rendering */
  chart_specs?: ChartSpec[];
  context_metadata: ContextMetadata;
  temporal_context?: Record<string, any>;
  lineage_context?: Record<string, any>;
  decision_history?: Array<Record<string, any>>;
  drift_context?: Record<string, any>;
  tool_context?: Record<string, any>;
  decision_tree?: Record<string, any>;
  search_results: ChatSearchResult[];
}

/**
 * Extended chat message type with references
 */
export interface ChatMessageWithReferences {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  entity_references?: EntityReference[];
  subgraph?: Subgraph | null;
  context_metadata?: ContextMetadata;
}

// ============================================================================
// API Functions
// ============================================================================

/** Whether the message requests the deterministic path via @search. */
export function messageUsesSearchEndpoint(message: string): boolean {
  return /@search\b/i.test(message ?? '');
}

const buildChatRequestBody = (request: GraphChatRequest) => ({
  message: request.message,
  conversation_history: (request.history ?? []).map(h => ({
    role: h.role,
    content: h.content,
  })),
  max_depth: request.max_depth ?? 2,
  search_limit: request.search_limit ?? 10,
  max_context_tokens: request.max_context_tokens ?? 4000,
  include_subgraph: request.include_subgraph ?? true,
  include_lineage: request.include_lineage ?? true,
  context_tools: request.context_tools ?? [],
  temporal_mode: request.temporal_mode ?? 'current',
});

/**
 * Send a chat message and get AI response with graph context
 * 
 * @param collectionReadableId - The collection's readable ID (e.g., "test-4xh86w")
 * @param request - Chat request parameters
 * @param signal - Optional AbortSignal for cancellation
 * @returns Chat response with AI message and references
 */
export async function graphChat(
  collectionReadableId: string,
  request: GraphChatRequest,
  signal?: AbortSignal
): Promise<GraphChatResponse> {
  const chatRequest = buildChatRequestBody(request);

  const response = await apiClient.post(
    `/collections/${collectionReadableId}/chat`,
    chatRequest,
    { signal }
  );

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Chat failed: ${errorText}`);
  }

  const rawResponse = await response.json();
  
  // Transform the subgraph from backend format to frontend format
  return {
    ...rawResponse,
    subgraph: transformSubgraph(rawResponse.subgraph),
  };
}

/**
 * Chat using only the deterministic path (Seed Search → PPR/MST).
 * Same request/response as graphChat; use when message contains @search.
 */
export async function graphChatSearch(
  collectionReadableId: string,
  request: GraphChatRequest,
  signal?: AbortSignal
): Promise<GraphChatResponse> {
  const chatRequest = buildChatRequestBody(request);

  const response = await apiClient.post(
    `/collections/${collectionReadableId}/chat/search`,
    chatRequest,
    { signal }
  );

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Chat failed: ${errorText}`);
  }

  const rawResponse = await response.json();
  return {
    ...rawResponse,
    subgraph: transformSubgraph(rawResponse.subgraph),
  };
}

/**
 * Get graph context for a query (without full chat)
 * 
 * @param collectionReadableId - The collection's readable ID
 * @param query - The query to get context for
 * @param options - Optional configuration
 * @returns Context data
 */
export async function getGraphContext(
  collectionReadableId: string,
  query: string,
  options?: {
    useSearch?: boolean;
    searchLimit?: number;
    maxDepth?: number;
    nodeIds?: string[];
  },
  signal?: AbortSignal
): Promise<{
  context: string;
  token_estimate: number;
  node_count: number;
  edge_count: number;
  truncated: boolean;
  search_results: ChatSearchResult[];
}> {
  const request = {
    query,
    use_search: options?.useSearch ?? true,
    search_limit: options?.searchLimit ?? 5,
    max_depth: options?.maxDepth ?? 2,
    node_ids: options?.nodeIds,
  };

  const response = await apiClient.post(
    `/collections/${collectionReadableId}/graph/context`,
    request,
    { signal }
  );

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Context retrieval failed: ${errorText}`);
  }

  return response.json();
}

/**
 * Traverse graph from specific nodes
 * 
 * @param collectionReadableId - The collection's readable ID
 * @param nodeIds - Starting node IDs for traversal
 * @param options - Optional configuration
 * @returns Traversal result with nodes and edges
 */
export async function traverseGraph(
  collectionReadableId: string,
  nodeIds: string[],
  options?: {
    maxDepth?: number;
    direction?: 'outgoing' | 'incoming' | 'both';
    relationshipTypes?: string[];
    nodeLimit?: number;
    includeProperties?: boolean;
  },
  signal?: AbortSignal
): Promise<{
  nodes: SubgraphNode[];
  edges: SubgraphEdge[];
  stats: {
    total_nodes: number;
    total_edges: number;
    start_nodes: number;
  };
}> {
  const request = {
    node_ids: nodeIds,
    max_depth: options?.maxDepth ?? 2,
    direction: options?.direction ?? 'both',
    relationship_types: options?.relationshipTypes,
    node_limit: options?.nodeLimit ?? 100,
    include_properties: options?.includeProperties ?? true,
  };

  const response = await apiClient.post(
    `/collections/${collectionReadableId}/graph/traverse`,
    request,
    { signal }
  );

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Graph traversal failed: ${errorText}`);
  }

  return response.json();
}

/**
 * Neighborhood expansion for an aggregate Decision-Trace row.
 * Samples underlying rows matching a filter, then expands 1..depth hops.
 */
export interface NeighborhoodNode {
  node_id: string;
  node_type: string;
  name: string;
  properties: Record<string, unknown>;
  is_seed: boolean;
}

export interface NeighborhoodEdge {
  source_id: string;
  target_id: string;
  relationship_type: string;
}

export interface NeighborhoodResponse {
  samples: Array<{
    node_id: string;
    node_type: string | null;
    name: string;
    properties: Record<string, unknown>;
  }>;
  nodes: NeighborhoodNode[];
  edges: NeighborhoodEdge[];
  stats: {
    sample_count?: number;
    depth?: number;
    node_count?: number;
    edge_count?: number;
  };
}

export async function expandTraceNeighborhood(
  collectionReadableId: string,
  body: {
    node_type: string;
    filter_key?: string | null;
    filter_value?: unknown;
    sample_limit?: number;
    depth?: number;
    neighbor_cap?: number;
  },
  signal?: AbortSignal
): Promise<NeighborhoodResponse> {
  const response = await apiClient.post(
    `/collections/${collectionReadableId}/trace/neighborhood`,
    body,
    { signal }
  );
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Neighborhood expansion failed: ${errorText}`);
  }
  return response.json();
}

// ============================================================================
// Utility Functions
// ============================================================================

/**
 * Extract source short name for icon lookup from entity type
 */
export function extractSourceFromEntityType(entityType: string): string | null {
  const sourcePatterns: { pattern: RegExp; source: string }[] = [
    { pattern: /^asana/i, source: 'asana' },
    { pattern: /^slack/i, source: 'slack' },
    { pattern: /^notion/i, source: 'notion' },
    { pattern: /^github/i, source: 'github' },
    { pattern: /^google/i, source: 'google_drive' },
    { pattern: /^jira/i, source: 'jira' },
    { pattern: /^confluence/i, source: 'confluence' },
    { pattern: /^hubspot/i, source: 'hubspot' },
    { pattern: /^salesforce/i, source: 'salesforce' },
    { pattern: /^zendesk/i, source: 'zendesk' },
    { pattern: /^intercom/i, source: 'intercom' },
    { pattern: /^linear/i, source: 'linear' },
    { pattern: /^clickup/i, source: 'clickup' },
    { pattern: /^trello/i, source: 'trello' },
    { pattern: /^monday/i, source: 'monday' },
    { pattern: /^airtable/i, source: 'airtable' },
    { pattern: /^dropbox/i, source: 'dropbox' },
    { pattern: /^outlook/i, source: 'outlook_mail' },
    { pattern: /^teams/i, source: 'teams' },
    { pattern: /^sharepoint/i, source: 'sharepoint' },
    { pattern: /^todoist/i, source: 'todoist' },
    { pattern: /^attio/i, source: 'attio' },
    { pattern: /^pipedrive/i, source: 'pipedrive' },
    { pattern: /^stripe/i, source: 'stripe' },
    { pattern: /^shopify/i, source: 'shopify' },
    { pattern: /^gitlab/i, source: 'gitlab' },
    { pattern: /^bitbucket/i, source: 'bitbucket' },
    { pattern: /^gmail/i, source: 'gmail' },
  ];

  for (const { pattern, source } of sourcePatterns) {
    if (pattern.test(entityType)) {
      return source;
    }
  }

  return null;
}

/**
 * Format entity type for display
 */
export function formatEntityType(entityType: string): string {
  let formatted = entityType
    .replace(/Entity$/i, '')
    .replace(/Node$/i, '');

  const sourcePrefixes = [
    'Asana', 'Slack', 'Notion', 'GitHub', 'Google', 'Jira',
    'Confluence', 'HubSpot', 'Salesforce', 'Zendesk', 'Intercom',
    'Linear', 'ClickUp', 'Trello', 'Monday', 'Airtable', 'Dropbox',
    'Box', 'Outlook', 'Teams', 'SharePoint', 'OneDrive', 'Todoist',
    'Calendly', 'Attio', 'Pipedrive', 'Stripe', 'Shopify', 'GitLab',
    'Bitbucket', 'Gmail'
  ];

  for (const prefix of sourcePrefixes) {
    if (formatted.startsWith(prefix)) {
      formatted = formatted.slice(prefix.length);
      break;
    }
  }

  formatted = formatted.replace(/([a-z])([A-Z])/g, '$1 $2');
  return formatted.charAt(0).toUpperCase() + formatted.slice(1);
}

/**
 * Convert subgraph to JSON string for ContextGraph component
 */
export function subgraphToJson(subgraph: Subgraph | null): string | null {
  if (!subgraph) return null;
  
  // Convert to format expected by ContextGraph component
  const graphData = {
    nodes: subgraph.nodes.map(n => ({
      id: n.id,
      labels: [n.entity_type],
      properties: {
        name: n.name,
        ...n.properties,
      },
    })),
    edges: subgraph.edges.map((e, idx) => ({
      id: `edge-${idx}`,
      source: e.source,
      target: e.target,
      type: e.relationship_type,
      properties: e.properties,
    })),
  };
  
  return JSON.stringify(graphData);
}
