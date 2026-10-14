import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  Clock,
  Database,
  Edit3,
  EyeOff,
  KeyRound,
  Loader2,
  RefreshCw,
  Save,
  Search,
  Server,
  ShieldCheck,
  Sparkles,
  Table2,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { GraphSchemaPreview, type ForgeGraphPreview } from "@/components/forge/GraphSchemaPreview";
import { Input } from "@/components/ui/input";
import { apiClient } from "@/lib/api";
import { useTheme } from "@/lib/theme-provider";
import { useCollectionsStore } from "@/lib/stores/collections";
import { cn } from "@/lib/utils";
import { getAppIconUrl } from "@/lib/utils/icons";

type ProviderKey = "postgresql" | "clickhouse" | "snowflake";
type WizardStep = "auth" | "test" | "discover" | "scope" | "schedule";

type FieldSpec = {
  key: string;
  label: string;
  type?: string;
  placeholder?: string;
  secret?: boolean;
  span?: "full";
};

type SetupDraft = {
  id: string;
  provider_short_name: string;
  target_collection_id?: string | null;
  connection_name?: string | null;
  current_step: WizardStep;
  status: string;
  config?: Record<string, unknown> | null;
  test_result?: TestResult | null;
  discovery_snapshot?: DiscoverySnapshot | null;
  scope?: SetupScope | null;
  schedule?: SetupSchedule | null;
  finalized_source_connection_id?: string | null;
};

type FinalizedConnection = {
  id: string;
  name: string;
  short_name: string;
  readable_collection_id?: string;
  status?: string;
  sync_id?: string | null;
  modified_at?: string | null;
  schedule?: {
    cron?: string | null;
    next_run?: string | null;
    continuous?: boolean;
    cursor_field?: string | null;
    cursor_value?: unknown;
  } | null;
  sync?: {
    total_runs?: number;
    successful_runs?: number;
    failed_runs?: number;
    last_job?: SyncJobDetails | null;
  } | null;
  last_job?: SyncJobDetails | null;
  entities?: {
    total_entities?: number;
    by_type?: Record<string, { count?: number; last_updated?: string | null; sync_status?: string | null }>;
  } | null;
  drift?: Record<string, unknown> | null;
};

type SyncJobDetails = {
  id?: string;
  status?: string;
  started_at?: string | null;
  completed_at?: string | null;
  duration_seconds?: number | null;
  entities_inserted?: number;
  entities_updated?: number;
  entities_deleted?: number;
  entities_failed?: number;
  error?: string | null;
};

type TestResult = {
  status: "passed" | "warning" | "failed";
  latency_ms: number;
  permissions: string[];
  object_count: number;
  dbt_model_count: number;
  message: string;
  checked_at: string;
};

type DiscoveredObject = {
  name: string;
  type: string;
  rows: number;
  columns: number;
  foreign_keys: number;
  inferred_entity: string;
  pii: string[];
  selected: boolean;
  fields?: Array<{
    name: string;
    data_type?: string | null;
    primary_key?: boolean;
    foreign_key?: boolean;
    ref_table?: string | null;
    pii?: string[];
  }>;
};

type DiscoverySnapshot = {
  source_identity: Record<string, string | number>;
  objects: DiscoveredObject[];
  totals: Record<string, string | number>;
  sync_estimate: Record<string, unknown>;
  generated_at: string;
  forge_mapping_id?: string | null;
  graph_preview?: ForgeGraphPreview | null;
};

type SetupScope = {
  selected_objects?: string[];
  exclude_masks?: string[];
  masked_fields?: Record<string, string[]>;
  sample_cap?: number | null;
  pii_acknowledged?: boolean;
};

type SetupSchedule = {
  cadence: string;
  cursor_field?: string | null;
  backfill_window: string;
  dead_letter_behavior: string;
};

type ProcessingPhase = "load" | "draft" | "test" | "discover" | "scope" | "schedule" | "refresh";

type ProcessingStat = {
  label: string;
  value: string;
};

const steps: Array<{ id: WizardStep; label: string; hint: string }> = [
  { id: "auth", label: "Auth", hint: "credentials" },
  { id: "test", label: "Test", hint: "latency and grants" },
  { id: "discover", label: "Discover", hint: "schema and logic" },
  { id: "scope", label: "Scope", hint: "tables and masks" },
  { id: "schedule", label: "Schedule", hint: "cursor cadence" },
];

const processingCopy: Record<ProcessingPhase, {
  title: string;
  subtitle: string;
  checks: string[];
}> = {
  load: {
    title: "Loading setup state",
    subtitle: "Restoring the draft, source identity, and latest sync handoff.",
    checks: ["Resolve draft", "Hydrate saved config", "Load connection state"],
  },
  draft: {
    title: "Saving setup draft",
    subtitle: "Persisting the current connector configuration without storing secrets.",
    checks: ["Validate draft shape", "Write config snapshot", "Update draft pointer"],
  },
  test: {
    title: "Testing connection",
    subtitle: "Validating credentials, grants, latency, and schema-read permissions.",
    checks: ["Open source session", "Check read grants", "Count discoverable objects"],
  },
  discover: {
    title: "Discovering schema",
    subtitle: "Reading tables, columns, foreign keys, PII hints, and Forge candidates.",
    checks: ["Scan information schema", "Build relationship map", "Generate Forge preview"],
  },
  scope: {
    title: "Saving ingestion scope",
    subtitle: "Locking selected objects, masking policy, sample cap, and PII acknowledgement.",
    checks: ["Persist selected objects", "Attach mask policy", "Prepare schedule step"],
  },
  schedule: {
    title: "Creating connection and starting sync",
    subtitle: "Persisting credentials, cursor schedule, scope, and the first graph sync request.",
    checks: ["Create source connection", "Store cursor baseline", "Queue first sync"],
  },
  refresh: {
    title: "Refreshing sync status",
    subtitle: "Reading the latest job, cursor, entity counts, and drift state.",
    checks: ["Fetch connection", "Read sync job", "Update dashboard state"],
  },
};

const processingStep: Record<ProcessingPhase, WizardStep | null> = {
  load: null,
  draft: null,
  test: "test",
  discover: "discover",
  scope: "scope",
  schedule: "schedule",
  refresh: "schedule",
};

const detectedMaskMap = (objects: DiscoveredObject[] = []) => {
  return objects.reduce<Record<string, string[]>>((acc, object) => {
    const fields = (object.fields || [])
      .filter((field) => (field.pii?.length || 0) > 0 && !field.primary_key && !field.foreign_key)
      .map((field) => field.name);
    if (fields.length > 0) acc[object.name] = Array.from(new Set(fields));
    return acc;
  }, {});
};

const normalizeMaskMap = (value?: Record<string, string[]> | null) => {
  if (!value) return {};
  return Object.entries(value).reduce<Record<string, string[]>>((acc, [objectName, fields]) => {
    const normalizedFields = Array.from(new Set((fields || []).map((field) => String(field).trim()).filter(Boolean)));
    if (objectName && normalizedFields.length > 0) acc[objectName] = normalizedFields;
    return acc;
  }, {});
};

