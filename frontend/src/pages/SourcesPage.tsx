import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  Database,
  ExternalLink,
  KeyRound,
  Loader2,
  Plug,
  Search,
  ShieldCheck,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useTheme } from "@/lib/theme-provider";
import { useSourcesStore } from "@/lib/stores";
import { useUsageStore } from "@/lib/stores/usage";
import { useCollectionCreationStore } from "@/stores/collectionCreationStore";
import { cn } from "@/lib/utils";
import { getAppIconUrl } from "@/lib/utils/icons";

interface Source {
  id: string;
  name: string;
  description?: string | null;
  short_name: string;
  labels?: string[];
  auth_type?: string;
  auth_methods?: string[];
}

type CatalogFilter =
  | "all"
  | "databases"
  | "communication"
  | "documents"
  | "crm"
  | "project"
  | "developer";

type ConnectorMetadata = {
  category:
    | "Databases"
    | "Communication"
    | "Documents"
    | "CRM"
    | "Project management"
    | "Support"
    | "Developer tools"
    | "Custom";
  authLabel: string;
  modeLabel: string;
  description: string;
};

const catalogFilters: Array<{ id: CatalogFilter; label: string }> = [
  { id: "all", label: "All" },
  { id: "databases", label: "Databases" },
  { id: "communication", label: "Communication" },
  { id: "documents", label: "Documents" },
  { id: "crm", label: "CRM" },
  { id: "project", label: "Projects" },
  { id: "developer", label: "Developer" },
];

const databaseTokens = [
  "postgres",
  "postgresql",
  "mysql",
  "sqlite",
  "snowflake",
  "clickhouse",
  "oracle",
  "mongodb",
  "sql_server",
  "mssql",
  "milvus",
  "pinecone",
  "weaviate",
];
const communicationTokens = ["gmail", "outlook", "mail", "slack", "teams", "calendar"];
const documentTokens = [
  "docs",
  "drive",
  "sheet",
  "slides",
  "excel",
  "word",
  "notion",
  "confluence",
  "box",
  "dropbox",
  "onedrive",
  "sharepoint",
  "onenote",
];
const crmTokens = ["salesforce", "hubspot", "mailchimp", "crm"];
const projectTokens = ["asana", "jira", "linear", "monday", "clickup", "attio", "airtable"];
const developerTokens = ["github", "gitlab", "bitbucket"];
const structuredSetupTokens = ["postgres", "postgresql", "clickhouse", "snowflake"];
const enabledConnectorTokens = ["postgres", "postgresql", "clickhouse", "snowflake", "gmail"];

const virtualStructuredSources: Source[] = [
  {
    id: "virtual-snowflake",
    name: "Snowflake",
    short_name: "snowflake",
    description: "Connect warehouse tables, schemas, and cursor fields through the guided setup flow.",
    labels: ["Database", "Warehouse"],
    auth_type: "key_pair",
    auth_methods: ["key_pair"],
  },
];

const sourceKey = (source: Source) => `${source.name} ${source.short_name}`.toLowerCase();

const sourceMatches = (source: Source, tokens: string[]) =>
  tokens.some((token) => sourceKey(source).includes(token));

const isConnectorEnabled = (source: Source) => sourceMatches(source, enabledConnectorTokens);

const getConnectorCategory = (source: Source): ConnectorMetadata["category"] => {
  if (sourceMatches(source, databaseTokens)) return "Databases";
  if (sourceMatches(source, developerTokens)) return "Developer tools";
  if (sourceMatches(source, crmTokens)) return "CRM";
  if (sourceMatches(source, projectTokens)) return "Project management";
  if (sourceMatches(source, communicationTokens)) return "Communication";
  if (sourceMatches(source, documentTokens)) return "Documents";
  if (source.labels?.some((label) => label.toLowerCase().includes("support"))) return "Support";
  return "Custom";
};

