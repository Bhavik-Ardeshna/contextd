import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  Check,
  Clock3,
  Database,
  GitBranch,
  Loader2,
  MoreHorizontal,
  Play,
  Plug,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  Table2,
  Upload,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { apiClient, clearApiResponseCache } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useTheme } from "@/lib/theme-provider";
import { useCollectionsStore } from "@/lib/stores/collections";
import { useUsageStore } from "@/lib/stores/usage";
import { useCollectionCreationStore } from "@/stores/collectionCreationStore";
import { cn } from "@/lib/utils";
import { getAppIconUrl } from "@/lib/utils/icons";
import type { Collection, SourceConnection } from "@/lib/stores/collections";
import { toast } from "sonner";

const itemsPerPage = 24;
const DASHBOARD_REFRESH_INTERVAL_MS = 60_000;
const DASHBOARD_STATUS_TTL_MS = 60_000;
const FORGE_SUMMARY_TTL_MS = 120_000;
const FORGE_SUMMARY_CONCURRENCY = 4;
const TRANSITION_REFRESH_INTERVAL_MS = 8_000;
const TRANSITION_ACTIVE_WINDOW_MS = 10 * 60_000;

type RichSourceConnection = SourceConnection & {
  entity_count?: number | string;
  entities_count?: number | string;
  total_entities?: number | string;
  edge_count?: number | string;
  edges_count?: number | string;
  total_edges?: number | string;
  entities?: {
    total_entities?: number | string;
    entity_count?: number | string;
    total_edges?: number | string;
    edge_count?: number | string;
  };
  last_job_status?: string;
  last_sync_status?: string;
  sync_status?: string;
  connection_status?: string;
  last_sync_at?: string;
  last_synced_at?: string;
  last_sync_started_at?: string;
  last_sync_job_completed_at?: string;
  last_sync_job_started_at?: string;
  last_sync_job?: {
    status?: string;
    started_at?: string | null;
    completed_at?: string | null;
  } | null;
  sync?: {
    last_job?: {
      status?: string;
      started_at?: string | null;
      completed_at?: string | null;
    } | null;
  } | null;
  updated_at?: string;
  modified_at?: string;
  cursor_field?: string;
  cursor?: string;
  drift_status?: string | null;
  drift_summary?: Record<string, unknown> | null;
  drift?: {
    status?: string;
    severity?: string;
    summary?: Record<string, unknown>;
  } | null;
};

type RichCollection = Collection & {
  entity_count?: number | string;
  entities_count?: number | string;
  total_entities?: number | string;
  edge_count?: number | string;
  edges_count?: number | string;
  total_edges?: number | string;
  updated_at?: string;
  modified_at?: string;
};

type StatusTone = "green" | "blue" | "amber" | "red" | "muted";

type ContextForgeGraphSummary = {
  entity_count?: number;
  graph_events_total?: number;
  nodes_committed?: number;
  edges_committed?: number;
  neo4j_nodes?: number;
  neo4j_edges?: number;
  events_pending?: number;
  events_failed?: number;
  events_skipped?: number;
};

type ContextForgeSourceSummary = {
  source_connection_id: string;
  source_name: string;
  provider: string;
  status?: string;
  graph?: ContextForgeGraphSummary;
  mappings?: Array<{ foreign_keys?: number }>;
};

type ContextForgeSummary = {
  generated_at?: string;
  totals?: Record<string, number | string | undefined>;
  sources?: ContextForgeSourceSummary[];
};

type DashboardNativeStatus = {
  drift?: {
    active_count?: number;
    severity?: string;
    status?: string;
  };
  graph?: {
    pending_events?: number;
    failed_events?: number;
  };
};

const formatCount = (value?: number | null) => {
  const number = value || 0;
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(1)}M`;
  if (number >= 1_000) return `${(number / 1_000).toFixed(number >= 100_000 ? 0 : 1)}K`;
  return number.toLocaleString();
};

const getNumeric = (...values: unknown[]) => {
  for (const value of values) {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim() !== "") {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return 0;
};

const normalizeStatus = (connection?: RichSourceConnection) =>
  (
    connection?.sync?.last_job?.status ||
    connection?.last_sync_job?.status ||
    connection?.last_job_status ||
    connection?.last_sync_status ||
    connection?.sync_status ||
    connection?.connection_status ||
    connection?.status ||
    ""
  ).toLowerCase();

const activeSyncStatuses = new Set(["created", "pending", "queued", "running", "syncing", "indexing", "in_progress", "cancelling"]);
const completedSyncStatuses = new Set(["completed"]);

const getLatestJobStatus = (connection?: RichSourceConnection) =>
  String(
    connection?.sync?.last_job?.status ||
      connection?.last_sync_job?.status ||
      connection?.last_job_status ||
      connection?.last_sync_status ||
      ""
  ).toLowerCase();

const isConnectionSyncRunning = (connection?: RichSourceConnection) => {
  const status = getLatestJobStatus(connection) || normalizeStatus(connection);
  return Array.from(activeSyncStatuses).some((token) => status === token || status.includes(token));
};

const isConnectionSyncComplete = (
  connection: RichSourceConnection | undefined,
  summary: ContextForgeSummary | undefined,
  source: ContextForgeSourceSummary | undefined,
  entityCount: number
) => {
  if (!connection) return false;
  if (hasCommittedForgeGraph(summary, source, entityCount)) return true;
  if (getLastSuccessfulSyncDate(connection)) return true;
  if (isConnectionSyncRunning(connection)) return false;
  const status = getLatestJobStatus(connection);
  return (
    completedSyncStatuses.has(status) ||
    Boolean(connection.sync?.last_job?.completed_at || connection.last_sync_job?.completed_at) ||
    Boolean(getNumeric(summary?.totals?.entities, source?.graph?.entity_count, entityCount) > 0)
  );
};

const getLastSyncDate = (connection?: RichSourceConnection, collection?: RichCollection) =>
  connection?.sync?.last_job?.completed_at ||
  connection?.last_sync_job?.completed_at ||
  connection?.last_sync_job_completed_at ||
  connection?.last_sync_at ||
  connection?.last_synced_at ||
  connection?.sync?.last_job?.started_at ||
  connection?.last_sync_job?.started_at ||
  connection?.last_sync_started_at ||
  connection?.last_sync_job_started_at ||
  connection?.updated_at ||
  connection?.modified_at ||
  collection?.updated_at ||
  collection?.modified_at ||
  null;

const getLastSuccessfulSyncDate = (connection?: RichSourceConnection) =>
  connection?.sync?.last_job?.completed_at ||
  connection?.last_sync_job?.completed_at ||
  connection?.last_sync_job_completed_at ||
  connection?.last_sync_at ||
  connection?.last_synced_at ||
  null;

const hasRecentSyncActivity = (connection: RichSourceConnection | undefined, nowMs: number) => {
  const lastActivity = getLastSyncDate(connection);
  if (!lastActivity) return false;
  const timestamp = Date.parse(lastActivity);
  return Number.isFinite(timestamp) && nowMs - timestamp <= TRANSITION_ACTIVE_WINDOW_MS;
};

const formatRelativeTime = (dateValue?: string | null) => {
  if (!dateValue) return "never";
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/.test(dateValue) ? dateValue : `${dateValue}Z`;
  const time = new Date(normalized).getTime();
  if (Number.isNaN(time)) return "never";

  const diffSeconds = Math.max(0, Math.floor((Date.now() - time) / 1000));
  if (diffSeconds < 60) return "just now";

  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes}m ago`;

  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;

  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 30) return `${diffDays}d ago`;

  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(normalized));
};

