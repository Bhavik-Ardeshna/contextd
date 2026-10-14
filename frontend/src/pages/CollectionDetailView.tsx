import { useState, useEffect, useRef } from "react";
import { useLocation, useParams, useNavigate, useSearchParams } from "react-router-dom";
import { Alert } from "@/components/ui/alert";
import {
    AlertCircle,
    Boxes,
    Check,
    Clock,
    Copy,
    Database,
    ArrowRight,
    GaugeCircle,
    Gavel,
    GitFork,
    Loader2,
    Network,
    Package,
    Pencil,
    Plug,
    Plus,
    RefreshCw,
    Route,
    RotateCw,
    Sparkles,
    Table2,
    TerminalSquare,
    Trash,
    AlertTriangle,
    Users,
} from "lucide-react";
import { apiClient, createApiError, ensureOk } from "@/lib/api";
import {
    detectContextDrift,
    fetchContextIntelligence,
    type ContextIntelligenceSummary,
} from "@/lib/contextIntelligenceApi";
import { useUsageStore } from "@/lib/stores/usage";
import { useOrganizationStore } from "@/lib/stores/organizations";
import { Button } from "@/components/ui/button";
import { GraphSchemaPreview, type ForgeGraphPreview } from "@/components/forge/GraphSchemaPreview";
import { KnowledgeGraphView } from "@/components/graph/KnowledgeGraphView";
import { Input } from "@/components/ui/input";
import { toast } from "@/hooks/use-toast";
import { getAppIconUrl } from "@/lib/utils/icons";
import { useTheme } from "@/lib/theme-provider";
import { cn } from "@/lib/utils";
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import SourceConnectionStateView from "@/components/collection/SourceConnectionStateView";
import { emitCollectionEvent, onCollectionEvent, COLLECTION_DELETED, SOURCE_CONNECTION_UPDATED } from "@/lib/events";
// import { DialogFlow } from '@/components/shared'; // TODO: Implement DialogFlow component
import { protectedPaths } from "@/constants/paths";
import { useSidePanelStore } from "@/lib/stores/sidePanelStore";
import { useCollectionCreationStore } from "@/stores/collectionCreationStore";
import { redirectWithError } from "@/lib/error-utils";


interface DeleteCollectionDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onConfirm: () => void;
    collectionReadableId: string;
    confirmText: string;
    setConfirmText: (text: string) => void;
}

const DeleteCollectionDialog = ({
    open,
    onOpenChange,
    onConfirm,
    collectionReadableId,
    confirmText,
    setConfirmText
}: DeleteCollectionDialogProps) => {
    const { resolvedTheme } = useTheme();
    const isDark = resolvedTheme === 'dark';
    const isConfirmValid = confirmText === collectionReadableId;

    return (
        <AlertDialog open={open} onOpenChange={onOpenChange}>
            <AlertDialogContent className={cn(
                "border-border max-w-md",
                isDark ? "bg-card-solid text-foreground" : "bg-white"
            )}>
                <AlertDialogHeader className="space-y-4">
                    {/* Header with warning icon */}
                    <div className="flex items-center gap-3">
                        <div className="flex-shrink-0 w-10 h-10 rounded-full bg-destructive/10 flex items-center justify-center">
                            <AlertTriangle className="w-5 h-5 text-destructive" />
                        </div>
                        <div>
                            <AlertDialogTitle className="text-lg font-semibold text-foreground">
                                Delete Collection
                            </AlertDialogTitle>
                            <p className="text-sm text-muted-foreground mt-1">
                                This action cannot be undone
                            </p>
                        </div>
                    </div>

                    {/* Warning content */}
                    <AlertDialogDescription className="space-y-4">
                        <div className="bg-destructive/5 border border-destructive/20 rounded-lg p-4">
                            <p className="font-medium text-foreground mb-3">
                                This will permanently delete:
                            </p>
                            <ul className="space-y-2 text-sm text-muted-foreground">
                                <li className="flex items-start gap-2">
                                    <div className="w-1.5 h-1.5 rounded-full bg-destructive/60 mt-2 flex-shrink-0" />
                                    <span>The collection and all its source connections</span>
                                </li>
                                <li className="flex items-start gap-2">
                                    <div className="w-1.5 h-1.5 rounded-full bg-destructive/60 mt-2 flex-shrink-0" />
                                    <span>All synced data from the knowledge base</span>
                                </li>
                                <li className="flex items-start gap-2">
                                    <div className="w-1.5 h-1.5 rounded-full bg-destructive/60 mt-2 flex-shrink-0" />
                                    <span>All sync history and configuration</span>
                                </li>
                            </ul>
                        </div>

                        {/* Confirmation input */}
                        <div className="space-y-3">
                            <div>
                                <label htmlFor="confirm-delete" className="text-sm font-medium text-foreground block mb-2">
                                    Type <span className="font-mono font-semibold text-destructive bg-destructive/10 px-1.5 py-0.5 rounded">
                                        {collectionReadableId}
                                    </span> to confirm deletion
                                </label>
                                <Input
                                    id="confirm-delete"
                                    value={confirmText}
                                    onChange={(e) => setConfirmText(e.target.value)}
                                    className={cn(
                                        "w-full transition-colors",
                                        isConfirmValid && confirmText.length > 0
                                            ? "border-green-500 focus:border-green-500 focus:ring-green-500/20"
                                            : confirmText.length > 0
                                                ? "border-destructive focus:border-destructive focus:ring-destructive/20"
                                                : ""
                                    )}
                                    placeholder={collectionReadableId}
                                />
                            </div>

                            {/* Validation feedback */}
                            {confirmText.length > 0 && (
                                <div className="flex items-center gap-2 text-sm">
                                    {isConfirmValid ? (
                                        <>
                                            <Check className="w-4 h-4 text-green-500" />
                                            <span className="text-green-600 dark:text-green-400">
                                                Confirmation matches
                                            </span>
                                        </>
                                    ) : (
                                        <>
                                            <AlertCircle className="w-4 h-4 text-destructive" />
                                            <span className="text-destructive">
                                                Confirmation does not match
                                            </span>
                                        </>
                                    )}
                                </div>
                            )}
                        </div>
                    </AlertDialogDescription>
                </AlertDialogHeader>

                <AlertDialogFooter className="gap-3">
                    <AlertDialogCancel className="flex-1">
                        Cancel
                    </AlertDialogCancel>
                    <AlertDialogAction
                        onClick={onConfirm}
                        disabled={!isConfirmValid}
                        className={cn(
                            "flex-1 bg-destructive text-destructive-foreground hover:bg-destructive/90",
                            "disabled:opacity-50 disabled:cursor-not-allowed",
                            "transition-all duration-200"
                        )}
                    >
                        <Trash className="w-4 h-4 mr-2" />
                        Delete Collection
                    </AlertDialogAction>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    );
};

interface Collection {
    name: string;
    readable_id: string;
    id: string;
    created_at: string;
    modified_at: string;
    organization_id: string;
    created_by_email: string;
    modified_by_email: string;
    status?: string;
}

interface SourceConnection {
    id: string;
    name: string;
    description?: string;
    short_name: string;
    readable_collection_id: string;
    config_fields?: Record<string, any>;
    sync_id?: string;
    organization_id: string;
    created_at: string;
    modified_at: string;
    connection_id?: string;
    collection: string;
    created_by_email: string;
    modified_by_email: string;
    auth_fields?: Record<string, any> | string;
    status?: string;
    is_authenticated?: boolean;
    authentication_url?: string;
    last_job_status?: string;
    last_sync_job_status?: string;
    last_sync_job_id?: string;
    last_sync_job_started_at?: string;
    last_sync_job_completed_at?: string;
    last_sync_at?: string;
    last_synced_at?: string;
    last_sync_job?: {
        completed_at?: string;
        started_at?: string;
        status?: string;
    };
    cron_schedule?: string;
    federated_search?: boolean;  // Whether this source uses federated search
    auth?: { authenticated?: boolean; method?: string };
    schedule?: {
        cron?: string;
        next_run?: string;
        continuous?: boolean;
        cursor_field?: string;
        cursor_value?: any;
    };
    sync?: {
        total_runs?: number;
        successful_runs?: number;
        failed_runs?: number;
        last_job?: {
            id?: string;
            status?: string;
            started_at?: string;
            completed_at?: string;
            entities_inserted?: number;
            entities_updated?: number;
            entities_deleted?: number;
            entities_failed?: number;
        };
    };
    entities?: {
        total_entities: number;
        by_type: Record<string, { count: number; last_updated?: string; sync_status?: string }>;
    };
}

type WorkbenchTab =
    | "overview"
    | "sources"
    | "schema"
    | "entities"
    | "graph"
    | "query"
    | "temporal"
    | "lineage"
    | "decisions"
    | "drift"
    | "forge"
    | "resolver"
    | "cores";

const WORKBENCH_TAB_IDS: WorkbenchTab[] = [
    "overview",
    "sources",
    "schema",
    "entities",
    "graph",
    "query",
    "temporal",
    "lineage",
    "decisions",
    "drift",
    "forge",
    "resolver",
    "cores",
];

interface ContextForgeMapping {
    object_name: string;
    inferred_entity: string;
    rows: number;
    columns: number;
    foreign_keys: number;
    pii: string[];
    selected: boolean;
}

interface ContextForgeMappingArtifact {
    id: string;
    source_connection_id?: string | null;
    setup_draft_id?: string | null;
    target_collection_id?: string | null;
    provider_short_name: string;
    source_name: string;
    version: number;
    status: string;
    generated_by: string;
    mapping_schema: Record<string, any>;
    graph_preview: ForgeGraphPreview;
    schema_fingerprint?: Record<string, any> | null;
    drift_snapshot?: Record<string, any> | null;
    applied_at?: string | null;
    created_at: string;
    modified_at: string;
}

interface ContextForgeSourceSummary {
    source_connection_id: string;
    source_name: string;
    provider: string;
    status: string;
    cursor_field?: string | null;
    source_identity: Record<string, any>;
    totals: Record<string, any>;
    sync_estimate: Record<string, any>;
    mappings: ContextForgeMapping[];
    graph: {
        entity_count: number;
        graph_events_total: number;
        nodes_committed: number;
        edges_committed: number;
        neo4j_nodes: number;
        neo4j_edges: number;
        events_pending: number;
        events_failed: number;
        events_skipped: number;
    };
    forge_ready: boolean;
    drift?: Record<string, any>;
    mapping_artifact?: ContextForgeMappingArtifact | null;
    graph_preview?: ForgeGraphPreview | null;
}

interface ContextForgeSummary {
    readable_id: string;
    name: string;
    totals: {
        sources: number;
        entities: number;
        graph_events: number;
        nodes_committed: number;
        edges_committed: number;
        neo4j_nodes: number;
        neo4j_edges: number;
        pending_events: number;
        failed_events: number;
        forge_ready_sources: number;
    };
    pipeline: Array<{
        key: string;
        label: string;
        status: string;
        detail: string;
    }>;
    sources: ContextForgeSourceSummary[];
}