const getAuthLabel = (source: Source) => {
  const key = sourceKey(source);
  if (key.includes("snowflake")) return "Key-pair";
  if (key.includes("postgres") || key.includes("mysql") || key.includes("oracle") || key.includes("sql")) {
    return "Database auth";
  }
  if (key.includes("github") || key.includes("gitlab") || key.includes("bitbucket")) return "OAuth / PAT";
  if (source.auth_type?.includes("oauth")) return "OAuth";
  if (source.auth_type === "api_key") return "API key";
  if (source.auth_type === "basic") return "Basic auth";
  if (source.auth_type) return source.auth_type.replace(/_/g, " ");
  return sourceMatches(source, communicationTokens.concat(crmTokens, projectTokens, documentTokens, developerTokens))
    ? "OAuth"
    : "API key";
};

const buildConnectorMetadata = (source: Source): ConnectorMetadata => {
  const category = getConnectorCategory(source);
  const key = sourceKey(source);
  const isDatabase = category === "Databases";
  const modeLabel = isDatabase || key.includes("airtable") || key.includes("notion")
    ? "Schema discovery"
    : category === "Communication"
      ? "Messages"
      : category === "Documents"
        ? "Files"
        : "Objects";

  return {
    category,
    authLabel: getAuthLabel(source),
    modeLabel,
    description:
      source.description ||
      (isDatabase
        ? "Connect structured records, schema, and cursor fields."
        : category === "Communication"
          ? "Sync messages, participants, and activity."
          : category === "Documents"
            ? "Sync files, folders, and extracted metadata."
            : category === "CRM"
              ? "Sync accounts, contacts, tickets, and ownership."
              : category === "Developer tools"
                ? "Sync repositories, issues, pull requests, and commits."
                : "Sync objects, activity, and provenance."),
  };
};

const filterSource = (source: Source, metadata: ConnectorMetadata, filter: CatalogFilter) => {
  switch (filter) {
    case "all":
      return true;
    case "databases":
      return metadata.category === "Databases";
    case "communication":
      return metadata.category === "Communication";
    case "documents":
      return metadata.category === "Documents";
    case "crm":
      return metadata.category === "CRM";
    case "project":
      return metadata.category === "Project management";
    case "developer":
      return metadata.category === "Developer tools";
    default:
      return true;
  }
};

const requestConnector = () => {
  window.open(
    "https://github.com/contextd/contextd/issues/new?labels=connector-request&template=connector_request.md&title=[Connector%20Request]%20",
    "_blank"
  );
};

