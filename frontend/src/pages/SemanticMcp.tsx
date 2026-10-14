import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Clipboard,
  Code2,
  Copy,
  Database,
  ExternalLink,
  FileJson,
  Globe2,
  KeyRound,
  Loader2,
  Network,
  Plug,
  RefreshCw,
  Route,
  Server,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiClient, API_CONFIG } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAPIKeysStore } from "@/lib/stores/apiKeys";
import { Collection, SourceConnection, useCollectionsStore } from "@/lib/stores/collections";
import { useOrganizationStore } from "@/lib/stores/organizations";

type HealthState = "checking" | "online" | "offline";
type SnippetTab = "rest" | "node" | "mcp";

const formatCount = (value?: number | null) => {
  const numberValue = Number(value || 0);
  if (numberValue >= 1000) return `${(numberValue / 1000).toFixed(numberValue >= 10000 ? 0 : 1)}K`;
  return String(numberValue);
};

const formatDate = (value?: string | null) => {
  if (!value) return "Not used yet";
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return "Not used yet";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(timestamp));
};

const getConnectionEntityCount = (connection?: SourceConnection | null) =>
  Number(connection?.entity_count ?? connection?.entities?.total_entities ?? 0) || 0;

const getConnectionStatus = (connection?: SourceConnection | null) =>
  String(connection?.last_job_status || connection?.sync?.last_job?.status || connection?.status || "idle").toLowerCase();

const maskKey = (key?: string | null) => {
  if (!key) return "No key selected";
  if (key.length <= 12) return key;
  return `${key.slice(0, 6)}...${key.slice(-4)}`;
};

const getDatabaseLabel = (database?: Collection | null) => database?.name || database?.readable_id || "Select database";

const endpointRows = (databaseId: string, connectionId?: string) => [
  {
    method: "POST",
    path: `/collections/${databaseId}/graph-search`,
    label: "Context query",
    description: "Search entities, relationships, lineage, temporal facts, and decision trace in one request.",
  },
  {
    method: "GET",
    path: `/context-intelligence/databases/${databaseId}`,
    label: "Context state",
    description: "Read graph health, drift status, Forge mapping, lineage counts, and temporal coverage.",
  },
  {
    method: "POST",
    path: `/context-intelligence/databases/${databaseId}/drift/detect`,
    label: "Drift scan",
    description: "Compare source config, schema fingerprints, cursor checkpoints, and active Forge mapping.",
  },
  {
    method: "POST",
    path: connectionId ? `/source-connections/${connectionId}/run` : "/source-connections/{connection_id}/run",
    label: "Run sync",
    description: "Start the connector sync that refreshes ContextD entities, links, and guard signals.",
  },
];

const buildRestSnippet = (baseUrl: string, databaseId: string, apiKey: string) => `curl -X POST "${baseUrl}/collections/${databaseId}/graph-search" \\
  -H "Content-Type: application/json" \\
  -H "x-api-key: ${apiKey}" \\
  -d '{
    "query": "@search @graph show the strongest relationships",
    "depth": 2,
    "limit": 50,
    "include_edges": true
  }'`;

const buildNodeSnippet = (baseUrl: string, databaseId: string, apiKey: string) => `const response = await fetch("${baseUrl}/collections/${databaseId}/graph-search", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "x-api-key": "${apiKey}"
  },
  body: JSON.stringify({
    query: "@search @graph show the strongest relationships",
    depth: 2,
    limit: 50,
    include_edges: true
  })
});

const context = await response.json();`;

const buildMcpSnippet = (baseUrl: string, databaseId: string, apiKey: string) => `{
  "mcpServers": {
    "contextd": {
      "command": "npx",
      "args": ["-y", "contextd-mcp-search"],
      "env": {
        "CONTEXTD_API_KEY": "${apiKey}",
        "CONTEXTD_BASE_URL": "${baseUrl}",
        "CONTEXTD_DATABASE": "${databaseId}"
      }
    }
  }
}`;