const Collections = () => {
    /********************************************
     * COMPONENT STATE
     ********************************************/
    const { readable_id, tab } = useParams<{ readable_id: string; tab?: string }>();
    const { resolvedTheme } = useTheme();
    const navigate = useNavigate();
    const location = useLocation();
    const currentOrganization = useOrganizationStore((state) => state.currentOrganization);
    const [searchParams, setSearchParams] = useSearchParams(); // Use setSearchParams to clean URL
    const isFromOAuthSuccess = searchParams.get("status") === "success";
    const activeTab: WorkbenchTab = WORKBENCH_TAB_IDS.includes(tab as WorkbenchTab)
        ? (tab as WorkbenchTab)
        : "overview";

    // Side panel store
    const { isOpen: isPanelOpen, openPanel } = useSidePanelStore();

    // Collection creation store to track modal state
    const { isOpen: isCreationModalOpen } = useCollectionCreationStore();

    // Page state
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [isReloading, setIsReloading] = useState(false);

    // Collection state
    const [collection, setCollection] = useState<Collection | null>(null);
    const [isEditingName, setIsEditingName] = useState(false);
    const nameInputRef = useRef<HTMLDivElement>(null);

    // Source connection state
    const [sourceConnections, setSourceConnections] = useState<SourceConnection[]>([]);
    const [selectedConnection, setSelectedConnection] = useState<SourceConnection | null>(null);
    const [forgeSummary, setForgeSummary] = useState<ContextForgeSummary | null>(null);
    const [intelligenceSummary, setIntelligenceSummary] = useState<ContextIntelligenceSummary | null>(null);
    const [isDetectingDrift, setIsDetectingDrift] = useState(false);
    const [forgeEditor, setForgeEditor] = useState<Record<string, any> | null>(null);
    const [isSavingForge, setIsSavingForge] = useState(false);
    const [isRegeneratingForge, setIsRegeneratingForge] = useState(false);
    const [isApplyingForge, setIsApplyingForge] = useState(false);
    const [queryInput, setQueryInput] = useState("studio relationships and active trainers");
    const [queryResult, setQueryResult] = useState<any | null>(null);
    const [queryError, setQueryError] = useState<string | null>(null);
    const [isQuerying, setIsQuerying] = useState(false);

    // Add state for delete dialog
    const [showDeleteDialog, setShowDeleteDialog] = useState(false);
    const [confirmText, setConfirmText] = useState('');
    const [isDeleting, setIsDeleting] = useState(false);

    // Add state for copy animation
    const [isCopied, setIsCopied] = useState(false);

    // Add state for refreshing all sources
    const [isRefreshingAll, setIsRefreshingAll] = useState(false);
    const [, setRefreshingSourceIds] = useState<string[]>([]);

    // Usage check from store (read-only, checking happens at app level)
    const actionChecks = useUsageStore(state => state.actionChecks);
    const isCheckingUsage = useUsageStore(state => state.isLoading);

    // Derived states from usage store
    const sourceConnectionsAllowed = actionChecks.source_connections?.allowed ?? true;
    const entitiesAllowed = actionChecks.entities?.allowed ?? true;

    const formatMetric = (value?: number) => {
        const num = value || 0;
        if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`;
        if (num >= 1_000) return `${(num / 1_000).toFixed(num >= 100_000 ? 0 : 1)}K`;
        return num.toLocaleString();
    };

    const activeForgeSource = selectedConnection
        ? forgeSummary?.sources.find((source) => source.source_connection_id === selectedConnection.id)
        : forgeSummary?.sources[0];
    const activeMappingArtifact = activeForgeSource?.mapping_artifact || null;
    const activeGraphPreview = activeMappingArtifact?.graph_preview || activeForgeSource?.graph_preview || null;

    const graphEntityTotal = forgeSummary
        ? Number(forgeSummary.totals.entities || activeForgeSource?.graph?.entity_count || 0)
        : Number(selectedConnection?.entities?.total_entities || 0);
    const graphNodeTotal = forgeSummary
        ? Number(forgeSummary.totals.neo4j_nodes || activeForgeSource?.graph?.neo4j_nodes || 0)
        : 0;
    const graphEdgeTotal = forgeSummary
        ? Number(forgeSummary.totals.neo4j_edges || activeForgeSource?.graph?.neo4j_edges || 0)
        : 0;
    const sourceMappings = activeForgeSource?.mappings || [];
    const forgeEntityTypeRows = sourceMappings
        .filter((mapping) => Number(mapping.rows || 0) > 0)
        .map((mapping) => [
            mapping.inferred_entity || mapping.object_name || "Entity",
            {
                count: Number(mapping.rows || 0),
                sourceObject: mapping.object_name,
            },
        ] as const);
    const connectionEntityTypeRows = Object.entries(selectedConnection?.entities?.by_type || {})
        .map(([type, stats]) => [type, { count: Number(stats.count || 0), sourceObject: type }] as const);
    const entityTypeRows = (forgeEntityTypeRows.length ? forgeEntityTypeRows : connectionEntityTypeRows)
        .sort(([, a], [, b]) => (b.count || 0) - (a.count || 0));
    const selectedSourceMappings = sourceMappings.filter((mapping) => mapping.selected);
    const sourceFieldCount = sourceMappings.reduce((sum, mapping) => sum + (mapping.columns || 0), 0);
    const sourceForeignKeyCount = sourceMappings.reduce((sum, mapping) => sum + (mapping.foreign_keys || 0), 0);
    const forgeEntityTypes = forgeEditor?.entity_types || [];
    const forgeRelationships = forgeEditor?.relationships || [];
    const getForgeEndpointLabel = (value?: string) => {
        if (!value) return "-";
        const normalizedValue = String(value).toLowerCase();
        const directMatch = forgeEntityTypes.find((entity: any) => (
            [entity.id, entity.source_object, entity.label]
                .filter(Boolean)
                .some((candidate) => String(candidate).toLowerCase() === normalizedValue)
        ));
        if (directMatch?.label) return directMatch.label;

        const containedMatch = forgeEntityTypes.find((entity: any) => (
            [entity.id, entity.source_object, entity.label]
                .filter(Boolean)
                .some((candidate) => normalizedValue.includes(String(candidate).toLowerCase()))
        ));
        if (containedMatch?.label) return containedMatch.label;

        const readable = String(value)
            .replace(/^entity_/, "")
            .split(/[._-]/)
            .filter(Boolean)
            .slice(-1)[0] || String(value);
        return readable.charAt(0).toUpperCase() + readable.slice(1);
    };

    useEffect(() => {
        setForgeEditor(activeMappingArtifact?.mapping_schema ? { ...activeMappingArtifact.mapping_schema } : null);
    }, [activeMappingArtifact?.id, activeMappingArtifact?.modified_at]);

    const connectionLimitReached = sourceConnections.length >= 1;
    const canAddSource = !connectionLimitReached && sourceConnectionsAllowed && entitiesAllowed && !isCheckingUsage;
    const headerConnection = selectedConnection || sourceConnections[0];
    const routePrefix = location.pathname.startsWith("/collections") ? "/collections" : "/databases";
    const syncingStatuses = new Set(["created", "pending", "queued", "running", "syncing", "indexing", "in_progress", "cancelling"]);
    const getSourceConnectionSyncStatus = (connection?: SourceConnection | null, includeComputedStatus = false) => String(
        connection?.sync?.last_job?.status
        || connection?.last_job_status
        || connection?.last_sync_job_status
        || (includeComputedStatus ? connection?.status : "")
        || ""
    ).toLowerCase();
    const getLastSuccessfulSourceSync = (connection?: SourceConnection | null) =>
        connection?.sync?.last_job?.completed_at
        || connection?.last_sync_job?.completed_at
        || connection?.last_sync_at
        || connection?.last_synced_at
        || null;
    const isSyncStatusRunning = (status?: string) => {
        const normalized = String(status || "").toLowerCase();
        return Array.from(syncingStatuses).some((token) => normalized === token || normalized.includes(token));
    };
    const isSourceConnectionSyncRunning = (connection?: SourceConnection | null) =>
        isSyncStatusRunning(getSourceConnectionSyncStatus(connection, true));
    const headerSyncStatus = getSourceConnectionSyncStatus(headerConnection, true);
    const headerSyncRunning = isSyncStatusRunning(headerSyncStatus);
    const databaseHealth =
        (forgeSummary?.totals.failed_events || 0) > 0
            ? { label: "Failing", className: "border-red-500/25 bg-red-500/10 text-red-600 dark:text-red-400" }
            : headerSyncRunning || (forgeSummary?.totals.pending_events || 0) > 0
                ? { label: "Indexing", className: "border-blue-500/25 bg-blue-500/10 text-blue-600 dark:text-blue-400" }
                : { label: "Healthy", className: "border-green-500/25 bg-green-500/10 text-green-600 dark:text-green-400" };
    const driftStatus = String(activeForgeSource?.drift?.status || activeForgeSource?.drift?.severity || "clean").toLowerCase();
    const nativeDriftSeverity = String(intelligenceSummary?.drift?.severity || driftStatus || "clean").toLowerCase();
    const hasDriftWarning = nativeDriftSeverity !== "clean" && nativeDriftSeverity !== "none" && nativeDriftSeverity !== "ok";
    const nativeTemporalFacts = Number(intelligenceSummary?.totals?.temporal_facts || 0);
    const nativeSupersededFacts = Number(intelligenceSummary?.totals?.superseded_facts || 0);
    const nativeLineageEdges = Number(intelligenceSummary?.totals?.lineage_edges || 0);
    const nativeDecisionCount = Number(intelligenceSummary?.totals?.decisions || 0);
    const nativeQueryTraceCount = Number(intelligenceSummary?.totals?.query_traces || 0);
    const nativeDecisionAuditCount = nativeDecisionCount + nativeQueryTraceCount;
    const nativeDriftCount = Number(intelligenceSummary?.totals?.active_drift || 0);
    const activeStatusConnection = selectedConnection || sourceConnections[0] || null;
    const activeSyncStatus = getSourceConnectionSyncStatus(activeStatusConnection) || activeStatusConnection?.status || "idle";
    const graphPendingEvents = Number(forgeSummary?.totals.pending_events || 0);
    const graphFailedEvents = Number(forgeSummary?.totals.failed_events || 0);
    const hasCommittedContextGraph = graphNodeTotal > 0 && graphPendingEvents === 0 && graphFailedEvents === 0;
    const hasStableSyncBaseline = hasCommittedContextGraph || Boolean(getLastSuccessfulSourceSync(activeStatusConnection));
    const isActiveSyncRunning = isSourceConnectionSyncRunning(activeStatusConnection) && !hasStableSyncBaseline;
    const hasGraphWork = graphEntityTotal > 0 || graphNodeTotal > 0 || graphEdgeTotal > 0 || Number(forgeSummary?.totals.pending_events || 0) > 0;
    const isGraphCommitPending =
        graphFailedEvents === 0
        && hasGraphWork
        && !hasStableSyncBaseline
        && (isActiveSyncRunning || graphPendingEvents > 0)
        && (graphNodeTotal === 0 || graphPendingEvents > 0);
    const shouldHoldFinalCounts = isActiveSyncRunning || isGraphCommitPending;
    const entityMetric = isActiveSyncRunning ? "syncing" : formatMetric(graphEntityTotal);
    const entityMetricSub = isActiveSyncRunning
        ? "source job running"
        : `${entityTypeRows.length || selectedSourceMappings.length || 0} types`;
    const temporalMetric = isActiveSyncRunning ? "building" : formatMetric(nativeTemporalFacts);
    const temporalMetricSub = isActiveSyncRunning ? "waiting for final cursor" : `${formatMetric(nativeSupersededFacts)} superseded`;
    const lineageMetric = shouldHoldFinalCounts ? "building" : formatMetric(nativeLineageEdges);
    const graphNodeMetric = shouldHoldFinalCounts ? "indexing" : formatMetric(graphNodeTotal);
    const graphEdgeMetric = shouldHoldFinalCounts ? "indexing" : formatMetric(graphEdgeTotal);
    const graphMetricSub = shouldHoldFinalCounts
        ? (isActiveSyncRunning ? "source job running" : "waiting for commit")
        : "ContextD indexed";
    const graphPipelineStatus = isGraphCommitPending
        ? { label: "Indexing graph", className: "border-blue-500/25 bg-blue-500/10 text-blue-600 dark:text-blue-400" }
        : isActiveSyncRunning
            ? { label: "Syncing source", className: "border-blue-500/25 bg-blue-500/10 text-blue-600 dark:text-blue-400" }
        : { label: "ContextD indexed", className: "border-green-500/25 bg-green-500/10 text-green-600 dark:text-green-400" };
    const displayPipeline = (forgeSummary?.pipeline || []).map((step) => {
        if (isActiveSyncRunning) {
            if (step.key === "extract") return { ...step, status: "running", detail: "reading source records" };
            if (step.key === "normalize") return { ...step, status: "pending", detail: "waiting for final entity state" };
            if (step.key === "graph_events") return { ...step, status: "pending", detail: "waiting for graph events" };
            if (step.key === "neo4j_commit") {
                return { ...step, label: "Commit to ContextD graph", status: "pending", detail: "waiting for completed sync" };
            }
        }
        return step.key === "neo4j_commit"
            ? {
                ...step,
                label: "Commit to ContextD graph",
                status: isGraphCommitPending ? "running" : step.status,
                detail: isGraphCommitPending ? "committing graph counts" : step.detail,
            }
            : step;
    });
    const isConnectionGraphPending = (connection: SourceConnection, forgeSource?: ContextForgeSourceSummary) => {
        const status = String(
            connection.sync?.last_job?.status
            || connection.last_job_status
            || connection.last_sync_job_status
            || connection.status
            || ""
        ).toLowerCase();
        const entities = Number(
            connection.entities?.total_entities
            || (connection as any).entity_count
            || forgeSource?.graph?.entity_count
            || 0
        );
        const nodes = Number(forgeSource?.graph?.neo4j_nodes || 0);
        const pending = Number(forgeSource?.graph?.events_pending || 0);
        return entities > 0 && (isSyncStatusRunning(status) || pending > 0) && (nodes === 0 || pending > 0);
    };
    const forgeNavStatus = activeMappingArtifact?.status === "review_required"
        ? "review"
        : activeMappingArtifact?.status?.replace(/_/g, " ") || "preview";

    const workbenchGroups: Array<{
        label: string;
        items: Array<{ id: WorkbenchTab; label: string; icon: any; meta?: string; tone?: "default" | "warn" | "roadmap" }>;
    }> = [
        {
            label: "Operate",
            items: [
                { id: "overview", label: "Overview", icon: GaugeCircle },
                { id: "sources", label: "Source", icon: Plug, meta: sourceConnections.length ? String(sourceConnections.length) : undefined },
                { id: "schema", label: "Schema", icon: Table2, meta: sourceMappings.length ? formatMetric(sourceMappings.length) : undefined },
                { id: "entities", label: "Entities", icon: Boxes, meta: graphEntityTotal ? entityMetric : undefined },
                { id: "graph", label: "Graph", icon: GitFork, meta: isGraphCommitPending ? "indexing" : (graphEdgeTotal ? formatMetric(graphEdgeTotal) : undefined) },
                { id: "query", label: "Query", icon: TerminalSquare },
            ],
        },
        {
            label: "Inspect",
            items: [
                { id: "temporal", label: "Temporal", icon: Clock, meta: isActiveSyncRunning ? "building" : (nativeTemporalFacts ? formatMetric(nativeTemporalFacts) : (activeForgeSource?.cursor_field ? "cursor" : undefined)) },
                { id: "lineage", label: "Lineage", icon: Route, meta: shouldHoldFinalCounts ? "building" : (nativeLineageEdges ? formatMetric(nativeLineageEdges) : undefined) },
                { id: "decisions", label: "Decisions", icon: Gavel, meta: formatMetric(nativeDecisionAuditCount) },
                { id: "drift", label: "Drift", icon: AlertTriangle, meta: hasDriftWarning ? formatMetric(nativeDriftCount || 1) : "clean", tone: hasDriftWarning ? "warn" : "default" },
            ],
        },
        {
            label: "Build",
            items: [
                { id: "forge", label: "Forge", icon: Sparkles, meta: forgeNavStatus },
                { id: "resolver", label: "Resolver", icon: Users, meta: "preview", tone: "roadmap" },
                { id: "cores", label: "Cores", icon: Package, meta: "preview", tone: "roadmap" },
            ],
        },
    ];

    const goToWorkbenchTab = (nextTab: WorkbenchTab) => {
        if (!collection?.readable_id) return;
        navigate(`${routePrefix}/${collection.readable_id}${nextTab === "overview" ? "" : `/${nextTab}`}`);
    };

    /********************************************
     * API AND DATA FETCHING FUNCTIONS
     ********************************************/

    const fetchForgeSummary = async (collectionId: string, forceRefresh = false) => {
        try {
            const response = await apiClient.get(
                `/context-forge/databases/${collectionId}`,
                undefined,
                { cache: !forceRefresh }
            );
            if (!response.ok) throw new Error("Failed to load Context Forge summary");
            const summary = await response.json();
            setForgeSummary(summary);
        } catch {
            setForgeSummary(null);
        }
    };

    const fetchIntelligenceSummary = async (collectionId: string, forceRefresh = false) => {
        try {
            const summary = await fetchContextIntelligence(collectionId, { cache: !forceRefresh });
            setIntelligenceSummary(summary);
        } catch {
            setIntelligenceSummary(null);
        }
    };

    const runDriftDetection = async () => {
        if (!collection?.readable_id) return;
        setIsDetectingDrift(true);
        try {
            const summary = await detectContextDrift(collection.readable_id);
            setIntelligenceSummary(summary);
            await fetchForgeSummary(collection.readable_id);
            toast({ title: "Drift checked", description: "ContextD drift signals were refreshed." });
        } catch (err) {
            toast({
                title: "Could not check drift",
                description: err instanceof Error ? err.message : "Please try again.",
                variant: "destructive",
            });
        } finally {
            setIsDetectingDrift(false);
        }
    };

    const updateForgeEntityLabel = (index: number, label: string) => {
        setForgeEditor((previous) => {
            if (!previous) return previous;
            const entity_types = [...(previous.entity_types || [])];
            entity_types[index] = { ...entity_types[index], label };
            return { ...previous, entity_types };
        });
    };

    const updateForgeRelationshipLabel = (index: number, label: string) => {
        setForgeEditor((previous) => {
            if (!previous) return previous;
            const relationships = [...(previous.relationships || [])];
            relationships[index] = { ...relationships[index], label };
            return { ...previous, relationships };
        });
    };

    const saveForgeMapping = async () => {
        if (!activeMappingArtifact || !forgeEditor) return;
        setIsSavingForge(true);
        try {
            const response = await apiClient.patch(`/context-forge/mappings/${activeMappingArtifact.id}`, {
                mapping_schema: forgeEditor,
                status: activeMappingArtifact.status === "active" ? "draft" : activeMappingArtifact.status,
            });
            if (!response.ok) throw new Error("Failed to save Forge schema");
            if (collection?.readable_id) await fetchForgeSummary(collection.readable_id);
            toast({ title: "Forge schema saved", description: "Schema edits are stored for review." });
        } catch (err) {
            toast({
                title: "Could not save Forge schema",
                description: err instanceof Error ? err.message : "Please try again.",
                variant: "destructive",
            });
        } finally {
            setIsSavingForge(false);
        }
    };

    const regenerateForgeMapping = async () => {
        const sourceId = selectedConnection?.id || activeForgeSource?.source_connection_id;
        if (!sourceId) return;
        setIsRegeneratingForge(true);
        try {
            const response = await apiClient.post(`/context-forge/sources/${sourceId}/regenerate`);
            if (!response.ok) throw new Error("Failed to regenerate Forge schema");
            if (collection?.readable_id) await fetchForgeSummary(collection.readable_id);
            toast({ title: "Forge schema regenerated", description: "A new AI-assisted schema version is ready to review." });
        } catch (err) {
            toast({
                title: "Could not regenerate mapping",
                description: err instanceof Error ? err.message : "Please try again.",
                variant: "destructive",
            });
        } finally {
            setIsRegeneratingForge(false);
        }
    };

    const applyForgeMapping = async () => {
        if (!activeMappingArtifact) return;
        setIsApplyingForge(true);
        try {
            const response = await apiClient.post(`/context-forge/mappings/${activeMappingArtifact.id}/apply`);
            if (!response.ok) throw new Error("Failed to apply Forge schema");
            if (collection?.readable_id) await fetchForgeSummary(collection.readable_id);
            toast({ title: "Forge schema applied", description: "Drift baseline and active Forge schema were updated." });
        } catch (err) {
            toast({
                title: "Could not apply mapping",
                description: err instanceof Error ? err.message : "Please try again.",
                variant: "destructive",
            });
        } finally {
            setIsApplyingForge(false);
        }
    };

    const runWorkbenchQuery = async () => {
        if (!collection?.readable_id || !queryInput.trim()) return;
        setIsQuerying(true);
        setQueryError(null);
        try {
            const response = await apiClient.post(`/collections/${collection.readable_id}/graph-search`, {
                query: queryInput.trim(),
                include_edges: true,
                search_limit: 8,
                max_depth: 2,
            });
            if (!response.ok) throw new Error("Scoped graph query failed");
            setQueryResult(await response.json());
        } catch (err) {
            setQueryError(err instanceof Error ? err.message : "Could not run scoped graph query");
        } finally {
            setIsQuerying(false);
        }
    };

    // Fetch source connections for a collection with sync stats from the bulk list endpoint.
    const fetchSourceConnections = async (collectionId: string, forceRefresh = false) => {
        try {
            const response = await apiClient.get(
                `/source-connections/?collection=${collectionId}`,
                undefined,
                { cache: !forceRefresh }
            );

            if (response.ok) {
                const listData = await response.json();
                const detailedConnections = listData.map((connection: any) => ({
                    ...connection,
                    last_sync_job: connection.sync?.last_job || connection.last_sync_job,
                }));

                setSourceConnections(detailedConnections);

                // Entity state mediator will handle subscriptions automatically

                // Always select the first connection when loading a new collection
                let nextSelectedConnection: SourceConnection | null = null;
                if (detailedConnections.length > 0) {
                    // if a source connection was just added, select that one
                    const newSourceId = searchParams.get("source_connection_id");
                    const newConnection = newSourceId ? detailedConnections.find(c => c.id === newSourceId) : null;
                    const existingSelection = selectedConnection?.id
                        ? detailedConnections.find(c => c.id === selectedConnection.id)
                        : null;
                    if (newConnection) {
                        nextSelectedConnection = newConnection;
                    } else if (existingSelection) {
                        nextSelectedConnection = existingSelection;
                    } else {
                        nextSelectedConnection = detailedConnections[0];
                    }
                    setSelectedConnection(nextSelectedConnection);
                } else {
                    // If no connections, ensure selectedConnection is null
                    setSelectedConnection(null);
                }

                if (nextSelectedConnection?.id) {
                    void (async (connectionId: string) => {
                        try {
                            const detailResponse = await apiClient.get(
                                `/source-connections/${connectionId}`,
                                undefined,
                                { cache: !forceRefresh }
                            );
                            if (!detailResponse.ok) return;
                            const detailedData = await detailResponse.json();
                            const mergedConnection = {
                                ...detailedData,
                                last_sync_job: detailedData.sync?.last_job || detailedData.last_sync_job,
                            };
                            setSourceConnections((previous) =>
                                previous.map((connection) =>
                                    connection.id === connectionId ? mergedConnection : connection
                                )
                            );
                            setSelectedConnection((previous) =>
                                previous?.id === connectionId ? mergedConnection : previous
                            );
                        } catch {
                            // The list endpoint already has the operational status; detail hydration is best-effort.
                        }
                    })(nextSelectedConnection.id);
                }
            } else {
                setSourceConnections([]);
                setSelectedConnection(null);
            }
            await Promise.all([
                fetchForgeSummary(collectionId, forceRefresh),
                fetchIntelligenceSummary(collectionId, forceRefresh),
            ]);
        } catch {
            setSourceConnections([]);
            setSelectedConnection(null);
            setForgeSummary(null);
            setIntelligenceSummary(null);
        } finally {
            setIsLoading(false);
        }
    };

    // Update the existing fetchCollection function to use our new function
    const fetchCollection = async (forceRefresh = false) => {
        if (!readable_id) return;

        setIsLoading(true);
        setError(null);

        try {
            const response = await apiClient.get(
                `/collections/${readable_id}`,
                undefined,
                { cache: !forceRefresh }
            );

            if (response.ok) {
                const data = await response.json();
                setCollection(data);
                // After successful collection fetch, fetch source connections
                await fetchSourceConnections(data.readable_id, forceRefresh);
            } else {
                if (response.status === 404) {
                    setError("Collection not found");
                } else {
                    const apiError = await createApiError(response, "Failed to load collection");
                    setError(`Failed to load collection: ${apiError.message}`);
                }
                setIsLoading(false);
            }
        } catch (err) {
            setError(`An error occurred: ${err instanceof Error ? err.message : String(err)}`);
            setIsLoading(false);
        }
    };

    // ** NEW: Handle OAuth callback and toast notification **
    useEffect(() => {
        if (isFromOAuthSuccess) {
            const newSourceId = searchParams.get("source_connection_id");

            // Always refresh source connections when returning from OAuth
            if (collection?.readable_id) {
                fetchSourceConnections(collection.readable_id, true);
            }

            if (newSourceId && sourceConnections.length > 0) {
                const newConnection = sourceConnections.find(c => c.id === newSourceId);
                if (newConnection) {
                    toast({
                        title: "Success",
                        description: `Source "${newConnection.name}" connected successfully!`
                    });
                }
            }

            // Clean up URL params
            const newSearchParams = new URLSearchParams(searchParams);
            newSearchParams.delete("status");
            newSearchParams.delete("source_connection_id");
            newSearchParams.delete("collection");
            setSearchParams(newSearchParams, { replace: true });
        }
    }, [isFromOAuthSuccess, collection?.readable_id, searchParams, setSearchParams]);

    // ** NEW: Refresh connections when panel or creation modal closes, in case a new one was added **
    useEffect(() => {
        if (!isPanelOpen && !isCreationModalOpen) {
            if (collection?.readable_id) {
                fetchSourceConnections(collection.readable_id, true);
            }
        }
    }, [isPanelOpen, isCreationModalOpen, collection?.readable_id]);


    /********************************************
     * UI EVENT HANDLERS
     ********************************************/

    // ** MODIFIED: Trigger the modal for adding source to existing collection **
    const handleAddSource = () => {
        if (connectionLimitReached) {
            toast({
                title: "Single-source database",
                description: "This database already has a source connection. Delete it before connecting another source."
            });
            return;
        }

        if (!canAddSource) {
            return;
        }

        if (collection) {
            const store = useCollectionCreationStore.getState();
            store.openForAddToCollection(collection.readable_id, collection.name);
        }
    };

    // Handle name editing
    const startEditingName = () => {
        setIsEditingName(true);
        setTimeout(() => {
            if (nameInputRef.current) {
                nameInputRef.current.innerText = collection?.name || "";
                // Place cursor at the end of text
                const range = document.createRange();
                const selection = window.getSelection();
                const textNode = nameInputRef.current.firstChild || nameInputRef.current;
                const textLength = nameInputRef.current.innerText.length;

                // Position at the end of text
                range.setStart(textNode, textLength);
                range.setEnd(textNode, textLength);

                if (selection) {
                    selection.removeAllRanges();
                    selection.addRange(range);
                }
                nameInputRef.current.focus();
            }
        }, 0);
    };

    const handleSaveNameChange = async () => {
        const newName = nameInputRef.current?.innerText.trim() || "";

        if (!newName || newName === collection?.name) {
            setIsEditingName(false);
            return;
        }

        try {
            const response = await apiClient.patch(`/collections/${readable_id}`, { name: newName });
            if (!response.ok) throw new Error("Failed to update collection name");

            // Update local state after successful API call
            setCollection(prev => prev ? { ...prev, name: newName } : null);
            setIsEditingName(false);

            toast({
                title: "Success",
                description: "Collection name updated successfully"
            });
        } catch {
            toast({
                title: "Error",
                description: "Failed to update collection name",
                variant: "destructive"
            });
            setIsEditingName(false);
        }
    };

    // Handle copy to clipboard
    const handleCopyId = () => {
        if (collection?.readable_id) {
            navigator.clipboard.writeText(collection.readable_id);
            setIsCopied(true);

            // Reset after animation completes
            setTimeout(() => {
                setIsCopied(false);
            }, 1500);

            toast({
                title: "Copied",
                description: "ID copied to clipboard"
            });
        }
    };

    /********************************************
     * UTILITY FUNCTIONS
     ********************************************/

    // Reload data
    const reloadData = async () => {
        if (!readable_id) return;

        setIsReloading(true);
        try {
            await fetchCollection(true);
        } finally {
            setIsReloading(false);
        }
    };

    const waitForRefreshCompletion = async (collectionId: string, sourceIds: string[]) => {
        const terminalStatuses = new Set(["completed", "failed", "cancelled", "canceled", "error"]);

        try {
            for (let attempt = 0; attempt < 60; attempt += 1) {
                await new Promise(resolve => setTimeout(resolve, 2000));

                const [connectionsResponse, forgeResponse] = await Promise.all([
                    apiClient.get(`/source-connections/?collection=${collectionId}`, undefined, { cache: false }),
                    apiClient.get(`/context-forge/databases/${collectionId}`, undefined, { cache: false }),
                ]);

                const listConnections = connectionsResponse.ok ? await connectionsResponse.json() : [];
                const detailedConnections = sourceIds.length
                    ? sourceIds.map((sourceId) => listConnections.find((connection: any) => connection.id === sourceId) || null)
                    : listConnections;

                const hasPendingDetails = detailedConnections.some(connection => !connection);
                const allTerminal = !hasPendingDetails && detailedConnections.every((connection) => {
                    const status = String(
                        connection?.sync?.last_job?.status
                        || connection?.last_job_status
                        || connection?.last_sync_job_status
                        || connection?.status
                        || ""
                    ).toLowerCase();
                    return terminalStatuses.has(status) || status === "active";
                });

                let graphReady = sourceIds.length === 0;
                try {
                    if (forgeResponse.ok) {
                        const forgeData = await forgeResponse.json();
                        setForgeSummary(forgeData);
                        const totals = forgeData?.totals || {};
                        const entities = Number(totals.entities || 0);
                        const pendingEvents = Number(totals.pending_events || 0);
                        const graphNodes = Number(totals.neo4j_nodes || 0);
                        const failedEvents = Number(totals.failed_events || 0);
                        graphReady = failedEvents > 0 || pendingEvents === 0 && (entities === 0 || graphNodes > 0);
                    }
                } catch {
                    graphReady = false;
                }

                if (allTerminal && graphReady) break;
            }

            await fetchSourceConnections(collectionId, true);
        } finally {
            setRefreshingSourceIds([]);
            setIsRefreshingAll(false);
        }
    };

    /********************************************
     * SIDE EFFECTS
     ********************************************/

    // Initial data loading
    useEffect(() => {
        setSelectedConnection(null);
        fetchCollection();
    }, [readable_id]); // Only depend on readable_id

    // Usage is now checked at app level by UsageChecker component

    // Handle collection deletion
    const handleDeleteCollection = async () => {
        if (!readable_id || confirmText !== readable_id) return;

        setIsDeleting(true);
        try {
            const response = await apiClient.delete(`/collections/${readable_id}`);

            if (response.ok) {
                // Emit event that collection was deleted
                emitCollectionEvent(COLLECTION_DELETED, { id: readable_id });

                toast({
                    title: "Success",
                    description: "Collection and all associated data deleted successfully"
                });
                // Navigate back to dashboard after successful deletion
                navigate(protectedPaths.dashboard);
            } else {
                await ensureOk(response, "Failed to delete collection");
            }
        } catch (err) {
            toast({
                title: "Error",
                description: err instanceof Error ? err.message : "Failed to delete collection",
                variant: "destructive"
            });
        } finally {
            setIsDeleting(false);
            setShowDeleteDialog(false);
            setConfirmText(''); // Reset confirm text
        }
    };

        // Entity state mediator handles its own cleanup

    // Listen for source connection updates
    useEffect(() => {
        const unsubscribe = onCollectionEvent(SOURCE_CONNECTION_UPDATED, (data) => {
            // Always refresh the list from server to ensure consistency
            if (collection?.readable_id) {
                fetchSourceConnections(collection.readable_id, true);
            }

            // If the deleted connection was selected, clear the selection
            // The fetchSourceConnections will auto-select the first connection if any remain
            if (data.deleted && selectedConnection?.id === data.id) {
                setSelectedConnection(null);
            }
        });

        return unsubscribe;
    }, [collection?.readable_id, selectedConnection?.id]);

    // Handle refreshing all sources
    const handleRefreshAllSources = async () => {
        if (!collection?.readable_id) return;

        let response: Response | undefined;

        setIsRefreshingAll(true);
        try {
            response = await apiClient.post(`/collections/${collection.readable_id}/refresh_all`);

            if (response.ok) {
                const jobs = await response.json();
                // Store IDs of sources being refreshed
                const sourceIds = jobs.map(job => job.source_connection_id);
                setRefreshingSourceIds(sourceIds);

                // Entity state mediator will handle subscriptions automatically

                toast({
                    title: "Success",
                    description: `Started refreshing ${sourceIds.length} source connection${sourceIds.length !== 1 ? 's' : ''}`
                });

                // Don't reload data immediately - we'll get live updates

                // Reset refreshing state if no jobs were started
                if (!jobs || jobs.length === 0) {
                    setIsRefreshingAll(false);
                    setRefreshingSourceIds([]);
                } else {
                    void waitForRefreshCompletion(collection.readable_id, sourceIds);
                }

                // Usage limits will be checked automatically by UsageChecker
            } else {
                throw new Error("Failed to refresh sources");
            }
        } catch (error) {
            let errorMessage = "Failed to refresh all sources";
            const errorDetails = "";

            // Try to parse error response
            if (error instanceof Error) {
                errorMessage = error.message;
            }

            // If the error came from an API response, try to get more details
            try {
                if (response && !response.ok) {
                    const errorData = await response.json();
                    if (errorData.detail) {
                        errorMessage = errorData.detail;
                    } else if (errorData.message) {
                        errorMessage = errorData.message;
                    } else if (typeof errorData === 'string') {
                        errorMessage = errorData;
                    }
                }
            } catch {
                // Keep the existing error message if the response body is not parseable JSON.
            }

            // Use redirectWithError to show the error in a dialog
            redirectWithError(navigate, {
                serviceName: collection?.name || "Collection",
                sourceShortName: "collection",
                errorMessage: errorMessage,
                errorDetails: errorDetails,
                canRetry: true,
                dialogId: `refresh-all-${collection?.readable_id}`,
                timestamp: Date.now()
            });

            setIsRefreshingAll(false);
        }
    };

    // Get connection status indicator based on connection state
    const getConnectionStatusIndicator = (connection: SourceConnection) => {
        // Detect federated sources based on the federated_search field
        const isFederated = connection.federated_search === true;

        // Use the connection's status directly from the API response
        let colorClass = "bg-gray-400";
        let status = "unknown";
        let isAnimated = false;

        // Federated sources have simpler status logic
        if (isFederated) {
            switch (connection.status) {
                case 'pending_auth':
                    colorClass = "bg-cyan-500";
                    status = "Authentication required";
                    break;
                case 'error':
                    colorClass = "bg-red-500";
                    status = "Connection error";
                    break;
                case 'inactive':
                    colorClass = "bg-gray-400";
                    status = "Inactive";
                    break;
                case 'active':
                default:
                    colorClass = "bg-green-500";
                    status = "Ready for real-time search";
                    break;
            }
        } else {
            // Map the backend SourceConnectionStatus enum values for regular sources
            switch (connection.status) {
                case 'pending_auth':
                    colorClass = "bg-cyan-500";
                    status = "Authentication required";
                    break;
                case 'syncing':
                    colorClass = "bg-blue-500";
                    status = "Syncing";
                    isAnimated = true;
                    break;
                case 'error':
                    colorClass = "bg-red-500";
                    status = "Sync failed";
                    break;
                case 'active':
                    colorClass = "bg-green-500";
                    status = "Active";
                    break;
                case 'inactive':
                    colorClass = "bg-gray-400";
                    status = "Inactive";
                    break;
                default:
                    // Fallback for unknown status
                    colorClass = "bg-gray-400";
                    status = "Unknown";
            }
        }

        return (
            <span
                className={cn(
                    "inline-flex h-2 w-2 rounded-full opacity-80",
                    colorClass,
                    isAnimated && "animate-pulse"
                )}
                title={status}
            />
        );
    };

    const driftSignals = Array.isArray(intelligenceSummary?.drift?.signals)
        ? intelligenceSummary.drift.signals
        : [];
    const activeDriftSignals = driftSignals.filter((signal: any) => String(signal.status || "active").toLowerCase() !== "resolved");
    const driftLastScan = activeDriftSignals[0]?.detected_at || intelligenceSummary?.generated_at || activeForgeSource?.drift?.last_checked_at;
    const driftLastScanLabel = driftLastScan
        ? new Date(driftLastScan).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
        : "not scanned";
    const driftStatusLabel = hasDriftWarning ? nativeDriftSeverity : "clean";
    const driftCategoryCards = [
        {
            key: "source-schema",
            label: "Source schema drift",
            badge: "schema",
            trigger: "New or removed columns, field type changes, config fingerprint changes, or Forge schema fingerprints that no longer match the connector catalog.",
            match: (signal: any) => ["schema", "source", "config", "mapping", "forge"].some((term) => String(signal.drift_type || "").toLowerCase().includes(term)),
        },
        {
            key: "sync",
            label: "Sync drift",
            badge: "sync",
            trigger: "Cursor lag, stalled schedules, repeated job failures, or checkpoints that stop advancing against the source.",
            match: (signal: any) => ["sync", "cursor", "schedule", "checkpoint", "job"].some((term) => String(signal.drift_type || "").toLowerCase().includes(term)),
        },
        {
            key: "entity",
            label: "Entity drift",
            badge: "preview",
            trigger: "Conflicting facts across sources, stale facts past their validity budget, or entity shape changes after supersession.",
            match: (signal: any) => ["entity", "fact", "temporal"].some((term) => String(signal.drift_type || "").toLowerCase().includes(term)),
        },
        {
            key: "relationship",
            label: "Relationship drift",
            badge: "preview",
            trigger: "Committed relationships disappear, new edges violate the active Forge schema, or relation confidence drops below policy.",
            match: (signal: any) => ["relationship", "relation", "edge", "graph"].some((term) => String(signal.drift_type || "").toLowerCase().includes(term)),
        },
        {
            key: "context",
            label: "Context drift",
            badge: "preview",
            trigger: "A saved query answer materially changes because the graph, temporal facts, or retrieval policy changed.",
            match: (signal: any) => ["context", "query", "answer", "decision"].some((term) => String(signal.drift_type || "").toLowerCase().includes(term)),
            wide: true,
        },
    ].map((category) => ({
        ...category,
        signals: activeDriftSignals.filter(category.match),
    }));

    if (error) {
        return (
            <div className="min-h-screen bg-background px-6 py-8">
                <div className="max-w-[1000px] mx-auto">
                    <h1 className="text-2xl font-bold mb-6 text-foreground">Collection Error</h1>
                    <Alert variant="destructive">
                        <AlertCircle className="h-4 w-4" />
                        <div className="font-medium">Error</div>
                        <div>{error}</div>
                    </Alert>
                    <div className="mt-4">
                        <Button onClick={() => navigate(protectedPaths.dashboard)}>
                            Return to Dashboard
                        </Button>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="flex h-full min-h-0 flex-col bg-background">
            {(isLoading || !collection) && !error ? (
                <div className="flex h-72 flex-col items-center justify-center gap-4">
                    <Loader2 className="h-9 w-9 animate-spin text-primary" />
                    <p className="text-sm text-muted-foreground">Loading database workbench...</p>
                </div>
            ) : (
                <>
                    <header className="shrink-0 border-b border-border bg-card/95 px-4 py-2.5">
                        <div className="grid gap-2 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-center">
                            <div className="flex min-w-0 items-center gap-3">
                                <div className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-md border border-primary/20 bg-primary/10 p-2 text-primary">
                                    {headerConnection ? (
                                        <img
                                            src={getAppIconUrl(headerConnection.short_name, resolvedTheme)}
                                            alt={headerConnection.name}
                                            className="h-full w-full object-contain"
                                        />
                                    ) : (
                                        <Database className="h-5 w-5" />
                                    )}
                                </div>
                                <div className="min-w-0">
                                    <div className="mb-1 flex flex-wrap items-center gap-2">
                                        <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                                            Context database
                                        </span>
                                        <span className={cn("inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium", databaseHealth.className)}>
                                            <span className="h-1.5 w-1.5 rounded-full bg-current" />
                                            {databaseHealth.label}
                                        </span>
                                        <span className="rounded-md border border-border bg-background px-2 py-0.5 text-xs font-medium text-muted-foreground">
                                            1 connection max
                                        </span>
                                    </div>
                                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                                        {isEditingName ? (
                                            <div
                                                ref={nameInputRef}
                                                contentEditable
                                                className="min-w-[220px] rounded border border-border px-2 py-1 text-xl font-semibold text-foreground outline-none"
                                                onKeyDown={(event) => {
                                                    if (event.key === "Enter") {
                                                        event.preventDefault();
                                                        handleSaveNameChange();
                                                    }
                                                    if (event.key === "Escape") {
                                                        event.preventDefault();
                                                        setIsEditingName(false);
                                                    }
                                                }}
                                                onBlur={handleSaveNameChange}
                                            />
                                        ) : (
                                            <h1 className="min-w-0 truncate text-lg font-semibold tracking-tight text-foreground">
                                                {collection?.name}
                                            </h1>
                                        )}
                                        <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={startEditingName}>
                                            <Pencil className="h-4 w-4" />
                                        </Button>
                                    </div>
                                    <div className="mt-1 flex min-w-0 flex-wrap items-center gap-2 text-xs text-muted-foreground">
                                        <span className="truncate font-mono">{collection?.readable_id}</span>
                                        <button type="button" onClick={handleCopyId} className="rounded p-1 hover:bg-muted" aria-label="Copy database id">
                                            {isCopied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                                        </button>
                                        <span className="text-muted-foreground/60">·</span>
                                        <span className="font-mono">v0.10 · core preview</span>
                                        <span className="text-muted-foreground/60">·</span>
                                        <span className={cn("font-mono", isActiveSyncRunning && "text-blue-600 dark:text-blue-400")}>
                                            {entityMetric} entities · {sourceConnections.length} source
                                        </span>
                                        {headerConnection && (
                                            <>
                                                <span className="text-muted-foreground/60">·</span>
                                                <span className="truncate">connected to {headerConnection.name}</span>
                                            </>
                                        )}
                                    </div>
                                </div>
                            </div>
                            <div className="flex flex-wrap items-center gap-1.5 xl:justify-end">
                                <Button variant="outline" size="sm" onClick={() => goToWorkbenchTab("query")}>
                                    <TerminalSquare className="h-4 w-4" />
                                    Query
                                </Button>
                                {!connectionLimitReached && (
                                    <Button variant="outline" size="sm" onClick={handleAddSource} disabled={!canAddSource}>
                                        <Plug className="h-4 w-4" />
                                        Connect source
                                    </Button>
                                )}
                                <Button variant="outline" size="sm" onClick={reloadData} disabled={isReloading}>
                                    <RotateCw className={cn("h-4 w-4", isReloading && "animate-spin")} />
                                    Refresh
                                </Button>
                                <Button size="sm" onClick={handleRefreshAllSources} disabled={isRefreshingAll || sourceConnections.length === 0}>
                                    {isRefreshingAll ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                                    Run sync
                                </Button>
                                <Button variant="outline" size="icon" className="h-8 w-8 shrink-0" onClick={() => setShowDeleteDialog(true)} aria-label="Delete database">
                                    <Trash className="h-4 w-4" />
                                </Button>
                            </div>
                        </div>
                    </header>

                    <div
                        className={cn(
                            "grid min-h-0 flex-1 overflow-hidden",
                            activeTab === "graph"
                                ? "xl:grid-cols-[188px_minmax(0,1fr)]"
                                : activeTab === "drift"
                                    ? "xl:grid-cols-[188px_minmax(0,1fr)]"
                                    : "xl:grid-cols-[188px_minmax(0,1fr)_300px]"
                        )}
                    >
                        <aside className="hidden min-h-0 overflow-y-auto border-r border-border bg-card/70 p-2.5 xl:block">
                            <nav className="space-y-5" aria-label="Database workbench sections">
                                {workbenchGroups.map((group) => (
                                    <div key={group.label}>
                                        <div className="px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                                            {group.label}
                                        </div>
                                        <div className="space-y-0.5">
                                            {group.items.map((item) => {
                                                const Icon = item.icon;
                                                const isActive = activeTab === item.id;
                                                return (
                                                    <button
                                                        key={item.id}
                                                        type="button"
                                                        onClick={() => goToWorkbenchTab(item.id)}
                                                        className={cn(
                                                            "group flex h-8 w-full items-center gap-2 rounded-md border-l-2 px-2 text-left text-xs font-medium transition",
                                                            isActive
                                                                ? "border-primary bg-primary/10 text-primary"
                                                                : "border-transparent text-muted-foreground hover:bg-background hover:text-foreground",
                                                        )}
                                                    >
                                                        <Icon className="h-4 w-4 shrink-0" />
                                                        <span className="min-w-0 flex-1 truncate">{item.label}</span>
                                                        {item.meta && (
                                                            <span
                                                                className={cn(
                                                                    "max-w-[74px] shrink-0 truncate rounded border border-border bg-background px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground",
                                                                    item.tone === "warn" && "border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300",
                                                                    item.tone === "roadmap" && "text-muted-foreground/80"
                                                                )}
                                                            >
                                                                {item.meta}
                                                            </span>
                                                        )}
                                                    </button>
                                                );
                                            })}
                                        </div>
                                    </div>
                                ))}
                            </nav>
                        </aside>

                        <main className={cn("min-w-0", activeTab === "graph" ? "overflow-hidden" : "overflow-y-auto px-4 py-4")}>
                            {activeTab === "graph" ? (
                                currentOrganization ? (
                                    <KnowledgeGraphView
                                        organizationId={currentOrganization.id}
                                        initialCollectionId={collection?.readable_id}
                                        lockCollection
                                        embedded
                                        title="ContextD graph"
                                        subtitle={`${collection?.readable_id} · ${shouldHoldFinalCounts ? "indexing graph" : "ContextD indexed"}`}
                                    />
                                ) : (
                                    <div className="flex h-full items-center justify-center p-6">
                                        <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
                                            Select an organization to inspect the graph.
                                        </div>
                                    </div>
                                )
                            ) : (
                                <div className="space-y-5">
                                    <div className="flex gap-2 overflow-x-auto xl:hidden">
                                        {workbenchGroups.flatMap((group) => group.items).map((item) => {
                                            const Icon = item.icon;
                                            return (
                                                <Button
                                                    key={item.id}
                                                    variant={activeTab === item.id ? "default" : "outline"}
                                                    size="sm"
                                                    className="shrink-0"
                                                    onClick={() => goToWorkbenchTab(item.id)}
                                                >
                                                    <Icon className="h-4 w-4" />
                                                    {item.label}
                                                </Button>
                                            );
                                        })}
                                    </div>

                                    {activeTab !== "drift" && (
                                    <div className="grid gap-2.5 md:grid-cols-3 2xl:grid-cols-6">
                                        {[
                                            { label: "Entities", value: entityMetric, sub: entityMetricSub, icon: Boxes },
                                            { label: "Relationships", value: graphEdgeMetric, sub: graphMetricSub, icon: GitFork },
                                            { label: "Graph nodes", value: graphNodeMetric, sub: graphMetricSub, icon: Database },
                                            { label: "Source slot", value: formatMetric(Math.min(sourceConnections.length, 1)), sub: connectionLimitReached ? "Connection locked" : "Ready to connect", icon: Plug },
                                            { label: "Temporal", value: temporalMetric, sub: temporalMetricSub, icon: Clock },
                                            { label: "Drift", value: hasDriftWarning ? formatMetric(nativeDriftCount || 1) : "Clean", sub: nativeDriftSeverity, icon: AlertTriangle },
                                        ].map((metric) => (
                                            <div key={metric.label} className="rounded-lg border border-border bg-card px-3 py-2.5">
                                                <metric.icon className="mb-2 h-4 w-4 text-primary" />
                                                <div className="font-mono text-lg font-semibold text-foreground">{metric.value}</div>
                                                <div className="mt-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">{metric.label}</div>
                                                <div className="mt-1 truncate text-xs text-muted-foreground">{metric.sub}</div>
                                            </div>
                                        ))}
                                    </div>
                                    )}

                                    <section className="min-w-0 space-y-5">
                                {activeTab === "overview" && (
                                    <>
                                        <div className="grid gap-5 lg:grid-cols-2">
                                            <div className="rounded-lg border border-border bg-card">
                                                <div className="flex items-center justify-between border-b border-border px-4 py-3">
                                                    <h2 className="text-sm font-semibold text-foreground">Context pipeline</h2>
                                                    <span className={cn("rounded border px-2 py-0.5 text-xs", graphPipelineStatus.className)}>
                                                        {graphPipelineStatus.label}
                                                    </span>
                                                </div>
                                                <div className="space-y-1 p-3">
                                                    {displayPipeline.map((step, index) => (
                                                        <div key={step.key} className="grid grid-cols-[28px_1fr_auto] items-center gap-3 rounded-md px-2 py-2 text-sm">
                                                            <span className={cn(
                                                                "flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold",
                                                                step.status === "done" || step.status === "ready" ? "bg-green-500 text-white" : "bg-muted text-muted-foreground",
                                                                step.status === "running" && "bg-primary text-primary-foreground"
                                                            )}>
                                                                {index + 1}
                                                            </span>
                                                            <span className="text-foreground">{step.label}</span>
                                                            <span className="font-mono text-xs text-muted-foreground">{step.detail}</span>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                            <div className="rounded-lg border border-border bg-card">
                                                <div className="border-b border-border px-4 py-3">
                                                    <h2 className="text-sm font-semibold text-foreground">Entity types</h2>
                                                </div>
                                                <div className="divide-y divide-border">
                                                    {entityTypeRows.length === 0 ? (
                                                        <div className="p-8 text-center text-sm text-muted-foreground">No entity rows yet.</div>
                                                    ) : entityTypeRows.map(([type, stats]) => (
                                                        <div key={type} className="grid grid-cols-[1fr_92px] items-center gap-3 px-4 py-3 text-sm">
                                                            <div className="min-w-0">
                                                                <div className="truncate font-mono text-xs text-foreground">{type.replace(/^DatabaseTableNode_public_/, "")}</div>
                                                                {stats.sourceObject && stats.sourceObject !== type && (
                                                                    <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{stats.sourceObject}</div>
                                                                )}
                                                                <div className="mt-1 h-1.5 overflow-hidden rounded bg-muted">
                                                                    <div className="h-full rounded bg-primary" style={{ width: `${Math.max(8, Math.min(100, (stats.count / Math.max(graphEntityTotal || 1, 1)) * 100))}%` }} />
                                                                </div>
                                                            </div>
                                                            <div className="text-right font-mono text-xs text-foreground">{formatMetric(stats.count)}</div>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        </div>
                                        <div className="rounded-lg border border-border bg-card">
                                            <div className="flex flex-col gap-3 border-b border-border px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                                                <div>
                                                    <h2 className="text-sm font-semibold text-foreground">Source boundary</h2>
                                                    <p className="mt-0.5 text-xs text-muted-foreground">
                                                        One live connector defines the scope, cursor, and provenance for this context database.
                                                    </p>
                                                </div>
                                                {connectionLimitReached ? (
                                                    <span className="inline-flex h-8 items-center rounded-md border border-border bg-muted/50 px-3 text-xs font-medium text-muted-foreground">
                                                        Connection locked
                                                    </span>
                                                ) : (
                                                    <Button size="sm" onClick={handleAddSource} disabled={!canAddSource}>
                                                        <Plus className="h-4 w-4" />
                                                        Connect source
                                                    </Button>
                                                )}
                                            </div>
                                            <div className="overflow-x-auto">
                                                <table className="w-full min-w-[780px] text-left text-xs">
                                                    <thead className="border-b border-border bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
                                                        <tr>
                                                            <th className="px-4 py-2 font-medium">Source</th>
                                                            <th className="px-4 py-2 font-medium">Cursor</th>
                                                            <th className="px-4 py-2 text-right font-medium">Entities</th>
                                                            <th className="px-4 py-2 text-right font-medium">Graph nodes</th>
                                                            <th className="px-4 py-2 text-right font-medium">Relationships</th>
                                                            <th className="px-4 py-2 font-medium">Status</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody className="divide-y divide-border">
                                                        {sourceConnections.length === 0 && (
                                                            <tr>
                                                                <td colSpan={6} className="px-4 py-10 text-center text-sm text-muted-foreground">
                                                                    Connect a source to start building the ContextD graph.
                                                                </td>
                                                            </tr>
                                                        )}
                                                        {sourceConnections.map((connection) => {
                                                            const forgeSource = forgeSummary?.sources.find((source) => source.source_connection_id === connection.id);
                                                            const rowPendingEvents = Number(forgeSource?.graph?.events_pending || 0);
                                                            const rowFailedEvents = Number(forgeSource?.graph?.events_failed || 0);
                                                            const rowGraphReady = Number(forgeSource?.graph?.neo4j_nodes || 0) > 0 && rowPendingEvents === 0 && rowFailedEvents === 0;
                                                            const rowHasStableBaseline = rowGraphReady || Boolean(getLastSuccessfulSourceSync(connection));
                                                            const rowSyncRunning = isSourceConnectionSyncRunning(connection) && !rowHasStableBaseline;
                                                            const rowGraphPending = !rowHasStableBaseline && isConnectionGraphPending(connection, forgeSource);
                                                            const rowEntityCount = Number(forgeSource?.graph?.entity_count || connection.entities?.total_entities || (connection as any).entity_count || 0);
                                                            const rowEntityMetric = rowSyncRunning ? "syncing" : formatMetric(rowEntityCount);
                                                            const rowGraphNodes = (rowSyncRunning || rowGraphPending) ? "indexing" : formatMetric(Number(forgeSource?.graph?.neo4j_nodes || 0));
                                                            const rowGraphEdges = (rowSyncRunning || rowGraphPending) ? "indexing" : formatMetric(Number(forgeSource?.graph?.neo4j_edges || 0));
                                                            return (
                                                                <tr
                                                                    key={connection.id}
                                                                    className={cn("cursor-pointer hover:bg-muted/30", selectedConnection?.id === connection.id && "bg-primary/5")}
                                                                    onClick={() => setSelectedConnection(connection)}
                                                                >
                                                                    <td className="px-4 py-3">
                                                                        <div className="flex items-center gap-2">
                                                                            {getConnectionStatusIndicator(connection)}
                                                                            <img src={getAppIconUrl(connection.short_name, resolvedTheme)} alt="" className="h-5 w-5" />
                                                                            <span className="font-medium text-foreground">{connection.name}</span>
                                                                        </div>
                                                                    </td>
                                                                    <td className="px-4 py-3 font-mono text-muted-foreground">{forgeSource?.cursor_field || connection.schedule?.cursor_field || "-"}</td>
                                                                    <td className={cn("px-4 py-3 text-right font-mono", rowSyncRunning ? "text-blue-600 dark:text-blue-400" : "text-foreground")}>{rowEntityMetric}</td>
                                                                    <td className={cn("px-4 py-3 text-right font-mono", rowSyncRunning || rowGraphPending ? "text-blue-600 dark:text-blue-400" : "text-foreground")}>{rowGraphNodes}</td>
                                                                    <td className={cn("px-4 py-3 text-right font-mono", rowSyncRunning || rowGraphPending ? "text-blue-600 dark:text-blue-400" : "text-foreground")}>{rowGraphEdges}</td>
                                                                    <td className="px-4 py-3">
                                                                        <span className={cn(
                                                                            "inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[11px]",
                                                                            rowSyncRunning || rowGraphPending
                                                                                ? "border-blue-500/25 bg-blue-500/10 text-blue-600 dark:text-blue-400"
                                                                                : "border-green-500/25 bg-green-500/10 text-green-600 dark:text-green-400"
                                                                        )}>
                                                                            {(rowSyncRunning || rowGraphPending) && <Loader2 className="h-3 w-3 animate-spin" />}
                                                                            {rowSyncRunning ? "syncing" : rowGraphPending ? "indexing" : (connection.sync?.last_job?.status || connection.status || "active")}
                                                                        </span>
                                                                    </td>
                                                                </tr>
                                                            );
                                                        })}
                                                    </tbody>
                                                </table>
                                            </div>
                                        </div>
                                    </>
                                )}

                                {activeTab === "sources" && (
                                    selectedConnection ? (
                                        <SourceConnectionStateView
                                            key={selectedConnection.id}
                                            sourceConnectionId={selectedConnection.id}
                                            sourceConnectionData={selectedConnection}
                                            collectionId={collection?.readable_id}
                                            collectionName={collection?.name}
                                            onConnectionDeleted={() => {
                                                setSelectedConnection(null);
                                                if (collection?.readable_id) fetchSourceConnections(collection.readable_id, true);
                                            }}
                                            onConnectionUpdated={() => {
                                                if (collection?.readable_id) fetchSourceConnections(collection.readable_id, true);
                                            }}
                                        />
                                    ) : (
                                        <div className="rounded-lg border border-dashed border-border bg-card p-10 text-center">
                                            <Plug className="mx-auto h-8 w-8 text-primary" />
                                            <h2 className="mt-3 text-base font-semibold text-foreground">No source connected</h2>
                                            <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
                                                Add one connector to define the database scope, cursor, sync schedule, and Forge schema.
                                            </p>
                                            <Button className="mt-5" onClick={handleAddSource} disabled={!canAddSource}>
                                                <Plus className="h-4 w-4" />
                                                Connect source
                                            </Button>
                                        </div>
                                    )
                                )}

                                {activeTab === "schema" && (
                                    <div className="grid gap-5 2xl:grid-cols-[minmax(0,1.05fr)_minmax(420px,0.95fr)]">
                                        <div className="rounded-lg border border-border bg-card">
                                            <div className="flex flex-col gap-2 border-b border-border px-4 py-2.5 lg:flex-row lg:items-center lg:justify-between">
                                                <div>
                                                    <h2 className="text-sm font-semibold text-foreground">Discovered source schema</h2>
                                                    <p className="mt-0.5 text-xs text-muted-foreground">
                                                        Tables, columns, foreign keys, and inferred entity names captured during connector setup.
                                                    </p>
                                                </div>
                                                <div className="flex flex-wrap gap-1.5 text-xs">
                                                    <div className="inline-flex h-7 items-center gap-1.5 rounded-md border border-border bg-background px-2">
                                                        <span className="font-mono text-xs font-semibold text-foreground">{selectedSourceMappings.length}</span>
                                                        <span className="text-[9px] uppercase tracking-[0.12em] text-muted-foreground">selected</span>
                                                    </div>
                                                    <div className="inline-flex h-7 items-center gap-1.5 rounded-md border border-border bg-background px-2">
                                                        <span className="font-mono text-xs font-semibold text-foreground">{formatMetric(sourceFieldCount)}</span>
                                                        <span className="text-[9px] uppercase tracking-[0.12em] text-muted-foreground">fields</span>
                                                    </div>
                                                    <div className="inline-flex h-7 items-center gap-1.5 rounded-md border border-border bg-background px-2">
                                                        <span className="font-mono text-xs font-semibold text-foreground">{formatMetric(sourceForeignKeyCount)}</span>
                                                        <span className="text-[9px] uppercase tracking-[0.12em] text-muted-foreground">FKs</span>
                                                    </div>
                                                </div>
                                            </div>
                                            <div className="divide-y divide-border">
                                                {sourceMappings.length === 0 ? (
                                                    <div className="p-10 text-center text-sm text-muted-foreground">
                                                        No discovered schema snapshot is stored for this source yet.
                                                    </div>
                                                ) : sourceMappings.map((mapping) => (
                                                    <div key={mapping.object_name} className="grid gap-2 px-4 py-2.5 text-sm md:grid-cols-[minmax(180px,1fr)_auto] md:items-center">
                                                        <div className="min-w-0">
                                                            <div className="truncate font-mono text-xs text-muted-foreground" title={mapping.object_name}>{mapping.object_name}</div>
                                                            <div className="mt-1 truncate font-medium text-foreground" title={mapping.inferred_entity}>{mapping.inferred_entity}</div>
                                                        </div>
                                                        <div className="flex flex-wrap gap-1 md:justify-end">
                                                            <span className="inline-flex h-6 items-center rounded border border-border bg-background px-1.5 font-mono text-[10px] text-muted-foreground">
                                                                {formatMetric(mapping.columns)} cols
                                                            </span>
                                                            <span className="inline-flex h-6 items-center rounded border border-border bg-background px-1.5 font-mono text-[10px] text-muted-foreground">
                                                                {formatMetric(mapping.foreign_keys)} FK
                                                            </span>
                                                            {(mapping.pii || []).length > 0 && (
                                                                <span className="inline-flex h-6 items-center rounded border border-amber-500/20 bg-amber-500/10 px-1.5 text-[10px] text-amber-700 dark:text-amber-300">
                                                                    PII hints
                                                                </span>
                                                            )}
                                                            <span
                                                                className={cn(
                                                                    "inline-flex h-6 items-center rounded-md border px-1.5 font-mono text-[10px]",
                                                                    mapping.selected
                                                                        ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                                                                        : "border-border bg-muted text-muted-foreground"
                                                                )}
                                                            >
                                                                {mapping.selected ? "scoped" : "excluded"}
                                                            </span>
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                        <div className="space-y-5">
                                            <div className="rounded-lg border border-border bg-card p-4">
                                                <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                                                    <Database className="h-4 w-4 text-primary" />
                                                    Schema readiness
                                                </div>
                                                <dl className="mt-4 grid grid-cols-2 gap-3 text-xs">
                                                    <div className="rounded-md border border-border bg-background p-3">
                                                        <dt className="text-muted-foreground">Entities</dt>
                                                        <dd className={cn("mt-1 font-mono text-base", isActiveSyncRunning ? "text-blue-600 dark:text-blue-400" : "text-foreground")}>{entityMetric}</dd>
                                                    </div>
                                                    <div className="rounded-md border border-border bg-background p-3">
                                                        <dt className="text-muted-foreground">Graph nodes</dt>
                                                        <dd className={cn("mt-1 font-mono text-base", isGraphCommitPending ? "text-blue-600 dark:text-blue-400" : "text-foreground")}>{graphNodeMetric}</dd>
                                                    </div>
                                                    <div className="rounded-md border border-border bg-background p-3">
                                                        <dt className="text-muted-foreground">Relationships</dt>
                                                        <dd className={cn("mt-1 font-mono text-base", isGraphCommitPending ? "text-blue-600 dark:text-blue-400" : "text-foreground")}>{graphEdgeMetric}</dd>
                                                    </div>
                                                    <div className="rounded-md border border-border bg-background p-3">
                                                        <dt className="text-muted-foreground">Cursor</dt>
                                                        <dd className="mt-1 truncate font-mono text-base text-foreground">{activeForgeSource?.cursor_field || selectedConnection?.schedule?.cursor_field || "-"}</dd>
                                                    </div>
                                                </dl>
                                            </div>
                                            <GraphSchemaPreview
                                                preview={activeGraphPreview}
                                                title="Schema-to-graph preview"
                                                subtitle="Entity types and joins inferred from the discovered source schema."
                                                compact
                                                className="self-start"
                                                canvasClassName="h-[260px]"
                                            />
                                        </div>
                                    </div>
                                )}

                                {activeTab === "forge" && (
                                    <div className="grid gap-5 xl:grid-cols-[minmax(380px,0.82fr)_minmax(0,1fr)]">
                                        <div className="self-start overflow-hidden rounded-lg border border-border bg-card">
                                            <div className="border-b border-border bg-background/40 px-4 py-3">
                                                <div className="flex items-start justify-between gap-3">
                                                    <div className="flex min-w-0 items-start gap-3">
                                                        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-primary/20 bg-primary/10 text-primary">
                                                            <Sparkles className="h-4 w-4" />
                                                        </div>
                                                        <div className="min-w-0">
                                                            <h2 className="text-sm font-semibold text-foreground">Mapping review</h2>
                                                            <p className="mt-0.5 text-xs text-muted-foreground">
                                                                {formatMetric(forgeEntityTypes.length)} entities · {formatMetric(forgeRelationships.length)} relations
                                                            </p>
                                                        </div>
                                                    </div>
                                                    <span className="rounded border border-primary/25 bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
                                                        {activeMappingArtifact?.status?.replace(/_/g, " ") || "preview"}
                                                    </span>
                                                </div>
                                                <div className="mt-3 grid grid-cols-3 gap-2">
                                                    <Button
                                                        variant="outline"
                                                        size="sm"
                                                        className="h-8 justify-center px-2 text-xs"
                                                        onClick={regenerateForgeMapping}
                                                        disabled={isRegeneratingForge || !activeForgeSource}
                                                    >
                                                        {isRegeneratingForge ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                                                        Regenerate
                                                    </Button>
                                                    <Button
                                                        variant="outline"
                                                        size="sm"
                                                        className="h-8 justify-center px-2 text-xs"
                                                        onClick={saveForgeMapping}
                                                        disabled={isSavingForge || !activeMappingArtifact || !forgeEditor}
                                                    >
                                                        {isSavingForge ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                                                        Save
                                                    </Button>
                                                    <Button
                                                        size="sm"
                                                        className="h-8 justify-center px-2 text-xs"
                                                        onClick={applyForgeMapping}
                                                        disabled={isApplyingForge || !activeMappingArtifact}
                                                    >
                                                        {isApplyingForge ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                                                        Apply
                                                    </Button>
                                                </div>
                                            </div>
                                            <div className="max-h-[640px] overflow-y-auto">
                                                <section className="border-b border-border p-4">
                                                    <div className="flex items-center justify-between gap-3">
                                                        <div>
                                                            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Entity labels</h3>
                                                            <p className="mt-0.5 text-[11px] text-muted-foreground">Name the node types that appear in the graph.</p>
                                                        </div>
                                                        <span className="rounded border border-border bg-background px-2 py-1 font-mono text-[10px] text-muted-foreground">
                                                            {formatMetric(forgeEntityTypes.length)}
                                                        </span>
                                                    </div>
                                                    <div className="mt-3 space-y-2">
                                                        {forgeEntityTypes.length === 0 ? (
                                                            <div className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                                                                Run discovery or regenerate Forge to create editable entity types.
                                                            </div>
                                                        ) : forgeEntityTypes.map((entity: any, index: number) => (
                                                            <div key={entity.id || entity.source_object || index} className="grid grid-cols-[minmax(84px,0.55fr)_minmax(120px,1fr)_44px] items-center gap-2 rounded-md border border-border bg-background/70 p-2">
                                                                <span className="truncate font-mono text-[11px] text-muted-foreground" title={entity.source_object}>
                                                                    {entity.source_object || entity.id}
                                                                </span>
                                                                <Input
                                                                    value={entity.label || ""}
                                                                    onChange={(event) => updateForgeEntityLabel(index, event.target.value)}
                                                                    className="h-7 border-border bg-card px-2 text-xs"
                                                                />
                                                                <span className="shrink-0 rounded border border-blue-500/20 bg-blue-500/10 px-1 py-0.5 text-center font-mono text-[10px] text-blue-600 dark:text-blue-300">
                                                                    {Math.round((entity.confidence || 0.7) * 100)}%
                                                                </span>
                                                            </div>
                                                        ))}
                                                    </div>
                                                </section>
                                                <section className="p-4">
                                                    <div className="flex items-center justify-between gap-3">
                                                        <div>
                                                            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Relationships</h3>
                                                            <p className="mt-0.5 text-[11px] text-muted-foreground">Review inferred edges before applying the schema.</p>
                                                        </div>
                                                        <span className="rounded border border-border bg-background px-2 py-1 font-mono text-[10px] text-muted-foreground">
                                                            {formatMetric(forgeRelationships.length)}
                                                        </span>
                                                    </div>
                                                    <div className="mt-3 space-y-2.5">
                                                        {forgeRelationships.length === 0 ? (
                                                            <div className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                                                                No relationships yet. ADK inference can propose candidates from columns and table names.
                                                            </div>
                                                        ) : forgeRelationships.map((relationship: any, index: number) => {
                                                            const sourceLabel = getForgeEndpointLabel(relationship.source_object || relationship.source);
                                                            const targetLabel = getForgeEndpointLabel(relationship.target_object || relationship.target);
                                                            return (
                                                                <div key={relationship.id || index} className="rounded-md border border-border bg-background/70 p-2.5">
                                                                    <div className="flex min-w-0 items-center gap-2 text-[11px] font-medium text-foreground">
                                                                        <span className="min-w-0 truncate rounded border border-border bg-card px-2 py-1" title={relationship.source_object || relationship.source}>
                                                                            {sourceLabel}
                                                                        </span>
                                                                        <ArrowRight className="h-3.5 w-3.5 shrink-0 text-primary" />
                                                                        <span className="min-w-0 truncate rounded border border-border bg-card px-2 py-1" title={relationship.target_object || relationship.target}>
                                                                            {targetLabel}
                                                                        </span>
                                                                    </div>
                                                                    <Input
                                                                        value={relationship.label || ""}
                                                                        onChange={(event) => updateForgeRelationshipLabel(index, event.target.value)}
                                                                        className="mt-2 h-8 border-border bg-card font-mono text-sm"
                                                                    />
                                                                    <div className="mt-2 truncate font-mono text-[10px] text-muted-foreground">
                                                                        {(relationship.source_object || relationship.source || "-")}{" -> "}{(relationship.target_object || relationship.target || "-")}
                                                                    </div>
                                                                    {relationship.rationale && (
                                                                        <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-muted-foreground">{relationship.rationale}</p>
                                                                    )}
                                                                </div>
                                                            );
                                                        })}
                                                    </div>
                                                </section>
                                            </div>
                                        </div>
                                        <GraphSchemaPreview
                                            preview={activeGraphPreview}
                                            title="Forge schema"
                                            subtitle={
                                                activeMappingArtifact
                                                    ? `v${activeMappingArtifact.version} · ${activeMappingArtifact.generated_by.replace(/_/g, " ")} · ${formatMetric(graphNodeTotal)} nodes · ${formatMetric(graphEdgeTotal)} relationships`
                                                    : "No stored Forge schema yet"
                                            }
                                            className="self-start"
                                            canvasClassName="h-[390px]"
                                        />
                                    </div>
                                )}

                                {activeTab === "entities" && (
                                    <div className="rounded-lg border border-border bg-card">
                                        <div className="border-b border-border px-4 py-3">
                                            <h2 className="text-sm font-semibold text-foreground">Normalized entities</h2>
                                        </div>
                                        <div className="divide-y divide-border">
                                            {entityTypeRows.map(([type, stats]) => (
                                                <div key={type} className="grid grid-cols-[1fr_120px_140px] items-center gap-3 px-4 py-3 text-sm">
                                                    <span className="font-mono text-xs text-foreground">{type}</span>
                                                    <span className="text-right font-mono text-xs">{formatMetric(stats.count)}</span>
                                                    <span className="text-right text-xs text-muted-foreground">{stats.sync_status || "synced"}</span>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {activeTab === "query" && (
                                    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
                                        <div className="rounded-lg border border-border bg-card">
                                            <div className="border-b border-border px-4 py-3">
                                                <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                                                    <TerminalSquare className="h-4 w-4 text-primary" />
                                                    Scoped context query
                                                </h2>
                                                <p className="mt-1 text-xs text-muted-foreground">
                                                    Queries use this database's indexed ContextD graph, temporal facts, lineage, and Forge schema.
                                                </p>
                                            </div>
                                            <form
                                                className="flex flex-col gap-3 p-4 md:flex-row"
                                                onSubmit={(event) => {
                                                    event.preventDefault();
                                                    void runWorkbenchQuery();
                                                }}
                                            >
                                                <Input
                                                    value={queryInput}
                                                    onChange={(event) => setQueryInput(event.target.value)}
                                                    className="h-11 flex-1 border-border bg-background font-mono text-sm"
                                                    placeholder="Ask for entities, relationships, lineage, or facts"
                                                />
                                                <Button type="submit" className="h-11 bg-primary text-primary-foreground hover:bg-primary/90" disabled={isQuerying || !queryInput.trim()}>
                                                    {isQuerying ? <Loader2 className="h-4 w-4 animate-spin" /> : <Network className="h-4 w-4" />}
                                                    Run query
                                                </Button>
                                            </form>
                                            {queryError && (
                                                <div className="mx-4 mb-4 rounded-md border border-destructive/25 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                                                    {queryError}
                                                </div>
                                            )}
                                            <div className="border-t border-border p-4">
                                                {!queryResult ? (
                                                    <div className="rounded-md border border-dashed border-border bg-background p-8 text-center text-sm text-muted-foreground">
                                                        Run a query to inspect source nodes, related entities, and ContextD links.
                                                    </div>
                                                ) : (
                                                    <div className="space-y-4">
                                                        <div className="grid gap-3 sm:grid-cols-3">
                                                            {[
                                                                { label: "Matches", value: queryResult.search_results?.length || 0 },
                                                                { label: "Nodes", value: queryResult.nodes?.length || 0 },
                                                                { label: "Edges", value: queryResult.edges?.length || 0 },
                                                            ].map((item) => (
                                                                <div key={item.label} className="rounded-md border border-border bg-background p-3">
                                                                    <div className="font-mono text-lg font-semibold text-foreground">{formatMetric(item.value)}</div>
                                                                    <div className="mt-1 text-[10px] uppercase tracking-wider text-muted-foreground">{item.label}</div>
                                                                </div>
                                                            ))}
                                                        </div>
                                                        <div className="divide-y divide-border rounded-md border border-border">
                                                            {(queryResult.search_results || []).slice(0, 8).map((result: any) => (
                                                                <div key={result.node_id} className="grid gap-2 px-3 py-3 text-sm md:grid-cols-[minmax(0,1fr)_96px]">
                                                                    <div className="min-w-0">
                                                                        <div className="truncate font-medium text-foreground">{result.name || result.payload?.name || result.node_id}</div>
                                                                        <div className="mt-1 truncate font-mono text-xs text-muted-foreground">{result.node_type || result.payload?.node_type || "graph node"}</div>
                                                                    </div>
                                                                    <div className="font-mono text-xs text-muted-foreground md:text-right">
                                                                        score {Number(result.score || 0).toFixed(2)}
                                                                    </div>
                                                                </div>
                                                            ))}
                                                            {(queryResult.search_results || []).length === 0 && (
                                                                <div className="px-3 py-8 text-center text-sm text-muted-foreground">No matched seed nodes for this query.</div>
                                                            )}
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                        <div className="rounded-lg border border-border bg-card p-4">
                                            <h3 className="text-sm font-semibold text-foreground">Context query contract</h3>
                                            <dl className="mt-4 grid grid-cols-[92px_1fr] gap-y-2 text-xs">
                                                <dt className="text-muted-foreground">Endpoint</dt>
                                                <dd className="truncate font-mono text-foreground">/collections/{collection?.readable_id}/graph-search</dd>
                                                <dt className="text-muted-foreground">Depth</dt>
                                                <dd className="font-mono text-foreground">2 hops</dd>
                                                <dt className="text-muted-foreground">Scope</dt>
                                                <dd className="truncate font-mono text-foreground">{collection?.readable_id}</dd>
                                                <dt className="text-muted-foreground">Graph index</dt>
                                                <dd className={cn("font-mono", isGraphCommitPending ? "text-blue-600 dark:text-blue-400" : "text-foreground")}>
                                                    {graphNodeMetric} {isGraphCommitPending ? "" : "nodes"}
                                                </dd>
                                            </dl>
                                        </div>
                                    </div>
                                )}

                                {activeTab === "temporal" && (
                                    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
                                        <div className="rounded-lg border border-border bg-card">
                                            <div className="border-b border-border px-4 py-3">
                                                <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                                                    <Clock className="h-4 w-4 text-primary" />
                                                    Bitemporal fact state
                                                </h2>
                                            </div>
                                            <dl className="grid gap-3 p-4 sm:grid-cols-3">
                                                {[
                                                    { label: "Current facts", value: nativeTemporalFacts },
                                                    { label: "Superseded", value: nativeSupersededFacts },
                                                    { label: "Coverage", value: intelligenceSummary?.temporal?.coverage || "current" },
                                                    { label: "Cursor field", value: activeForgeSource?.cursor_field || selectedConnection?.schedule?.cursor_field || "-" },
                                                    { label: "Cursor value", value: selectedConnection?.schedule?.cursor_value ?? "checkpointed by sync" },
                                                    { label: "Cadence", value: selectedConnection?.schedule?.cron || selectedConnection?.cron_schedule || "manual / every 15 min" },
                                                    { label: "Status", value: activeSyncStatus },
                                                    { label: "Last started", value: selectedConnection?.sync?.last_job?.started_at || selectedConnection?.last_sync_job_started_at || "never" },
                                                    { label: "Last completed", value: selectedConnection?.sync?.last_job?.completed_at || selectedConnection?.last_sync_job_completed_at || "never" },
                                                ].map((item) => (
                                                    <div key={item.label} className="rounded-md border border-border bg-background p-3">
                                                        <dt className="text-[10px] uppercase tracking-wider text-muted-foreground">{item.label}</dt>
                                                        <dd className="mt-1 truncate font-mono text-sm text-foreground">{typeof item.value === "number" ? formatMetric(item.value) : String(item.value)}</dd>
                                                    </div>
                                                ))}
                                            </dl>
                                            <div className="border-t border-border">
                                                {(intelligenceSummary?.temporal?.recent_changes || []).length === 0 ? (
                                                    <div className="p-8 text-center text-sm text-muted-foreground">No bitemporal fact rows are projected yet.</div>
                                                ) : (
                                                    <div className="divide-y divide-border">
                                                        {(intelligenceSummary?.temporal?.recent_changes || []).slice(0, 8).map((fact: any) => (
                                                            <div key={fact.id} className="grid gap-2 px-4 py-3 text-sm md:grid-cols-[minmax(0,1fr)_120px]">
                                                                <div className="min-w-0">
                                                                    <div className="truncate font-medium text-foreground">{fact.subject_node_id || fact.primitive_ref}</div>
                                                                    <div className="mt-1 truncate font-mono text-xs text-muted-foreground">{fact.predicate} · {fact.primitive_type}</div>
                                                                </div>
                                                                <div className="font-mono text-xs text-muted-foreground md:text-right">{fact.status}</div>
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                        <div className="rounded-lg border border-border bg-card">
                                            <div className="border-b border-border px-4 py-3">
                                                <h2 className="text-sm font-semibold text-foreground">Graph event checkpoint</h2>
                                            </div>
                                            <div className="grid gap-3 p-4 sm:grid-cols-2">
                                                {[
                                                    { label: "Events", value: activeForgeSource?.graph.graph_events_total || forgeSummary?.totals.graph_events || 0 },
                                                    { label: "Pending", value: activeForgeSource?.graph.events_pending || forgeSummary?.totals.pending_events || 0 },
                                                    { label: "Failed", value: activeForgeSource?.graph.events_failed || forgeSummary?.totals.failed_events || 0 },
                                                    { label: "Skipped", value: activeForgeSource?.graph.events_skipped || 0 },
                                                ].map((item) => (
                                                    <div key={item.label} className="rounded-md border border-border bg-background p-3">
                                                        <div className="font-mono text-lg font-semibold text-foreground">{formatMetric(item.value)}</div>
                                                        <div className="mt-1 text-[10px] uppercase tracking-wider text-muted-foreground">{item.label}</div>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    </div>
                                )}

                                {activeTab === "lineage" && (
                                    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
                                        <div className="rounded-lg border border-border bg-card">
                                            <div className="border-b border-border px-4 py-3">
                                                <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                                                    <Route className="h-4 w-4 text-primary" />
                                                    Lineage records
                                                </h2>
                                                <p className="mt-1 text-xs text-muted-foreground">Source, graph-event, Forge, and relationship provenance projected from sync commits.</p>
                                            </div>
                                            <div className="divide-y divide-border">
                                                {(intelligenceSummary?.lineage?.recent_edges || []).length === 0 ? (
                                                    <div className="p-8 text-center text-sm text-muted-foreground">No lineage edges are projected yet.</div>
                                                ) : (intelligenceSummary?.lineage?.recent_edges || []).slice(0, 12).map((edge: any, index: number) => (
                                                    <div key={edge.id || index} className="grid grid-cols-[36px_1fr_auto] items-center gap-3 px-4 py-3 text-sm">
                                                        <span className={cn(
                                                            "flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold",
                                                            "bg-primary/10 text-primary"
                                                        )}>
                                                            {index + 1}
                                                        </span>
                                                        <div className="min-w-0">
                                                            <div className="truncate font-medium text-foreground">{edge.from_ref} → {edge.to_ref}</div>
                                                            <div className="mt-0.5 truncate font-mono text-xs text-muted-foreground">{edge.from_type} · {edge.to_type}</div>
                                                        </div>
                                                        <div className="text-right font-mono text-xs text-muted-foreground">{edge.relationship_type}</div>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                        <div className="rounded-lg border border-border bg-card p-4">
                                            <h3 className="text-sm font-semibold text-foreground">Lineage summary</h3>
                                            <div className="mt-4 space-y-3 text-sm">
                                                <div className="rounded-md border border-border bg-background p-3">
                                                    <div className="font-medium text-foreground">{selectedConnection?.name || "Source"}</div>
                                                    <div className="mt-1 font-mono text-xs text-muted-foreground">source connector</div>
                                                </div>
                                                <ArrowRight className="mx-auto h-4 w-4 text-primary" />
                                                <div className="rounded-md border border-border bg-background p-3">
                                                    <div className="font-medium text-foreground">{entityMetric} normalized entities</div>
                                                    <div className="mt-1 font-mono text-xs text-muted-foreground">{formatMetric(selectedSourceMappings.length)} mappings</div>
                                                </div>
                                                <ArrowRight className="mx-auto h-4 w-4 text-primary" />
                                                <div className="rounded-md border border-border bg-background p-3">
                                                    <div className="font-medium text-foreground">{lineageMetric} lineage links</div>
                                                    <div className="mt-1 font-mono text-xs text-muted-foreground">bitemporal provenance</div>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                )}

                                {activeTab === "decisions" && (
                                    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
                                        <div className="rounded-lg border border-border bg-card">
                                            <div className="border-b border-border px-4 py-3">
                                                <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                                                    <Gavel className="h-4 w-4 text-primary" />
                                                    Decision lineage
                                                </h2>
                                                <p className="mt-1 text-xs text-muted-foreground">First-class Decision primitives with inputs, policies, affected entities, and bitemporal audit fields.</p>
                                            </div>
                                            {(intelligenceSummary?.decisions?.recent || []).length === 0 ? (
                                                <div className="p-10 text-center">
                                                    <Gavel className="mx-auto h-9 w-9 text-primary" />
                                                    <h2 className="mt-4 text-base font-semibold text-foreground">No decision nodes emitted yet</h2>
                                                    <p className="mx-auto mt-2 max-w-lg text-sm text-muted-foreground">
                                                        This database has {graphNodeMetric} graph nodes, {graphEdgeMetric} relationships, and {formatMetric(nativeQueryTraceCount)} query decision traces. Source decision events will appear here when connector sync or Forge emits policy decisions.
                                                    </p>
                                                </div>
                                            ) : (
                                                <div className="divide-y divide-border">
                                                    {(intelligenceSummary?.decisions?.recent || []).map((decision: any) => (
                                                        <div key={decision.id} className="grid gap-3 px-4 py-3 text-sm md:grid-cols-[minmax(0,1fr)_130px]">
                                                            <div className="min-w-0">
                                                                <div className="truncate font-medium text-foreground">{decision.subject}</div>
                                                                <div className="mt-1 truncate font-mono text-xs text-muted-foreground">{decision.decision_type} · {decision.outcome}</div>
                                                            </div>
                                                            <div className="text-left font-mono text-xs text-muted-foreground md:text-right">
                                                                {decision.decided_at ? new Date(decision.decided_at).toLocaleDateString() : "recorded"}
                                                            </div>
                                                        </div>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                        <div className="rounded-lg border border-border bg-card p-4">
                                            <h3 className="text-sm font-semibold text-foreground">Decision contract</h3>
                                            <dl className="mt-4 grid grid-cols-[110px_1fr] gap-y-2 text-xs">
                                                <dt className="text-muted-foreground">Rows</dt>
                                                <dd className="font-mono text-foreground">{formatMetric(nativeDecisionAuditCount)}</dd>
                                                <dt className="text-muted-foreground">Query traces</dt>
                                                <dd className="font-mono text-foreground">{formatMetric(nativeQueryTraceCount)}</dd>
                                                <dt className="text-muted-foreground">Edges</dt>
                                                <dd className="font-mono text-foreground">DECIDED_BY · INFORMED_BY · APPLIED_POLICY · AFFECTED</dd>
                                                <dt className="text-muted-foreground">Temporal</dt>
                                                <dd className="font-mono text-foreground">valid_at · invalid_at · created_at · expired_at</dd>
                                            </dl>
                                        </div>
                                    </div>
                                )}

                                {activeTab === "drift" && (
                                    <div className="overflow-hidden rounded-lg border border-border bg-card">
                                        <div className="border-b border-border bg-background/50 px-4 py-3">
                                            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                                                <div className="min-w-0">
                                                    <div className="flex flex-wrap items-center gap-2">
                                                        <AlertTriangle className={cn("h-4 w-4", hasDriftWarning ? "text-amber-600" : "text-green-600")} />
                                                        <h2 className="text-base font-semibold text-foreground">Drift monitor</h2>
                                                        <span className={cn(
                                                            "rounded border px-2 py-0.5 text-[11px] font-medium",
                                                            hasDriftWarning
                                                                ? "border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300"
                                                                : "border-green-500/25 bg-green-500/10 text-green-700 dark:text-green-300"
                                                        )}>
                                                            {driftStatusLabel}
                                                        </span>
                                                    </div>
                                                    <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
                                                        ContextD checks compare source schema, connector config, cursor progress, committed graph relationships, query context, and the active Forge schema.
                                                    </p>
                                                </div>
                                                <div className="flex flex-wrap items-center gap-2">
                                                    <span className="rounded-md border border-border bg-card px-2.5 py-1.5 font-mono text-[11px] text-muted-foreground">
                                                        last scan {driftLastScanLabel}
                                                    </span>
                                                    <Button
                                                        size="sm"
                                                        className="h-8 bg-primary text-primary-foreground hover:bg-primary/90"
                                                        onClick={runDriftDetection}
                                                        disabled={isDetectingDrift}
                                                    >
                                                        {isDetectingDrift ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                                                        Run drift scan
                                                    </Button>
                                                </div>
                                            </div>

                                            <div className="mt-3 flex flex-wrap gap-1.5">
                                                <span className="rounded-md border border-primary/25 bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
                                                    All <span className="ml-1 font-mono">{formatMetric(activeDriftSignals.length)}</span>
                                                </span>
                                                {driftCategoryCards.map((category) => (
                                                    <span key={category.key} className="rounded-md border border-border bg-card px-2.5 py-1 text-xs text-muted-foreground">
                                                        {category.label.replace(" drift", "")}
                                                        {category.signals.length > 0 && <span className="ml-1 font-mono text-amber-700 dark:text-amber-300">{formatMetric(category.signals.length)}</span>}
                                                    </span>
                                                ))}
                                            </div>
                                        </div>

                                        <div className="grid gap-4 p-4 lg:grid-cols-2">
                                            {driftCategoryCards.map((category) => {
                                                const hasSignals = category.signals.length > 0;
                                                return (
                                                    <div
                                                        key={category.key}
                                                        className={cn(
                                                            "rounded-lg border p-4",
                                                            category.wide && "lg:col-span-2",
                                                            hasSignals
                                                                ? "border-amber-500/25 bg-amber-500/5"
                                                                : "border-border bg-background"
                                                        )}
                                                    >
                                                        <div className="flex items-start justify-between gap-3">
                                                            <div className="min-w-0">
                                                                <h3 className="text-sm font-semibold text-foreground">{category.label}</h3>
                                                                <p className="mt-1 text-xs text-muted-foreground">{category.trigger}</p>
                                                            </div>
                                                            <span className={cn(
                                                                "shrink-0 rounded border px-2 py-0.5 text-[11px] font-medium",
                                                                hasSignals
                                                                    ? "border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300"
                                                                    : "border-border bg-muted/40 text-muted-foreground"
                                                            )}>
                                                                {hasSignals ? `${formatMetric(category.signals.length)} warning${category.signals.length === 1 ? "" : "s"}` : category.badge}
                                                            </span>
                                                        </div>

                                                        <div className="mt-3 space-y-2">
                                                            {hasSignals ? (
                                                                category.signals.map((signal: any) => (
                                                                    <div key={signal.id || `${category.key}-${signal.summary}`} className="rounded-md border border-border bg-card p-3 text-xs">
                                                                        <div className="flex flex-wrap items-center justify-between gap-2">
                                                                            <div className="min-w-0 truncate font-medium text-foreground">{signal.summary}</div>
                                                                            <span className="rounded border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 font-mono text-[10px] text-amber-700 dark:text-amber-300">
                                                                                {signal.severity || "warning"}
                                                                            </span>
                                                                        </div>
                                                                        <div className="mt-2 grid gap-2 md:grid-cols-2">
                                                                            <div className="rounded border border-border bg-background px-2.5 py-2">
                                                                                <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Expected</div>
                                                                                <div className="mt-1 truncate font-mono text-[11px] text-foreground">
                                                                                    {JSON.stringify(signal.expected || {})}
                                                                                </div>
                                                                            </div>
                                                                            <div className="rounded border border-border bg-background px-2.5 py-2">
                                                                                <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Observed</div>
                                                                                <div className="mt-1 truncate font-mono text-[11px] text-foreground">
                                                                                    {JSON.stringify(signal.actual || {})}
                                                                                </div>
                                                                            </div>
                                                                        </div>
                                                                    </div>
                                                                ))
                                                            ) : (
                                                                <div className="rounded-md border border-dashed border-border bg-card/60 p-3 text-xs text-muted-foreground">
                                                                    No active findings in this lane.
                                                                </div>
                                                            )}
                                                        </div>
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    </div>
                                )}

                                {activeTab === "resolver" && (
                                    <div className="grid gap-5 lg:grid-cols-2">
                                        <div className="rounded-lg border border-border bg-card p-5">
                                            <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                                                <Users className="h-4 w-4 text-primary" />
                                                Entity resolver
                                            </h2>
                                            <p className="mt-2 text-sm text-muted-foreground">
                                                Resolver configuration will use the active Forge schema, source keys, and inferred identities. Current data is ready for {entityMetric} entities.
                                            </p>
                                        </div>
                                        <div className="rounded-lg border border-border bg-card p-5">
                                            <h3 className="text-sm font-semibold text-foreground">Signals available</h3>
                                            <div className="mt-4 grid grid-cols-2 gap-3">
                                                {[
                                                    { label: "Entity labels", value: forgeEntityTypes.length },
                                                    { label: "Relationships", value: forgeRelationships.length },
                                                    { label: "Source objects", value: sourceMappings.length },
                                                    { label: "Fields", value: sourceFieldCount },
                                                ].map((item) => (
                                                    <div key={item.label} className="rounded-md border border-border bg-background p-3">
                                                        <div className="font-mono text-lg font-semibold text-foreground">{formatMetric(item.value)}</div>
                                                        <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{item.label}</div>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    </div>
                                )}

                                {activeTab === "cores" && (
                                    <div className="rounded-lg border border-border bg-card">
                                        <div className="border-b border-border px-4 py-3">
                                            <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                                                <Package className="h-4 w-4 text-primary" />
                                                Context cores
                                            </h2>
                                            <p className="mt-1 text-xs text-muted-foreground">
                                                Cores are built from the active database graph, Forge schema, and source lineage.
                                            </p>
                                        </div>
                                        <div className="grid gap-4 p-4 lg:grid-cols-3">
                                            {[
                                                { label: "Source core", value: selectedConnection?.name || "No source", detail: selectedConnection?.short_name || "connect source" },
                                                { label: "Graph core", value: isGraphCommitPending ? graphNodeMetric : `${graphNodeMetric} nodes`, detail: isGraphCommitPending ? "relationships pending" : `${graphEdgeMetric} relationships` },
                                                { label: "Forge core", value: activeMappingArtifact?.status || "preview", detail: `${formatMetric(forgeEntityTypes.length)} entity labels` },
                                            ].map((item) => (
                                                <div key={item.label} className="rounded-md border border-border bg-background p-4">
                                                    <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{item.label}</div>
                                                    <div className="mt-2 truncate text-base font-semibold text-foreground">{item.value}</div>
                                                    <div className="mt-1 truncate font-mono text-xs text-muted-foreground">{item.detail}</div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                            </section>
                                </div>
                            )}
                        </main>

                        {activeTab !== "graph" && activeTab !== "drift" && (
                            <aside className="hidden min-w-0 flex-col overflow-hidden border-l border-border bg-card/70 xl:flex">
                                <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
                                <div className="rounded-lg border border-border bg-card">
                                    <div className="border-b border-border px-4 py-3">
                                        <h2 className="text-sm font-semibold text-foreground">Inspector</h2>
                                    </div>
                                    <div className="space-y-3 p-4 text-sm">
                                        <div className="flex items-center gap-2">
                                            {selectedConnection && <img src={getAppIconUrl(selectedConnection.short_name, resolvedTheme)} alt="" className="h-6 w-6" />}
                                            <div className="min-w-0">
                                                <div className="truncate font-medium text-foreground">{selectedConnection?.name || "No source selected"}</div>
                                                <div className="font-mono text-xs text-muted-foreground">{selectedConnection?.short_name || "source"}</div>
                                            </div>
                                        </div>
                                        <dl className="grid grid-cols-[96px_1fr] gap-y-2 text-xs">
                                            <dt className="text-muted-foreground">Cursor</dt>
                                            <dd className="truncate font-mono text-foreground">{activeForgeSource?.cursor_field || selectedConnection?.schedule?.cursor_field || "-"}</dd>
                                            <dt className="text-muted-foreground">Entities</dt>
                                            <dd className={cn("font-mono", isActiveSyncRunning ? "text-blue-600 dark:text-blue-400" : "text-foreground")}>
                                                {isActiveSyncRunning ? "syncing" : formatMetric(activeForgeSource?.graph.entity_count || selectedConnection?.entities?.total_entities)}
                                            </dd>
                                            <dt className="text-muted-foreground">Graph</dt>
                                            <dd className={cn("font-mono", isGraphCommitPending ? "text-blue-600 dark:text-blue-400" : "text-foreground")}>
                                                {isGraphCommitPending ? "indexing" : `${formatMetric(activeForgeSource?.graph?.neo4j_nodes)} nodes`}
                                            </dd>
                                            <dt className="text-muted-foreground">Rels</dt>
                                            <dd className={cn("font-mono", isGraphCommitPending ? "text-blue-600 dark:text-blue-400" : "text-foreground")}>
                                                {isGraphCommitPending ? "indexing" : formatMetric(activeForgeSource?.graph?.neo4j_edges)}
                                            </dd>
                                        </dl>
                                    </div>
                                </div>
                                <div className="rounded-lg border border-primary/30 bg-primary/10">
                                    <div className="border-b border-primary/20 px-4 py-3">
                                        <h2 className="flex items-center gap-2 text-sm font-semibold text-primary">
                                            <Sparkles className="h-4 w-4" />
                                            Context Forge
                                        </h2>
                                    </div>
                                    <div className="space-y-3 p-4 text-sm text-muted-foreground">
                                        <p>
                                            Forge preview is built from the connector setup discovery, selected scope, cursor schedule, entity rows, and graph events.
                                        </p>
                                        <div className="rounded-md bg-background/60 p-3">
                                            <div className="text-xs uppercase tracking-wider text-muted-foreground">Mappings ready</div>
                                            <div className="mt-1 font-mono text-lg font-semibold text-foreground">{formatMetric(activeForgeSource?.mappings.length)}</div>
                                        </div>
                                    </div>
                                </div>
                                </div>
                            </aside>
                        )}
                    </div>

                    <DeleteCollectionDialog
                        open={showDeleteDialog}
                        onOpenChange={setShowDeleteDialog}
                        onConfirm={handleDeleteCollection}
                        collectionReadableId={collection?.readable_id || ''}
                        confirmText={confirmText}
                        setConfirmText={setConfirmText}
                    />
                </>
            )}
        </div>
    );
};

export default Collections;
