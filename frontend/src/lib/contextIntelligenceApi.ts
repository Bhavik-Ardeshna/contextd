import { apiClient } from './api';

export interface ContextIntelligenceSource {
  source_connection_id: string;
  source_name: string;
  provider: string;
  sync_id?: string | null;
  cursor_field?: string | null;
  drift?: Record<string, any>;
}

export interface ContextIntelligenceSummary {
  collection_id: string;
  readable_id: string;
  name: string;
  generated_at: string;
  totals: {
    temporal_facts?: number;
    superseded_facts?: number;
    lineage_edges?: number;
    decisions?: number;
    active_drift?: number;
    query_traces?: number;
    [key: string]: any;
  };
  temporal: Record<string, any>;
  lineage: Record<string, any>;
  decisions: Record<string, any>;
  drift: Record<string, any>;
  query_traces: Array<Record<string, any>>;
  sources: ContextIntelligenceSource[];
}

export interface ContextQueryFeedbackRequest {
  query_id?: string | null;
  rating: number;
  comment?: string | null;
  retrieved_node_ids?: string[];
  retrieved_edge_ids?: string[];
}

export interface ContextQueryFeedbackResponse {
  query_id?: string | null;
  rating: number;
  target_weight: number;
  alpha: number;
  updated_facts: number;
  previous_average_weight?: number | null;
  new_average_weight?: number | null;
  trace_updated: boolean;
}

export async function fetchContextIntelligence(
  readableId: string,
  options?: { cache?: boolean }
): Promise<ContextIntelligenceSummary> {
  const response = await apiClient.get(
    `/context-intelligence/databases/${readableId}`,
    undefined,
    { cache: options?.cache }
  );
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Context intelligence failed: ${response.status}`);
  }
  return response.json();
}

export async function submitQueryFeedback(
  readableId: string,
  payload: ContextQueryFeedbackRequest
): Promise<ContextQueryFeedbackResponse> {
  const response = await apiClient.post(`/context-intelligence/databases/${readableId}/feedback`, payload);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Feedback failed: ${response.status}`);
  }
  return response.json();
}

export async function detectContextDrift(readableId: string): Promise<ContextIntelligenceSummary> {
  const response = await apiClient.post(`/context-intelligence/databases/${readableId}/drift/detect`);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Drift detection failed: ${response.status}`);
  }
  return response.json();
}
