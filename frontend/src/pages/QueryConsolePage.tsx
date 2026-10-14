import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { toast } from 'sonner';
import {
  AlertCircle,
  ArrowRight,
  Bookmark,
  Boxes,
  Check,
  Clock,
  Copy,
  Database,
  FileJson,
  GaugeCircle,
  GitBranch,
  History,
  Layers,
  Loader2,
  MessageSquareText,
  Network,
  Play,
  Plug,
  Route,
  Search,
  ShieldCheck,
  Sparkles,
  Star,
  Table2,
  TerminalSquare,
  ThumbsUp,
  Users,
  Zap,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { apiClient } from '@/lib/api';
import {
  fetchContextIntelligence,
  submitQueryFeedback,
  type ContextIntelligenceSummary,
} from '@/lib/contextIntelligenceApi';
import {
  extractSourceFromEntityType,
  formatEntityType,
  graphChat,
  graphChatSearch,
  type ChatSearchResult,
  type EntityReference,
  type GraphChatResponse,
  type Subgraph,
} from '@/lib/graphChatApi';
import { useCollectionsStore } from '@/lib/stores/collections';
import { useOrganizationStore } from '@/lib/stores/organizations';
import { useTheme } from '@/lib/theme-provider';
import { cn } from '@/lib/utils';
import { getAppIconUrl } from '@/lib/utils/icons';
import {
  queryConsoleUrl,
  readQueryHistory,
  readSavedQueries,
  writeQueryHistory,
  writeSavedQueries,
  type QueryHistoryItem,
  type QueryRecipe,
  type SavedQuery,
} from '@/lib/queryConsoleStorage';

type Recipe = QueryRecipe;
type TraceStatus = 'done' | 'running' | 'pending' | 'failed' | 'warn' | 'skipped';
type TraceTone = 'blue' | 'purple' | 'orange';

interface TraceStep {
  key: string;
  label: string;
  detail: string;
  icon: typeof Search;
  ms: number | null;
  status: TraceStatus;
}

interface ContextForgeSourceSummary {
  source_connection_id: string;
  source_name: string;
  provider: string;
  status: string;
  cursor_field?: string | null;
  graph?: {
    entity_count?: number;
    graph_events_total?: number;
    nodes_committed?: number;
    edges_committed?: number;
    neo4j_nodes?: number;
    neo4j_edges?: number;
  };
  mapping_artifact?: {
    id: string;
    status: string;
    version: number;
  } | null;
}

interface ContextForgeSummary {
  readable_id: string;
  name: string;
  totals?: {
    entities?: number;
    graph_events?: number;
    nodes_committed?: number;
    edges_committed?: number;
    neo4j_nodes?: number;
    neo4j_edges?: number;
    pending_events?: number;
    forge_ready_sources?: number;
  };
  sources?: ContextForgeSourceSummary[];
}

interface RawGraphSearchResponse {
  nodes?: Array<{
    node_id?: string;
    node_type?: string;
    name?: string;
    source?: string;
    depth?: number;
    is_primary?: boolean;
    properties?: Record<string, unknown>;
  }>;
  edges?: Array<{
    from_node_id?: string;
    to_node_id?: string;
    relationship_type?: string;
    label?: string;
  }>;
  search_results?: Array<{
    node_id?: string;
    score?: number;
    payload?: Record<string, unknown>;
    name?: string;
    node_type?: string;
  }>;
  start_node_ids?: string[];
  stats?: Record<string, unknown>;
  context_metadata?: GraphChatResponse['context_metadata'];
  temporal_context?: Record<string, any>;
  lineage_context?: Record<string, any>;
  decision_history?: Array<Record<string, any>>;
  drift_context?: Record<string, any>;
  decision_tree?: Record<string, any>;
}

interface RetrievedEntity {
  id: string;
  label: string;
  type: string;
  table: string;
  source: string;
  score: number | null;
  detail: string;
}

interface SourceUsage {
  label: string;
  source: string;
  count: number;
}

const DEFAULT_QUERY =
  '@search @graph show the studios, trainers, classes, subscriptions, and bookings with the strongest relationships';

type ContextToolKey = 'search' | 'graph' | 'temporal' | 'core' | 'cohort' | 'decision';

const contextToolDefinitions: Array<{
  key: ContextToolKey;
  token: `@${ContextToolKey}`;
  label: string;
  purpose: string;
  summary: string;
  icon: typeof Search;
}> = [
  {
    key: 'search',
    token: '@search',
    label: 'Search',
    purpose: 'Seed the packet with deterministic hybrid search and RRF.',
    summary: 'hybrid seeds',
    icon: Search,
  },
  {
    key: 'graph',
    token: '@graph',
    label: 'Graph',
    purpose: 'Expand seed matches into a linked ContextD neighborhood.',
    summary: 'neighborhood',
    icon: Network,
  },
  {
    key: 'temporal',
    token: '@temporal',
    label: 'Temporal',
    purpose: 'Attach current bitemporal facts and cursor-aware state.',
    summary: 'current facts',
    icon: Clock,
  },
  {
    key: 'core',
    token: '@core',
    label: 'Core',
    purpose: 'Attach the selected database core summary and source shape.',
    summary: 'database core',
    icon: Boxes,
  },
  {
    key: 'cohort',
    token: '@cohort',
    label: 'Cohort',
    purpose: 'Attach cohort scope; defaults to all entities when no cohort is selected.',
    summary: 'entity scope',
    icon: Users,
  },
  {
    key: 'decision',
    token: '@decision',
    label: 'Decision',
    purpose: 'Attach query audit and first-class Decision lineage.',
    summary: 'audit trace',
    icon: ShieldCheck,
  },
];

const traceBlueprint = [
  { key: 'parse', label: 'Parse intent', detail: 'mentions, scope, filters', icon: MessageSquareText, weight: 0.06 },
  { key: 'seed', label: 'Seed retrieval', detail: 'semantic + full-text RRF', icon: Search, weight: 0.22 },
  { key: 'bfs', label: 'Neighborhood expand', detail: 'ContextD neighborhood with depth cap', icon: Network, weight: 0.27 },
  { key: 'rerank', label: 'Rerank', detail: 'score, recency, authority', icon: Route, weight: 0.14 },
  { key: 'feedback', label: 'Memory prior', detail: 'workspace feedback weights', icon: Star, weight: 0.06 },
  { key: 'temporal', label: 'Temporal guard', detail: 'cursor-aware current view', icon: Clock, weight: 0.08 },
  { key: 'assemble', label: 'Assemble context', detail: 'citations and token budget', icon: FileJson, weight: 0.17 },
];

function compactNumber(value?: number | null) {
  const safeValue = Number(value || 0);
  if (safeValue >= 1_000_000) return `${(safeValue / 1_000_000).toFixed(1)}M`;
  if (safeValue >= 1_000) return `${(safeValue / 1_000).toFixed(safeValue >= 10_000 ? 0 : 1)}K`;
  return String(safeValue);
}

function formatMs(value?: number | null) {
  if (!value) return '0 ms';
  if (value >= 1000) return `${(value / 1000).toFixed(1)} s`;
  return `${Math.max(1, Math.round(value))} ms`;
}

function safeString(value: unknown, fallback = '') {
  if (typeof value === 'string' && value.trim()) return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return fallback;
}

function toRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function stripMentions(query: string) {
  return query.replace(/@\w+\b/g, ' ').replace(/\s+/g, ' ').trim() || query.trim();
}

function parseContextTools(query: string): ContextToolKey[] {
  return contextToolDefinitions
    .filter((tool) => new RegExp(`${tool.token}\\b`, 'i').test(query))
    .map((tool) => tool.key);
}

function removeMention(query: string, token: string) {
  return query
    .replace(new RegExp(`\\s*${token}\\b`, 'gi'), ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function estimateTokens(query: string, response?: GraphChatResponse | null) {
  const responseEstimate = response?.context_metadata?.token_estimate;
  if (responseEstimate && responseEstimate > 0) return responseEstimate;
  return Math.max(42, Math.round(query.trim().length / 3.6));
}

function metricNumber(value: unknown, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function createAuditId() {
  return `qry_${Date.now().toString(36)}_${Math.random().toString(16).slice(2, 8)}`;
}

function createTraceSteps(latencyMs: number | null, isRunning: boolean, failed = false): TraceStep[] {
  if (failed) {
    return traceBlueprint.map((step, index) => ({
      ...step,
      ms: index === 0 ? Math.max(1, Math.round((latencyMs || 60) * 0.12)) : null,
      status: index === 0 ? 'failed' : 'pending',
    }));
  }

  if (isRunning && !latencyMs) {
    return traceBlueprint.map((step, index) => ({
      ...step,
      ms: null,
      status: index === 0 ? 'running' : 'pending',
    }));
  }

  if (!latencyMs) {
    return traceBlueprint.map((step) => ({ ...step, ms: null, status: 'pending' }));
  }

  return traceBlueprint.map((step) => ({
    ...step,
    ms: Math.max(1, Math.round(latencyMs * step.weight)),
    status: 'done',
  }));
}

const backendTraceIcons: Record<string, typeof Search> = {
  parse_intent: MessageSquareText,
  seed_selection: Search,
  graph_expand: Network,
  feedback_prior: Star,
  temporal_prune: Clock,
  lineage_attach: Route,
  decision_lineage: ShieldCheck,
  drift_guard: AlertCircle,
  assemble_packet: FileJson,
};

function createTraceStepsFromDecisionTree(
  decisionTree: Record<string, any> | undefined,
  latencyMs: number | null,
  isRunning: boolean,
  failed = false
): TraceStep[] {
  const backendSteps = Array.isArray(decisionTree?.steps) ? decisionTree.steps : [];
  if (!backendSteps.length) return createTraceSteps(latencyMs, isRunning, failed);
  return backendSteps.map((step: Record<string, any>, index: number) => ({
    key: safeString(step.key, `step_${index}`),
    label: safeString(step.label, `Step ${index + 1}`),
    detail: safeString(step.detail, 'context assembly'),
    icon: backendTraceIcons[safeString(step.key)] || Search,
    ms: metricNumber(step.latency_ms ?? step.duration_ms ?? step.ms, 0) || null,
    status: failed
      ? index === 0
        ? 'failed'
        : 'pending'
      : (['done', 'running', 'pending', 'failed', 'warn', 'skipped'].includes(safeString(step.status))
          ? safeString(step.status)
          : 'done') as TraceStatus,
  }));
}

function sumStepMs(steps: TraceStep[], keys: string[]) {
  return steps
    .filter((step) => keys.includes(step.key))
    .reduce((total, step) => total + (step.ms || 0), 0);
}

function inferSourceShortName(entity: EntityReference): string {
  return entity.source || extractSourceFromEntityType(entity.entity_type) || 'postgresql';
}

function firstTitle(words: string) {
  return stripMentions(words).split(/\s+/).slice(0, 7).join(' ') || 'Untitled context query';
}

function titleize(value: string) {
  return value
    .replace(/^public\./, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function tableFromPayload(payload: Record<string, unknown>, nodeId?: string) {
  const rawTable =
    safeString(payload.table) ||
    safeString(payload.table_name) ||
    safeString(payload.relation) ||
    safeString(payload.schema_table);
  if (rawTable) return rawTable.includes('.') ? rawTable : `public.${rawTable}`;

  const nodePrefix = nodeId?.includes(':') ? nodeId.split(':')[0] : '';
  if (nodePrefix) return nodePrefix;

  const entityType = safeString(payload.entity_type || payload.node_type);
  const match = entityType.match(/^DatabaseTableNode_(.+)$/);
  if (match?.[1]) {
    const parts = match[1].split('_');
    if (parts.length > 1) return `${parts[0]}.${parts.slice(1).join('_')}`;
    return parts[0];
  }
  return 'graph';
}

function labelFromPayload(payload: Record<string, unknown>, fallback: string) {
  const first = safeString(payload.first_name);
  const last = safeString(payload.last_name);
  if (first || last) return [first, last].filter(Boolean).join(' ');
  return (
    safeString(payload.name) ||
    safeString(payload.title) ||
    safeString(payload.email) ||
    safeString(payload.slug) ||
    safeString(payload.id) ||
    fallback
  );
}

function typeFromPayload(payload: Record<string, unknown>, nodeType?: string) {
  const table = tableFromPayload(payload);
  const raw =
    safeString(payload.entity_label) ||
    safeString(payload.business_type) ||
    safeString(payload.entity_type || payload.node_type || nodeType);
  if (!raw || raw === 'Entity') return titleize(table);
  if (raw.startsWith('DatabaseTableNode_')) return titleize(table);
  return formatEntityType(raw);
}

function buildRetrievedEntities(response: GraphChatResponse | null, sourceFallback: string): RetrievedEntity[] {
  if (!response) return [];

  const fromSearch = (response.search_results || [])
    .filter((result) => result.node_id)
    .slice(0, 12)
    .map((result) => {
      const payload = toRecord(result.payload);
      const source = safeString(payload.source || payload.provider || payload.source_type, sourceFallback);
      const table = tableFromPayload(payload, result.node_id);
      const label = labelFromPayload(payload, result.name || result.node_id);
      return {
        id: result.node_id,
        label,
        type: typeFromPayload(payload, result.graph_context?.node_type as string | undefined),
        table,
        source,
        score: typeof result.score === 'number' ? result.score : null,
        detail: `${table} · ${result.node_id}`,
      };
    });

  if (fromSearch.length) return fromSearch;

  return (response.entity_references || []).slice(0, 12).map((entity) => {
    const payload = toRecord(entity.properties);
    const table = tableFromPayload(payload, entity.node_id);
    return {
      id: entity.node_id || entity.entity_id,
      label: entity.name || labelFromPayload(payload, entity.node_id),
      type: typeFromPayload(payload, entity.entity_type),
      table,
      source: inferSourceShortName(entity),
      score: entity.score,
      detail: `${table} · ${entity.node_id}`,
    };
  });
}

function buildSourceUsage(response: GraphChatResponse | null, sourceFallback: string): SourceUsage[] {
  const counts = new Map<string, { source: string; count: number }>();

  (response?.search_results || []).forEach((result) => {
    const payload = toRecord(result.payload);
    const label = tableFromPayload(payload, result.node_id);
    const source = safeString(payload.source || payload.provider || payload.source_type, sourceFallback);
    const current = counts.get(label) || { source, count: 0 };
    current.count += 1;
    counts.set(label, current);
  });

  if (!counts.size) {
    (response?.entity_references || []).forEach((entity) => {
      const label = tableFromPayload(toRecord(entity.properties), entity.node_id);
      const current = counts.get(label) || { source: inferSourceShortName(entity), count: 0 };
      current.count += 1;
      counts.set(label, current);
    });
  }

  if (!counts.size && sourceFallback) counts.set(sourceFallback, { source: sourceFallback, count: 1 });

  return Array.from(counts.entries())
    .map(([label, value]) => ({ label, source: value.source, count: value.count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 6);
}

function buildFallbackMessage(raw: RawGraphSearchResponse, query: string) {
  const seeds = raw.search_results || [];
  const nodes = raw.nodes || [];
  const edges = raw.edges || [];
  const names = seeds
    .slice(0, 6)
    .map((result) => safeString(result.name || result.payload?.name || result.payload?.entity_type || result.node_type))
    .filter(Boolean);

  return [
    `I retrieved ${seeds.length} primary matches and ${Math.max(0, nodes.length - seeds.length)} related ContextD nodes for "${stripMentions(query)}".`,
    names.length ? `Top matches: ${names.join(', ')}.` : 'No named seed entities were returned.',
    `The context packet includes ${nodes.length} nodes and ${edges.length} relationships from the ContextD graph.`,
  ].join('\n\n');
}

function transformRawGraphSearch(raw: RawGraphSearchResponse, query: string): GraphChatResponse {
  const rawNodes = raw.nodes || [];
  const rawEdges = raw.edges || [];
  const rawSearchResults = raw.search_results || [];
  const primaryIds = new Set((raw.start_node_ids || rawSearchResults.map((item) => item.node_id)).filter(Boolean));

  const entityReferences: EntityReference[] = rawSearchResults
    .filter((item) => item.node_id)
    .map((item) => {
      const payload = toRecord(item.payload);
      const entityType = safeString(payload.entity_type || payload.node_type || item.node_type, 'Entity');
      const name = labelFromPayload(payload, item.name || item.node_id || 'Unknown entity');
      return {
        entity_id: safeString(payload.entity_id || item.node_id, item.node_id || name),
        node_id: item.node_id || name,
        name,
        entity_type: entityType,
        source: safeString(payload.source || payload.provider || payload.source_type || extractSourceFromEntityType(entityType), 'graph'),
        url: safeString(payload.web_url || payload.url, '') || null,
        score: typeof item.score === 'number' ? item.score : null,
        properties: payload,
      };
    });

  const subgraph: Subgraph = {
    nodes: rawNodes
      .filter((node) => node.node_id)
      .map((node) => ({
        id: node.node_id || '',
        name: safeString(node.name || node.properties?.name || node.node_id, 'Unknown node'),
        entity_type: safeString(node.node_type, 'Entity'),
        source: typeof node.source === 'string' ? node.source : undefined,
        depth: typeof node.depth === 'number' ? node.depth : undefined,
        is_primary: node.is_primary ?? primaryIds.has(node.node_id),
        properties: toRecord(node.properties),
      })),
    edges: rawEdges
      .filter((edge) => edge.from_node_id && edge.to_node_id)
      .map((edge) => ({
        source: edge.from_node_id || '',
        target: edge.to_node_id || '',
        relationship_type: edge.relationship_type || 'RELATED_TO',
        label: edge.label,
        properties: {},
      })),
    center_node_ids: Array.from(primaryIds) as string[],
  };

  const searchResults: ChatSearchResult[] = rawSearchResults
    .filter((item) => item.node_id)
    .map((item) => {
      const payload = toRecord(item.payload);
      return {
        id: item.node_id || '',
        node_id: item.node_id || '',
        score: typeof item.score === 'number' ? item.score : 0,
        payload,
        source: 'graph-search',
        graph_context: {
          node_type: safeString(item.node_type || payload.node_type || payload.entity_type, 'Entity'),
          name: safeString(item.name || payload.name),
          properties: payload,
        },
        relationships: [],
      };
    });

  return {
    message: buildFallbackMessage(raw, query),
    entity_references: entityReferences,
    subgraph,
    context_metadata: {
      node_count: subgraph.nodes.length,
      edge_count: subgraph.edges.length,
      search_result_count: searchResults.length,
      token_estimate: Math.max(128, subgraph.nodes.length * 36 + subgraph.edges.length * 12),
      max_depth: 2,
      path_used: 'graph_search',
      queries: [],
      total_rows: Number(raw.stats?.total_rows || raw.stats?.merged_count || subgraph.nodes.length),
      source_types: Array.from(new Set(entityReferences.map((entity) => entity.source).filter(Boolean))),
      ...(raw.context_metadata || {}),
    },
    temporal_context: raw.temporal_context || {},
    lineage_context: raw.lineage_context || {},
    decision_history: raw.decision_history || [],
    drift_context: raw.drift_context || {},
    tool_context: raw.tool_context || {},
    decision_tree: raw.decision_tree || {},
    search_results: searchResults,
  };
}

async function runRawGraphSearch(
  collectionReadableId: string,
  query: string,
  signal?: AbortSignal,
  contextTools: ContextToolKey[] = []
) {
  const response = await apiClient.post(
    `/collections/${collectionReadableId}/graph-search`,
    {
      query: stripMentions(query),
      include_edges: true,
      search_limit: 12,
      max_depth: contextTools.includes('graph') ? 2 : 1,
      context_tools: contextTools,
    },
    { signal }
  );

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return transformRawGraphSearch((await response.json()) as RawGraphSearchResponse, query);
}

function SourceIcon({ shortName, className }: { shortName: string; className?: string }) {
  const { resolvedTheme } = useTheme();
  return (
    <img
      src={getAppIconUrl(shortName || 'postgresql', resolvedTheme)}
      alt=""
      className={cn('h-5 w-5 rounded object-contain', className)}
    />
  );
}

function StatusDot({ tone = 'green' }: { tone?: 'green' | 'orange' | 'blue' | 'muted' }) {
  return (
    <span
      className={cn(
        'h-2 w-2 rounded-full',
        tone === 'green' && 'bg-emerald-500',
        tone === 'orange' && 'bg-primary',
        tone === 'blue' && 'bg-blue-500',
        tone === 'muted' && 'bg-muted-foreground'
      )}
    />
  );
}

function QueryPanel({
  title,
  meta,
  icon: Icon,
  children,
  actions,
  className,
}: {
  title: string;
  meta?: React.ReactNode;
  icon?: typeof Search;
  children: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn('rounded-lg border border-border bg-background shadow-sm', className)}>
      <div className="flex min-h-11 items-center justify-between gap-3 border-b border-border px-3.5 py-2.5">
        <div className="min-w-0">
          <h2 className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
            {Icon && <Icon className="h-3.5 w-3.5 text-primary" />}
            <span className="truncate">{title}</span>
          </h2>
          {meta && <div className="mt-0.5 text-xs text-muted-foreground">{meta}</div>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

function summarizeTraceValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '';
  if (typeof value === 'string') return value.length > 90 ? `${value.slice(0, 87)}...` : value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return `${value.length} item${value.length === 1 ? '' : 's'}`;
  const record = toRecord(value);
  const entries = Object.entries(record)
    .filter(([, item]) => {
      if (item === null || item === undefined || item === '') return false;
      if (Array.isArray(item) && item.length === 0) return false;
      if (typeof item === 'object' && !Array.isArray(item) && Object.keys(toRecord(item)).length === 0) return false;
      return true;
    })
    .slice(0, 3)
    .map(([key, item]) => `${key}: ${summarizeTraceValue(item)}`);
  return entries.join(' · ');
}

function traceStepOutput(step: Record<string, any>) {
  const output = step.output ?? {};
  const summary = summarizeTraceValue(output);
  if (summary) return summary;
  if (typeof step.output_count === 'number') return `${compactNumber(step.output_count)} output`;
  if (typeof step.input_count === 'number') return `${compactNumber(step.input_count)} input`;
  return safeString(step.status, 'recorded');
}

function NativeDecisionTrace({
  response,
  traceSteps,
  latencyMs,
}: {
  response: GraphChatResponse | null;
  traceSteps: TraceStep[];
  latencyMs: number | null;
}) {
  if (!response) return null;

  const decisionTree = toRecord(response.decision_tree);
  const nativeSteps = Array.isArray(decisionTree.steps) ? decisionTree.steps : [];
  const metrics = toRecord(decisionTree.metrics);
  const queryId = safeString(response.context_metadata?.query_id || decisionTree.query_id, 'pending');
  const drift = safeString(response.drift_context?.severity || metrics.drift_severity, 'clean');
  const lineageEdges = Number(response.lineage_context?.edge_count || metrics.lineage_edges || 0);
  const temporalFacts = Number(response.temporal_context?.current_facts || metrics.temporal_facts || 0);
  const queryTraceCount = Number(response.context_metadata?.query_trace_count || metrics.query_traces || (queryId !== 'pending' ? 1 : 0));
  const nativeDecisionCount = Number(response.decision_history?.length || metrics.native_decisions || 0);
  const decisions = Math.max(
    Number(response.context_metadata?.decision_count || 0),
    Number(metrics.decisions || 0),
    nativeDecisionCount + queryTraceCount
  );

  return (
    <QueryPanel
      title="Decision trace"
      icon={ShieldCheck}
      meta={`ContextD response · ${queryId}`}
      actions={
        <span
          className={cn(
            'inline-flex h-6 items-center rounded-md border px-2 text-[11px] font-medium',
            drift === 'clean'
              ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
              : 'border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300'
          )}
        >
          drift {drift}
        </span>
      }
    >
      <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_280px] lg:divide-x lg:divide-border">
        <div className="px-3 py-3">
          <div className="grid gap-2 sm:grid-cols-3">
            {[
              { label: 'Temporal', value: compactNumber(temporalFacts), sub: 'current facts', icon: Clock },
              { label: 'Lineage', value: compactNumber(lineageEdges), sub: 'attached edges', icon: Route },
              {
                label: 'Decisions',
                value: compactNumber(decisions),
                sub: queryTraceCount ? `${compactNumber(queryTraceCount)} query trace${queryTraceCount === 1 ? '' : 's'}` : 'response evidence',
                icon: ShieldCheck,
              },
            ].map((item) => {
              const Icon = item.icon;
              return (
                <div key={item.label} className="rounded-md border border-border bg-muted/20 p-2.5">
                  <div className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
                    <Icon className="h-3.5 w-3.5 text-primary" />
                    {item.label}
                  </div>
                  <div className="mt-1 font-mono text-lg font-semibold text-foreground">{item.value}</div>
                  <div className="text-[10.5px] text-muted-foreground">{item.sub}</div>
                </div>
              );
            })}
          </div>

          <div className="mt-3 divide-y divide-border rounded-md border border-border">
            {(nativeSteps.length ? nativeSteps : traceSteps).map((rawStep: any, index: number) => {
              const step = nativeSteps.length ? rawStep : traceSteps[index];
              const status = safeString(step.status, 'done') as TraceStatus;
              const Icon = backendTraceIcons[safeString(step.key)] || traceSteps[index]?.icon || Search;
              return (
                <div key={`${safeString(step.key, `step-${index}`)}-${index}`} className="grid gap-2 px-3 py-2.5 text-xs md:grid-cols-[180px_minmax(0,1fr)_70px] md:items-center">
                  <div className="flex min-w-0 items-center gap-2">
                    <span
                      className={cn(
                        'inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full',
                        status === 'done' && 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
                        status === 'warn' && 'bg-amber-500/10 text-amber-700 dark:text-amber-300',
                        status === 'skipped' && 'bg-muted text-muted-foreground',
                        status === 'failed' && 'bg-destructive/10 text-destructive',
                        status === 'running' && 'bg-primary/10 text-primary',
                        status === 'pending' && 'bg-muted text-muted-foreground'
                      )}
                    >
                      {status === 'done' ? <Check className="h-3.5 w-3.5" /> : <Icon className="h-3.5 w-3.5" />}
                    </span>
                    <div className="min-w-0">
                      <div className="truncate font-medium text-foreground">{safeString(step.label, `Step ${index + 1}`)}</div>
                      <div className="truncate text-[11px] text-muted-foreground">{safeString(step.detail, 'context assembly')}</div>
                    </div>
                  </div>
                  <div className="min-w-0 truncate font-mono text-[11px] text-muted-foreground">
                    {traceStepOutput(step)}
                  </div>
                  <div className="font-mono text-[11px] text-muted-foreground md:text-right">
                    {traceSteps[index]?.ms ? formatMs(traceSteps[index].ms) : status}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="space-y-2 px-3 py-3">
          <div className="rounded-md border border-border bg-muted/20 p-3">
            <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">Response audit</div>
            <dl className="mt-2 grid grid-cols-[80px_1fr] gap-y-1.5 text-xs">
              <dt className="text-muted-foreground">Trace</dt>
              <dd className="truncate font-mono text-foreground">{queryId}</dd>
              <dt className="text-muted-foreground">Route</dt>
              <dd className="truncate font-mono text-foreground">{safeString(response.context_metadata?.path_used || decisionTree.path_used, 'graph_search')}</dd>
              <dt className="text-muted-foreground">Latency</dt>
              <dd className="font-mono text-foreground">{formatMs(Number(response.context_metadata?.latency_ms || decisionTree.latency_ms || latencyMs || 0))}</dd>
              <dt className="text-muted-foreground">Tokens</dt>
              <dd className="font-mono text-foreground">{compactNumber(Number(metrics.token_estimate || response.context_metadata?.token_estimate || 0))}</dd>
            </dl>
          </div>
          <div className="rounded-md border border-primary/20 bg-primary/5 p-3 text-xs text-muted-foreground">
            This trace is persisted as a ContextD query decision record and is used by feedback, lineage review, and future retrieval guards.
          </div>
        </div>
      </div>
    </QueryPanel>
  );
}

function EmptyAnswer({ onRun, disabled }: { onRun: () => void; disabled: boolean }) {
  return (
    <div className="rounded-md border border-dashed border-border bg-muted/20 p-4">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-primary/20 bg-primary/10 text-primary">
            <TerminalSquare className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <h3 className="text-base font-semibold text-foreground">Ready to ask ContextD</h3>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
              Run the prompt to retrieve graph context, apply temporal and drift guards, then persist the decision trace.
            </p>
            <div className="mt-3 flex flex-wrap gap-1.5 text-[11px] text-muted-foreground">
              {['seed matches', 'graph neighborhood', 'guarded packet'].map((item) => (
                <span key={item} className="rounded-md border border-border bg-background px-2 py-1">
                  {item}
                </span>
              ))}
            </div>
          </div>
        </div>
        <Button
          onClick={onRun}
          disabled={disabled}
          size="sm"
          className="h-9 shrink-0 border border-primary bg-primary px-4 text-primary-foreground hover:bg-primary/90"
        >
          <Play className="h-4 w-4" />
          Run query
        </Button>
      </div>
    </div>
  );
}

function RunningAnswer() {
  return (
    <div className="flex min-h-[180px] flex-col justify-center rounded-md border border-primary/20 bg-primary/[0.04] px-5">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-primary/25 bg-background text-primary">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
        <div className="min-w-0">
          <h3 className="text-base font-semibold text-foreground">Assembling ContextD answer</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Retrieving ContextD graph context, applying temporal and drift guards, then assembling the response packet.
          </p>
        </div>
      </div>
      <div className="mt-5 grid gap-2 sm:grid-cols-3">
        {['Seed retrieval', 'Neighborhood expand', 'Decision trace'].map((label, index) => (
          <div key={label} className="rounded-md border border-border bg-background px-3 py-2">
            <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
              <span className={cn('h-2 w-2 rounded-full', index === 0 ? 'animate-pulse bg-primary' : 'bg-muted-foreground/35')} />
              {label}
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary/80"
                style={{ width: `${index === 0 ? 72 : index === 1 ? 45 : 28}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function RailItem({
  icon: Icon,
  label,
  count,
  active,
  onClick,
}: {
  icon: typeof Search;
  label: string;
  count?: string;
  active?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-xs font-medium transition-colors',
        active
          ? 'bg-primary/10 text-primary'
          : 'text-muted-foreground hover:bg-muted hover:text-foreground'
      )}
    >
      <Icon className="h-3.5 w-3.5 shrink-0" />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {count && <span className="font-mono text-[10px] text-muted-foreground">{count}</span>}
    </button>
  );
}

function QueryConsolePage() {
  const navigate = useNavigate();
  const { readable_id: routeDatabaseId } = useParams<{ readable_id?: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const databaseParam = searchParams.get('database') || routeDatabaseId || '';
  const queryParam = searchParams.get('q');
  const recipeParam = searchParams.get('recipe');
  const { collections, fetchCollections, sourceConnections, fetchSourceConnections, isLoading } = useCollectionsStore();
  const currentOrganization = useOrganizationStore((state) => state.currentOrganization);

  const [selectedCollectionId, setSelectedCollectionId] = useState<string>('');
  const [queryText, setQueryText] = useState(DEFAULT_QUERY);
  const [recipe, setRecipe] = useState<Recipe>('rrf');
  const [response, setResponse] = useState<GraphChatResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [fallbackMode, setFallbackMode] = useState(false);
  const [auditId, setAuditId] = useState(createAuditId());
  const [forgeSummary, setForgeSummary] = useState<ContextForgeSummary | null>(null);
  const [isForgeLoading, setIsForgeLoading] = useState(false);
  const [intelligenceSummary, setIntelligenceSummary] = useState<ContextIntelligenceSummary | null>(null);
  const [isIntelligenceLoading, setIsIntelligenceLoading] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [copied, setCopied] = useState(false);
  const [feedback, setFeedback] = useState<number | null>(null);
  const [isFeedbackSaving, setIsFeedbackSaving] = useState(false);
  const [queryHistory, setQueryHistory] = useState<QueryHistoryItem[]>(() => readQueryHistory());
  const [savedQueries, setSavedQueries] = useState<SavedQuery[]>(() => readSavedQueries());
  const abortRef = useRef<AbortController | null>(null);
  const appliedQueryParamRef = useRef<string | null>(null);
  const activeContextTools = useMemo(() => parseContextTools(queryText), [queryText]);
  const activeContextToolLabels = useMemo(
    () =>
      contextToolDefinitions
        .filter((tool) => activeContextTools.includes(tool.key))
        .map((tool) => tool.summary),
    [activeContextTools]
  );

  useEffect(() => {
    fetchCollections();
  }, [fetchCollections]);

  useEffect(() => {
    if (!collections.length) return;
    setSelectedCollectionId((current) => {
      if (current && collections.some((collection) => collection.readable_id === current)) return current;
      const paramMatch = databaseParam
        ? collections.find((collection) => collection.readable_id === databaseParam)
        : null;
      const activeMatch = collections.find((collection) => /active|completed|ready/i.test(collection.status || ''));
      return (paramMatch || activeMatch || collections[0]).readable_id;
    });
  }, [collections, databaseParam]);

  useEffect(() => {
    if (!selectedCollectionId) return;
    if (routeDatabaseId) return;
    const next = new URLSearchParams(searchParams);
    if (next.get('database') !== selectedCollectionId) {
      next.set('database', selectedCollectionId);
      setSearchParams(next, { replace: true });
    }
  }, [routeDatabaseId, selectedCollectionId, searchParams, setSearchParams]);

  useEffect(() => {
    if (queryParam && appliedQueryParamRef.current !== queryParam) {
      setQueryText(queryParam);
      appliedQueryParamRef.current = queryParam;
    }
  }, [queryParam]);

  useEffect(() => {
    if (recipeParam === 'rrf' || recipeParam === 'graph-chat') {
      setRecipe(recipeParam);
    }
  }, [recipeParam]);

  useEffect(() => {
    if (!selectedCollectionId) return;
    fetchSourceConnections(selectedCollectionId);
  }, [fetchSourceConnections, selectedCollectionId]);

  useEffect(() => {
    if (!selectedCollectionId) {
      setForgeSummary(null);
      return;
    }

    let cancelled = false;
    setIsForgeLoading(true);
    apiClient
      .get(`/context-forge/databases/${selectedCollectionId}`)
      .then(async (apiResponse) => {
        if (!apiResponse.ok) throw new Error('Forge summary unavailable');
        const data = (await apiResponse.json()) as ContextForgeSummary;
        if (!cancelled) setForgeSummary(data);
      })
      .catch(() => {
        if (!cancelled) setForgeSummary(null);
      })
      .finally(() => {
        if (!cancelled) setIsForgeLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedCollectionId]);

  useEffect(() => {
    if (!selectedCollectionId) {
      setIntelligenceSummary(null);
      return;
    }

    let cancelled = false;
    setIsIntelligenceLoading(true);
    fetchContextIntelligence(selectedCollectionId)
      .then((summary) => {
        if (!cancelled) setIntelligenceSummary(summary);
      })
      .catch(() => {
        if (!cancelled) setIntelligenceSummary(null);
      })
      .finally(() => {
        if (!cancelled) setIsIntelligenceLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedCollectionId]);

  const selectedCollection = useMemo(
    () => collections.find((collection) => collection.readable_id === selectedCollectionId) || null,
    [collections, selectedCollectionId]
  );

  const selectedConnections = selectedCollectionId ? sourceConnections[selectedCollectionId] || [] : [];
  const primaryConnection = selectedConnections[0] || null;
  const primaryForgeSource = forgeSummary?.sources?.[0] || null;

  const databaseName = selectedCollection?.name || forgeSummary?.name || selectedCollectionId || 'Choose database';
  const sourceName = primaryConnection?.name || primaryForgeSource?.source_name || 'no source connected';
  const sourceShortName = primaryConnection?.short_name || primaryForgeSource?.provider || 'postgresql';
  const primaryIntelSource = intelligenceSummary?.sources?.[0] || null;
  const cursorField = primaryIntelSource?.cursor_field || primaryForgeSource?.cursor_field || 'current';
  const responseMetrics = toRecord(response?.decision_tree?.metrics);
  const temporalFacts = response
    ? metricNumber(response.temporal_context?.current_facts ?? responseMetrics.temporal_facts, 0)
    : metricNumber(intelligenceSummary?.totals?.temporal_facts, 0);
  const supersededFacts = response
    ? metricNumber(response.temporal_context?.superseded_facts, 0)
    : metricNumber(intelligenceSummary?.totals?.superseded_facts, 0);
  const lineageEdgeCount = response
    ? metricNumber(response.lineage_context?.edge_count ?? responseMetrics.lineage_edges, 0)
    : metricNumber(intelligenceSummary?.totals?.lineage_edges, 0);
  const decisionPrimitiveCount = response
    ? metricNumber(response.context_metadata?.native_decision_count ?? responseMetrics.native_decisions ?? response.decision_history?.length, 0)
    : metricNumber(intelligenceSummary?.totals?.decisions, 0);
  const queryDecisionTraceCount = response
    ? metricNumber(response.context_metadata?.query_trace_count ?? responseMetrics.query_traces ?? (response.context_metadata?.query_id ? 1 : 0), 0)
    : metricNumber(intelligenceSummary?.totals?.query_traces, 0);
  const decisionAuditCount = response
    ? Math.max(
        metricNumber(response.context_metadata?.decision_count, 0),
        metricNumber(responseMetrics.decisions, 0),
        decisionPrimitiveCount + queryDecisionTraceCount
      )
    : decisionPrimitiveCount + queryDecisionTraceCount;
  const driftActiveCount =
    Number(response?.drift_context?.active_count ?? intelligenceSummary?.totals?.active_drift ?? 0);
  const driftSeverity = safeString(response?.drift_context?.severity || intelligenceSummary?.drift?.severity, 'clean');
  const entityCount = forgeSummary
    ? Number(forgeSummary.totals?.entities || primaryForgeSource?.graph?.entity_count || 0)
    : Math.max(
        Number(primaryConnection?.entities?.total_entities || 0),
        Number(primaryConnection?.entity_count || 0)
      );
  const relationshipCount = Math.max(
    Number(forgeSummary?.totals?.neo4j_edges || 0),
    Number(primaryForgeSource?.graph?.neo4j_edges || 0)
  );
  const graphNodeCount = forgeSummary
    ? Number(forgeSummary.totals?.neo4j_nodes || primaryForgeSource?.graph?.neo4j_nodes || 0)
    : Number(response?.context_metadata?.node_count || 0);
  const pendingEvents = forgeSummary?.totals?.pending_events || 0;
  const tokenEstimate = estimateTokens(queryText, response);
  const tokenBudget = Math.max(1, metricNumber(response?.context_metadata?.token_limit, 4000));
  const budgetPercent = Math.min(100, Math.round((tokenEstimate / tokenBudget) * 100));
  const tokensRemaining = Math.max(0, metricNumber(response?.context_metadata?.token_remaining, tokenBudget - tokenEstimate));
  const budgetRemainingPercent = Math.max(0, Math.round((tokensRemaining / tokenBudget) * 100));
  const displayedLatencyMs = metricNumber(
    response?.context_metadata?.latency_ms ?? response?.decision_tree?.latency_ms,
    latencyMs || 0
  ) || null;
  const traceSteps = useMemo(
    () => createTraceStepsFromDecisionTree(response?.decision_tree, displayedLatencyMs, isRunning, Boolean(error)),
    [displayedLatencyMs, error, isRunning, response?.decision_tree]
  );
  const activePathLabel = fallbackMode ? 'graph-search fallback' : recipe === 'rrf' ? 'RRF graph answer' : 'graph chat';
  const topEntities = useMemo(() => buildRetrievedEntities(response, sourceShortName), [response, sourceShortName]);
  const sourceUsage = useMemo(() => buildSourceUsage(response, sourceShortName), [response, sourceShortName]);
  const visibleSavedQueries = savedQueries.length
    ? savedQueries.slice(0, 4)
    : queryHistory.slice(0, 4).map((item) => ({
        id: item.id,
        title: firstTitle(item.query),
        query: item.query,
        databaseId: item.databaseId,
        createdAt: item.createdAt,
      }));

  const phaseTimings = toRecord(response?.context_metadata?.phase_timings_ms);
  const traceGroups = [
    {
      label: 'Retrieval',
      keys: ['parse', 'seed', 'bfs', 'parse_intent', 'seed_selection', 'graph_expand'],
      tone: 'blue' as TraceTone,
      phaseMs: metricNumber(phaseTimings.retrieval_ms ?? phaseTimings.retrieval, 0),
    },
    {
      label: 'Guards',
      keys: ['rerank', 'feedback', 'feedback_prior', 'temporal_prune', 'lineage_attach', 'decision_lineage', 'drift_guard'],
      tone: 'purple' as TraceTone,
      phaseMs: metricNumber(phaseTimings.intelligence_ms ?? phaseTimings.guards_ms ?? phaseTimings.intelligence, 0),
    },
    {
      label: 'Assemble',
      keys: ['temporal', 'assemble', 'assemble_packet'],
      tone: 'orange' as TraceTone,
      phaseMs:
        metricNumber(phaseTimings.context_ms ?? phaseTimings.context, 0) +
        metricNumber(phaseTimings.synthesis_ms ?? phaseTimings.synthesis, 0),
    },
  ].map((group) => ({ ...group, ms: group.phaseMs || sumStepMs(traceSteps, group.keys) }));
  const hasMeasuredTraceTimings = traceGroups.some((group) => group.ms > 0);

  const contextPacket = useMemo(
    () => ({
      audit_id: auditId,
      recipe,
      path: response?.context_metadata?.path_used || activePathLabel,
      scope: {
        database: selectedCollection?.readable_id || null,
        database_name: selectedCollection?.name || null,
        source: sourceName,
        temporal: cursorField === 'current' ? 'now' : `cursor:${cursorField}`,
        filter: 'type:entity',
        cohort: 'all',
      },
      query: stripMentions(queryText),
      retrieved: {
        entities: topEntities.map((entity) => ({
          node_id: entity.id,
          name: entity.label,
          type: entity.type,
          table: entity.table,
          score: entity.score,
        })),
        node_count: response?.context_metadata?.node_count || 0,
        edge_count: response?.context_metadata?.edge_count || 0,
        search_result_count: response?.context_metadata?.search_result_count || 0,
      },
      temporal_context: response?.temporal_context || intelligenceSummary?.temporal || {},
      lineage_context: response?.lineage_context || intelligenceSummary?.lineage || {},
      decision_history: response?.decision_history || intelligenceSummary?.decisions?.recent || [],
      drift_context: response?.drift_context || intelligenceSummary?.drift || {},
      tool_context:
        response?.tool_context ||
        response?.context_metadata?.context_tools || {
          requested: activeContextTools,
          applied: activeContextTools,
        },
      decision_tree: response?.decision_tree || {},
      subgraph_sample: {
        nodes: response?.subgraph?.nodes?.slice(0, 8) || [],
        edges: response?.subgraph?.edges?.slice(0, 8) || [],
      },
      token_budget: {
        estimated: tokenEstimate,
        limit: tokenBudget,
        remaining: tokensRemaining,
        used_percent: budgetPercent,
        remaining_percent: budgetRemainingPercent,
      },
      phase_timings_ms: response?.context_metadata?.phase_timings_ms || {},
    }),
    [
      activePathLabel,
      activeContextTools,
      auditId,
      cursorField,
      queryText,
      recipe,
      response,
      selectedCollection?.name,
      selectedCollection?.readable_id,
      sourceName,
      intelligenceSummary,
      budgetPercent,
      budgetRemainingPercent,
      tokenEstimate,
      tokenBudget,
      tokensRemaining,
      topEntities,
    ]
  );

  const toggleMention = (token: string) => {
    setQueryText((current) => {
      if (new RegExp(`${token}\\b`, 'i').test(current)) return removeMention(current, token);
      return `${token} ${current}`.trim();
    });
  };

  const persistHistory = (next: QueryHistoryItem[]) => {
    const trimmed = next.slice(0, 20);
    setQueryHistory(trimmed);
    writeQueryHistory(trimmed);
  };

  const openSavedQuery = (item: SavedQuery) => {
    setQueryText(item.query);
    setSelectedCollectionId(item.databaseId);
    setRecipe(item.recipe || 'rrf');
    setShowHistory(false);
    navigate(queryConsoleUrl(item));
  };

  const handleCollectionChange = (nextCollectionId: string) => {
    setSelectedCollectionId(nextCollectionId);
    if (routeDatabaseId) {
      const params = new URLSearchParams(searchParams);
      params.delete('database');
      navigate(`/databases/${nextCollectionId}/query${params.toString() ? `?${params.toString()}` : ''}`);
    }
  };

  const runQuery = async () => {
    if (!selectedCollectionId || !queryText.trim()) {
      toast.error('Choose a database and enter a query first.');
      return;
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const nextAuditId = createAuditId();
    setAuditId(nextAuditId);
    setIsRunning(true);
    setError(null);
    setLatencyMs(null);
    setCopied(false);
    setFallbackMode(false);

    const started = performance.now();
    try {
      const cleanQuery = stripMentions(queryText.trim());
      const contextTools = parseContextTools(queryText);
      const request = {
        message: cleanQuery,
        history: [],
        max_depth: contextTools.includes('graph') ? 2 : 1,
        search_limit: 12,
        max_context_tokens: tokenBudget,
        include_subgraph: contextTools.includes('graph'),
        include_lineage: true,
        context_tools: contextTools,
        temporal_mode: 'current' as const,
      };

      let result: GraphChatResponse;
      try {
        result =
          recipe === 'rrf' || contextTools.includes('search')
            ? await graphChatSearch(selectedCollectionId, request, controller.signal)
            : await graphChat(selectedCollectionId, request, controller.signal);
        const emptyRetrieval =
          !result.entity_references?.length &&
          !result.search_results?.length &&
          !(result.context_metadata?.node_count || result.context_metadata?.edge_count);
        if (emptyRetrieval) {
          result = await runRawGraphSearch(selectedCollectionId, cleanQuery, controller.signal, contextTools);
          setFallbackMode(true);
        }
      } catch {
        result = await runRawGraphSearch(selectedCollectionId, cleanQuery, controller.signal, contextTools);
        setFallbackMode(true);
        toast.warning('AI synthesis was unavailable. Showing deterministic graph retrieval.');
      }

      const elapsed = performance.now() - started;
      setLatencyMs(elapsed);
      setResponse(result);
      setFeedback(null);
      fetchContextIntelligence(selectedCollectionId)
        .then(setIntelligenceSummary)
        .catch(() => undefined);

      const historyItem: QueryHistoryItem = {
        id: nextAuditId,
        query: queryText.trim(),
        databaseId: selectedCollectionId,
        databaseName: selectedCollection?.name || selectedCollectionId,
        createdAt: new Date().toISOString(),
        latencyMs: elapsed,
        resultCount: result.context_metadata?.search_result_count || result.entity_references.length || 0,
        recipe,
      };
      persistHistory([historyItem, ...queryHistory.filter((item) => item.id !== nextAuditId)]);
    } catch (err) {
      if (controller.signal.aborted) return;
      const message = err instanceof Error ? err.message : 'Query failed';
      setError(message);
      setLatencyMs(performance.now() - started);
      toast.error('Query failed', { description: message });
    } finally {
      if (!controller.signal.aborted) setIsRunning(false);
    }
  };

  const saveQuery = () => {
    if (!queryText.trim()) return;
    const saved: SavedQuery = {
      id: createAuditId(),
      title: firstTitle(queryText),
      query: queryText.trim(),
      databaseId: selectedCollectionId,
      databaseName: selectedCollection?.name || selectedCollectionId,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      recipe,
      lastRunAt: response ? new Date().toISOString() : undefined,
      latencyMs,
      resultCount: response?.context_metadata?.search_result_count || topEntities.length || null,
      rating: feedback,
    };
    const next = [saved, ...savedQueries].slice(0, 20);
    setSavedQueries(next);
    writeSavedQueries(next);
    toast.success('Query saved');
  };

  const copyPacket = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(contextPacket, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      toast.error('Could not copy context packet');
    }
  };

  const submitRating = async (value: number) => {
    if (!selectedCollectionId || !response) {
      toast.error('Run a query before rating the answer.');
      return;
    }

    setFeedback(value);
    setIsFeedbackSaving(true);
    try {
      const nodeIds = [
        ...(response.subgraph?.nodes?.map((node) => node.id) || []),
        ...topEntities.map((entity) => entity.id),
      ].filter(Boolean);
      const result = await submitQueryFeedback(selectedCollectionId, {
        query_id: response.context_metadata?.query_id || null,
        rating: value,
        retrieved_node_ids: Array.from(new Set(nodeIds)).slice(0, 250),
      });
      toast.success('Feedback applied to ContextD memory', {
        description: `${result.updated_facts} facts updated · weight ${result.new_average_weight ?? result.target_weight}`,
      });
      fetchContextIntelligence(selectedCollectionId)
        .then(setIntelligenceSummary)
        .catch(() => undefined);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Could not save feedback';
      toast.error('Feedback failed', { description: message });
    } finally {
      setIsFeedbackSaving(false);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-background text-foreground">
      <header className="shrink-0 border-b border-border bg-background px-4 py-2.5">
        <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-primary/20 bg-primary/10 text-primary">
              <Database className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="truncate text-base font-semibold tracking-normal text-foreground">{databaseName}</h1>
                <span className="inline-flex h-6 items-center gap-1.5 rounded-md border border-emerald-500/20 bg-emerald-500/10 px-2 text-xs font-medium text-emerald-700 dark:text-emerald-300">
                  <StatusDot />
                  {graphNodeCount || relationshipCount ? 'healthy' : 'ready'}
                </span>
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-2 font-mono text-[10.5px] text-muted-foreground">
                <span>retrieval · {recipe === 'rrf' ? 'RRF' : 'Context chat'}</span>
                <span>·</span>
                <span>latency {displayedLatencyMs ? formatMs(displayedLatencyMs) : 'ready'}</span>
                <span>·</span>
                <span>packet {compactNumber(tokenEstimate)} / {compactNumber(tokenBudget)}</span>
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => setShowHistory((current) => !current)}>
              <History className="h-4 w-4" />
              History
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => selectedCollectionId && navigate(`/databases/${selectedCollectionId}/lineage`)}
              disabled={!selectedCollectionId}
            >
              <GitBranch className="h-4 w-4" />
              Lineage
            </Button>
            <Button
              size="sm"
              onClick={saveQuery}
              className="border border-primary bg-primary text-primary-foreground hover:bg-primary/90"
            >
              <Bookmark className="h-4 w-4" />
              Save query
            </Button>
          </div>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 xl:grid-cols-[160px_minmax(0,1fr)]">
        <aside className="hidden min-h-0 overflow-y-auto border-r border-border bg-background p-3 xl:block">
          <div className="space-y-5">
            <div>
              <div className="mb-1.5 px-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                Operate
              </div>
              <div className="space-y-0.5">
                <RailItem icon={GaugeCircle} label="Overview" onClick={() => selectedCollectionId && navigate(`/databases/${selectedCollectionId}`)} />
                <RailItem icon={Plug} label="Sources" count={String(selectedConnections.length)} onClick={() => selectedCollectionId && navigate(`/databases/${selectedCollectionId}/sources`)} />
                <RailItem icon={Table2} label="Schema" onClick={() => selectedCollectionId && navigate(`/databases/${selectedCollectionId}/schema`)} />
                <RailItem icon={Layers} label="Entities" count={compactNumber(entityCount)} onClick={() => selectedCollectionId && navigate(`/databases/${selectedCollectionId}/entities`)} />
                <RailItem icon={Network} label="Graph" count={compactNumber(relationshipCount)} onClick={() => navigate(`/graph${selectedCollectionId ? `?database=${selectedCollectionId}` : ''}`)} />
                <RailItem icon={TerminalSquare} label="Query" active />
              </div>
            </div>

            <div>
              <div className="mb-1.5 px-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                Inspect
              </div>
              <div className="space-y-0.5">
                <RailItem icon={Clock} label="Temporal" count={temporalFacts ? compactNumber(temporalFacts) : (cursorField === 'current' ? 'now' : cursorField)} onClick={() => selectedCollectionId && navigate(`/databases/${selectedCollectionId}/temporal`)} />
                <RailItem icon={Route} label="Lineage" count={lineageEdgeCount ? compactNumber(lineageEdgeCount) : undefined} onClick={() => selectedCollectionId && navigate(`/databases/${selectedCollectionId}/lineage`)} />
                <RailItem icon={ShieldCheck} label="Decisions" count={decisionAuditCount ? compactNumber(decisionAuditCount) : '0'} onClick={() => selectedCollectionId && navigate(`/databases/${selectedCollectionId}/decisions`)} />
                <RailItem icon={AlertCircle} label="Drift" count={driftActiveCount ? compactNumber(driftActiveCount) : driftSeverity} onClick={() => selectedCollectionId && navigate(`/databases/${selectedCollectionId}/drift`)} />
              </div>
            </div>

            <div>
              <div className="mb-1.5 px-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                Build
              </div>
              <div className="space-y-0.5">
                <RailItem icon={Sparkles} label="Forge" onClick={() => selectedCollectionId && navigate(`/databases/${selectedCollectionId}/forge`)} />
                <RailItem icon={Users} label="Resolver" />
                <RailItem icon={Boxes} label="Cores" />
              </div>
            </div>

            <div>
              <div className="mb-1.5 px-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                Saved queries
              </div>
              <div className="space-y-0.5">
                {visibleSavedQueries.length ? (
                  visibleSavedQueries.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => openSavedQuery(item)}
                      className="block w-full truncate rounded-md px-2 py-1.5 text-left text-[11.5px] text-muted-foreground hover:bg-muted hover:text-foreground"
                      title={item.title}
                    >
                      {item.title}
                    </button>
                  ))
                ) : (
                  <div className="rounded-md border border-dashed border-border px-2 py-2 text-[11.5px] leading-5 text-muted-foreground">
                    Save a query to pin it here.
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => navigate('/saved-queries')}
                  className="mt-1 block w-full rounded-md px-2 py-1.5 text-left text-[11px] font-medium text-primary hover:bg-primary/10"
                >
                  View library
                </button>
              </div>
            </div>
          </div>
        </aside>

        <div className="grid min-h-0 min-w-0 xl:grid-cols-[minmax(0,1fr)_322px]">
          <main className="min-h-0 min-w-0 overflow-y-auto border-r border-border">
            {showHistory && (
              <section className="border-b border-border bg-muted/20 px-4 py-3">
                <div className="mb-2 flex items-center justify-between gap-3">
                  <div>
                    <h2 className="text-sm font-semibold text-foreground">Recent context queries</h2>
                    <p className="text-xs text-muted-foreground">{savedQueries.length} saved · {queryHistory.length} recent runs</p>
                  </div>
                  <Button variant="ghost" size="sm" onClick={() => setShowHistory(false)}>
                    Close
                  </Button>
                </div>
                <div className="grid gap-2 md:grid-cols-2 2xl:grid-cols-3">
                  {[...savedQueries.slice(0, 3), ...queryHistory.slice(0, 3).map((item) => ({
                    id: item.id,
                    title: firstTitle(item.query),
                    query: item.query,
                    databaseId: item.databaseId,
                    createdAt: item.createdAt,
                  }))].slice(0, 6).map((item) => (
                    <button
                      key={item.id}
                      onClick={() => openSavedQuery(item)}
                      className="rounded-md border border-border bg-background p-3 text-left transition hover:border-primary/40 hover:bg-primary/5"
                    >
                      <p className="line-clamp-1 text-sm font-medium text-foreground">{item.title}</p>
                      <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">{item.query}</p>
                    </button>
                  ))}
                </div>
              </section>
            )}

            <div className="space-y-3 p-3">
              <section className="overflow-hidden rounded-lg border border-border bg-background shadow-sm">
                <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_238px] lg:divide-x lg:divide-border">
                  <div className="min-w-0 px-3 py-2">
                    <div className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                      <span>Route</span>
                      <span className="h-px flex-1 bg-border" />
                    </div>
                    <div className="grid min-w-0 gap-2 md:grid-cols-[minmax(220px,330px)_minmax(0,1fr)] md:items-center">
                      <Select value={selectedCollectionId} onValueChange={handleCollectionChange}>
                        <SelectTrigger className="h-9 w-full rounded-md border-primary/20 bg-primary/10 px-2.5 text-sm font-semibold text-primary">
                          <SelectValue placeholder={isLoading ? 'Loading databases...' : 'Choose database'} />
                        </SelectTrigger>
                        <SelectContent>
                          {collections.map((collection) => (
                            <SelectItem key={collection.readable_id} value={collection.readable_id}>
                              {collection.name || collection.readable_id}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <div className="flex min-w-0 flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                        <span className="inline-flex h-8 min-w-0 max-w-[150px] items-center gap-1.5 rounded-md border border-border bg-muted/30 px-2">
                          <SourceIcon shortName={sourceShortName} className="h-3.5 w-3.5 shrink-0" />
                          <span className="truncate">{sourceName}</span>
                        </span>
                        <span className="inline-flex h-8 min-w-0 max-w-[150px] items-center gap-1.5 rounded-md border border-border bg-muted/30 px-2">
                          <Clock className="h-3.5 w-3.5 shrink-0 text-primary" />
                          <span className="truncate">{cursorField === 'current' ? 'current view' : cursorField}</span>
                        </span>
                        <span className="inline-flex h-8 min-w-0 items-center gap-1.5 rounded-md border border-border bg-muted/30 px-2">
                          <Network className="h-3.5 w-3.5 shrink-0 text-primary" />
                          <span className="truncate">{compactNumber(graphNodeCount || entityCount)} nodes</span>
                        </span>
                      </div>
                    </div>
                  </div>
                  <div className="flex min-w-0 flex-col justify-center gap-2 border-t border-border px-3 py-2 lg:border-t-0">
                    <div className="flex min-h-5 items-center justify-between gap-2">
                      <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                        Answer
                      </span>
                      <span className="inline-flex h-5 items-center gap-1 rounded-full bg-primary/10 px-2 text-[10px] font-medium text-primary">
                        <StatusDot tone="orange" />
                        {activeContextTools.length} tools
                      </span>
                    </div>
                    <div className="grid items-center gap-2">
                      <Select value={recipe} onValueChange={(value) => setRecipe(value as Recipe)}>
                        <SelectTrigger className="h-8 w-full rounded-md border-border bg-background text-sm">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="rrf">Recipe · RRF</SelectItem>
                          <SelectItem value="graph-chat">Recipe · Context chat</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                </div>
              </section>

              <QueryPanel
                title="Context prompt"
                icon={Search}
                actions={<span className="font-mono text-[11px] text-muted-foreground">{auditId}</span>}
              >
                <div className="px-4 py-3">
                  <div className="flex items-start gap-2">
                    <span className="mt-1 select-none font-mono text-sm text-primary">&gt;</span>
                    <Textarea
                      value={queryText}
                      onChange={(event) => setQueryText(event.target.value)}
                      onKeyDown={(event) => {
                        if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
                          event.preventDefault();
                          runQuery();
                        }
                      }}
                      spellCheck={false}
                      className="min-h-[72px] resize-none border-0 bg-transparent p-0 font-mono text-[13px] leading-6 text-foreground shadow-none outline-none placeholder:text-muted-foreground selection:bg-primary/20 focus-visible:ring-0"
                      placeholder="@search @graph find customers with open risks"
                    />
                  </div>
                </div>
                <div className="flex flex-col gap-2 border-t border-border bg-muted/20 px-3 py-2 xl:flex-row xl:items-center">
                  <div className="flex min-w-0 flex-1 items-center gap-1.5 overflow-x-auto pb-0.5 xl:pb-0">
                    <span className="mr-1 shrink-0 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                      Lanes
                    </span>
                    {contextToolDefinitions.map((tool) => {
                      const Icon = tool.icon;
                      const isActive = activeContextTools.includes(tool.key);
                      return (
                      <button
                        key={tool.key}
                        type="button"
                        onClick={() => toggleMention(tool.token)}
                        title={tool.purpose}
                        aria-pressed={isActive}
                        aria-label={`${isActive ? 'Remove' : 'Add'} ${tool.label} context tool`}
                        className={cn(
                          'inline-flex h-7 shrink-0 items-center gap-1 rounded-md border px-2 font-mono text-[11px] transition',
                          isActive
                            ? 'border-primary/25 bg-primary/10 text-primary'
                            : 'border-border bg-background text-muted-foreground hover:border-primary/30 hover:text-primary'
                        )}
                      >
                        <Icon className="h-3 w-3" />
                        {tool.token}
                      </button>
                      );
                    })}
                    <span className="ml-1 hidden max-w-[180px] truncate text-[11px] text-muted-foreground 2xl:block">
                      {activeContextToolLabels.length
                        ? activeContextToolLabels.join(' · ')
                        : 'select packet lanes'}
                    </span>
                  </div>
                  <div className="flex shrink-0 flex-col gap-2 rounded-md border border-border bg-background/90 p-1.5 shadow-sm sm:flex-row sm:items-center sm:justify-end">
                    <div className="flex min-w-0 items-center gap-2 rounded-md bg-muted/35 px-2.5 py-1.5">
                      <span className="text-xs font-medium text-muted-foreground">Packet</span>
                      <div className="h-2 w-24 rounded-full bg-background sm:w-28">
                        <div className="h-full rounded-full bg-primary" style={{ width: `${budgetPercent}%` }} />
                      </div>
                      <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
                        {compactNumber(tokenEstimate)} / {compactNumber(tokenBudget)}
                      </span>
                    </div>
                    <div className="hidden items-center gap-1 px-1 text-[10px] text-muted-foreground 2xl:flex">
                      <span className="rounded border border-border bg-background px-1.5 py-0.5 font-mono">⌘</span>
                      <span className="rounded border border-border bg-background px-1.5 py-0.5 font-mono">↵</span>
                    </div>
                    <Button
                      onClick={runQuery}
                      disabled={isRunning || !selectedCollectionId}
                      size="sm"
                      className="h-9 min-w-[104px] rounded-md border border-primary bg-primary px-4 text-primary-foreground shadow-sm shadow-primary/15 hover:bg-primary/90"
                    >
                      {isRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                      Run
                    </Button>
                  </div>
                </div>
              </QueryPanel>

              <QueryPanel
                title="Answer"
                icon={Sparkles}
                meta={`${activePathLabel} · context packet attached`}
                actions={
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="inline-flex h-6 items-center gap-1 rounded-md border border-emerald-500/20 bg-emerald-500/10 px-2 text-[11px] font-medium text-emerald-700 dark:text-emerald-300">
                      ★ {feedback || '—'}
                    </span>
                    <span className="inline-flex h-6 items-center rounded-md border border-blue-500/20 bg-blue-500/10 px-2 font-mono text-[11px] text-blue-700 dark:text-blue-300">
                      {displayedLatencyMs ? formatMs(displayedLatencyMs) : 'ready'}
                    </span>
                    <span className="inline-flex h-6 items-center rounded-md border border-emerald-500/20 bg-emerald-500/10 px-2 font-mono text-[11px] text-emerald-700 dark:text-emerald-300">
                      {compactNumber(tokensRemaining)} left
                    </span>
                  </div>
                }
              >
                <div className="p-4">
                  {error ? (
                    <div className="rounded-md border border-destructive/25 bg-destructive/5 p-4 text-sm text-destructive">
                      <div className="mb-2 flex items-center gap-2 font-semibold">
                        <AlertCircle className="h-4 w-4" />
                        Query failed
                      </div>
                      {error}
                    </div>
                  ) : isRunning ? (
                    <RunningAnswer />
                  ) : response ? (
                    <div className="prose prose-sm max-w-none dark:prose-invert prose-p:leading-7 prose-li:leading-7">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{response.message}</ReactMarkdown>
                    </div>
                  ) : (
                    <EmptyAnswer onRun={runQuery} disabled={isRunning || !selectedCollectionId} />
                  )}
                </div>
              </QueryPanel>

              <NativeDecisionTrace response={response} traceSteps={traceSteps} latencyMs={displayedLatencyMs} />

              <QueryPanel
                title="Retrieved context"
                meta={`${response?.context_metadata?.search_result_count || topEntities.length || 0} entities · ${sourceUsage.length} sources · ${response?.context_metadata?.edge_count || 0} facts`}
              >
                <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_280px] lg:divide-x lg:divide-border">
                  <div className="px-3 py-3">
                    <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                      Entity matches
                    </div>
                    {topEntities.length ? (
                      <div className="flex flex-wrap gap-1.5">
                        {topEntities.slice(0, 12).map((entity, index) => (
                          <span
                            key={`${entity.id}-${index}`}
                            className={cn(
                              'inline-flex max-w-full items-center gap-1.5 rounded-md border px-2 py-1 text-[11.5px]',
                              index < 4
                                ? 'border-primary/25 bg-primary/10 text-primary'
                                : 'border-blue-500/20 bg-blue-500/10 text-blue-700 dark:text-blue-300'
                            )}
                            title={entity.detail}
                          >
                            <span className="truncate">{entity.label}</span>
                            <span className="font-mono opacity-75">{entity.type}</span>
                          </span>
                        ))}
                      </div>
                    ) : (
                      <div className="rounded-md border border-dashed border-border p-3 text-sm text-muted-foreground">
                        Retrieval details will appear after the first run.
                      </div>
                    )}
                  </div>
                  <div className="px-3 py-3">
                    <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                      Source evidence
                    </div>
                    <ul className="space-y-2 text-sm">
                      {sourceUsage.map((item) => (
                        <li key={item.label} className="flex items-center gap-2">
                          <SourceIcon shortName={item.source} className="h-4 w-4" />
                          <span className="min-w-0 flex-1 truncate">{item.label}</span>
                          <span className="font-mono text-[11px] text-muted-foreground">{item.count}</span>
                        </li>
                      ))}
                    </ul>
                    <div className="mt-2 border-t border-border pt-2 font-mono text-[10.5px] text-muted-foreground">
                      scoped to {sourceName}
                    </div>
                  </div>
                </div>
              </QueryPanel>

              <details className="rounded-lg border border-border bg-background shadow-sm">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 border-b border-border px-3.5 py-2.5">
                  <h2 className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
                    <FileJson className="h-3.5 w-3.5 text-primary" />
                    Context packet JSON
                  </h2>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[11px] text-muted-foreground">
                      JSON · {compactNumber(tokenEstimate)} tokens
                    </span>
                    <Button variant="outline" size="sm" className="h-7" onClick={copyPacket}>
                      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                      {copied ? 'Copied' : 'Copy'}
                    </Button>
                  </div>
                </summary>
                <pre
                  className="max-h-[320px] overflow-auto bg-zinc-950 p-4 font-mono text-[11.5px] leading-6 text-zinc-100"
                  style={{ color: '#F8FAFC' }}
                >
                  {JSON.stringify(contextPacket, null, 2)}
                </pre>
              </details>

              <QueryPanel title="Tune retrieval memory" icon={ThumbsUp} meta="Persists feedback for cited entities and graph facts.">
                <div className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="text-sm text-muted-foreground">
                    Ratings update the query trace and memory prior used by future ContextD retrieval.
                  </div>
                  <div className="flex items-center gap-1">
                    {[1, 2, 3, 4, 5].map((value) => (
                      <button
                        key={value}
                        onClick={() => submitRating(value)}
                        disabled={!response || isFeedbackSaving}
                        className={cn(
                          'rounded-md p-1.5 transition disabled:cursor-not-allowed disabled:opacity-50',
                          feedback && value <= feedback
                            ? 'text-primary'
                            : 'text-muted-foreground hover:text-primary'
                        )}
                        aria-label={`Rate context answer ${value}`}
                      >
                        <Star className={cn('h-4 w-4', feedback && value <= feedback && 'fill-current')} />
                      </button>
                    ))}
                  </div>
                </div>
              </QueryPanel>
            </div>
          </main>

          <aside className="hidden min-h-0 overflow-y-auto bg-muted/15 xl:block">
            <div className="space-y-3 p-3">
              <QueryPanel
                title="Response path"
                meta={`${traceSteps.length} steps`}
                actions={
                  <span className="inline-flex h-6 items-center gap-1 rounded-md border border-blue-500/20 bg-blue-500/10 px-2 font-mono text-[11px] text-blue-700 dark:text-blue-300">
                    <Zap className="h-3 w-3" />
                    {displayedLatencyMs ? formatMs(displayedLatencyMs) : isRunning ? 'running' : 'idle'}
                  </span>
                }
              >
                <ol className="space-y-1.5 px-3 py-3 text-[11.5px]">
                  {traceSteps.map((step, index) => (
                    <li key={step.key} className="flex items-center gap-2">
                      <span
                        className={cn(
                          'inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold',
                          step.status === 'done' && 'bg-emerald-500 text-white',
                          step.status === 'warn' && 'bg-amber-500 text-white',
                          step.status === 'skipped' && 'bg-muted text-muted-foreground',
                          step.status === 'running' && 'bg-primary text-primary-foreground',
                          step.status === 'failed' && 'bg-destructive text-destructive-foreground',
                          step.status === 'pending' && 'bg-muted text-muted-foreground'
                        )}
                      >
                        {step.status === 'done' ? <Check className="h-3 w-3" /> : step.status === 'warn' ? '!' : index + 1}
                      </span>
                      <span className="min-w-0 flex-1 truncate">{step.label}</span>
                      <span className="font-mono text-[10.5px] text-muted-foreground">
                        {step.ms ? formatMs(step.ms) : step.status}
                      </span>
                    </li>
                  ))}
                </ol>
              </QueryPanel>

              <QueryPanel
                title="Guardrails"
                meta={isIntelligenceLoading ? 'refreshing ContextD lanes' : 'temporal · lineage · decisions · drift'}
                actions={
                  <span className={cn(
                    'inline-flex h-6 items-center rounded-md border px-2 text-[11px] font-medium',
                    driftSeverity === 'clean'
                      ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
                      : 'border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300'
                  )}>
                    {driftSeverity}
                  </span>
                }
              >
                <div className="grid grid-cols-2 gap-2 px-3 py-3 text-xs">
                  {[
                    { label: 'Temporal facts', value: compactNumber(temporalFacts), sub: `${compactNumber(supersededFacts)} superseded`, icon: Clock },
                    { label: 'Lineage edges', value: compactNumber(lineageEdgeCount), sub: 'provenance chain', icon: Route },
                    { label: 'Decisions', value: compactNumber(decisionAuditCount), sub: queryDecisionTraceCount ? `${compactNumber(queryDecisionTraceCount)} query traces` : 'first-class audit', icon: ShieldCheck },
                    { label: 'Drift signals', value: compactNumber(driftActiveCount), sub: driftSeverity, icon: AlertCircle },
                  ].map((item) => {
                    const Icon = item.icon;
                    return (
                      <div key={item.label} className="rounded-md border border-border bg-background p-2.5">
                        <div className="flex items-center gap-1.5 text-muted-foreground">
                          <Icon className="h-3.5 w-3.5 text-primary" />
                          <span className="truncate">{item.label}</span>
                        </div>
                        <div className="mt-1 font-mono text-base font-semibold text-foreground">{item.value}</div>
                        <div className="mt-0.5 truncate text-[10.5px] text-muted-foreground">{item.sub}</div>
                      </div>
                    );
                  })}
                </div>
              </QueryPanel>

              <QueryPanel title="Assembly timing" meta={displayedLatencyMs ? formatMs(displayedLatencyMs) : activePathLabel}>
                <div className="space-y-3 px-3 py-3">
                  {hasMeasuredTraceTimings ? (
                    traceGroups.map((group) => {
                      const width = displayedLatencyMs ? Math.min(100, Math.max(8, Math.round((group.ms / displayedLatencyMs) * 100))) : 0;
                      return (
                        <div key={group.label}>
                          <div className="mb-1 flex items-center justify-between text-[11px]">
                            <span className="text-muted-foreground">{group.label}</span>
                            <span className="font-mono text-muted-foreground">{group.ms ? formatMs(group.ms) : '-'}</span>
                          </div>
                          <div className="h-2 rounded-full bg-muted">
                            <div
                              className={cn(
                                'h-full rounded-full',
                                group.tone === 'blue' && 'bg-blue-500',
                                group.tone === 'purple' && 'bg-violet-500',
                                group.tone === 'orange' && 'bg-primary'
                              )}
                              style={{ width: `${width}%` }}
                            />
                          </div>
                        </div>
                      );
                    })
                  ) : (
                    <div className="rounded-md border border-dashed border-border bg-background p-3 text-xs leading-5 text-muted-foreground">
                      Step timings are shown only when the backend emits measured phase durations. The total above is the measured response latency.
                    </div>
                  )}
                </div>
              </QueryPanel>

              <QueryPanel title="Context budget" meta={`${budgetRemainingPercent}% remaining`}>
                <div className="px-3 py-3">
                  <div className="h-2 rounded-full bg-muted">
                    <div className="h-full rounded-full bg-primary" style={{ width: `${budgetPercent}%` }} />
                  </div>
                  <div className="mt-1.5 flex justify-between font-mono text-[10.5px] text-muted-foreground">
                    <span>used {compactNumber(tokenEstimate)}</span>
                    <span>{compactNumber(tokensRemaining)} left of {compactNumber(tokenBudget)}</span>
                  </div>
                </div>
              </QueryPanel>

              <QueryPanel title="Workspace caller" icon={ShieldCheck}>
                <div className="space-y-3 px-3 py-3 text-sm">
                  <div className="flex items-center gap-2.5">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-primary/20 bg-primary/10 text-xs font-semibold text-primary">
                      {(currentOrganization?.name || 'Superuser').slice(0, 2).toUpperCase()}
                    </div>
                    <div className="min-w-0">
                      <div className="truncate font-medium text-foreground">{currentOrganization?.name || 'Superuser'}</div>
                      <div className="truncate font-mono text-[10.5px] text-muted-foreground">owner · audit {auditId.slice(-8)}</div>
                    </div>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    className="w-full justify-between"
                    disabled={!selectedCollectionId}
                    onClick={() => selectedCollectionId && navigate(`/databases/${selectedCollectionId}`)}
                  >
                    Open database
                    <ArrowRight className="h-4 w-4" />
                  </Button>
                </div>
              </QueryPanel>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}

export default QueryConsolePage;