const SourcesPage = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { resolvedTheme } = useTheme();
  const { sources, isLoading: isLoadingSources, fetchSources } = useSourcesStore();
  const actionChecks = useUsageStore((state) => state.actionChecks);
  const isCheckingUsage = useUsageStore((state) => state.isLoading);
  const sourceConnectionsAllowed = actionChecks.source_connections?.allowed ?? true;
  const entitiesAllowed = actionChecks.entities?.allowed ?? true;

  const [connectorSearchQuery, setConnectorSearchQuery] = useState("");
  const [connectorFilter, setConnectorFilter] = useState<CatalogFilter>("all");

  useEffect(() => {
    fetchSources();
  }, [fetchSources]);

  const catalogSources = useMemo(() => {
    const hasSnowflake = sources.some((source) => sourceKey(source).includes("snowflake"));
    return hasSnowflake ? sources : [...sources, ...virtualStructuredSources];
  }, [sources]);

  const sourceMetadata = useMemo(
    () => new Map(catalogSources.map((source) => [source.id, buildConnectorMetadata(source)])),
    [catalogSources]
  );

  const visibleSources = useMemo(() => {
    const query = connectorSearchQuery.trim().toLowerCase();

    return [...catalogSources]
      .filter((source) => {
        const metadata = sourceMetadata.get(source.id) || buildConnectorMetadata(source);
        const searchable = [
          source.name,
          source.short_name,
          source.description || "",
          metadata.category,
          metadata.authLabel,
          metadata.modeLabel,
        ].join(" ").toLowerCase();

        return (!query || searchable.includes(query)) && filterSource(source, metadata, connectorFilter);
      })
      .sort((a, b) => {
        const aEnabled = isConnectorEnabled(a);
        const bEnabled = isConnectorEnabled(b);
        if (aEnabled !== bEnabled) return aEnabled ? -1 : 1;
        const aCategory = sourceMetadata.get(a.id)?.category || "";
        const bCategory = sourceMetadata.get(b.id)?.category || "";
        if (aCategory !== bCategory) return aCategory.localeCompare(bCategory);
        return a.name.localeCompare(b.name);
      });
  }, [catalogSources, connectorFilter, connectorSearchQuery, sourceMetadata]);

  const handleSourceClick = (source: Source) => {
    if (!isConnectorEnabled(source) || !sourceConnectionsAllowed || !entitiesAllowed || isCheckingUsage) return;

    const normalizedShortName = source.short_name.toLowerCase().replace("-", "_");
    const targetDatabase = searchParams.get("database");
    const setupProvider = normalizedShortName === "postgres"
      ? "postgresql"
      : normalizedShortName.includes("snowflake")
        ? "snowflake"
        : normalizedShortName;
    const setupUrl = `/sources/${setupProvider}/setup${targetDatabase ? `?database=${encodeURIComponent(targetDatabase)}` : ""}`;

    if (structuredSetupTokens.includes(setupProvider) || targetDatabase) {
      navigate(setupUrl);
      return;
    }

    const store = useCollectionCreationStore.getState();
    let authMode: "oauth2" | "direct_auth" | undefined;
    if (source.auth_type?.startsWith("oauth2")) {
      authMode = "oauth2";
    } else if (source.auth_type === "api_key" || source.auth_type === "basic") {
      authMode = "direct_auth";
    }
    store.openForCreateWithSource(source.short_name, source.name, authMode);
  };

  return (
    <div className="min-h-full bg-background px-4 py-5 md:px-6">
      <div className="mx-auto max-w-[1480px]">
        <header className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <div className="mb-2 inline-flex items-center gap-2 rounded-md border border-border bg-card px-2.5 py-1 text-xs font-medium text-muted-foreground">
              <Plug className="h-3.5 w-3.5 text-primary" />
              Connectors
            </div>
            <h1 className="text-[28px] font-semibold tracking-normal text-foreground">Connector catalog</h1>
            <p className="mt-1.5 max-w-2xl text-sm text-muted-foreground">
              Choose the one system that will feed a ContextD database. Auth, discovery, scope, cursor, and Forge schema stay together.
            </p>
          </div>

          <Button variant="outline" className="h-9 w-fit rounded-md border-border bg-card" onClick={requestConnector}>
            Request connector
            <ExternalLink className="h-4 w-4" />
          </Button>
        </header>

        <section className="rounded-lg border border-border bg-card">
          <div className="flex flex-col gap-3 border-b border-border px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-wrap gap-1.5">
              {catalogFilters.map((filter) => (
                <button
                  key={filter.id}
                  type="button"
                  onClick={() => setConnectorFilter(filter.id)}
                  className={cn(
                    "inline-flex h-8 items-center rounded-md px-3 text-sm font-medium transition-colors",
                    connectorFilter === filter.id
                      ? "bg-primary text-primary-foreground"
                      : "border border-border bg-background text-muted-foreground hover:bg-muted hover:text-foreground"
                  )}
                >
                  {filter.label}
                </button>
              ))}
            </div>

            <div className="relative w-full lg:w-[340px]">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={connectorSearchQuery}
                onChange={(event) => setConnectorSearchQuery(event.target.value)}
                placeholder="Search connectors"
                className="h-9 rounded-md border-border bg-background pl-9 text-sm"
              />
            </div>
          </div>

          <div className="p-3">
            {isLoadingSources ? (
              <div className="grid gap-2.5 md:grid-cols-2 xl:grid-cols-3">
                {Array.from({ length: 9 }).map((_, index) => (
                  <div key={index} className="h-[138px] animate-pulse rounded-lg border border-border bg-background p-4">
                    <div className="flex gap-3">
                      <div className="h-11 w-11 rounded-md bg-muted" />
                      <div className="flex-1 space-y-2">
                        <div className="h-4 w-1/2 rounded bg-muted" />
                        <div className="h-3 w-2/3 rounded bg-muted" />
                      </div>
                    </div>
                    <div className="mt-5 h-8 rounded bg-muted" />
                  </div>
                ))}
              </div>
            ) : visibleSources.length === 0 ? (
              <div className="rounded-lg border border-dashed border-border bg-background px-4 py-16 text-center">
                <Search className="mx-auto mb-3 h-9 w-9 text-muted-foreground/50" />
                <p className="text-base font-medium text-foreground">No connectors match this view</p>
                <p className="mt-1 text-sm text-muted-foreground">Clear the search or switch categories.</p>
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-4 h-8 rounded-md border-border bg-card"
                  onClick={() => {
                    setConnectorSearchQuery("");
                    setConnectorFilter("all");
                  }}
                >
                  Reset
                </Button>
              </div>
            ) : (
              <div className="grid gap-2.5 md:grid-cols-2 xl:grid-cols-3">
                {visibleSources.map((source) => {
                  const metadata = sourceMetadata.get(source.id) || buildConnectorMetadata(source);
                  const connectorEnabled = isConnectorEnabled(source);
                  const disabled = !connectorEnabled || !sourceConnectionsAllowed || !entitiesAllowed || isCheckingUsage;

                  return (
                    <article
                      key={source.id}
                      className={cn(
                        "group flex min-h-[138px] flex-col justify-between rounded-lg border bg-background p-3.5 transition-colors",
                        connectorEnabled ? "border-border hover:border-primary/35 hover:bg-primary/[0.03]" : "border-border/80 opacity-65"
                      )}
                    >
                      <div className="flex items-start gap-3">
                        <div className="flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border bg-card p-2">
                          <img
                            src={getAppIconUrl(source.short_name, resolvedTheme)}
                            alt={`${source.name} icon`}
                            className="h-full w-full object-contain"
                          />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                              <h2 className="truncate text-base font-semibold text-foreground">{source.name}</h2>
                              <div className="mt-0.5 truncate font-mono text-xs text-muted-foreground">
                                {source.short_name}
                              </div>
                            </div>
                            <span
                              className={cn(
                                "shrink-0 rounded-md border px-2 py-0.5 text-xs font-medium",
                                connectorEnabled
                                  ? "border-green-500/25 bg-green-500/10 text-green-600 dark:text-green-400"
                                  : "border-border bg-muted text-muted-foreground"
                              )}
                            >
                              {connectorEnabled ? "Enabled" : "Soon"}
                            </span>
                          </div>
                          <p className="mt-2 line-clamp-2 text-sm leading-5 text-muted-foreground">
                            {metadata.description}
                          </p>
                        </div>
                      </div>

                      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-2.5">
                        <div className="flex min-w-0 flex-wrap gap-1.5">
                          <span className="inline-flex h-6 items-center gap-1 rounded-md border border-border bg-card px-2 text-xs text-muted-foreground">
                            <Database className="h-3.5 w-3.5" />
                            {metadata.category}
                          </span>
                          <span className="inline-flex h-6 items-center gap-1 rounded-md border border-border bg-card px-2 text-xs text-muted-foreground">
                            <KeyRound className="h-3.5 w-3.5" />
                            {metadata.authLabel}
                          </span>
                        </div>
                        <Button
                          size="sm"
                          disabled={disabled}
                          onClick={() => handleSourceClick(source)}
                          className="h-8 rounded-md bg-primary px-3 text-xs text-primary-foreground hover:bg-primary/90"
                        >
                          {connectorEnabled ? "Connect" : "Soon"}
                          {isCheckingUsage ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ArrowRight className="h-3.5 w-3.5" />}
                        </Button>
                      </div>
                    </article>
                  );
                })}

                <button
                  type="button"
                  onClick={requestConnector}
                  className="group flex min-h-[138px] flex-col justify-between rounded-lg border border-dashed border-border bg-background p-3.5 text-left transition-colors hover:border-primary/35 hover:bg-primary/[0.03]"
                >
                  <div className="flex items-start gap-3">
                    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md border border-border bg-card text-muted-foreground">
                      <ShieldCheck className="h-5 w-5" />
                    </div>
                    <div className="min-w-0">
                      <h2 className="text-base font-semibold text-foreground">Request connector</h2>
                      <p className="mt-2 text-sm leading-5 text-muted-foreground">
                        Need another system? Add it to the connector request queue.
                      </p>
                    </div>
                  </div>
                  <div className="mt-4 inline-flex items-center gap-2 border-t border-border pt-3 text-sm font-medium text-primary">
                    Open request
                    <ExternalLink className="h-4 w-4" />
                  </div>
                </button>
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
};

export default SourcesPage;