const getDisplayName = (user: any) => {
  const rawName = user?.name || user?.full_name || user?.email || "Superuser";
  if (rawName.includes("@")) {
    const localPart = rawName.split("@")[0] || "Superuser";
    return localPart
      .split(/[._-]/)
      .filter(Boolean)
      .map((part: string) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ");
  }
  return String(rawName).split(" ")[0] || "Superuser";
};

const getGreeting = (date: Date) => {
  const hour = date.getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
};

const getConnectionEntityCount = (connection?: RichSourceConnection) =>
  getNumeric(
    connection?.entity_count,
    connection?.entities_count,
    connection?.total_entities,
    connection?.entities?.total_entities,
    connection?.entities?.entity_count
  );

const getConnectionEdgeCount = (connection?: RichSourceConnection) =>
  getNumeric(
    connection?.edge_count,
    connection?.edges_count,
    connection?.total_edges,
    connection?.entities?.total_edges,
    connection?.entities?.edge_count
  );

const getCollectionEntityCount = (collection: RichCollection) =>
  getNumeric(collection.entity_count, collection.entities_count, collection.total_entities);

const getCollectionEdgeCount = (collection: RichCollection) =>
  getNumeric(collection.edge_count, collection.edges_count, collection.total_edges);

const getForgeMetric = (summary: ContextForgeSummary | undefined, ...keys: string[]) =>
  Math.max(0, ...keys.map((key) => getNumeric(summary?.totals?.[key])));

const sumForgeSourceMetric = (summary: ContextForgeSummary | undefined, key: string) =>
  (summary?.sources || []).reduce((sum, source) => sum + getNumeric(source?.graph?.[key]), 0);

const getCurrentForgeEntityCount = (
  summary: ContextForgeSummary | undefined,
  source?: ContextForgeSourceSummary,
) =>
  getNumeric(summary?.totals?.entities)
  || sumForgeSourceMetric(summary, "entity_count")
  || getNumeric(source?.graph?.entity_count);

const getCurrentForgeEdgeCount = (
  summary: ContextForgeSummary | undefined,
  source?: ContextForgeSourceSummary,
) =>
  getNumeric(summary?.totals?.neo4j_edges)
  || sumForgeSourceMetric(summary, "neo4j_edges")
  || getNumeric(source?.graph?.neo4j_edges);

const getForgeSourceEdges = (source?: ContextForgeSourceSummary) =>
  getNumeric(source?.graph?.neo4j_edges);

const getForgeCommittedNodes = (
  summary: ContextForgeSummary | undefined,
  source?: ContextForgeSourceSummary,
) =>
  getForgeMetric(summary, "neo4j_nodes") ||
  getNumeric(source?.graph?.neo4j_nodes);

const hasCommittedForgeGraph = (
  summary: ContextForgeSummary | undefined,
  source: ContextForgeSourceSummary | undefined,
  entityCount: number,
) => {
  if (!summary || entityCount <= 0) return false;
  if (getForgeMetric(summary, "failed_events") || getNumeric(source?.graph?.events_failed)) {
    return false;
  }
  if (getForgeMetric(summary, "pending_events") || getNumeric(source?.graph?.events_pending)) {
    return false;
  }
  return getForgeCommittedNodes(summary, source) > 0;
};

const getGraphState = (
  connection: RichSourceConnection | undefined,
  entityCount: number,
  summary?: ContextForgeSummary,
  source?: ContextForgeSourceSummary
) => {
  const status = normalizeStatus(connection);
  if (!connection || entityCount === 0) return { label: "empty", tone: "muted" as StatusTone, pulse: false };
  if (status.includes("fail") || status.includes("error")) {
    return { label: "failing", tone: "red" as StatusTone, pulse: false };
  }
  if (getForgeMetric(summary, "failed_events") || getNumeric(source?.graph?.events_failed)) {
    return { label: "failing", tone: "red" as StatusTone, pulse: false };
  }
  if (!summary) {
    return {
      label: completedSyncStatuses.has(getLatestJobStatus(connection)) ? "checking" : "pending",
      tone: "muted" as StatusTone,
      pulse: false,
    };
  }
  if (getForgeMetric(summary, "pending_events") || getNumeric(source?.graph?.events_pending)) {
    return { label: "indexing", tone: "blue" as StatusTone, pulse: true };
  }
  if (hasCommittedForgeGraph(summary, source, entityCount)) {
    return { label: "indexed", tone: "green" as StatusTone, pulse: false };
  }
  if (status.includes("run") || status.includes("pending") || status.includes("progress") || status.includes("sync")) {
    return { label: "indexing", tone: "blue" as StatusTone, pulse: true };
  }
  if (
    summary &&
    !getForgeMetric(summary, "neo4j_nodes") &&
    !getForgeSourceEdges(source)
  ) {
    return { label: "pending", tone: "amber" as StatusTone, pulse: false };
  }
  return { label: "indexed", tone: "green" as StatusTone, pulse: false };
};

const getTemporalState = (
  connection: RichSourceConnection | undefined,
  entityCount: number,
  graphReady = false
) => {
  if (!connection) return { label: "planned", tone: "muted" as StatusTone };
  const status = normalizeStatus(connection);
  if (status.includes("fail") || status.includes("error")) return { label: "partial", tone: "amber" as StatusTone };
  if (entityCount > 0 && graphReady) return { label: "current", tone: "blue" as StatusTone };
  if (isConnectionSyncRunning(connection)) return { label: "updating", tone: "blue" as StatusTone, pulse: true };
  if (entityCount > 0) return { label: "current", tone: "blue" as StatusTone };
  return { label: "planned", tone: "muted" as StatusTone };
};

const getDriftState = (
  connection: RichSourceConnection | undefined,
  nativeStatus?: DashboardNativeStatus,
) => {
  const status = normalizeStatus(connection);
  const driftStatus = String(
    nativeStatus?.drift?.status ||
      connection?.drift?.status ||
      connection?.drift_status ||
      ""
  ).toLowerCase();
  const driftSeverity = String(
    nativeStatus?.drift?.severity ||
      connection?.drift?.severity ||
      ""
  ).toLowerCase();
  const activeDriftCount = getNumeric(nativeStatus?.drift?.active_count);
  if (!connection) return { label: "pending", tone: "muted" as StatusTone };
  if (status.includes("fail") || status.includes("error")) return { label: "failing", tone: "red" as StatusTone };
  if (driftSeverity === "critical") return { label: "critical", tone: "red" as StatusTone };
  if (activeDriftCount > 0 || driftStatus === "changed" || ["warning", "info"].includes(driftSeverity)) {
    return { label: "review", tone: "amber" as StatusTone };
  }
  if (driftStatus === "unknown" || driftSeverity === "unknown") return { label: "checking", tone: "muted" as StatusTone };
  if (status.includes("warning") || status.includes("drift")) return { label: "warning", tone: "amber" as StatusTone };
  return { label: "clean", tone: "green" as StatusTone };
};

const statusClassName = (tone: StatusTone) =>
  cn(
    "inline-flex h-6 items-center gap-1.5 rounded-md border px-2 text-[11px] font-medium leading-none",
    tone === "green" && "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
    tone === "blue" && "border-blue-500/25 bg-blue-500/10 text-blue-700 dark:text-blue-300",
    tone === "amber" && "border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300",
    tone === "red" && "border-destructive/25 bg-destructive/10 text-destructive",
    tone === "muted" && "border-border bg-muted text-muted-foreground"
  );

const StatusBadge = ({
  label,
  tone,
  pulse = false,
}: {
  label: string;
  tone: StatusTone;
  pulse?: boolean;
}) => (
  <span className={statusClassName(tone)}>
    <span
      className={cn(
        "h-1.5 w-1.5 rounded-full",
        tone === "green" && "bg-emerald-500",
        tone === "blue" && "bg-blue-500",
        tone === "amber" && "bg-amber-500",
        tone === "red" && "bg-destructive",
        tone === "muted" && "bg-muted-foreground/50",
        pulse && "animate-pulse"
      )}
    />
    {label}
  </span>
);

const DatabasesPage = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { resolvedTheme } = useTheme();
  const {
    fetchCollectionsPaginated,
    fetchCollectionsCount,
    totalCount,
    sourceConnections,
    fetchSourceConnections,
  } = useCollectionsStore();
  const actionChecks = useUsageStore((state) => state.actionChecks);
  const isCheckingUsage = useUsageStore((state) => state.isLoading);
  const sourceConnectionsAllowed = actionChecks.source_connections?.allowed ?? true;
  const entitiesAllowed = actionChecks.entities?.allowed ?? true;

  const [collections, setCollections] = useState<Collection[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [forgeSummaries, setForgeSummaries] = useState<Record<string, ContextForgeSummary>>({});
  const [dashboardStatuses, setDashboardStatuses] = useState<Record<string, DashboardNativeStatus>>({});
  const forgeSummariesRef = useRef<Record<string, ContextForgeSummary>>({});
  const forgeSummaryFetchedAtRef = useRef<Record<string, number>>({});
  const dashboardStatusFetchedAtRef = useRef<Record<string, number>>({});
  const hasLoadedDatabasesRef = useRef(false);
  const [now, setNow] = useState(() => new Date());
  const [runningConnectionId, setRunningConnectionId] = useState<string | null>(null);

  const startIndex = (currentPage - 1) * itemsPerPage;
  const displayCount = totalCount ?? collections.length;
  const totalPages = Math.max(1, Math.ceil(displayCount / itemsPerPage));
  const displayName = useMemo(() => getDisplayName(user), [user]);
  const greeting = useMemo(() => getGreeting(now), [now]);
  const formattedDate = useMemo(
    () => new Intl.DateTimeFormat(undefined, { weekday: "long", month: "short", day: "numeric" }).format(now),
    [now]
  );
  const formattedTime = useMemo(
    () => new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(now),
    [now]
  );

  const loadDatabases = useCallback(async ({ background = false }: { background?: boolean } = {}) => {
    const showLoading = !background && !hasLoadedDatabasesRef.current;
    if (showLoading) setIsLoading(true);
    try {
      const [, data] = await Promise.all([
        fetchCollectionsCount(debouncedSearchQuery || undefined),
        fetchCollectionsPaginated(
          startIndex,
          itemsPerPage,
          debouncedSearchQuery || undefined
        ),
      ]);
      setCollections(data);
      hasLoadedDatabasesRef.current = true;
    } finally {
      if (showLoading) setIsLoading(false);
    }
  }, [debouncedSearchQuery, fetchCollectionsCount, fetchCollectionsPaginated, startIndex]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearchQuery(searchQuery);
      setCurrentPage(1);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [searchQuery]);

  useEffect(() => {
    void loadDatabases({ background: refreshNonce > 0 || hasLoadedDatabasesRef.current });
  }, [loadDatabases, refreshNonce]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      setRefreshNonce((value) => value + 1);
    }, DASHBOARD_REFRESH_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    const interval = window.setInterval(() => {
      setNow(new Date());
    }, 60_000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    collections.forEach((collection) => {
      if (!Object.prototype.hasOwnProperty.call(sourceConnections, collection.readable_id)) {
        void fetchSourceConnections(collection.readable_id, false);
      }
    });
  }, [collections, fetchSourceConnections, sourceConnections]);

  useEffect(() => {
    let cancelled = false;

    const loadDashboardStatus = async () => {
      if (!collections.length) return;
      const nowMs = Date.now();
      const staleCollections = collections.filter((collection) => {
        const lastFetchedAt = dashboardStatusFetchedAtRef.current[collection.readable_id] || 0;
        return (
          !dashboardStatuses[collection.readable_id] ||
          nowMs - lastFetchedAt > DASHBOARD_STATUS_TTL_MS
        );
      });

      if (!staleCollections.length) return;

      const params = new URLSearchParams();
      staleCollections.forEach((collection) => {
        dashboardStatusFetchedAtRef.current[collection.readable_id] = nowMs;
        params.append("readable_ids", collection.readable_id);
      });

      try {
        const response = await apiClient.get(
          `/collections/dashboard-status?${params.toString()}`,
          undefined,
          { cache: true }
        );
        if (!response.ok) throw new Error("Failed to load dashboard status");
        const data = (await response.json()) as Record<string, DashboardNativeStatus>;
        if (cancelled) return;
        setDashboardStatuses((previous) => ({ ...previous, ...data }));
      } catch {
        staleCollections.forEach((collection) => {
          dashboardStatusFetchedAtRef.current[collection.readable_id] = 0;
        });
      }
    };

    void loadDashboardStatus();

    return () => {
      cancelled = true;
    };
  }, [collections, dashboardStatuses, refreshNonce]);

  useEffect(() => {
    let cancelled = false;

    const loadForgeSummaries = async () => {
      const nowMs = Date.now();
      const staleCollections = collections.filter((collection) => {
        const readableId = collection.readable_id;
        const lastFetchedAt = forgeSummaryFetchedAtRef.current[readableId] || 0;
        return (
          !forgeSummariesRef.current[readableId] ||
          nowMs - lastFetchedAt > FORGE_SUMMARY_TTL_MS
        );
      });

      if (!staleCollections.length) return;

      const entries: Array<readonly [string, ContextForgeSummary] | null> = [];
      for (let index = 0; index < staleCollections.length; index += FORGE_SUMMARY_CONCURRENCY) {
        if (cancelled) return;
        const batch = staleCollections.slice(index, index + FORGE_SUMMARY_CONCURRENCY);
        const batchEntries = await Promise.all(
          batch.map(async (collection) => {
            const readableId = collection.readable_id;
            forgeSummaryFetchedAtRef.current[readableId] = nowMs;
            try {
              const response = await apiClient.get(
                `/context-forge/databases/${readableId}`,
                undefined,
                { cache: true }
              );
              if (!response.ok) return [readableId, { totals: {}, sources: [] }] as const;
              const summary = (await response.json()) as ContextForgeSummary;
              return [readableId, summary] as const;
            } catch {
              return [readableId, { totals: {}, sources: [] }] as const;
            }
          })
        );
        entries.push(...batchEntries);
      }

      if (cancelled || !entries.length) return;

      setForgeSummaries((previous) => {
        const next = { ...previous };
        entries.forEach((entry) => {
          if (entry) next[entry[0]] = entry[1];
        });
        forgeSummariesRef.current = next;
        return next;
      });
    };

    if (collections.length) {
      void loadForgeSummaries();
    }

    return () => {
      cancelled = true;
    };
  }, [collections, refreshNonce]);
  const databaseRows = useMemo(() => {
    return collections.map((collection) => {
      const richCollection = collection as RichCollection;
      const connectionsLoaded = Object.prototype.hasOwnProperty.call(sourceConnections, collection.readable_id);
      const connections = (sourceConnections[collection.readable_id] || []) as RichSourceConnection[];
      const connection = connections[0];
      const forgeSummary = forgeSummaries[collection.readable_id];
      const nativeStatus = dashboardStatuses[collection.readable_id];
      const forgeSource = connection
        ? forgeSummary?.sources?.find((source) => source.source_connection_id === connection.id) || forgeSummary?.sources?.[0]
        : forgeSummary?.sources?.[0];
      const sourceEntityCount = connections.reduce((sum, item) => sum + getConnectionEntityCount(item), 0);
      const sourceEdgeCount = connections.reduce((sum, item) => sum + getConnectionEdgeCount(item), 0);
      const forgeEntityCount = getCurrentForgeEntityCount(forgeSummary, forgeSource);
      const forgeEdgeCount = getCurrentForgeEdgeCount(forgeSummary, forgeSource);
      const entityCount = forgeSummary
        ? forgeEntityCount
        : Math.max(getCollectionEntityCount(richCollection), sourceEntityCount);
      const edgeCount = forgeSummary
        ? forgeEdgeCount
        : Math.max(getCollectionEdgeCount(richCollection), sourceEdgeCount);
      const committedGraphReady = hasCommittedForgeGraph(forgeSummary, forgeSource, entityCount);
      const hasStableBaseline = committedGraphReady || Boolean(getLastSuccessfulSyncDate(connection));
      const pendingGraphEvents = getNumeric(
        nativeStatus?.graph?.pending_events,
        getForgeMetric(forgeSummary, "pending_events"),
        forgeSource?.graph?.events_pending
      );
      const failedGraphEvents = getNumeric(
        nativeStatus?.graph?.failed_events,
        getForgeMetric(forgeSummary, "failed_events"),
        forgeSource?.graph?.events_failed
      );
      const rawSyncRunning = Boolean(connection && (isConnectionSyncRunning(connection) || runningConnectionId === connection.id));
      const recentSyncActivity = Boolean(
        connection &&
          (runningConnectionId === connection.id ||
            pendingGraphEvents > 0 ||
            hasRecentSyncActivity(connection, now.getTime()))
      );
      const syncRunning = rawSyncRunning && !hasStableBaseline && recentSyncActivity;
      const syncComplete = isConnectionSyncComplete(connection, forgeSummary, forgeSource, entityCount);
      const isGraphMetricsPending = Boolean(
        connection &&
          connectionsLoaded &&
          !hasStableBaseline &&
          (syncRunning || pendingGraphEvents)
      );
      const graph = connectionsLoaded
        ? getGraphState(connection, entityCount, forgeSummary, forgeSource)
        : { label: "pending", tone: "muted" as const, pulse: false };
      const displayGraph = isGraphMetricsPending
        ? { label: "indexing", tone: "blue" as const, pulse: true }
        : graph;
      const temporal = connectionsLoaded
        ? getTemporalState(connection, entityCount, committedGraphReady)
        : { label: "loading", tone: "muted" as const };
      const drift = connectionsLoaded
        ? getDriftState(connection, nativeStatus)
        : { label: "loading", tone: "muted" as const };
      const activeDriftSignals = getNumeric(nativeStatus?.drift?.active_count);
      const lastSync = formatRelativeTime(getLastSyncDate(connection, richCollection));

      return {
        collection,
        connection,
        connections,
        entityCount,
        edgeCount,
        finalEntityCount: (syncComplete || committedGraphReady) ? entityCount : 0,
        finalEdgeCount: (syncComplete || committedGraphReady) && graph.label === "indexed" && !isGraphMetricsPending ? edgeCount : 0,
        syncRunning,
        syncComplete,
        committedGraphReady,
        hasStableBaseline,
        graph,
        displayGraph,
        temporal,
        drift,
        activeDriftSignals,
        pendingGraphEvents,
        failedGraphEvents,
        lastSync: isGraphMetricsPending ? "indexing" : lastSync,
        forgeSummary,
        connectionsLoaded,
        isGraphMetricsPending,
      };
    });
  }, [collections, dashboardStatuses, forgeSummaries, now, runningConnectionId, sourceConnections]);

  const isDashboardHydrating = useMemo(
    () =>
      isLoading && databaseRows.length === 0,
    [databaseRows, isLoading]
  );

  useEffect(() => {
    const hasTransitioningGraph = databaseRows.some((row) =>
      Boolean(
        row.connection &&
          !row.hasStableBaseline &&
          (row.isGraphMetricsPending ||
            (row.syncRunning && !row.committedGraphReady))
      )
    );

    if (!hasTransitioningGraph) return;

    const refreshTransitionState = () => {
      databaseRows.forEach((row) => {
        if (!row.hasStableBaseline && (row.isGraphMetricsPending || (row.syncRunning && !row.committedGraphReady))) {
          forgeSummaryFetchedAtRef.current[row.collection.readable_id] = 0;
        }
      });
      clearApiResponseCache((key) =>
        key.includes("/source-connections") ||
        key.includes("/collections/dashboard-status") ||
        key.includes("/context-forge/databases") ||
        key.includes("/context-intelligence/databases") ||
        key.includes("/graph/organizations")
      );
      databaseRows.forEach((row) => {
        if (!row.hasStableBaseline && (row.isGraphMetricsPending || (row.syncRunning && !row.committedGraphReady))) {
          dashboardStatusFetchedAtRef.current[row.collection.readable_id] = 0;
          void fetchSourceConnections(row.collection.readable_id, true);
        }
      });
      setRefreshNonce((value) => value + 1);
    };

    const firstRefresh = window.setTimeout(refreshTransitionState, 1_000);
    const interval = window.setInterval(refreshTransitionState, TRANSITION_REFRESH_INTERVAL_MS);
    return () => {
      window.clearTimeout(firstRefresh);
      window.clearInterval(interval);
    };
  }, [databaseRows, fetchSourceConnections]);

  const summary = useMemo(() => {
    const connected = databaseRows.filter((row) => row.connection).length;
    const entityTotal = databaseRows.reduce((sum, row) => sum + row.finalEntityCount, 0);
    const edgeTotal = databaseRows.reduce((sum, row) => sum + row.finalEdgeCount, 0);
    const pending = databaseRows.filter((row) => row.pendingGraphEvents > 0 || row.isGraphMetricsPending).length;
    const pendingEvents = databaseRows.reduce((sum, row) => sum + row.pendingGraphEvents, 0);
    const drift = databaseRows.filter((row) => row.drift.tone === "amber" || row.drift.tone === "red").length;
    const driftSignals = databaseRows.reduce((sum, row) => sum + row.activeDriftSignals, 0);
    const indexed = databaseRows.filter((row) => row.graph.label === "indexed").length;
    return { connected, entityTotal, edgeTotal, pending, pendingEvents, drift, driftSignals, indexed };
  }, [databaseRows]);
  const operationalFocus = useMemo(() => {
    const missingSourceRows = databaseRows.filter((row) => row.connectionsLoaded && !row.connection);
    const driftRows = databaseRows.filter((row) => row.drift.tone === "amber" || row.drift.tone === "red");
    const graphWorkRows = databaseRows.filter(
      (row) =>
        row.connection &&
        row.graph.label !== "checking" &&
        row.graph.label !== "indexed" &&
        !row.isGraphMetricsPending &&
        (row.finalEntityCount > 0 || row.graph.label === "indexing")
    );
    const queryReadyRows = databaseRows.filter((row) => row.graph.label === "indexed" && row.finalEntityCount > 0);
    const readyPercent = displayCount > 0 ? Math.round((queryReadyRows.length / displayCount) * 100) : 0;
    const firstMissingSource = missingSourceRows[0]?.collection.readable_id;
    const firstDrift = driftRows[0]?.collection.readable_id;
    const firstGraphWork = graphWorkRows[0]?.collection.readable_id;

    return {
      isHydrating: isDashboardHydrating,
      readyPercent,
      queryReadyCount: queryReadyRows.length,
      items: [
        {
          key: "source",
          label: "Missing source",
          count: missingSourceRows.length,
          detail: missingSourceRows.length
            ? "Attach a connector before sync."
            : "Every loaded database has a source.",
          icon: Plug,
          tone: "blue" as StatusTone,
          actionLabel: "Connect",
          onClick: () =>
            navigate(firstMissingSource ? `/sources?database=${encodeURIComponent(firstMissingSource)}` : "/sources"),
        },
        {
          key: "drift",
          label: "Drift review",
          count: driftRows.length,
          detail: driftRows.length ? "Schema, cursor, or Forge schema changed." : "No drift to review.",
          icon: ShieldCheck,
          tone: driftRows.length ? ("amber" as StatusTone) : ("green" as StatusTone),
          actionLabel: "Review",
          onClick: () => navigate(firstDrift ? `/databases/${firstDrift}/drift` : "/databases"),
        },
        {
          key: "graph",
          label: "Graph readiness",
          count: graphWorkRows.length,
          detail: graphWorkRows.length ? "Run sync or inspect graph commits." : "Loaded graphs are query-ready.",
          icon: GitBranch,
          tone: graphWorkRows.length ? ("amber" as StatusTone) : ("green" as StatusTone),
          actionLabel: "Inspect",
          onClick: () => navigate(firstGraphWork ? `/databases/${firstGraphWork}/sources` : "/graph"),
        },
      ],
    };
  }, [databaseRows, displayCount, isDashboardHydrating, navigate]);

  const kpis = [
    {
      label: "Databases",
      value: formatCount(displayCount),
      sub: debouncedSearchQuery ? "matching filter" : "workspace total",
      icon: Database,
      iconTone: "border-primary/20 bg-primary/10 text-primary",
      tone: "text-foreground",
    },
    {
      label: "Sources",
      value: isDashboardHydrating ? "checking" : (
        <>
          {formatCount(summary.connected)}
          <span className="text-muted-foreground">/</span>
          {formatCount(displayCount)}
        </>
      ),
      sub: "one source per database",
      icon: Plug,
      iconTone: "border-blue-500/20 bg-blue-500/10 text-blue-600 dark:text-blue-300",
      tone: "text-foreground",
    },
    {
      label: "Entities",
      value: isDashboardHydrating ? "checking" : formatCount(summary.entityTotal),
      sub: isDashboardHydrating ? "loading source totals" : "synced into context",
      icon: Table2,
      iconTone: "border-emerald-500/20 bg-emerald-500/10 text-emerald-600 dark:text-emerald-300",
      tone: "text-foreground",
    },
    {
      label: "Edges",
      value: isDashboardHydrating ? "checking" : formatCount(summary.edgeTotal),
      sub: isDashboardHydrating ? "loading graph totals" : summary.edgeTotal ? "graph materialized" : "awaiting graph",
      icon: GitBranch,
      iconTone: "border-violet-500/20 bg-violet-500/10 text-violet-600 dark:text-violet-300",
      tone: "text-foreground",
    },
    {
      label: "Pending",
      value: isDashboardHydrating ? "checking" : formatCount(summary.pending),
      sub: isDashboardHydrating
        ? "loading graph jobs"
        : summary.pendingEvents
          ? `${formatCount(summary.pendingEvents)} graph events`
          : "no graph commits pending",
      icon: Activity,
      iconTone: "border-amber-500/20 bg-amber-500/10 text-amber-600 dark:text-amber-300",
      tone: summary.pending ? "text-blue-600 dark:text-blue-300" : "text-foreground",
    },
    {
      label: "Drift",
      value: isDashboardHydrating ? "checking" : formatCount(summary.drift),
      sub: isDashboardHydrating
        ? "loading drift signals"
        : summary.driftSignals
          ? `${formatCount(summary.driftSignals)} active signals`
          : "clean",
      icon: ShieldCheck,
      iconTone: "border-emerald-500/20 bg-emerald-500/10 text-emerald-600 dark:text-emerald-300",
      tone: summary.drift ? "text-amber-600 dark:text-amber-300" : "text-foreground",
    },
    {
      label: "Indexed",
      value: isDashboardHydrating ? "checking" : formatCount(summary.indexed),
      sub: isDashboardHydrating ? "loading graph readiness" : "graph-ready databases",
      icon: Sparkles,
      iconTone: "border-primary/20 bg-primary/10 text-primary",
      tone: "text-foreground",
    },
  ];

  const createDatabase = () => {
    useCollectionCreationStore.getState().openForCreateCollection();
  };

  const connectSource = (readableId: string) => {
    navigate(`/sources?database=${encodeURIComponent(readableId)}`);
  };

  const openDatabase = (readableId: string) => {
    navigate(`/databases/${readableId}`);
  };

  const runSourceSync = async (connection: RichSourceConnection, databaseName: string, readableId: string) => {
    if (!connection?.id) return;

    setRunningConnectionId(connection.id);
    try {
      const response = await apiClient.post(`/source-connections/${connection.id}/run`);
      if (!response.ok) throw new Error("Failed to start sync");
      toast.success(`Sync started for ${databaseName}`);
      clearApiResponseCache((key) =>
        key.includes("/source-connections") ||
        key.includes("/context-forge/databases") ||
        key.includes("/context-intelligence/databases") ||
        key.includes("/graph/organizations") ||
        key.includes("/collections")
      );
      forgeSummaryFetchedAtRef.current[readableId] = 0;
      dashboardStatusFetchedAtRef.current[readableId] = 0;
      void fetchSourceConnections(readableId, true);
      setRefreshNonce((value) => value + 1);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to start sync");
    } finally {
      setRunningConnectionId(null);
    }
  };

  return (
    <div className="min-h-full bg-background px-4 py-4 md:px-6">
      <div className="mx-auto max-w-[1500px]">
        <header className="mb-4 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="inline-flex h-7 items-center gap-2 rounded-md border border-primary/20 bg-primary/10 px-2.5 text-xs font-medium text-primary">
                <Sparkles className="h-3.5 w-3.5" />
                {greeting}
              </span>
              <span className="inline-flex h-7 items-center gap-2 rounded-md border border-border bg-card px-2.5 font-mono text-[11px] text-muted-foreground">
                <Clock3 className="h-3.5 w-3.5" />
                {formattedDate} at {formattedTime}
              </span>
            </div>
            <h1 className="flex flex-wrap items-baseline gap-x-2 text-[30px] font-semibold tracking-normal text-foreground">
              <span>Welcome,</span>
              <span className="font-semibold text-foreground">
                {displayName}
              </span>
            </h1>
            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
              Your ContextD workspaces are ready: sources, sync health, graph coverage, and query readiness in one view.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              className="h-9 rounded-md border-primary/25 px-3 text-xs text-primary hover:bg-primary/10 hover:text-primary"
              onClick={() => navigate("/sources")}
            >
              <Upload className="h-3.5 w-3.5" />
              Import source
            </Button>
            <Button
              onClick={createDatabase}
              disabled={!sourceConnectionsAllowed || !entitiesAllowed || isCheckingUsage}
              className="h-9 rounded-md bg-primary px-3 text-xs text-primary-foreground shadow-sm shadow-primary/20 hover:bg-primary/90"
            >
              <Plus className="h-3.5 w-3.5" />
              New database
            </Button>
          </div>
        </header>

        <section className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-7">
          {kpis.map((item) => {
            const Icon = item.icon;
            return (
              <div
                key={item.label}
                className="rounded-lg border border-border bg-card px-3 py-3 shadow-sm transition-colors hover:border-primary/25 hover:bg-muted/25"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                    {item.label}
                  </div>
                  <span className={cn("flex h-7 w-7 items-center justify-center rounded-md border", item.iconTone)}>
                    <Icon className="h-3.5 w-3.5" />
                  </span>
                </div>
                <div className={cn("mt-2 font-mono text-2xl font-semibold leading-none", item.tone)}>
                  {item.value}
                </div>
                <div className="mt-1.5 truncate text-[11.5px] text-muted-foreground">{item.sub}</div>
              </div>
            );
          })}
        </section>

        <section className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
          <div className="min-w-0 rounded-lg border border-border bg-card">
            <div className="flex flex-col gap-3 border-b border-border px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="min-w-0">
                <h2 className="text-sm font-semibold text-foreground">Context databases</h2>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Each database owns one source boundary, one cursor, and one ContextD graph.
                </p>
              </div>
              <div className="relative w-full lg:w-[320px]">
                <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder="Filter by database or source"
                  className="h-8 rounded-md border-border bg-background pl-8 text-xs"
                />
              </div>
            </div>

            {isLoading && collections.length === 0 ? (
              <div className="p-4">
                <div className="space-y-2">
                  {Array.from({ length: 6 }).map((_, index) => (
                    <div key={index} className="h-14 animate-pulse rounded-md border border-border bg-background" />
                  ))}
                </div>
              </div>
            ) : databaseRows.length === 0 ? (
              <div className="px-4 py-16 text-center">
                <Database className="mx-auto mb-3 h-9 w-9 text-muted-foreground/50" />
                <p className="text-base font-medium text-foreground">
                  {searchQuery ? "No databases match this search" : "No context databases yet"}
                </p>
                <p className="mt-1 text-sm text-muted-foreground">Create a database, then connect one source.</p>
                {!searchQuery && (
                  <Button className="mt-4 h-8 rounded-md px-3 text-xs" onClick={createDatabase}>
                    <Plus className="h-3.5 w-3.5" />
                    New database
                  </Button>
                )}
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[940px] table-fixed text-left text-sm">
                  <colgroup>
                    <col className="w-[23%]" />
                    <col className="w-[18%]" />
                    <col className="w-[8%]" />
                    <col className="w-[7%]" />
                    <col className="w-[9%]" />
                    <col className="w-[9%]" />
                    <col className="w-[8%]" />
                    <col className="w-[8%]" />
                    <col className="w-[8%]" />
                  </colgroup>
                  <thead className="border-b border-border bg-muted/35 text-[10.5px] uppercase tracking-[0.14em] text-muted-foreground">
                    <tr>
                      <th className="px-3 py-3 font-semibold">Database</th>
                      <th className="px-3 py-3 font-semibold">Source</th>
                      <th className="px-3 py-3 text-right font-semibold">Entities</th>
                      <th className="px-3 py-3 text-right font-semibold">Edges</th>
                      <th className="px-3 py-3 font-semibold">Graph</th>
                      <th className="px-3 py-3 font-semibold">Temporal</th>
                      <th className="px-3 py-3 font-semibold">Drift</th>
                      <th className="px-3 py-3 font-semibold">Last sync</th>
                      <th className="px-3 py-3 text-center font-semibold">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {databaseRows.map((row) => {
                      const {
                        collection,
                        connection,
                        connectionsLoaded,
                        entityCount,
                        finalEntityCount,
                        finalEdgeCount,
                        syncRunning,
                        syncComplete,
                        graph,
                        displayGraph,
                        temporal,
                        drift,
                        lastSync,
                        isGraphMetricsPending,
                      } = row;
                      return (
                        <tr
                          key={collection.id}
                          className="group cursor-pointer bg-card transition-colors hover:bg-muted/35"
                          onClick={() => navigate(`/databases/${collection.readable_id}`)}
                        >
                          <td className="px-3 py-3.5">
                            <div className="flex min-w-0 items-center gap-2.5">
                              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-primary/20 bg-primary/10 text-primary">
                                <Database className="h-3.5 w-3.5" />
                              </div>
                              <div className="min-w-0">
                                <div className="truncate font-medium leading-tight text-foreground group-hover:text-primary">
                                  {collection.name}
                                </div>
                                <div className="truncate font-mono text-[11px] text-muted-foreground">
                                  {collection.readable_id}
                                </div>
                              </div>
                            </div>
                          </td>
                          <td className="px-3 py-3.5">
                            {connection ? (
                              <div className="flex min-w-0 items-center gap-2">
                                <div className="flex h-7 w-7 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border bg-background p-1.5">
                                  <img
                                    src={getAppIconUrl(connection.short_name, resolvedTheme)}
                                    alt=""
                                    className="h-full w-full object-contain"
                                  />
                                </div>
                                <div className="min-w-0">
                                  <div className="truncate text-sm font-medium leading-tight text-foreground">
                                    {connection.name}
                                  </div>
                                  <div className="truncate font-mono text-[11px] text-muted-foreground">
                                    {connection.short_name}
                                  </div>
                                </div>
                              </div>
                            ) : !connectionsLoaded ? (
                              <div className="inline-flex items-center gap-2 text-sm text-muted-foreground">
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                Checking source
                              </div>
                            ) : (
                              <button
                                type="button"
                                className="text-sm text-muted-foreground underline-offset-4 hover:text-primary hover:underline"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  connectSource(collection.readable_id);
                                }}
                              >
                                Connect source
                              </button>
                            )}
                          </td>
                          <td className="px-3 py-3.5 text-right font-mono text-sm text-foreground">
                            {syncComplete ? (
                              formatCount(finalEntityCount || entityCount)
                            ) : (
                              <span className="text-muted-foreground">-</span>
                            )}
                          </td>
                          <td className="px-3 py-3.5 text-right font-mono text-sm text-foreground">
                            {!isGraphMetricsPending && finalEdgeCount > 0 ? (
                              formatCount(finalEdgeCount)
                            ) : (
                              <span className="text-muted-foreground">-</span>
                            )}
                          </td>
                          <td className="px-3 py-3.5">
                            <StatusBadge label={displayGraph.label} tone={displayGraph.tone} pulse={displayGraph.pulse} />
                          </td>
                          <td className="px-3 py-3.5">
                            <StatusBadge label={temporal.label} tone={temporal.tone} pulse={temporal.pulse} />
                          </td>
                          <td className="px-3 py-3.5">
                            <StatusBadge label={drift.label} tone={drift.tone} />
                          </td>
                          <td className="px-3 py-3.5 font-mono text-[11.5px] text-muted-foreground">{lastSync}</td>
                          <td className="px-3 py-3.5">
                            <div className="flex items-center justify-center gap-1">
                              {connection ? (
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-7 w-7 rounded-md text-muted-foreground hover:bg-primary/10 hover:text-primary"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    void runSourceSync(connection, collection.name, collection.readable_id);
                                  }}
                                  title="Run sync"
                                  aria-label={`Run sync for ${collection.name}`}
                                  disabled={runningConnectionId === connection.id}
                                >
                                  {runningConnectionId === connection.id ? (
                                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                  ) : (
                                    <Play className="h-3.5 w-3.5" />
                                  )}
                                </Button>
                              ) : null}
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7 rounded-md text-foreground hover:bg-primary/10 hover:text-primary"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  openDatabase(collection.readable_id);
                                }}
                                title="Open database"
                                aria-label={`Open ${collection.name}`}
                              >
                                <ArrowRight className="h-3.5 w-3.5" />
                              </Button>
                              <DropdownMenu>
                                <DropdownMenuTrigger asChild onClick={(event) => event.stopPropagation()}>
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-7 w-7 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
                                    title="More actions"
                                    aria-label={`More actions for ${collection.name}`}
                                  >
                                    <MoreHorizontal className="h-3.5 w-3.5" />
                                  </Button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent
                                  align="end"
                                  className="w-44"
                                  onClick={(event) => event.stopPropagation()}
                                >
                                  <DropdownMenuItem onClick={() => openDatabase(collection.readable_id)}>
                                    <ArrowRight className="mr-2 h-3.5 w-3.5" />
                                    Open database
                                  </DropdownMenuItem>
                                  {connection ? (
                                    <DropdownMenuItem
                                      onClick={() => void runSourceSync(connection, collection.name, collection.readable_id)}
                                      disabled={runningConnectionId === connection.id}
                                    >
                                      {runningConnectionId === connection.id ? (
                                        <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                                      ) : (
                                        <Play className="mr-2 h-3.5 w-3.5" />
                                      )}
                                      Run sync
                                    </DropdownMenuItem>
                                  ) : (
                                    <DropdownMenuItem onClick={() => connectSource(collection.readable_id)}>
                                      <Plug className="mr-2 h-3.5 w-3.5" />
                                      Connect source
                                    </DropdownMenuItem>
                                  )}
                                  <DropdownMenuSeparator />
                                  <DropdownMenuItem onClick={() => navigate(`/databases/${collection.readable_id}?tab=sources`)}>
                                    <Database className="mr-2 h-3.5 w-3.5" />
                                    Source settings
                                  </DropdownMenuItem>
                                </DropdownMenuContent>
                              </DropdownMenu>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {totalPages > 1 && (
              <div className="flex items-center justify-end gap-2 border-t border-border px-4 py-3">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 rounded-md text-xs"
                  disabled={currentPage === 1 || isLoading}
                  onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
                >
                  Previous
                </Button>
                <span className="font-mono text-xs text-muted-foreground">
                  {currentPage}/{totalPages}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 rounded-md text-xs"
                  disabled={currentPage === totalPages || isLoading}
                  onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
                >
                  Next
                </Button>
              </div>
            )}
          </div>

          <aside className="space-y-4">
            <div className="rounded-lg border border-border bg-card">
              <div className="border-b border-border px-4 py-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold text-foreground">Operational focus</h3>
                    <p className="mt-0.5 text-xs text-muted-foreground">The next useful actions for this workspace.</p>
                  </div>
                  <span className="rounded-md border border-primary/20 bg-primary/10 px-2 py-1 font-mono text-xs font-semibold text-primary">
                    {operationalFocus.isHydrating ? "checking" : `${formatCount(operationalFocus.readyPercent)}%`}
                  </span>
                </div>
              </div>
              <div className="border-b border-border px-4 py-3">
                <div className="flex items-end justify-between gap-3">
                  <div>
                    <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                      Query-ready
                    </div>
                    <div className="mt-1 font-mono text-2xl font-semibold text-foreground">
                      {operationalFocus.isHydrating ? "..." : formatCount(operationalFocus.queryReadyCount)}
                      <span className="text-sm font-normal text-muted-foreground">
                        {" "}
                        / {formatCount(displayCount)}
                      </span>
                    </div>
                  </div>
                  <StatusBadge
                    label={operationalFocus.isHydrating ? "checking" : operationalFocus.readyPercent === 100 ? "ready" : "warming"}
                    tone={operationalFocus.readyPercent === 100 && !operationalFocus.isHydrating ? "green" : "blue"}
                    pulse={operationalFocus.isHydrating}
                  />
                </div>
                <div className="mt-3 h-2 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-primary transition-all"
                    style={{ width: `${operationalFocus.isHydrating ? 12 : Math.max(3, operationalFocus.readyPercent)}%` }}
                  />
                </div>
              </div>
              <div className="divide-y divide-border">
                {operationalFocus.items.map((item) => {
                  const Icon = item.icon;
                  const isClear = item.count === 0;
                  return (
                    <button
                      key={item.key}
                      type="button"
                      className="grid w-full grid-cols-[32px_1fr_auto] items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/35"
                      onClick={item.onClick}
                    >
                      <span
                        className={cn(
                          "flex h-8 w-8 items-center justify-center rounded-md border",
                          item.tone === "green" && "border-emerald-500/20 bg-emerald-500/10 text-emerald-600 dark:text-emerald-300",
                          item.tone === "blue" && "border-blue-500/20 bg-blue-500/10 text-blue-600 dark:text-blue-300",
                          item.tone === "amber" && "border-amber-500/20 bg-amber-500/10 text-amber-600 dark:text-amber-300"
                        )}
                      >
                        {isClear ? <Check className="h-4 w-4" /> : <Icon className="h-4 w-4" />}
                      </span>
                      <span className="min-w-0">
                        <span className="flex items-center gap-2">
                          <span className="truncate text-xs font-semibold text-foreground">{item.label}</span>
                          <span className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                            {operationalFocus.isHydrating ? "..." : formatCount(item.count)}
                          </span>
                        </span>
                        <span className="mt-0.5 block text-[11px] leading-snug text-muted-foreground">{item.detail}</span>
                      </span>
                      <span className={cn("text-[11px] font-medium", isClear ? "text-muted-foreground" : "text-primary")}>
                        {item.actionLabel}
                      </span>
                    </button>
                  );
                })}
              </div>
              <div className="border-t border-border px-4 py-3">
                <button
                  type="button"
                  className="flex w-full items-center justify-between rounded-md border border-border bg-background px-3 py-2 text-left text-xs transition-colors hover:border-primary/30 hover:bg-primary/5"
                  onClick={() => navigate("/query")}
                >
                  <span>
                    <span className="block font-medium text-foreground">Ask across context</span>
                    <span className="mt-0.5 block text-muted-foreground">Use query-ready databases to assemble compact context packets.</span>
                  </span>
                  <ArrowRight className="h-3.5 w-3.5 text-primary" />
                </button>
              </div>
            </div>

            <div className="rounded-lg border border-border bg-card">
              <div className="border-b border-border px-4 py-3">
                <h3 className="text-sm font-semibold text-foreground">ContextD defaults</h3>
                <p className="mt-0.5 text-xs text-muted-foreground">The operating model behind every database.</p>
              </div>
              <div className="grid grid-cols-3 divide-x divide-border text-center">
                {[
                  { label: "Source", value: "single" },
                  { label: "Cursor", value: "tracked" },
                  { label: "Graph", value: "indexed" },
                ].map((item) => (
                  <div key={item.label} className="px-2 py-3">
                    <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">{item.label}</div>
                    <div className="mt-1 truncate text-[11px] font-medium text-foreground">{item.value}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-lg border border-border bg-card">
              <div className="flex items-center justify-between border-b border-border px-4 py-3">
                <h3 className="text-sm font-semibold text-foreground">Recent context changes</h3>
                {isLoading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
              </div>
              <div className="divide-y divide-border">
                {databaseRows.slice(0, 5).map((row) => (
                  <button
                    key={row.collection.id}
                    type="button"
                    className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/35"
                    onClick={() => navigate(`/databases/${row.collection.readable_id}`)}
                  >
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border bg-background">
                      {row.connection ? (
                        <img
                          src={getAppIconUrl(row.connection.short_name, resolvedTheme)}
                          alt=""
                          className="h-4 w-4 object-contain"
                        />
                      ) : (
                        <Database className="h-3.5 w-3.5 text-muted-foreground" />
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-xs font-medium text-foreground">{row.collection.name}</div>
                      <div className="truncate text-[11px] text-muted-foreground">
                        {row.connection ? `${formatCount(row.entityCount)} entities · ${row.lastSync}` : "Waiting for source"}
                      </div>
                    </div>
                    <StatusBadge label={row.graph.label} tone={row.graph.tone} pulse={row.graph.pulse} />
                  </button>
                ))}
                {!isLoading && databaseRows.length === 0 && (
                  <div className="px-4 py-8 text-center text-sm text-muted-foreground">No activity yet.</div>
                )}
              </div>
            </div>
          </aside>
        </section>
      </div>
    </div>
  );
};

export default DatabasesPage;
