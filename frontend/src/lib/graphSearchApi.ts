/**
 * Graph Search API client
 *
 * Uses POST /collections/{id}/graph-search (deterministic path: seed search + PPR/MST).
 * Use include_edges: true for subgraph (MST), false for nodes only.
 */

import { apiClient } from './api';

/**
 * Graph search request parameters (maps to backend GraphSearchRequest)
 */
export interface GraphSearchRequest {
  query: string;
  /** If true, return subgraph (nodes + edges / MST); if false, nodes only */
  include_edges?: boolean;
  search_limit?: number;
  max_depth?: number;
  retrieval_strategy?: 'hybrid' | 'semantic' | 'fulltext';
  semantic_weight?: number;
  fulltext_weight?: number;
  min_score?: number;
}

/**
 * Single result item from graph search
 */
export interface GraphSearchResultItem {
  id: string;
  node_id: string;
  score: number;
  source: 'semantic' | 'fulltext' | 'fulltext_semantic' | 'hybrid';
  payload: {
    entity_type: string;
    node_id: string;
    node_type: string;
    entity_id: string;
    name: string;
    contextd_collection_id: string;
    organization_id: string;
    indexable_text?: string;
    indexable_fields?: string[];
    created_at?: string;
    updated_at?: string;
    web_url?: string;
    [key: string]: any;
  };
  graph_context: {
    node_type: string;
    name: string | null;
    properties: Record<string, any>;
  };
  relationships: Array<{
    related_id: string;
    relationship_type: string;
    related_type: string;
    direction: 'incoming' | 'outgoing';
    related_name: string | null;
  }>;
}

/**
 * Graph search response
 */
export interface GraphSearchResponse {
  results: GraphSearchResultItem[];
  related_nodes: Array<Record<string, any>>;
  total: number;
  stats: {
    semantic_count: number;
    fulltext_count: number;
    merged_count: number;
    primary_count: number;
    related_count: number;
  };
}

/** Raw response from POST /collections/{id}/graph-search */
interface GraphSearchApiResponse {
  nodes: Array<{ node_id: string; node_type?: string; name?: string; properties?: Record<string, unknown>; depth?: number; source_node_id?: string }>;
  edges: Array<{ from_node_id: string; to_node_id: string; relationship_type?: string }>;
  search_results: Array<{ node_id: string; score?: number; payload?: Record<string, unknown>; name?: string; node_type?: string }>;
  start_node_ids: string[];
  stats: Record<string, unknown>;
}

/**
 * Perform graph search (deterministic path: seed search + PPR/MST).
 * Uses POST /collections/{id}/graph-search. include_edges true = subgraph (MST), false = nodes only.
 *
 * @param collectionReadableId - The collection's readable ID
 * @param request - Search parameters (query, include_edges, search_limit, max_depth)
 * @param signal - Optional AbortSignal for cancellation
 * @returns Search results + related nodes in existing GraphSearchResponse shape
 */
export async function graphSearch(
  collectionReadableId: string,
  request: GraphSearchRequest,
  signal?: AbortSignal
): Promise<GraphSearchResponse> {
  const body = {
    query: request.query,
    include_edges: request.include_edges ?? true,
    search_limit: request.search_limit ?? 10,
    max_depth: request.max_depth ?? 2,
  };

  const response = await apiClient.post(
    `/collections/${collectionReadableId}/graph-search`,
    body,
    { signal }
  );

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Graph search failed: ${errorText}`);
  }

  const raw = (await response.json()) as GraphSearchApiResponse;
  const primaryIds = new Set((raw.search_results || []).map((r) => r.node_id));
  const results: GraphSearchResultItem[] = (raw.search_results || []).map((r) => ({
    id: r.node_id,
    node_id: r.node_id,
    score: r.score ?? 0,
    source: 'hybrid',
    payload: { ...(r.payload || {}), node_id: r.node_id, name: r.name, node_type: r.node_type },
    graph_context: { node_type: r.node_type ?? '', name: r.name ?? null, properties: r.payload ?? {} },
    relationships: [],
  }));
  const related_nodes = (raw.nodes || []).filter((n) => !primaryIds.has(n.node_id)).map((n) => ({
    node_id: n.node_id,
    node_type: n.node_type,
    name: n.name,
    properties: n.properties,
    depth: n.depth,
  }));
  return {
    results,
    related_nodes,
    total: results.length,
    stats: {
      semantic_count: 0,
      fulltext_count: 0,
      merged_count: raw.nodes?.length ?? 0,
      primary_count: results.length,
      related_count: related_nodes.length,
      ...raw.stats,
    },
  };
}

/**
 * Debounced graph search for real-time search UI
 * Returns a function that can be called with the same parameters
 */
export function createDebouncedGraphSearch(delayMs: number = 300) {
  let timeoutId: ReturnType<typeof setTimeout> | null = null;
  let abortController: AbortController | null = null;

  return async function debouncedSearch(
    collectionReadableId: string,
    request: GraphSearchRequest
  ): Promise<GraphSearchResponse | null> {
    // Cancel any pending search
    if (timeoutId) {
      clearTimeout(timeoutId);
    }
    if (abortController) {
      abortController.abort();
    }

    // Create new abort controller for this search
    abortController = new AbortController();
    const currentController = abortController;

    return new Promise((resolve, reject) => {
      timeoutId = setTimeout(async () => {
        try {
          const result = await graphSearch(
            collectionReadableId,
            request,
            currentController.signal
          );
          resolve(result);
        } catch (error) {
          if (error instanceof Error && error.name === 'AbortError') {
            // Search was cancelled, resolve with null
            resolve(null);
          } else {
            reject(error);
          }
        }
      }, delayMs);
    });
  };
}