const providerConfig: Record<ProviderKey, {
  label: string;
  shortName: string;
  logoKey: string;
  title: string;
  subtitle: string;
  authMethod: string;
  defaultName: string;
  canFinalize: boolean;
  fields: FieldSpec[];
  defaultValues: Record<string, string>;
}> = {
  postgresql: {
    label: "PostgreSQL",
    shortName: "postgresql",
    logoKey: "postgresql",
    title: "Connect PostgreSQL",
    subtitle: "Validate read-only credentials, discover schemas, scope tables, then persist a cursor schedule.",
    authMethod: "direct",
    defaultName: "postgres-prod",
    canFinalize: true,
    fields: [
      { key: "host", label: "Host", placeholder: "db.internal" },
      { key: "port", label: "Port", type: "number", placeholder: "5432" },
      { key: "database", label: "Database", placeholder: "appdb" },
      { key: "db_schema", label: "Schema", placeholder: "public" },
      { key: "user", label: "User", placeholder: "contextd_reader" },
      { key: "password", label: "Password", type: "password", secret: true },
      { key: "tables", label: "Tables", placeholder: "*", span: "full" },
      { key: "dbt_project", label: "dbt project", placeholder: "github.com/acme/analytics-dbt", span: "full" },
    ],
    defaultValues: {
      host: "",
      port: "5432",
      database: "",
      db_schema: "public",
      user: "",
      password: "",
      tables: "*",
      dbt_project: "",
    },
  },
  clickhouse: {
    label: "ClickHouse",
    shortName: "clickhouse",
    logoKey: "clickhouse",
    title: "Connect ClickHouse",
    subtitle: "Validate service credentials, inspect databases, scope tables, and schedule recurring sync.",
    authMethod: "direct",
    defaultName: "clickhouse-warehouse",
    canFinalize: true,
    fields: [
      { key: "host", label: "Host", placeholder: "cluster.us-east1.gcp.clickhouse.cloud" },
      { key: "port", label: "Port", type: "number", placeholder: "8443" },
      { key: "database", label: "Database", placeholder: "default" },
      { key: "user", label: "User", placeholder: "default" },
      { key: "password", label: "Password", type: "password", secret: true },
      { key: "secure", label: "Secure", placeholder: "true" },
      { key: "tables", label: "Tables", placeholder: "*", span: "full" },
      { key: "cursor_field", label: "Cursor field", placeholder: "updated_at", span: "full" },
    ],
    defaultValues: {
      host: "",
      port: "8443",
      database: "default",
      user: "default",
      password: "",
      secure: "true",
      tables: "*",
      cursor_field: "",
    },
  },
  snowflake: {
    label: "Snowflake",
    shortName: "snowflake",
    logoKey: "snowflake",
    title: "Connect Snowflake",
    subtitle: "Use a read-only key-pair role, inspect INFORMATION_SCHEMA, and stage the Forge-ready mapping path.",
    authMethod: "key_pair",
    defaultName: "snowflake-warehouse",
    canFinalize: false,
    fields: [
      { key: "account", label: "Account", placeholder: "acme.us-east-1" },
      { key: "warehouse", label: "Warehouse", placeholder: "ANALYTICS_WH" },
      { key: "database", label: "Database", placeholder: "PROD" },
      { key: "schema", label: "Schema", placeholder: "ANALYTICS" },
      { key: "role", label: "Role", placeholder: "CONTEXTD_READER" },
      { key: "user", label: "User", placeholder: "CONTEXTD_SERVICE" },
      { key: "private_key", label: "Private key", type: "password", secret: true, span: "full" },
      { key: "private_key_passphrase", label: "Key passphrase", type: "password", secret: true, span: "full" },
      { key: "dbt_project", label: "dbt project", placeholder: "github.com/acme/analytics-dbt", span: "full" },
    ],
    defaultValues: {
      account: "",
      warehouse: "",
      database: "",
      schema: "",
      role: "CONTEXTD_READER",
      user: "",
      private_key: "",
      private_key_passphrase: "",
      dbt_project: "",
    },
  },
};

const secretKeys = new Set(["password", "private_key", "private_key_passphrase"]);

const normalizeProvider = (value?: string): ProviderKey | null => {
  const normalized = (value || "").toLowerCase().replace("-", "_");
  if (normalized === "postgres" || normalized === "pg" || normalized === "postgresql") {
    return "postgresql";
  }
  if (normalized === "clickhouse" || normalized === "click_house") {
    return "clickhouse";
  }
  if (normalized === "snowflake" || normalized === "snowflake_warehouse") {
    return "snowflake";
  }
  return null;
};