const Panel = ({
  title,
  description,
  icon,
  action,
  children,
  className,
}: {
  title: string;
  description?: string;
  icon: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) => (
  <section className={cn("rounded-lg border border-border bg-card", className)}>
    <div className="flex items-start justify-between gap-4 border-b border-border px-4 py-3">
      <div className="flex min-w-0 items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-primary/15 bg-primary/5 text-primary">
          {icon}
        </div>
        <div className="min-w-0">
          <h2 className="text-base font-semibold leading-tight text-foreground">{title}</h2>
          {description && <p className="mt-1 text-sm leading-snug text-muted-foreground">{description}</p>}
        </div>
      </div>
      {action}
    </div>
    {children}
  </section>
);

const StatPill = ({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "good" | "warn";
}) => (
  <div
    className={cn(
      "rounded-lg border bg-card px-3 py-2",
      tone === "good" && "border-emerald-500/20 bg-emerald-500/5",
      tone === "warn" && "border-amber-500/20 bg-amber-500/5"
    )}
  >
    <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">{label}</div>
    <div className="mt-1 font-mono text-lg font-semibold text-foreground">{value}</div>
  </div>
);

const CodeBlock = ({
  code,
  onCopy,
}: {
  code: string;
  onCopy: () => void;
}) => (
  <div className="overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950 text-zinc-100 shadow-sm">
    <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2">
      <div className="flex items-center gap-2 text-xs text-zinc-300">
        <TerminalSquare className="h-3.5 w-3.5 text-primary" />
        Copy into your client
      </div>
      <Button type="button" size="sm" variant="ghost" className="h-7 gap-1.5 text-zinc-100 hover:bg-white/10 hover:text-white" onClick={onCopy}>
        <Copy className="h-3.5 w-3.5" />
        Copy
      </Button>
    </div>
    <pre className="max-h-[320px] overflow-auto p-4 font-mono text-xs leading-relaxed text-zinc-100">
      <code className="block whitespace-pre text-zinc-100">{code}</code>
    </pre>
  </div>
);

const ConnectionRow = ({ connection }: { connection: SourceConnection }) => {
  const status = getConnectionStatus(connection);
  const isReady = status === "completed" || status === "active" || status === "ready";
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3 last:border-b-0">
      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-2">
          <span className={cn("h-2 w-2 shrink-0 rounded-full", isReady ? "bg-emerald-500" : "bg-muted-foreground")} />
          <span className="truncate text-sm font-semibold text-foreground">{connection.name || connection.short_name}</span>
        </div>
        <div className="mt-0.5 font-mono text-xs text-muted-foreground">
          {connection.short_name || "connector"} · {formatCount(getConnectionEntityCount(connection))} entities
        </div>
      </div>
      <span
        className={cn(
          "shrink-0 rounded-md border px-2 py-1 text-xs capitalize",
          isReady
            ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
            : "border-border bg-muted text-muted-foreground"
        )}
      >
        {status}
      </span>
    </div>
  );
};

const SemanticMcp = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [health, setHealth] = useState<HealthState>("checking");
  const [snippetTab, setSnippetTab] = useState<SnippetTab>("rest");
  const [newKey, setNewKey] = useState<string | null>(null);
  const [isCreatingKey, setIsCreatingKey] = useState(false);

  const { currentOrganization } = useOrganizationStore();
  const collections = useCollectionsStore((state) => state.collections);
  const collectionsLoading = useCollectionsStore((state) => state.isLoading);
  const fetchCollections = useCollectionsStore((state) => state.fetchCollections);
  const sourceConnections = useCollectionsStore((state) => state.sourceConnections);
  const sourceConnectionsLoading = useCollectionsStore((state) => state.sourceConnectionsLoading);
  const fetchSourceConnections = useCollectionsStore((state) => state.fetchSourceConnections);

  const apiKeys = useAPIKeysStore((state) => state.apiKeys);
  const keysLoading = useAPIKeysStore((state) => state.isLoading);
  const fetchAPIKeys = useAPIKeysStore((state) => state.fetchAPIKeys);
  const createAPIKey = useAPIKeysStore((state) => state.createAPIKey);

  const selectedDatabaseId = searchParams.get("database") || collections[0]?.readable_id || "";
  const selectedDatabase = collections.find((collection) => collection.readable_id === selectedDatabaseId) || null;
  const selectedConnections = selectedDatabaseId ? sourceConnections[selectedDatabaseId] || [] : [];
  const primaryConnection = selectedConnections[0];
  const connectionLoading = selectedDatabaseId ? sourceConnectionsLoading[selectedDatabaseId] : false;
  const totalEntities = selectedConnections.reduce((sum, connection) => sum + getConnectionEntityCount(connection), 0);
  const storedApiKey = apiKeys[0]?.decrypted_key || "";
  const activeApiKey = newKey || storedApiKey;
  const snippetKey = newKey || "YOUR_CONTEXTD_API_KEY";
  const snippetDatabaseId = selectedDatabaseId || "DATABASE_READABLE_ID";
  const baseUrl = API_CONFIG.baseURL.replace(/\/$/, "");

  useEffect(() => {
    void fetchCollections();
    void fetchAPIKeys();
  }, [fetchAPIKeys, fetchCollections]);

  useEffect(() => {
    let cancelled = false;
    setHealth("checking");
    apiClient
      .get("/health")
      .then((response) => {
        if (!cancelled) setHealth(response.ok ? "online" : "offline");
      })
      .catch(() => {
        if (!cancelled) setHealth("offline");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!collections.length) return;
    if (selectedDatabaseId) return;
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set("database", collections[0].readable_id);
    setSearchParams(nextParams, { replace: true });
  }, [collections, searchParams, selectedDatabaseId, setSearchParams]);

  useEffect(() => {
    if (!selectedDatabaseId) return;
    void fetchSourceConnections(selectedDatabaseId);
  }, [fetchSourceConnections, selectedDatabaseId]);

  const snippets = useMemo(
    () => ({
      rest: buildRestSnippet(baseUrl, snippetDatabaseId, snippetKey),
      node: buildNodeSnippet(baseUrl, snippetDatabaseId, snippetKey),
      mcp: buildMcpSnippet(baseUrl, snippetDatabaseId, snippetKey),
    }),
    [baseUrl, snippetDatabaseId, snippetKey]
  );

  const activeSnippet = snippets[snippetTab];
  const activeSnippetLabel =
    snippetTab === "rest" ? "REST cURL" : snippetTab === "node" ? "Node fetch" : "MCP client";

  const handleDatabaseChange = (databaseId: string) => {
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set("database", databaseId);
    setSearchParams(nextParams);
  };

  const copyText = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success(`${label} copied`);
    } catch {
      toast.error("Copy failed");
    }
  };

  const handleCreateKey = async () => {
    setIsCreatingKey(true);
    try {
      const key = await createAPIKey(90);
      setNewKey(key.decrypted_key);
      await copyText(key.decrypted_key, "New API key");
      toast.success("API key created for 90 days");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to create API key");
    } finally {
      setIsCreatingKey(false);
    }
  };

  const endpoints = endpointRows(snippetDatabaseId, primaryConnection?.id);

  return (
    <div className="min-h-full bg-background">
      <div className="mx-auto flex max-w-[1500px] flex-col gap-4 px-4 py-5 md:px-6">
        <section className="rounded-lg border border-border bg-card px-4 py-4 shadow-sm md:px-5">
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center gap-2 rounded-md border border-primary/20 bg-primary/5 px-2.5 py-1 text-sm font-medium text-primary">
                  <Route className="h-4 w-4" />
                  Integration Workbench
                </span>
                <span
                  className={cn(
                    "inline-flex items-center gap-2 rounded-md border px-2.5 py-1 text-sm font-medium",
                    health === "online" && "border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
                    health === "checking" && "border-border bg-muted text-muted-foreground",
                    health === "offline" && "border-destructive/20 bg-destructive/10 text-destructive"
                  )}
                >
                  {health === "checking" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Activity className="h-3.5 w-3.5" />}
                  API {health}
                </span>
              </div>
              <h1 className="mt-3 text-3xl font-semibold tracking-normal text-foreground">API & MCP Access</h1>
              <p className="mt-2 max-w-3xl text-base leading-relaxed text-muted-foreground">
                Connect agents, internal tools, and scripts to the same ContextD graph, temporal, lineage, drift, and decision context used by the app.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:w-[560px]">
              <StatPill label="Databases" value={formatCount(collections.length)} />
              <StatPill label="Keys" value={formatCount(apiKeys.length)} tone={apiKeys.length ? "good" : "warn"} />
              <StatPill label="Sources" value={formatCount(selectedConnections.length)} tone={selectedConnections.length ? "good" : "warn"} />
              <StatPill label="Entities" value={formatCount(totalEntities)} />
            </div>
          </div>
        </section>

        <div className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
          <main className="space-y-4">
            <Panel
              title="Access Target"
              description="Choose the context database that API and MCP clients should query by default."
              icon={<Database className="h-4 w-4" />}
              action={
                <Button asChild variant="outline" size="sm" className="h-8 gap-2">
                  <Link to={selectedDatabaseId ? `/query?database=${selectedDatabaseId}` : "/query"}>
                    Open query
                    <ArrowRight className="h-3.5 w-3.5" />
                  </Link>
                </Button>
              }
            >
              <div className="grid gap-3 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.7fr)]">
                <div className="rounded-lg border border-border bg-background/50 p-3">
                  <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Default database</div>
                  <div className="mt-2">
                    <Select value={selectedDatabaseId} onValueChange={handleDatabaseChange}>
                      <SelectTrigger className="h-10 w-full rounded-md">
                        <SelectValue placeholder={collectionsLoading ? "Loading databases..." : "Select database"} />
                      </SelectTrigger>
                      <SelectContent>
                        {collections.map((collection) => (
                          <SelectItem key={collection.id} value={collection.readable_id}>
                            {collection.name || collection.readable_id}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="mt-3 grid gap-2 sm:grid-cols-3">
                    <div className="rounded-md border border-border bg-card px-3 py-2">
                      <div className="text-xs text-muted-foreground">Database ID</div>
                      <div className="mt-1 truncate font-mono text-sm">{selectedDatabaseId || "not selected"}</div>
                    </div>
                    <div className="rounded-md border border-border bg-card px-3 py-2">
                      <div className="text-xs text-muted-foreground">Organization</div>
                      <div className="mt-1 truncate text-sm font-medium">{currentOrganization?.name || "Current organization"}</div>
                    </div>
                    <div className="rounded-md border border-border bg-card px-3 py-2">
                      <div className="text-xs text-muted-foreground">Base URL</div>
                      <div className="mt-1 truncate font-mono text-sm">{baseUrl}</div>
                    </div>
                  </div>
                </div>

                <div className="rounded-lg border border-border bg-background/50">
                  <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
                    <div>
                      <div className="text-sm font-semibold text-foreground">Live source</div>
                      <div className="text-xs text-muted-foreground">One connector feeds this context boundary.</div>
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() => selectedDatabaseId && fetchSourceConnections(selectedDatabaseId, true)}
                      disabled={!selectedDatabaseId || connectionLoading}
                    >
                      {connectionLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                    </Button>
                  </div>
                  {connectionLoading && selectedConnections.length === 0 ? (
                    <div className="flex items-center gap-2 px-4 py-5 text-sm text-muted-foreground">
                      <Loader2 className="h-4 w-4 animate-spin text-primary" />
                      Loading source status
                    </div>
                  ) : selectedConnections.length ? (
                    selectedConnections.slice(0, 3).map((connection) => (
                      <ConnectionRow key={connection.id} connection={connection} />
                    ))
                  ) : (
                    <div className="px-4 py-5 text-sm text-muted-foreground">
                      No source is connected yet. Create the database connection first, then return here for API access.
                    </div>
                  )}
                </div>
              </div>
            </Panel>

            <Panel
              title="REST API Surface"
              description="Use these endpoints for apps, automations, and backend services."
              icon={<Globe2 className="h-4 w-4" />}
              action={
                <Button type="button" variant="outline" size="sm" className="h-8 gap-2" onClick={() => copyText(baseUrl, "Base URL")}>
                  <Copy className="h-3.5 w-3.5" />
                  Copy base URL
                </Button>
              }
            >
              <div className="divide-y divide-border">
                {endpoints.map((endpoint) => (
                  <div key={`${endpoint.method}-${endpoint.path}`} className="grid gap-3 px-4 py-3 lg:grid-cols-[160px_minmax(0,1fr)_auto] lg:items-center">
                    <div className="flex items-center gap-2">
                      <span className="rounded-md border border-primary/20 bg-primary/5 px-2 py-1 font-mono text-xs font-semibold text-primary">
                        {endpoint.method}
                      </span>
                      <span className="text-sm font-semibold text-foreground">{endpoint.label}</span>
                    </div>
                    <div className="min-w-0">
                      <div className="truncate rounded-md border border-border bg-muted/40 px-2 py-1 font-mono text-xs text-foreground">
                        {endpoint.path}
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">{endpoint.description}</p>
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-8 justify-start gap-2"
                      onClick={() => copyText(`${baseUrl}${endpoint.path}`, endpoint.label)}
                    >
                      <Clipboard className="h-3.5 w-3.5" />
                      Copy
                    </Button>
                  </div>
                ))}
              </div>
            </Panel>

            <Panel
              title="Client Starter"
              description={`${activeSnippetLabel} configured for ${getDatabaseLabel(selectedDatabase)}.`}
              icon={snippetTab === "mcp" ? <Sparkles className="h-4 w-4" /> : <Code2 className="h-4 w-4" />}
              action={
                <div className="flex rounded-md border border-border bg-muted p-0.5">
                  {([
                    ["rest", "REST"],
                    ["node", "Node"],
                    ["mcp", "MCP"],
                  ] as const).map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setSnippetTab(value)}
                      className={cn(
                        "rounded px-2.5 py-1 text-xs font-medium transition-colors",
                        snippetTab === value ? "bg-card text-primary shadow-sm" : "text-muted-foreground hover:text-foreground"
                      )}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              }
            >
              <div className="p-4">
                <CodeBlock code={activeSnippet} onCopy={() => copyText(activeSnippet, activeSnippetLabel)} />
              </div>
            </Panel>
          </main>

          <aside className="space-y-4">
            <Panel
              title="API Key"
              description="Keys authenticate REST calls and MCP clients."
              icon={<KeyRound className="h-4 w-4" />}
              action={
                <Button
                  type="button"
                  size="sm"
                  className="h-8 gap-2 bg-primary text-primary-foreground hover:bg-primary/90"
                  onClick={handleCreateKey}
                  disabled={isCreatingKey || keysLoading}
                >
                  {isCreatingKey ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <KeyRound className="h-3.5 w-3.5" />}
                  New key
                </Button>
              }
            >
              <div className="space-y-3 p-4">
                <div className="rounded-lg border border-border bg-background/50 p-3">
                  <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Active key</div>
                  <div className="mt-2 break-all font-mono text-sm text-foreground">{maskKey(activeApiKey)}</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {newKey ? "Created this session and copied to clipboard." : apiKeys[0] ? `Last used ${formatDate(apiKeys[0].last_used_date)}` : "Create a key before using external clients."}
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-9 gap-2"
                    onClick={() => activeApiKey && copyText(activeApiKey, "API key")}
                    disabled={!activeApiKey}
                  >
                    <Copy className="h-3.5 w-3.5" />
                    Copy key
                  </Button>
                  <Button asChild variant="outline" size="sm" className="h-9 gap-2">
                    <Link to="/api-keys">
                      Manage
                      <ExternalLink className="h-3.5 w-3.5" />
                    </Link>
                  </Button>
                </div>
              </div>
            </Panel>

            <Panel
              title="Readiness"
              description="What external clients need before they can query real context."
              icon={<ShieldCheck className="h-4 w-4" />}
            >
              <div className="space-y-3 p-4">
                {[
                  {
                    label: "API is reachable",
                    complete: health === "online",
                    detail: health === "online" ? "Health check passed" : "Waiting for backend health",
                  },
                  {
                    label: "Database selected",
                    complete: Boolean(selectedDatabaseId),
                    detail: selectedDatabaseId || "Choose a context database",
                  },
                  {
                    label: "Source indexed",
                    complete: selectedConnections.length > 0 && totalEntities > 0,
                    detail: `${formatCount(totalEntities)} entities available`,
                  },
                  {
                    label: "Access key ready",
                    complete: Boolean(activeApiKey),
                    detail: apiKeys.length ? `${apiKeys.length} key${apiKeys.length === 1 ? "" : "s"} in this organization` : "No key yet",
                  },
                ].map((item) => (
                  <div key={item.label} className="flex gap-3">
                    <div
                      className={cn(
                        "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border",
                        item.complete
                          ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-600"
                          : "border-border bg-muted text-muted-foreground"
                      )}
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-foreground">{item.label}</div>
                      <div className="truncate text-xs text-muted-foreground">{item.detail}</div>
                    </div>
                  </div>
                ))}
              </div>
            </Panel>

            <Panel
              title="Context Tools"
              description="Fast jumps into the same database context."
              icon={<Network className="h-4 w-4" />}
            >
              <div className="grid gap-2 p-4">
                <Button asChild variant="outline" className="h-10 justify-between">
                  <Link to={selectedDatabaseId ? `/graph?database=${selectedDatabaseId}` : "/graph"}>
                    <span className="inline-flex items-center gap-2">
                      <Network className="h-4 w-4 text-primary" />
                      Graph Explorer
                    </span>
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                </Button>
                <Button asChild variant="outline" className="h-10 justify-between">
                  <Link to={selectedDatabaseId ? `/query?database=${selectedDatabaseId}` : "/query"}>
                    <span className="inline-flex items-center gap-2">
                      <TerminalSquare className="h-4 w-4 text-primary" />
                      Query Console
                    </span>
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                </Button>
                <Button asChild variant="outline" className="h-10 justify-between">
                  <Link to={selectedDatabaseId ? `/databases/${selectedDatabaseId}/sources` : "/sources"}>
                    <span className="inline-flex items-center gap-2">
                      <Plug className="h-4 w-4 text-primary" />
                      Connector Setup
                    </span>
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                </Button>
              </div>
            </Panel>

            <Panel
              title="Contract"
              description="The same API powers the app, agents, and external clients."
              icon={<FileJson className="h-4 w-4" />}
            >
              <div className="space-y-2 p-4 text-sm text-muted-foreground">
                <div className="rounded-md border border-border bg-background/50 px-3 py-2">
                  <span className="font-medium text-foreground">Auth:</span> bearer token or x-api-key
                </div>
                <div className="rounded-md border border-border bg-background/50 px-3 py-2">
                  <span className="font-medium text-foreground">Scope:</span> one selected ContextD database
                </div>
                <div className="rounded-md border border-border bg-background/50 px-3 py-2">
                  <span className="font-medium text-foreground">Response:</span> answer, packet, facts, lineage, decisions
                </div>
              </div>
            </Panel>
          </aside>
        </div>
      </div>
    </div>
  );
};

export default SemanticMcp;