const formatNumber = (value: number) => {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 1 : 2)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 100_000 ? 0 : 1)}K`;
  return String(value);
};

const formatPreviewValue = (value: unknown) => {
  if (value == null || value === "") return "-";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "-";
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, entryValue]) => entryValue != null && entryValue !== "" && entryValue !== 0)
      .map(([key, entryValue]) => `${key.replace(/_/g, " ")} ${String(entryValue)}`);
    return entries.length ? entries.join(" · ") : "none";
  }
  return String(value);
};

const wideSyncEstimateKeys = new Set(["first_sync", "incremental", "cursor_coverage"]);

const formatLabel = (value?: string | null) => {
  if (!value) return "-";
  return value.replace(/_/g, " ");
};

const formatCadence = (value?: string | null) => {
  if (!value) return "-";
  if (value === "every_5_min") return "every 5 min";
  if (value === "every_15_min") return "every 15 min";
  if (value === "all_history") return "all history";
  return formatLabel(value);
};

const statusTone = (status?: string | null) => {
  if (
    status === "passed" ||
    status === "ready" ||
    status === "active" ||
    status === "completed" ||
    status === "finalized" ||
    status === "clean"
  ) return "text-green-600 bg-green-500/10 border-green-500/25 dark:text-green-400";
  if (status === "running" || status === "syncing" || status === "pending" || status === "pending_sync" || status === "created") {
    return "text-blue-600 bg-blue-500/10 border-blue-500/25 dark:text-blue-400";
  }
  if (status === "warning" || status === "changed" || status === "discovered" || status === "tested") {
    return "text-amber-600 bg-amber-500/10 border-amber-500/25 dark:text-amber-400";
  }
  if (status === "failed" || status === "error" || status === "critical" || status === "cancelled") {
    return "text-red-600 bg-red-500/10 border-red-500/25 dark:text-red-400";
  }
  return "text-muted-foreground bg-muted/50 border-border";
};

const readApiError = async (response: Response, fallback: string) => {
  const text = await response.text();
  if (!text) return fallback;

  try {
    const data = JSON.parse(text);
    return data.detail || data.message || fallback;
  } catch {
    return text;
  }
};

const PhaseProcessingCard = ({
  phase,
  stats,
  compact = false,
  className,
}: {
  phase: ProcessingPhase;
  stats?: ProcessingStat[];
  compact?: boolean;
  className?: string;
}) => {
  const copy = processingCopy[phase];

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-lg border border-primary/25 bg-primary/10 text-foreground shadow-sm",
        compact ? "p-3" : "p-4",
        className
      )}
      role="status"
      aria-live="polite"
    >
      <div className="absolute inset-0 shimmer opacity-60" />
      <div className="relative flex min-w-0 items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-primary/25 bg-background text-primary">
          <Loader2 className="h-4 w-4 animate-spin" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className={cn("font-semibold text-foreground", compact ? "text-sm" : "text-base")}>{copy.title}</h3>
            <span className="rounded border border-primary/25 bg-background/70 px-2 py-0.5 font-mono text-[10px] text-primary">
              processing
            </span>
          </div>
          <p className={cn("mt-1 text-muted-foreground", compact ? "text-xs" : "text-sm")}>{copy.subtitle}</p>
          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            {copy.checks.map((check, index) => (
              <div
                key={check}
                className="flex min-w-0 items-center gap-2 rounded-md border border-primary/15 bg-background/70 px-2.5 py-2"
              >
                {index === 0 ? (
                  <Activity className="h-3.5 w-3.5 shrink-0 text-primary" />
                ) : (
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary/60" />
                )}
                <span className="truncate text-xs text-muted-foreground">{check}</span>
              </div>
            ))}
          </div>
          {stats && stats.length > 0 && (
            <dl className="mt-3 grid gap-2 sm:grid-cols-3">
              {stats.map((stat) => (
                <div key={stat.label} className="rounded-md border border-primary/15 bg-background/70 px-2.5 py-2">
                  <dt className="text-[10px] uppercase tracking-wider text-muted-foreground">{stat.label}</dt>
                  <dd className="mt-1 truncate font-mono text-xs text-foreground">{stat.value}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      </div>
    </div>
  );
};

const SourceSetupPage = () => {
  const { provider: providerParam } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const providerKey = normalizeProvider(providerParam);
  const provider = providerKey ? providerConfig[providerKey] : null;
  const requestedDatabase = searchParams.get("database") || "";
  const draftStorageKey = providerKey
    ? `contextd-source-setup-draft:${providerKey}:${requestedDatabase || "workspace"}`
    : null;
  const navigate = useNavigate();
  const { resolvedTheme } = useTheme();
  const { collections, fetchCollections, fetchSourceConnections } = useCollectionsStore();

  const [currentStep, setCurrentStep] = useState<WizardStep>("auth");
  const [draft, setDraft] = useState<SetupDraft | null>(null);
  const [connectionName, setConnectionName] = useState(provider?.defaultName || "");
  const [targetDatabase, setTargetDatabase] = useState(requestedDatabase);
  const [values, setValues] = useState<Record<string, string>>(provider?.defaultValues || {});
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [discovery, setDiscovery] = useState<DiscoverySnapshot | null>(null);
  const [finalizedConnection, setFinalizedConnection] = useState<FinalizedConnection | null>(null);
  const [selectedObjects, setSelectedObjects] = useState<Set<string>>(new Set());
  const [objectFilter, setObjectFilter] = useState("");
  const [excludeMasks, setExcludeMasks] = useState("*.password,*.secret,*token*");
  const [maskedFields, setMaskedFields] = useState<Record<string, string[]>>({});
  const [sampleCap, setSampleCap] = useState("10000");
  const [piiAcknowledged, setPiiAcknowledged] = useState(false);
  const [schedule, setSchedule] = useState<SetupSchedule>({
    cadence: "every_15_min",
    cursor_field: providerKey === "snowflake" ? "LOAD_TIMESTAMP" : "updated_at",
    backfill_window: "all_history",
    dead_letter_behavior: "retain_and_alert",
  });
  const [setupError, setSetupError] = useState<string | null>(null);
  const [, setIsSaving] = useState(false);
  const [isSavingScope, setIsSavingScope] = useState(false);
  const [isRefreshingConnection, setIsRefreshingConnection] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [isDiscovering, setIsDiscovering] = useState(false);
  const [processingPhase, setProcessingPhase] = useState<ProcessingPhase | null>(null);
  const draftCreatePromiseRef = useRef<Promise<SetupDraft> | null>(null);

  useEffect(() => {
    fetchCollections().catch(() => undefined);
  }, [fetchCollections]);

  useEffect(() => {
    if (requestedDatabase && requestedDatabase !== targetDatabase) {
      setTargetDatabase(requestedDatabase);
      setDraft(null);
      setTestResult(null);
      setDiscovery(null);
      setFinalizedConnection(null);
      setSelectedObjects(new Set());
      setMaskedFields({});
    }
  }, [requestedDatabase, targetDatabase]);

  useEffect(() => {
    if (!provider) return;
    setConnectionName(provider.defaultName);
    setValues(provider.defaultValues);
    setSchedule((previous) => ({
      ...previous,
      cursor_field: provider.shortName === "snowflake" ? "LOAD_TIMESTAMP" : "updated_at",
    }));
  }, [provider]);

  useEffect(() => {
    if (!targetDatabase && collections.length > 0) {
      setTargetDatabase(collections[0].readable_id);
    }
  }, [collections, targetDatabase]);

  const safeConfig = useMemo(() => {
    return Object.entries(values).reduce<Record<string, string>>((acc, [key, value]) => {
      if (!secretKeys.has(key) && value !== "") acc[key] = value;
      return acc;
    }, {});
  }, [values]);

  const persistDraftReference = useCallback((draftId: string) => {
    if (draftStorageKey && typeof window !== "undefined") {
      window.localStorage.setItem(draftStorageKey, draftId);
    }
    if (searchParams.get("draft") !== draftId) {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.set("draft", draftId);
      setSearchParams(nextParams, { replace: true });
    }
  }, [draftStorageKey, searchParams, setSearchParams]);

  const hydrateDraftState = useCallback((loadedDraft: SetupDraft) => {
    if (!provider) return;

    const loadedConfig = loadedDraft.config || {};
    const nextValues = { ...provider.defaultValues };
    Object.entries(loadedConfig).forEach(([key, value]) => {
      if (secretKeys.has(key) || value == null) return;
      if (key in nextValues) nextValues[key] = String(value);
    });
    if ("db_schema" in nextValues && loadedConfig.schema && !loadedConfig.db_schema) {
      nextValues.db_schema = String(loadedConfig.schema);
    }

    const loadedScope = loadedDraft.scope;
    const loadedDiscovery = loadedDraft.discovery_snapshot || null;
    const selectedFromScope = loadedScope?.selected_objects;
    const selectedFromDiscovery = loadedDiscovery?.objects
      ?.filter((object) => object.selected)
      .map((object) => object.name);

    setDraft(loadedDraft);
    setConnectionName(loadedDraft.connection_name || provider.defaultName);
    setTargetDatabase(loadedDraft.target_collection_id || requestedDatabase || "");
    setValues((previousValues) => {
      const withTransientSecrets = { ...nextValues };
      Object.keys(withTransientSecrets).forEach((key) => {
        if (secretKeys.has(key) && previousValues[key]) {
          withTransientSecrets[key] = previousValues[key];
        }
      });
      return withTransientSecrets;
    });
    setTestResult(loadedDraft.test_result || null);
    setDiscovery(loadedDiscovery);
    setCurrentStep(loadedDraft.status === "finalized" ? "schedule" : loadedDraft.current_step || "auth");
    setSelectedObjects(new Set(selectedFromScope || selectedFromDiscovery || []));
    setMaskedFields(
      loadedScope?.masked_fields
        ? normalizeMaskMap(loadedScope.masked_fields)
        : detectedMaskMap(loadedDiscovery?.objects || [])
    );
    if (loadedScope?.exclude_masks) setExcludeMasks(loadedScope.exclude_masks.join(","));
    if (loadedScope?.sample_cap != null) setSampleCap(String(loadedScope.sample_cap));
    if (typeof loadedScope?.pii_acknowledged === "boolean") {
      setPiiAcknowledged(loadedScope.pii_acknowledged);
    }
    if (loadedDraft.schedule) {
      setSchedule((previous) => ({
        ...previous,
        ...loadedDraft.schedule,
        cursor_field: loadedDraft.schedule?.cursor_field || previous.cursor_field,
      }));
    }
  }, [provider, requestedDatabase]);

  useEffect(() => {
    if (!provider || !providerKey) return;

    const storedDraftId = draftStorageKey && typeof window !== "undefined"
      ? window.localStorage.getItem(draftStorageKey)
      : null;
    const draftId = searchParams.get("draft") || storedDraftId;
    if (!draftId) return;

    let cancelled = false;
    const loadDraft = async () => {
      setIsSaving(true);
      setProcessingPhase("load");
      setSetupError(null);
      try {
        const response = await apiClient.get(`/source-setup-drafts/${draftId}`);
        if (!response.ok) throw new Error(await readApiError(response, "Failed to load setup draft"));
        const loadedDraft = await response.json() as SetupDraft;
        if (normalizeProvider(loadedDraft.provider_short_name) !== providerKey) {
          if (draftStorageKey && typeof window !== "undefined") {
            window.localStorage.removeItem(draftStorageKey);
          }
          return;
        }
        if (
          requestedDatabase &&
          loadedDraft.target_collection_id &&
          loadedDraft.target_collection_id !== requestedDatabase
        ) {
          if (draftStorageKey && typeof window !== "undefined") {
            window.localStorage.removeItem(draftStorageKey);
          }
          return;
        }
        if (cancelled) return;

        hydrateDraftState(loadedDraft);
        persistDraftReference(loadedDraft.id);

        if (loadedDraft.finalized_source_connection_id) {
          const connectionResponse = await apiClient.get(
            `/source-connections/${loadedDraft.finalized_source_connection_id}`
          );
          if (!connectionResponse.ok) throw new Error(await readApiError(connectionResponse, "Failed to load source connection"));
          const connection = await connectionResponse.json() as FinalizedConnection;
          if (!cancelled) setFinalizedConnection(connection);
        } else {
          setFinalizedConnection(null);
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : "Failed to load setup draft";
        if (!cancelled) setSetupError(message);
      } finally {
        if (!cancelled) {
          setIsSaving(false);
          setProcessingPhase((phase) => phase === "load" ? null : phase);
        }
      }
    };

    loadDraft();
    return () => {
      cancelled = true;
    };
  }, [
    draftStorageKey,
    hydrateDraftState,
    persistDraftReference,
    provider,
    providerKey,
    searchParams,
  ]);

  const ensureDraft = useCallback(async () => {
    if (!provider || !providerKey) throw new Error("Unsupported provider");
    if (draft) return draft;
    if (draftCreatePromiseRef.current) {
      return draftCreatePromiseRef.current;
    }

    const createDraft = async () => {
      const response = await apiClient.post("/source-setup-drafts", {
        provider_short_name: provider.shortName,
        target_collection_id: targetDatabase || null,
        connection_name: connectionName,
        current_step: "auth",
        auth_method: provider.authMethod,
        config: safeConfig,
      });
      if (!response.ok) throw new Error(await readApiError(response, "Failed to create setup draft"));
      const created = await response.json();
      setDraft(created);
      persistDraftReference(created.id);
      return created as SetupDraft;
    };

    draftCreatePromiseRef.current = createDraft();
    try {
      return await draftCreatePromiseRef.current;
    } finally {
      draftCreatePromiseRef.current = null;
    }
  }, [connectionName, draft, persistDraftReference, provider, providerKey, safeConfig, targetDatabase]);

  const saveDraft = useCallback(async (patch: Record<string, unknown> = {}) => {
    if (!provider) return;
    setIsSaving(true);
    setProcessingPhase("draft");
    setSetupError(null);
    try {
      const activeDraft = await ensureDraft();
      const response = await apiClient.patch(`/source-setup-drafts/${activeDraft.id}`, {
        target_collection_id: targetDatabase || null,
        connection_name: connectionName,
        auth_method: provider.authMethod,
        config: safeConfig,
        ...patch,
      });
      if (!response.ok) throw new Error(await readApiError(response, "Failed to save setup draft"));
      const updated = await response.json();
      setDraft(updated);
      toast.success("Setup draft saved");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to save setup draft";
      setSetupError(message);
      toast.error(message);
    } finally {
      setIsSaving(false);
      setProcessingPhase((phase) => phase === "draft" ? null : phase);
    }
  }, [connectionName, ensureDraft, provider, safeConfig, targetDatabase]);

  const refreshFinalizedConnection = useCallback(async (
    connectionId?: string | null,
    options: { silent?: boolean } = {}
  ) => {
    if (!connectionId) return null;
    if (!options.silent) {
      setIsRefreshingConnection(true);
      setProcessingPhase("refresh");
      setSetupError(null);
    }

    try {
      const response = await apiClient.get(`/source-connections/${connectionId}`);
      if (!response.ok) throw new Error(await readApiError(response, "Failed to load source connection"));
      const connection = await response.json() as FinalizedConnection;
      setFinalizedConnection(connection);
      const collectionId = connection.readable_collection_id || targetDatabase;
      if (collectionId) {
        void fetchSourceConnections(collectionId, true);
      }
      void fetchCollections(true);
      if (!options.silent) toast.success("Sync state refreshed");
      return connection;
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to load source connection";
      if (!options.silent) {
        setSetupError(message);
        toast.error(message);
      }
      return null;
    } finally {
      if (!options.silent) {
        setIsRefreshingConnection(false);
        setProcessingPhase((phase) => phase === "refresh" ? null : phase);
      }
    }
  }, [fetchCollections, fetchSourceConnections, targetDatabase]);

  const runTest = async () => {
    if (!provider) return;
    setIsTesting(true);
    setCurrentStep("test");
    setProcessingPhase("test");
    setSetupError(null);
    try {
      const activeDraft = await ensureDraft();
      const response = await apiClient.post(`/source-setup-drafts/${activeDraft.id}/test`, {
        auth_method: provider.authMethod,
        credentials: values,
        config: safeConfig,
        target_collection_id: targetDatabase || null,
        connection_name: connectionName,
      });
      if (!response.ok) throw new Error(await readApiError(response, "Connection test failed"));
      const result = await response.json();
      setTestResult(result);
      setDraft((previous) =>
        previous ? { ...previous, current_step: "test", status: "tested" } : previous
      );
      setCurrentStep("test");
      toast.success("Connection test passed");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Connection test failed";
      setSetupError(message);
      toast.error(message);
    } finally {
      setIsTesting(false);
      setProcessingPhase((phase) => phase === "test" ? null : phase);
    }
  };

  const runDiscovery = async () => {
    setIsDiscovering(true);
    setCurrentStep("discover");
    setProcessingPhase("discover");
    setSetupError(null);
    try {
      const activeDraft = await ensureDraft();
      const response = await apiClient.post(`/source-setup-drafts/${activeDraft.id}/discover`, {
        config: safeConfig,
        credentials: values,
      });
      if (!response.ok) throw new Error(await readApiError(response, "Discovery failed"));
      const snapshot = await response.json();
      setDiscovery(snapshot);
      setDraft((previous) =>
        previous ? { ...previous, current_step: "discover", status: "discovered" } : previous
      );
      setSelectedObjects(new Set(
        snapshot.objects
          .filter((object: DiscoveredObject) => object.selected)
          .map((object: DiscoveredObject) => object.name)
      ));
      setMaskedFields(detectedMaskMap(snapshot.objects));
      const suggestedCursor = snapshot.sync_estimate?.default_cursor_field;
      if (typeof suggestedCursor === "string" && suggestedCursor) {
        setSchedule((previous) => {
          if (
            !previous.cursor_field ||
            previous.cursor_field === "updated_at" ||
            previous.cursor_field === "LOAD_TIMESTAMP"
          ) {
            return { ...previous, cursor_field: suggestedCursor };
          }
          return previous;
        });
      }
      setCurrentStep("discover");
      toast.success("Discovery snapshot saved");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Discovery failed";
      setSetupError(message);
      toast.error(message);
    } finally {
      setIsDiscovering(false);
      setProcessingPhase((phase) => phase === "discover" ? null : phase);
    }
  };

  const saveScope = async () => {
    setIsSavingScope(true);
    setProcessingPhase("scope");
    setSetupError(null);
    try {
      const activeDraft = await ensureDraft();
      const response = await apiClient.post(`/source-setup-drafts/${activeDraft.id}/scope`, buildScopePayload());
      if (!response.ok) throw new Error(await readApiError(response, "Failed to save scope"));
      const updated = await response.json();
      setDraft(updated);
      setCurrentStep("schedule");
      toast.success("Scope saved");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to save scope";
      setSetupError(message);
      toast.error(message);
    } finally {
      setIsSavingScope(false);
      setProcessingPhase((phase) => phase === "scope" ? null : phase);
    }
  };

  const saveSchedule = async () => {
    setIsSaving(true);
    setProcessingPhase("schedule");
    setSetupError(null);
    try {
      const activeDraft = await ensureDraft();
      if (provider?.canFinalize) {
        const response = await apiClient.post(`/source-setup-drafts/${activeDraft.id}/finalize`, {
          auth_method: provider.authMethod,
          credentials: values,
          config: safeConfig,
          schedule,
          scope: buildScopePayload(),
          target_collection_id: targetDatabase || null,
          connection_name: connectionName,
          sync_immediately: true,
        });
        if (!response.ok) throw new Error(await readApiError(response, "Failed to create source connection"));
        const finalized = await response.json() as FinalizedConnection;
        setFinalizedConnection(finalized);
        setDraft((previous) =>
          previous
            ? {
              ...previous,
              current_step: "schedule",
              status: "finalized",
              finalized_source_connection_id: finalized.id,
            }
            : previous
        );
        persistDraftReference(activeDraft.id);
        await refreshFinalizedConnection(finalized.id, { silent: true });
        toast.success("Connection created and sync started");
        return;
      }

      const response = await apiClient.post(`/source-setup-drafts/${activeDraft.id}/schedule`, schedule);
      if (!response.ok) throw new Error(await readApiError(response, "Failed to save schedule"));
      const updated = await response.json();
      setDraft(updated);
      toast.success("Setup draft is ready");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to save schedule";
      setSetupError(message);
      toast.error(message);
    } finally {
      setIsSaving(false);
      setProcessingPhase((phase) => phase === "schedule" ? null : phase);
    }
  };

  function buildScopePayload() {
    const selected = Array.from(selectedObjects);
    const scopedMasks = selected.reduce<Record<string, string[]>>((acc, objectName) => {
      const fields = maskedFields[objectName] || [];
      if (fields.length > 0) acc[objectName] = fields;
      return acc;
    }, {});
    return {
      selected_objects: selected,
      exclude_masks: excludeMasks.split(",").map((mask) => mask.trim()).filter(Boolean),
      masked_fields: scopedMasks,
      sample_cap: Number(sampleCap) || null,
      pii_acknowledged: piiAcknowledged,
    };
  }

  const currentStepIndex = steps.findIndex((step) => step.id === currentStep);
  const filteredObjects = (discovery?.objects || []).filter((object) =>
    [object.name, object.inferred_entity, object.pii.join(" ")].join(" ").toLowerCase().includes(objectFilter.toLowerCase())
  );
  const selectedRows = discovery?.objects.filter((object) => selectedObjects.has(object.name)) || [];
  const selectedSummary = `${selectedObjects.size || 0} objects selected`;
  const maskedFieldCount = selectedRows.reduce((total, object) => total + (maskedFields[object.name]?.length || 0), 0);
  const selectedPiiObjects = selectedRows
    .map((object) => ({
      ...object,
      piiFields: (object.fields || []).filter((field) => (field.pii?.length || 0) > 0 && !field.primary_key && !field.foreign_key),
    }))
    .filter((object) => object.piiFields.length > 0);
  const toggleMaskedField = (objectName: string, fieldName: string, checked: boolean) => {
    setMaskedFields((previous) => {
      const current = new Set(previous[objectName] || []);
      if (checked) current.add(fieldName);
      else current.delete(fieldName);
      const next = { ...previous };
      if (current.size > 0) next[objectName] = Array.from(current);
      else delete next[objectName];
      return next;
    });
  };
  const forgePreview = discovery?.graph_preview || draft?.discovery_snapshot?.graph_preview || null;
  const previewIdentityEntries = Object.entries(discovery?.source_identity || safeConfig)
    .filter(([, value]) => value != null && value !== "")
    .slice(0, 5);
  const syncEstimateEntries = [
    "rows",
    "entities",
    "first_sync",
    "default_cursor_field",
    "incremental",
  ].map((key) => [
    key,
    (discovery?.sync_estimate || {
      rows: "-",
      entities: "-",
      first_sync: "-",
      default_cursor_field: schedule.cursor_field || "-",
      incremental: schedule.cadence.replace(/_/g, " "),
    })[key],
  ] as const);
  const forgeSummary = forgePreview
    ? `${forgePreview.nodes.length} nodes · ${forgePreview.edges.length} edges`
    : "waiting for discovery";
  const finalizedJob = finalizedConnection?.sync?.last_job || finalizedConnection?.last_job || null;
  const finalizedState = finalizedJob?.status || finalizedConnection?.status || (finalizedConnection ? "active" : draft?.status || "draft");
  const finalizedSchedule = finalizedConnection?.schedule;
  const finalizedEntityTotal = finalizedConnection?.entities?.total_entities
    ?? ((finalizedJob?.entities_inserted || 0) + (finalizedJob?.entities_updated || 0));
  const finalizedDrift = finalizedConnection?.drift || null;
  const finalizedDriftStatus = typeof finalizedDrift?.status === "string" ? finalizedDrift.status : "clean";
  const finalizedSchemaStatus = typeof finalizedDrift?.schema === "object" && finalizedDrift.schema !== null && "status" in finalizedDrift.schema
    ? String((finalizedDrift.schema as Record<string, unknown>).status || "clean")
    : "clean";
  const finalizedSyncCopy = finalizedJob
    ? `job ${finalizedJob.id?.slice(0, 8) || "queued"} · ${formatLabel(finalizedJob.status)}`
    : finalizedConnection?.sync_id
      ? `sync ${String(finalizedConnection.sync_id).slice(0, 8)}`
      : "sync requested";
  const activeProcessingStep = processingPhase ? processingStep[processingPhase] : null;
  const isProcessing = processingPhase !== null;
  const processingStats: ProcessingStat[] = (() => {
    if (!processingPhase) return [];
    if (processingPhase === "test") {
      return [
        { label: "database", value: targetDatabase || "not selected" },
        { label: "provider", value: provider?.label || "source" },
        { label: "connection", value: connectionName || "unnamed" },
      ];
    }
    if (processingPhase === "discover") {
      return [
        { label: "database", value: targetDatabase || "not selected" },
        { label: "schema", value: values.db_schema || values.database || "default" },
        { label: "tables", value: values.tables || "*" },
      ];
    }
    if (processingPhase === "scope") {
      return [
        { label: "selected", value: String(selectedObjects.size) },
        { label: "sample cap", value: sampleCap || "-" },
        { label: "masked fields", value: String(maskedFieldCount) },
      ];
    }
    if (processingPhase === "schedule") {
      return [
        { label: "cadence", value: formatCadence(schedule.cadence) },
        { label: "cursor", value: schedule.cursor_field || "-" },
        { label: "forge", value: forgeSummary },
      ];
    }
    if (processingPhase === "refresh") {
      return [
        { label: "sync", value: finalizedSyncCopy },
        { label: "state", value: formatLabel(finalizedState) },
        { label: "entities", value: formatNumber(finalizedEntityTotal) },
      ];
    }
    return [
      { label: "draft", value: draft?.id?.slice(0, 8) || "new" },
      { label: "database", value: targetDatabase || "not selected" },
      { label: "step", value: formatLabel(currentStep) },
    ];
  })();

  if (!provider || !providerKey) {
    return (
      <div className="min-h-full bg-background p-6">
        <div className="rounded-lg border border-border bg-card p-8">
          <h1 className="text-xl font-semibold text-foreground">Unsupported connector setup</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            This phase supports PostgreSQL, ClickHouse, and Snowflake structured-source setup.
          </p>
          <Button className="mt-6" onClick={() => navigate("/sources")}>
            Back to connectors
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="border-b border-border bg-card px-4 py-2 sm:px-6">
        <div className="flex min-w-0 flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border bg-background p-1.5">
              <img
                src={getAppIconUrl(provider.logoKey, resolvedTheme)}
                alt={`${provider.label} icon`}
                className="h-full w-full object-contain"
              />
            </div>
            <div className="min-w-0">
              <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                <h1 className="truncate text-sm font-semibold tracking-tight text-foreground">{provider.title}</h1>
                <span className="rounded border border-green-500/25 bg-green-500/10 px-2 py-0.5 text-[10px] font-medium text-green-600 dark:text-green-400">
                  Setup draft
                </span>
                <span className="rounded border border-primary/25 bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
                  Forge ready
                </span>
              </div>
              <p className="mt-0.5 truncate text-[10px] text-muted-foreground">
                {targetDatabase ? `Attach to ${targetDatabase}` : "Choose a context database"} · auth, discovery, scope, and schedule
              </p>
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span className="inline-flex h-7 items-center gap-2 rounded-md border border-border bg-background px-2.5">
              <span>Draft</span>
              <span className="font-mono text-foreground">{draft?.id?.slice(0, 8) || "not saved"}</span>
            </span>
            <span className="inline-flex h-7 items-center gap-2 rounded-md border border-border bg-background px-2.5">
              <span>Status</span>
              <span className={cn("rounded border px-2 py-0.5 font-medium", statusTone(processingPhase ? "running" : finalizedConnection ? finalizedState : draft?.status))}>
                {processingPhase ? "processing" : formatLabel(finalizedConnection ? finalizedState : draft?.status || "draft")}
              </span>
            </span>
          </div>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 xl:grid-cols-[minmax(0,1fr)_340px]">
        <main className="flex min-h-0 min-w-0 flex-col">
          <div className="border-b border-border bg-card px-4 py-2 sm:px-6">
            <div className="flex min-w-0 flex-col gap-2 2xl:flex-row 2xl:items-center">
              <div className="-mx-1 overflow-x-auto px-1">
              <ol className="flex min-w-max flex-1 gap-1 2xl:grid 2xl:min-w-0 2xl:grid-cols-5">
                {steps.map((step, index) => {
                  const done = index < currentStepIndex;
                  const active = step.id === currentStep;
                  const processing = activeProcessingStep === step.id;
                  return (
                    <li key={step.id} className="w-[138px] min-w-0 2xl:w-auto">
                      <button
                        type="button"
                        aria-label={`${step.label}: ${step.hint}`}
                        onClick={() => {
                          if (index <= currentStepIndex || discovery) setCurrentStep(step.id);
                        }}
                        disabled={isProcessing}
                        className={cn(
                          "group relative flex h-9 w-full min-w-0 items-center gap-2 rounded-md px-2.5 text-left transition-colors",
                          active && "bg-background text-foreground shadow-sm ring-1 ring-primary/25",
                          processing && "bg-primary/10 text-foreground ring-1 ring-primary/35",
                          done && !active && "text-foreground hover:bg-muted/60",
                          !active && !done && "text-muted-foreground hover:bg-muted/60",
                          isProcessing && "cursor-wait"
                        )}
                      >
                        <span
                          className={cn(
                            "absolute inset-x-2 bottom-0 h-0.5 rounded-full opacity-0 transition-opacity",
                            done && "bg-primary opacity-40",
                            active && "bg-primary opacity-100",
                            processing && "bg-primary opacity-100"
                          )}
                        />
                        <span
                          className={cn(
                            "flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[10px] font-semibold transition-colors",
                            done && "border-primary/25 bg-primary/10 text-primary",
                            active && "border-primary bg-primary text-primary-foreground",
                            !active && !done && "border-border bg-background text-muted-foreground"
                          )}
                        >
                          {processing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : done ? <Check className="h-3.5 w-3.5" /> : index + 1}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-xs font-semibold">{step.label}</span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ol>
              </div>
              {testResult && (
                <div className="flex min-h-9 shrink-0 flex-wrap items-center gap-2 rounded-md border border-border bg-background px-2.5 py-1 text-xs text-muted-foreground">
                  <span className="h-2 w-2 rounded-full bg-green-500" />
                  <span className="font-semibold text-foreground">Connection OK</span>
                  <span className="hidden h-4 w-px bg-border sm:block" />
                  <span className="font-mono">{testResult.latency_ms} ms</span>
                  <span className="font-mono">{testResult.object_count} objects</span>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="ml-0.5 h-7 w-7 rounded-md"
                    onClick={() => setCurrentStep("auth")}
                    aria-label="Edit connection auth"
                  >
                    <Edit3 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              )}
            </div>
          </div>

          <div className={cn(
            "min-h-0 flex-1 px-4 py-2.5 sm:px-6",
            currentStep === "discover" ? "overflow-hidden" : "overflow-y-auto"
          )}>
            {processingPhase && (
              <PhaseProcessingCard
                phase={processingPhase}
                stats={processingStats}
                className="mb-3"
                compact={currentStep === "discover"}
              />
            )}

            {setupError && (
              <div className="mb-5 rounded-lg border border-red-500/25 bg-red-500/10 p-3">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="mt-0.5 h-5 w-5 text-red-500" />
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground">Setup action failed</p>
                    <p className="mt-1 break-words font-mono text-[11px] text-muted-foreground">
                      {setupError}
                    </p>
                  </div>
                </div>
              </div>
            )}

            {currentStep === "auth" && (
              <section className="space-y-5">
                <div>
                  <h2 className="text-lg font-semibold text-foreground">Connection identity</h2>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Validate read-only access and name the one source that will feed this ContextD database.
                  </p>
                </div>

                <div className="grid gap-4 lg:grid-cols-2">
                  <div className="rounded-lg border border-border bg-card p-4">
                    <label className="mb-2 block text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      Context database
                    </label>
                    <select
                      value={targetDatabase}
                      onChange={(event) => setTargetDatabase(event.target.value)}
                      className="h-9 w-full rounded-md border border-border bg-background px-3 text-sm text-foreground outline-none focus:border-primary"
                    >
                      {targetDatabase && !collections.some((collection) => collection.readable_id === targetDatabase) && (
                        <option value={targetDatabase}>{targetDatabase}</option>
                      )}
                      {collections.length === 0 && !targetDatabase && <option value="">No databases available</option>}
                      {collections.map((collection) => (
                        <option key={collection.id} value={collection.readable_id}>
                          {collection.name} ({collection.readable_id})
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="rounded-lg border border-border bg-card p-4">
                    <label className="mb-2 block text-xs font-medium uppercase tracking-wider text-muted-foreground">
                      Connection name
                    </label>
                    <Input
                      value={connectionName}
                      onChange={(event) => setConnectionName(event.target.value)}
                      className="h-9 border-border bg-background"
                    />
                  </div>
                </div>

                <div className="rounded-lg border border-border bg-card p-4">
                  <div className="mb-4 flex items-center gap-2">
                    <KeyRound className="h-4 w-4 text-primary" />
                    <h3 className="text-sm font-semibold text-foreground">{provider.label} credentials</h3>
                  </div>
                  <div className="grid gap-4 lg:grid-cols-2">
                    {provider.fields.map((field) => (
                      <div key={field.key} className={cn(field.span === "full" && "lg:col-span-2")}>
                        <label className="mb-1.5 flex items-center gap-2 text-xs font-medium text-muted-foreground">
                          {field.label}
                          {field.secret && <EyeOff className="h-3 w-3" />}
                        </label>
                        <Input
                          type={field.type || "text"}
                          value={values[field.key] || ""}
                          placeholder={field.placeholder}
                          onChange={(event) => setValues((previous) => ({ ...previous, [field.key]: event.target.value }))}
                          className="h-9 border-border bg-background font-mono text-xs"
                        />
                      </div>
                    ))}
                  </div>
                </div>
              </section>
            )}

            {currentStep === "test" && (
              <section className="space-y-5">
                <div>
                  <h2 className="text-lg font-semibold text-foreground">Connection test</h2>
                  <p className="mt-1 text-sm text-muted-foreground">
                    This is the checkpoint before schema discovery. It validates auth shape, read grants, and discovery readiness.
                  </p>
                </div>
                <div className="grid gap-3 md:grid-cols-4">
                  {[
                    { label: "Auth", value: testResult?.status || "pending", icon: ShieldCheck },
                    { label: "Latency", value: testResult ? `${testResult.latency_ms} ms` : "-", icon: Clock },
                    { label: "Objects", value: testResult ? String(testResult.object_count) : "-", icon: Table2 },
                    { label: "dbt models", value: testResult ? String(testResult.dbt_model_count) : "-", icon: Sparkles },
                  ].map((metric) => (
                    <div key={metric.label} className="rounded-lg border border-border bg-card p-4">
                      <metric.icon className="mb-3 h-4 w-4 text-primary" />
                      <div className="font-mono text-xl font-semibold text-foreground">{metric.value}</div>
                      <div className="mt-1 text-xs text-muted-foreground">{metric.label}</div>
                    </div>
                  ))}
                </div>
                <div className="rounded-lg border border-border bg-card p-4">
                  <h3 className="text-sm font-semibold text-foreground">Permission map</h3>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {(testResult?.permissions || ["SELECT", "USAGE", "INFORMATION_SCHEMA"]).map((permission) => (
                      <span key={permission} className="inline-flex items-center gap-1 rounded border border-green-500/25 bg-green-500/10 px-2 py-1 text-xs text-green-500">
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        {permission}
                      </span>
                    ))}
                  </div>
                  <p className="mt-3 text-sm text-muted-foreground">{testResult?.message || "Run the connection test to populate this result."}</p>
                </div>
              </section>
            )}

            {currentStep === "discover" && (
              <section className="flex h-full min-h-0 flex-col gap-2">
                <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
                  <div>
                    <h2 className="text-base font-semibold text-foreground">Discover source shape</h2>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {discovery
                        ? `${discovery.totals.shown} shown of ${discovery.totals.tables} objects. ${discovery.totals.foreign_keys} FKs. ${discovery.totals.dbt_models} dbt models.`
                        : "Run discovery to snapshot tables, FKs, PII hints, and Forge candidates."}
                    </p>
                  </div>
                  <div className="relative w-full lg:w-[260px]">
                    <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
	                    <Input
	                      value={objectFilter}
	                      onChange={(event) => setObjectFilter(event.target.value)}
	                      placeholder="Filter objects"
	                      className="h-8 border-border bg-card pl-9 text-sm"
	                    />
	                  </div>
                </div>

                <div className="overflow-x-auto rounded-lg border border-border bg-card">
                  <table className="w-full min-w-[760px] text-left text-xs">
                    <thead className="border-b border-border bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
                      <tr>
	                        <th className="w-10 px-3 py-1.5"></th>
	                        <th className="px-3 py-1.5 font-medium">Table</th>
	                        <th className="px-3 py-1.5 text-right font-medium">Rows</th>
	                        <th className="px-3 py-1.5 text-right font-medium">Cols</th>
	                        <th className="px-3 py-1.5 text-right font-medium">FKs</th>
	                        <th className="px-3 py-1.5 font-medium">Inferred entity</th>
	                        <th className="px-3 py-1.5 font-medium">PII</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {filteredObjects.length === 0 ? (
                        <tr>
                          <td colSpan={7} className="px-3 py-10 text-center text-muted-foreground">
                            {discovery ? "No objects match this filter." : "No discovery snapshot yet."}
                          </td>
                        </tr>
                      ) : filteredObjects.map((object) => (
                        <tr key={object.name} className="hover:bg-muted/30">
	                          <td className="px-3 py-1.5">
                            <input
                              type="checkbox"
                              checked={selectedObjects.has(object.name)}
                              onChange={(event) => {
                                setSelectedObjects((previous) => {
                                  const next = new Set(previous);
                                  if (event.target.checked) next.add(object.name);
                                  else next.delete(object.name);
                                  return next;
                                });
                              }}
                            />
                          </td>
	                          <td className="px-3 py-1.5 font-mono text-foreground">{object.name}</td>
	                          <td className="px-3 py-1.5 text-right font-mono text-muted-foreground">{formatNumber(object.rows)}</td>
	                          <td className="px-3 py-1.5 text-right font-mono text-muted-foreground">{object.columns}</td>
	                          <td className="px-3 py-1.5 text-right font-mono text-muted-foreground">{object.foreign_keys}</td>
	                          <td className="px-3 py-1.5">
                            <span className="rounded border border-primary/25 bg-primary/10 px-2 py-0.5 text-[11px] text-primary">
                              {object.inferred_entity}
                            </span>
                          </td>
	                          <td className="px-3 py-1.5">
                            <div className="flex flex-wrap gap-1">
                              {object.pii.map((pii) => (
                                <span key={pii} className="rounded border border-amber-500/25 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-500">
                                  {pii}
                                </span>
                              ))}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                  <span>{selectedObjects.size} of {discovery?.objects.length || 0} selected</span>
                  <button
                    type="button"
                    className="font-medium text-primary hover:underline"
                    onClick={() => setSelectedObjects(new Set(discovery?.objects.map((object) => object.name) || []))}
                  >
                    Select all shown
                  </button>
                </div>
                <GraphSchemaPreview
                  preview={forgePreview}
                  title="Forge schema preview"
                  subtitle="Entity labels and relationship candidates from discovery."
                  className="min-h-0 flex flex-1 flex-col"
                  canvasClassName="min-h-[260px] flex-1"
                />
              </section>
            )}

            {currentStep === "scope" && (
              <section className="space-y-5">
                <div>
                  <h2 className="text-lg font-semibold text-foreground">Choose source scope</h2>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Select the objects ContextD should index and set masking defaults before scheduling.
                  </p>
                </div>
                <div className="grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
                  <div className="rounded-lg border border-border bg-card p-4">
                    <h3 className="text-sm font-semibold text-foreground">{selectedSummary}</h3>
                    <div className="mt-3 max-h-72 space-y-2 overflow-y-auto">
                      {selectedRows.map((object) => (
                        <div key={object.name} className="flex items-center justify-between rounded-md border border-border bg-background px-3 py-2">
                          <span className="font-mono text-xs text-foreground">{object.name}</span>
                          <span className="text-[11px] text-muted-foreground">{object.inferred_entity}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="rounded-lg border border-border bg-card">
                    <div className="flex items-start justify-between gap-3 border-b border-border p-4">
                      <div>
                        <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                          <ShieldCheck className="h-4 w-4 text-primary" />
                          Masking policy
                        </h3>
                        <p className="mt-1 text-xs text-muted-foreground">
                          Selected fields are redacted before ContextD sync, graph indexing, and query packets.
                        </p>
                      </div>
                      <span className="rounded-md border border-primary/25 bg-primary/10 px-2 py-1 font-mono text-xs text-primary">
                        {maskedFieldCount} masked
                      </span>
                    </div>
                    <div className="max-h-[300px] divide-y divide-border overflow-y-auto">
                      {selectedPiiObjects.length === 0 ? (
                        <div className="flex items-center gap-3 p-4 text-sm text-muted-foreground">
                          <EyeOff className="h-4 w-4" />
                          No detected PII fields in the selected objects.
                        </div>
                      ) : selectedPiiObjects.map((object) => (
                        <div key={object.name} className="p-4">
                          <div className="mb-2 flex items-center justify-between gap-3">
                            <span className="truncate font-mono text-xs font-semibold text-foreground">{object.name}</span>
                            <span className="rounded border border-amber-500/25 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-600 dark:text-amber-300">
                              {object.piiFields.length} detected
                            </span>
                          </div>
                          <div className="grid gap-2 sm:grid-cols-2">
                            {object.piiFields.map((field) => {
                              const checked = (maskedFields[object.name] || []).includes(field.name);
                              return (
                                <label
                                  key={`${object.name}-${field.name}`}
                                  className={cn(
                                    "flex cursor-pointer items-start gap-2 rounded-md border px-3 py-2 text-xs transition-colors",
                                    checked
                                      ? "border-primary/30 bg-primary/10 text-foreground"
                                      : "border-border bg-background text-muted-foreground hover:bg-muted/50"
                                  )}
                                >
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={(event) => toggleMaskedField(object.name, field.name, event.target.checked)}
                                    className="mt-0.5"
                                  />
                                  <span className="min-w-0">
                                    <span className="block truncate font-mono font-semibold">{field.name}</span>
                                    <span className="mt-1 flex flex-wrap gap-1">
                                      {(field.pii || []).map((label) => (
                                        <span key={label} className="rounded border border-amber-500/25 bg-amber-500/10 px-1 py-0.5 text-[10px] text-amber-600 dark:text-amber-300">
                                          {label}
                                        </span>
                                      ))}
                                    </span>
                                  </span>
                                </label>
                              );
                            })}
                          </div>
                        </div>
                      ))}
                    </div>
                    <div className="grid gap-3 border-t border-border p-4 sm:grid-cols-2">
                      <div>
                        <label className="mb-1.5 block text-xs font-medium text-muted-foreground">Additional mask patterns</label>
                        <Input value={excludeMasks} onChange={(event) => setExcludeMasks(event.target.value)} className="h-8 border-border bg-background font-mono text-xs" />
                      </div>
                      <div>
                        <label className="mb-1.5 block text-xs font-medium text-muted-foreground">Sample cap per object</label>
                        <Input value={sampleCap} onChange={(event) => setSampleCap(event.target.value)} className="h-8 border-border bg-background font-mono text-xs" />
                      </div>
                      <label className="flex items-start gap-2 text-xs text-muted-foreground sm:col-span-2">
                        <input
                          type="checkbox"
                          checked={piiAcknowledged}
                          onChange={(event) => setPiiAcknowledged(event.target.checked)}
                          className="mt-1"
                        />
                        Store only masked values for selected PII fields and keep the masking decision as graph provenance.
                      </label>
                    </div>
                  </div>
                </div>
              </section>
            )}

            {currentStep === "schedule" && (
              <section className="space-y-3">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                  <div>
                    <h2 className="text-base font-semibold text-foreground">Schedule and sync handoff</h2>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      Persist the cursor schedule, attach the Forge schema, then start the first sync.
                    </p>
                  </div>
                  <span className="inline-flex w-fit items-center gap-2 rounded-md border border-primary/20 bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
                    <Sparkles className="h-3.5 w-3.5" />
                    {forgeSummary}
                  </span>
                </div>

                {!finalizedConnection ? (
                  <>
                    <div className="grid gap-3 lg:grid-cols-4">
                      <div className="rounded-lg border border-border bg-card p-3">
                        <label className="mb-1.5 block text-xs font-medium text-muted-foreground">Cadence</label>
                        <select
                          value={schedule.cadence}
                          onChange={(event) => setSchedule((previous) => ({ ...previous, cadence: event.target.value }))}
                          className="h-8 w-full rounded-md border border-border bg-background px-3 text-sm outline-none focus:border-primary"
                        >
                          <option value="every_5_min">Every 5 minutes</option>
                          <option value="every_15_min">Every 15 minutes</option>
                          <option value="hourly">Hourly</option>
                          <option value="daily">Daily</option>
                        </select>
                      </div>
                      <div className="rounded-lg border border-border bg-card p-3">
                        <label className="mb-1.5 block text-xs font-medium text-muted-foreground">Cursor field</label>
                        <Input
                          value={schedule.cursor_field || ""}
                          onChange={(event) => setSchedule((previous) => ({ ...previous, cursor_field: event.target.value }))}
                          className="h-8 border-border bg-background font-mono text-xs"
                        />
                      </div>
                      <div className="rounded-lg border border-border bg-card p-3">
                        <label className="mb-1.5 block text-xs font-medium text-muted-foreground">Backfill</label>
                        <select
                          value={schedule.backfill_window}
                          onChange={(event) => setSchedule((previous) => ({ ...previous, backfill_window: event.target.value }))}
                          className="h-8 w-full rounded-md border border-border bg-background px-3 text-sm outline-none focus:border-primary"
                        >
                          <option value="all_history">All history</option>
                          <option value="last_365_days">Last 365 days</option>
                          <option value="last_90_days">Last 90 days</option>
                        </select>
                      </div>
                      <div className="rounded-lg border border-border bg-card p-3">
                        <label className="mb-1.5 block text-xs font-medium text-muted-foreground">Failures</label>
                        <select
                          value={schedule.dead_letter_behavior}
                          onChange={(event) => setSchedule((previous) => ({ ...previous, dead_letter_behavior: event.target.value }))}
                          className="h-8 w-full rounded-md border border-border bg-background px-3 text-sm outline-none focus:border-primary"
                        >
                          <option value="retain_and_alert">Retain and alert</option>
                          <option value="skip_and_report">Skip and report</option>
                          <option value="pause_sync">Pause sync</option>
                        </select>
                      </div>
                    </div>
                    <div className="rounded-lg border border-primary/25 bg-primary/10 p-3">
                      <div className="flex items-start gap-3">
                        <Sparkles className="mt-0.5 h-4 w-4 text-primary" />
                        <div>
                          <h3 className="text-sm font-semibold text-foreground">Forge handoff is ready</h3>
                          <p className="mt-1 text-xs text-muted-foreground">
                            The finalized source will keep this schema mapping, scope, schedule, cursor state, and drift baseline together for later reconfiguration.
                          </p>
                        </div>
                      </div>
                    </div>
                  </>
                ) : (
                  <div className="grid gap-3 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
                    <div className="rounded-lg border border-primary/25 bg-primary/10 p-4">
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div className="flex min-w-0 items-start gap-3">
                          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-primary/25 bg-background text-primary">
                            <Activity className="h-5 w-5" />
                          </div>
                          <div className="min-w-0">
                            <h3 className="text-base font-semibold text-foreground">
                              {finalizedJob?.status === "completed" ? "First sync completed" : "Sync started"}
                            </h3>
                            <p className="mt-1 truncate font-mono text-xs text-muted-foreground">
                              {finalizedConnection.name} / {finalizedConnection.short_name}
                            </p>
                          </div>
                        </div>
                        <span className={cn("inline-flex w-fit shrink-0 items-center rounded border px-2 py-0.5 text-[11px] font-medium", statusTone(finalizedState))}>
                          {formatLabel(finalizedState)}
                        </span>
                      </div>
                      <dl className="mt-4 grid gap-3 sm:grid-cols-3">
                        <div className="rounded-md border border-primary/15 bg-background/75 p-3">
                          <dt className="text-[10px] uppercase tracking-wider text-muted-foreground">Sync run</dt>
                          <dd className="mt-1 truncate font-mono text-xs text-foreground">{finalizedSyncCopy}</dd>
                        </div>
                        <div className="rounded-md border border-primary/15 bg-background/75 p-3">
                          <dt className="text-[10px] uppercase tracking-wider text-muted-foreground">Entities</dt>
                          <dd className="mt-1 font-mono text-xs text-foreground">{formatNumber(finalizedEntityTotal)}</dd>
                        </div>
                        <div className="rounded-md border border-primary/15 bg-background/75 p-3">
                          <dt className="text-[10px] uppercase tracking-wider text-muted-foreground">Cursor</dt>
                          <dd className="mt-1 truncate font-mono text-xs text-foreground">
                            {finalizedSchedule?.cursor_field || schedule.cursor_field || "-"}
                          </dd>
                        </div>
                      </dl>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
                      <div className="rounded-lg border border-border bg-card p-3">
                        <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
                          <Clock className="h-3.5 w-3.5 text-primary" />
                          Schedule
                        </div>
                        <p className="mt-2 font-mono text-xs text-muted-foreground">
                          {finalizedSchedule?.cron || formatCadence(schedule.cadence)}
                        </p>
                      </div>
                      <div className="rounded-lg border border-border bg-card p-3">
                        <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
                          <Sparkles className="h-3.5 w-3.5 text-primary" />
                          Forge schema
                        </div>
                        <p className="mt-2 font-mono text-xs text-muted-foreground">{forgeSummary}</p>
                      </div>
                      <div className="rounded-lg border border-border bg-card p-3">
                        <div className="flex items-center justify-between gap-2">
                          <span className="flex items-center gap-2 text-xs font-semibold text-foreground">
                            <ShieldCheck className="h-3.5 w-3.5 text-primary" />
                            Drift guard
                          </span>
                          <span className={cn("rounded border px-2 py-0.5 text-[10px] font-medium", statusTone(finalizedDriftStatus))}>
                            {formatLabel(finalizedDriftStatus)}
                          </span>
                        </div>
                        <p className="mt-2 font-mono text-xs text-muted-foreground">schema {formatLabel(finalizedSchemaStatus)}</p>
                      </div>
                    </div>
                  </div>
                )}
              </section>
            )}
          </div>

          <div className="flex flex-col gap-2 border-t border-border bg-card px-4 py-2 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <Button
              variant="ghost"
              className="h-8"
              onClick={() => {
                const previous = steps[Math.max(0, currentStepIndex - 1)];
                setCurrentStep(previous.id);
              }}
              disabled={currentStepIndex === 0 || isProcessing}
            >
              <ArrowLeft className="h-4 w-4" />
              Back
            </Button>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <span className="hidden text-xs text-muted-foreground sm:inline">
                {processingPhase
                  ? processingCopy[processingPhase].title
                  : currentStep === "schedule" && finalizedConnection
                    ? finalizedSyncCopy
                    : selectedSummary}
              </span>
              {!finalizedConnection && (
                <Button
                  variant="outline"
                  className="h-8 border-primary/30 text-primary hover:bg-primary/10"
                  onClick={() => saveDraft()}
                  disabled={isProcessing}
                >
                  {processingPhase === "draft" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  {processingPhase === "draft" ? "Saving draft" : "Save draft"}
                </Button>
              )}
              {currentStep === "auth" && (
                <Button className="h-8" onClick={runTest} disabled={isProcessing || !targetDatabase || !connectionName}>
                  {isTesting ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
                  {isTesting ? "Testing connection" : "Test connection"}
                </Button>
              )}
              {currentStep === "test" && (
                <Button className="h-8" onClick={runDiscovery} disabled={isProcessing}>
                  {isDiscovering ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                  {isDiscovering ? "Discovering schema" : "Discover schema"}
                </Button>
              )}
              {currentStep === "discover" && (
                <Button className="h-8" onClick={() => setCurrentStep("scope")} disabled={isProcessing || !discovery}>
                  Continue to scope
                  <ArrowRight className="h-4 w-4" />
                </Button>
              )}
              {currentStep === "scope" && (
                <Button className="h-8" onClick={saveScope} disabled={isProcessing || selectedObjects.size === 0}>
                  {isSavingScope ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
                  {isSavingScope ? "Saving scope" : "Save scope"}
                </Button>
              )}
              {currentStep === "schedule" && finalizedConnection && (
                <>
                  <Button
                    type="button"
                    variant="outline"
                    className="h-8 border-primary/30 text-primary hover:bg-primary/10"
                    onClick={() => void refreshFinalizedConnection(finalizedConnection.id)}
                    disabled={isProcessing}
                  >
                    {isRefreshingConnection ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                    {isRefreshingConnection ? "Refreshing" : "Refresh status"}
                  </Button>
                  <Button
                    type="button"
                    className="h-8"
                    onClick={() => navigate(`/databases/${finalizedConnection.readable_collection_id || targetDatabase}`)}
                    disabled={isProcessing}
                  >
                    Open database
                    <ArrowRight className="h-4 w-4" />
                  </Button>
                </>
              )}
              {currentStep === "schedule" && !finalizedConnection && (
                <Button type="button" className="h-8" onClick={saveSchedule} disabled={isProcessing}>
                  {processingPhase === "schedule" ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                  {processingPhase === "schedule"
                    ? "Starting sync"
                    : provider?.canFinalize
                      ? "Create connection & start sync"
                      : "Save setup"}
                </Button>
              )}
            </div>
          </div>
        </main>

        <aside className="hidden min-h-0 overflow-hidden border-l border-border bg-card xl:block">
          <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
            <div className="flex min-w-0 items-center gap-2 text-sm font-semibold text-foreground">
              <Server className="h-4 w-4 shrink-0 text-primary" />
              <span className="truncate">Setup state</span>
            </div>
            <span className={cn("shrink-0 rounded border px-2 py-0.5 text-[10px] font-medium", statusTone(processingPhase ? "running" : finalizedConnection ? finalizedState : draft?.status))}>
              {processingPhase ? "processing" : formatLabel(finalizedConnection ? finalizedState : draft?.status || "draft")}
            </span>
          </div>
          <div className="space-y-3 p-4">
            {processingPhase && (
              <PhaseProcessingCard phase={processingPhase} stats={processingStats} compact />
            )}

            <div className="rounded-lg border border-border bg-background">
              <div className="flex items-center justify-between border-b border-border px-3 py-2">
                <h3 className="text-xs font-semibold text-foreground">Connection fingerprint</h3>
                <span className={cn("rounded border px-2 py-0.5 text-[10px] font-medium", statusTone(testResult?.status))}>
                  {testResult ? "Verified" : "Draft"}
                </span>
              </div>
              <dl className="grid grid-cols-[86px_1fr] gap-y-1.5 px-3 py-2.5 text-[11px]">
                {previewIdentityEntries.map(([key, value]) => (
                  <div key={key} className="contents">
                    <dt className="text-muted-foreground">{key}</dt>
                    <dd className="truncate font-mono text-foreground">{formatPreviewValue(value)}</dd>
                  </div>
                ))}
                {previewIdentityEntries.length === 0 && (
                  <div className="col-span-2 text-muted-foreground">Connection fields appear here as the draft is filled.</div>
                )}
              </dl>
            </div>

            <div className="rounded-lg border border-border bg-background">
              <div className="border-b border-border px-3 py-2">
                <h3 className="text-xs font-semibold text-foreground">Context database</h3>
              </div>
              <div className="flex items-center gap-3 px-3 py-2.5">
                <div className="flex h-8 w-8 items-center justify-center rounded-md border border-primary/25 bg-primary/10 text-primary">
                  <Database className="h-4 w-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate font-mono text-xs text-foreground">{targetDatabase || "choose database"}</div>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">single-source context boundary</div>
                </div>
              </div>
            </div>

            <div className="rounded-lg border border-primary/25 bg-primary/10">
              <div className="flex items-center justify-between border-b border-primary/20 px-3 py-2">
                <h3 className="flex items-center gap-1.5 text-xs font-semibold text-primary">
                  <Sparkles className="h-3.5 w-3.5" />
                  Forge schema
                </h3>
                <span className="rounded border border-primary/25 bg-background/60 px-2 py-0.5 text-[10px] font-medium text-primary">
                  {finalizedConnection ? "stored" : forgePreview?.status?.replace(/_/g, " ") || "pending"}
                </span>
              </div>
              <div className="space-y-2 px-3 py-2.5 text-[11px] text-muted-foreground">
                <div className="flex items-center justify-between gap-3">
                  <span>Schema preview</span>
                  <span className="font-mono text-foreground">{forgeSummary}</span>
                </div>
                <p>Saved with scope and cursor state so the graph can be reviewed after sync.</p>
              </div>
            </div>

            <div className="rounded-lg border border-border bg-background">
              <div className="border-b border-border px-3 py-2">
                <h3 className="text-xs font-semibold text-foreground">{finalizedConnection ? "Sync handoff" : "Run forecast"}</h3>
              </div>
              {finalizedConnection ? (
                <div className="grid grid-cols-2 gap-3 px-3 py-2.5 text-[11px]">
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-muted-foreground">state</div>
                    <div className="mt-1 font-mono text-foreground">{formatLabel(finalizedState)}</div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-muted-foreground">runs</div>
                    <div className="mt-1 font-mono text-foreground">{finalizedConnection.sync?.total_runs ?? 0}</div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-muted-foreground">entities</div>
                    <div className="mt-1 font-mono text-foreground">{formatNumber(finalizedEntityTotal)}</div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-muted-foreground">drift</div>
                    <div className="mt-1 font-mono text-foreground">{formatLabel(finalizedDriftStatus)}</div>
                  </div>
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-3 px-3 py-2.5 text-[11px]">
                  {syncEstimateEntries.map(([key, value]) => (
                    <div key={key} className={wideSyncEstimateKeys.has(key) ? "col-span-2" : ""}>
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{key.replace(/_/g, " ")}</div>
                      <div className="mt-1 font-mono text-foreground">{formatPreviewValue(value)}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {collections.length === 0 && !targetDatabase && (
              <div className="rounded-lg border border-amber-500/25 bg-amber-500/10 p-3 text-xs text-amber-500">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="mt-0.5 h-4 w-4" />
                  <span>Create a context database before finalizing this connector setup.</span>
                </div>
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
};

export default SourceSetupPage;
