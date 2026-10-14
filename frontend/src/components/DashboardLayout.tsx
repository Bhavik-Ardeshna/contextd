import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Activity,
  ArrowLeft,
  Bell,
  BookOpen,
  Bookmark,
  ChevronRight,
  CircleHelp,
  Command,
  Database,
  Key,
  Menu,
  Monitor,
  Moon,
  Network,
  PanelLeft,
  Plug,
  Search,
  Send,
  Settings,
  ShieldCheck,
  Sun,
  TerminalSquare,
  Users,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { useTheme } from "@/lib/theme-provider";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { UserProfileDropdown } from "@/components/UserProfileDropdown";
import { memo, useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { env } from "@/config/env";
import { ScrollArea } from "@/components/ui/scroll-area";
import { APIKeysSettings } from "@/components/settings/APIKeysSettings";
import { useCollectionsStore, useSourcesStore } from "@/lib/stores";
import { useOrganizationStore } from "@/lib/stores/organizations";
import { BillingGuard } from "@/components/BillingGuard";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { SidePanelFlow } from "@/components/shared/SidePanelFlow";
import { CollectionCreationModal } from "@/components/CollectionCreationModal";
import { UsageChecker } from "@/components/UsageChecker";
import { readSavedQueries, SAVED_QUERIES_EVENT } from "@/lib/queryConsoleStorage";

const SIDEBAR_WIDTH = 244;
const SIDEBAR_COLLAPSED_WIDTH = 52;

const themeOptions = [
  { value: "light" as const, label: "Light", icon: Sun },
  { value: "dark" as const, label: "Dark", icon: Moon },
  { value: "system" as const, label: "System", icon: Monitor },
];

const formatCount = (value: number) => {
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}K`;
  return String(value);
};

const formatRelativeSyncTime = (value?: string | null) => {
  if (!value) return "never";
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${value}Z`;
  const timestamp = new Date(normalized).getTime();
  if (Number.isNaN(timestamp)) return "never";

  const diffSeconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (diffSeconds < 60) return "just now";

  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes}m ago`;

  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;

  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 30) return `${diffDays}d ago`;

  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(normalized));
};

const getConnectionSyncDate = (connection: any) =>
  connection?.sync?.last_job?.completed_at ||
  connection?.last_sync_at ||
  connection?.sync?.last_job?.started_at ||
  connection?.last_sync_started_at ||
  connection?.modified_at ||
  null;

const getConnectionSuccessfulSyncDate = (connection: any) =>
  connection?.sync?.last_job?.completed_at ||
  connection?.last_sync_at ||
  connection?.last_sync_job_completed_at ||
  connection?.last_synced_at ||
  null;

const getConnectionSyncStatus = (connection: any) =>
  String(connection?.last_job_status || connection?.sync?.last_job?.status || connection?.status || "idle").toLowerCase();

const getActiveDatabaseId = (pathname: string) => {
  const match = pathname.match(/^\/(?:collections|databases)\/([^/?#]+)/);
  return match?.[1] ? decodeURIComponent(match[1]) : null;
};

type BreadcrumbItem = {
  label: string;
  to?: string;
};

const titleCase = (value: string) =>
  value
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

const getProviderLabel = (provider?: string | null) => {
  if (!provider) return "Connector";
  const labels: Record<string, string> = {
    postgres: "PostgreSQL",
    postgresql: "PostgreSQL",
    clickhouse: "ClickHouse",
    snowflake: "Snowflake",
    gmail: "Gmail",
    github: "GitHub",
  };
  return labels[provider.toLowerCase()] || titleCase(provider);
};

const getReadableDatabaseFallback = (databaseId: string) => {
  const withoutSuffix = databaseId.replace(/-[a-z0-9]{6,}$/i, "");
  return titleCase(withoutSuffix || databaseId);
};

const getBreadcrumb = (
  pathname: string,
  searchParams: URLSearchParams,
  getDatabaseLabel: (databaseId: string) => string
): BreadcrumbItem[] => {
  const databaseMatch = pathname.match(/^\/(?:collections|databases)\/([^/?#]+)(?:\/([^/?#]+))?/);
  if (databaseMatch?.[1]) {
    const activeDatabaseId = decodeURIComponent(databaseMatch[1]);
    const tab = databaseMatch[2];
    const databaseCrumb = {
      label: getDatabaseLabel(activeDatabaseId),
      to: `/databases/${activeDatabaseId}`,
    };
    if (tab) {
      return [
        { label: "Databases", to: "/databases" },
        databaseCrumb,
        { label: titleCase(tab) },
      ];
    }
    return [{ label: "Databases", to: "/databases" }, { label: databaseCrumb.label }];
  }
  const scopedDatabaseId = searchParams.get("database");
  if (pathname === "/query" && scopedDatabaseId) {
    return [
      { label: "Databases", to: "/databases" },
      { label: getDatabaseLabel(scopedDatabaseId), to: `/databases/${scopedDatabaseId}` },
      { label: "Query" },
    ];
  }
  if (pathname.startsWith("/graph") && scopedDatabaseId) {
    return [
      { label: "Databases", to: "/databases" },
      { label: getDatabaseLabel(scopedDatabaseId), to: `/databases/${scopedDatabaseId}` },
      { label: "Graph" },
    ];
  }
  if (pathname === "/" || pathname === "/databases") {
    return [{ label: "Databases" }];
  }
  if (pathname === "/sources") return [{ label: "Connectors" }];
  const sourceSetupMatch = pathname.match(/^\/sources\/([^/?#]+)\/setup/);
  if (sourceSetupMatch?.[1]) {
    const targetDatabaseId = searchParams.get("database");
    if (targetDatabaseId) {
      return [
        { label: "Databases", to: "/databases" },
        { label: getDatabaseLabel(targetDatabaseId), to: `/databases/${targetDatabaseId}/sources` },
        { label: `Connect ${getProviderLabel(decodeURIComponent(sourceSetupMatch[1]))}` },
      ];
    }
    return [
      { label: "Connectors", to: "/sources" },
      { label: getProviderLabel(decodeURIComponent(sourceSetupMatch[1])) },
      { label: "Setup" },
    ];
  }
  if (pathname === "/saved-queries") return [{ label: "Query Console", to: "/query" }, { label: "Saved Queries" }];
  if (pathname === "/query" || pathname.startsWith("/chat")) return [{ label: "Query Console" }];
  if (pathname.startsWith("/graph")) return [{ label: "Graph Explorer" }];
  if (pathname.startsWith("/cohorts")) return [{ label: "Databases", to: "/databases" }, { label: "Cohorts" }];
  if (pathname.startsWith("/auth-providers")) return [{ label: "Settings" }, { label: "Auth Providers" }];
  if (pathname.startsWith("/organization")) return [{ label: "Settings" }, { label: "Organization" }];
  if (pathname.startsWith("/admin")) return [{ label: "Platform" }, { label: "Admin" }];
  if (pathname.startsWith("/mcp") || pathname.startsWith("/semantic-mcp")) {
    return [{ label: "Integrations" }, { label: "API & MCP" }];
  }
  if (pathname.startsWith("/billing")) return [{ label: "Settings" }, { label: "Billing" }];
  if (pathname.startsWith("/api-keys")) return [{ label: "Settings" }, { label: "API Keys" }];
  if (pathname.startsWith("/dashboard")) return [{ label: "Legacy Dashboard" }];
  return [{ label: "Console" }];
};

const getBackTarget = (pathname: string, searchParams: URLSearchParams) => {
  const databaseMatch = pathname.match(/^\/(?:collections|databases)\/([^/?#]+)(?:\/([^/?#]+))?/);
  if (databaseMatch?.[1]) {
    const databaseId = decodeURIComponent(databaseMatch[1]);
    return databaseMatch[2] ? `/databases/${databaseId}` : "/databases";
  }

  const scopedDatabaseId = searchParams.get("database");
  if (pathname === "/query" && scopedDatabaseId) return `/databases/${scopedDatabaseId}`;
  if (pathname.startsWith("/graph") && scopedDatabaseId) return `/databases/${scopedDatabaseId}`;

  const setupMatch = pathname.match(/^\/sources\/[^/?#]+\/setup/);
  if (setupMatch) {
    return scopedDatabaseId ? `/databases/${scopedDatabaseId}/sources` : "/sources";
  }

  if (pathname === "/sources") return "/databases";
  if (pathname === "/saved-queries") return "/query";
  if (pathname === "/query") return "/databases";
  if (pathname.startsWith("/graph")) return "/databases";
  if (pathname.startsWith("/cohorts")) return "/databases";
  if (pathname.startsWith("/auth-providers") || pathname.startsWith("/organization")) return "/databases";
  if (pathname.startsWith("/admin") || pathname.startsWith("/mcp")) return "/databases";
  if (pathname.startsWith("/billing") || pathname.startsWith("/api-keys")) return "/databases";
  if (pathname.startsWith("/dashboard")) return "/databases";
  return null;
};

const Logo = memo(() => {
  return (
    <Link to="/" className="flex h-full min-w-0 items-center overflow-hidden">
      <div className="min-w-0 text-[25px] font-semibold leading-none tracking-normal text-foreground">
        Context<span className="text-primary">D</span>
      </div>
    </Link>
  );
});

Logo.displayName = "Logo";

const NavSection = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <div className="space-y-1.5">
    <div className="px-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
      {title}
    </div>
    <div className="space-y-0.5">{children}</div>
  </div>
);

const NavItem = memo(
  ({
    to,
    isActive,
    icon,
    children,
    count,
    badge,
    tone = "default",
  }: {
    to: string;
    isActive: boolean;
    icon: React.ReactNode;
    children: React.ReactNode;
    count?: number | string;
    badge?: string;
    tone?: "default" | "warn" | "danger";
  }) => {
    return (
      <Link
        to={to}
        className={cn(
          "group relative flex h-9 items-center gap-2.5 overflow-hidden rounded-md px-3 text-[13px] font-medium transition-colors",
          isActive
            ? "bg-primary/10 text-primary"
            : "text-muted-foreground hover:bg-muted hover:text-foreground"
        )}
      >
        {isActive && (
          <span className="absolute left-0 top-1.5 h-6 w-0.5 rounded-r-full bg-primary" />
        )}
        <span className={cn("flex h-4 w-4 shrink-0 items-center justify-center", isActive && "text-primary")}>
          {icon}
        </span>
        <span className="min-w-0 flex-1 truncate">{children}</span>
        {typeof count !== "undefined" && (
          <span
            className={cn(
              "rounded border px-1.5 py-0.5 font-mono text-[10px] leading-none",
              tone === "warn" &&
                "border-amber-500/25 bg-amber-500/10 text-amber-600 dark:text-amber-400",
              tone === "danger" &&
                "border-destructive/25 bg-destructive/10 text-destructive",
              tone === "default" &&
                "border-border bg-muted text-muted-foreground"
            )}
          >
            {count}
          </span>
        )}
        {badge && (
          <span className="shrink-0 rounded border border-blue-500/25 bg-blue-500/10 px-1.5 py-0.5 text-[10px] leading-none text-blue-600 dark:text-blue-300">
            {badge}
          </span>
        )}
      </Link>
    );
  }
);

NavItem.displayName = "NavItem";

const IconRailItem = memo(
  ({
    to,
    label,
    isActive,
    icon,
  }: {
    to: string;
    label: string;
    isActive: boolean;
    icon: React.ReactNode;
  }) => (
    <Tooltip>
      <TooltipTrigger asChild>
        <Link
          to={to}
          aria-label={label}
          className={cn(
            "relative flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
            isActive && "bg-primary/10 text-primary"
          )}
        >
          {isActive && <span className="absolute -left-2 h-5 w-0.5 rounded-r-full bg-primary" />}
          {icon}
        </Link>
      </TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  )
);

IconRailItem.displayName = "IconRailItem";

const IconRailButton = ({ label, icon }: { label: string; icon: React.ReactNode }) => (
  <Tooltip>
    <TooltipTrigger asChild>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label={label}
        className="h-8 w-8 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        {icon}
      </Button>
    </TooltipTrigger>
    <TooltipContent side="right">{label}</TooltipContent>
  </Tooltip>
);

const ThemeMenu = () => {
  const { theme, resolvedTheme, setTheme } = useTheme();
  const CurrentIcon = themeOptions.find((option) => option.value === theme)?.icon ?? Monitor;

  return (
    <DropdownMenu>
      <Tooltip>
        <TooltipTrigger asChild>
          <DropdownMenuTrigger asChild>
            <button className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-card text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
              <CurrentIcon className="h-4 w-4" />
            </button>
          </DropdownMenuTrigger>
        </TooltipTrigger>
        <TooltipContent>Theme</TooltipContent>
      </Tooltip>
      <DropdownMenuContent align="end" className="w-36">
        {themeOptions.map((option) => {
          const Icon = option.icon;
          return (
            <DropdownMenuItem
              key={option.value}
              onClick={() => setTheme(option.value)}
              className="gap-2"
            >
              <Icon className="h-4 w-4" />
              <span>{option.label}</span>
              {theme === option.value && (
                <span className="ml-auto h-1.5 w-1.5 rounded-full bg-primary" />
              )}
            </DropdownMenuItem>
          );
        })}
        {theme === "system" && (
          <div className="border-t border-border px-2 py-1.5 text-[11px] text-muted-foreground">
            Using {resolvedTheme}
          </div>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

const DashboardLayout = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { currentOrganization } = useOrganizationStore();
  const collections = useCollectionsStore((state) => state.collections);
  const fetchCollections = useCollectionsStore((state) => state.fetchCollections);
  const sourceConnections = useCollectionsStore((state) => state.sourceConnections);
  const fetchSourceConnections = useCollectionsStore((state) => state.fetchSourceConnections);
  const sources = useSourcesStore((state) => state.sources);
  const fetchSources = useSourcesStore((state) => state.fetchSources);
  const [apiHealth, setApiHealth] = useState<"checking" | "healthy" | "offline">("checking");
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [savedQueryCount, setSavedQueryCount] = useState(0);
  const [routeDatabaseLabels, setRouteDatabaseLabels] = useState<Record<string, string>>({});

  const routeSearchParams = new URLSearchParams(location.search);
  const databaseLabelById = useMemo(
    () => new Map(collections.map((collection) => [collection.readable_id, collection.name || collection.readable_id])),
    [collections]
  );
  const activeDatabaseId = getActiveDatabaseId(location.pathname);
  const sourceSetupDatabaseId = location.pathname.startsWith("/sources/")
    ? routeSearchParams.get("database")
    : null;
  const queryDatabaseId = location.pathname === "/query" ? routeSearchParams.get("database") : null;
  const graphDatabaseId = location.pathname.startsWith("/graph") ? routeSearchParams.get("database") : null;
  const scopedDatabaseId = queryDatabaseId || graphDatabaseId;
  const routeDatabaseIds = useMemo(
    () => Array.from(new Set([activeDatabaseId, sourceSetupDatabaseId, scopedDatabaseId].filter(Boolean) as string[])),
    [activeDatabaseId, sourceSetupDatabaseId, scopedDatabaseId]
  );
  const getDatabaseLabel = (databaseId: string) =>
    routeDatabaseLabels[databaseId] || databaseLabelById.get(databaseId) || getReadableDatabaseFallback(databaseId);
  const breadcrumbs = getBreadcrumb(location.pathname, routeSearchParams, getDatabaseLabel);
  const backTarget = getBackTarget(location.pathname, routeSearchParams);
  const isBillingRoute = location.pathname.startsWith("/billing");
  const isNonScrollable =
    location.pathname === "/query" ||
    location.pathname.startsWith("/chat") ||
    location.pathname.startsWith("/graph") ||
    location.pathname.startsWith("/sources/") ||
    (location.pathname.startsWith("/databases/") && location.pathname !== "/databases") ||
    location.pathname === "/dashboard";

  useEffect(() => {
    if (collections.length === 0) fetchCollections();
    if (sources.length === 0) fetchSources();
  }, [collections.length, fetchCollections, fetchSources, sources.length]);

  useEffect(() => {
    const missingDatabaseId = routeDatabaseIds.find((databaseId) => !routeDatabaseLabels[databaseId]);
    if (!missingDatabaseId) return;

    let cancelled = false;
    apiClient
      .get(`/collections/${encodeURIComponent(missingDatabaseId)}`)
      .then(async (response) => {
        if (!response.ok) return null;
        return (await response.json()) as { name?: string; readable_id?: string };
      })
      .then((collection) => {
        if (cancelled || !collection) return;
        const readableId = collection.readable_id || missingDatabaseId;
        const label = collection.name || readableId;
        setRouteDatabaseLabels((labels) => ({ ...labels, [readableId]: label }));
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
    };
  }, [routeDatabaseIds, routeDatabaseLabels]);

  useEffect(() => {
    let cancelled = false;
    apiClient
      .get("/health")
      .then((response) => {
        if (!cancelled) setApiHealth(response.ok ? "healthy" : "offline");
      })
      .catch(() => {
        if (!cancelled) setApiHealth("offline");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const refreshSavedQueries = () => {
      setSavedQueryCount(readSavedQueries().length);
    };

    refreshSavedQueries();
    window.addEventListener("storage", refreshSavedQueries);
    window.addEventListener(SAVED_QUERIES_EVENT, refreshSavedQueries);
    return () => {
      window.removeEventListener("storage", refreshSavedQueries);
      window.removeEventListener(SAVED_QUERIES_EVENT, refreshSavedQueries);
    };
  }, []);

  const isDatabasesActive =
    location.pathname === "/" ||
    location.pathname.startsWith("/collections") ||
    location.pathname.startsWith("/databases");
  const isSourceCatalogActive = location.pathname === "/sources";
  const isQueryActive = location.pathname === "/query" || location.pathname.startsWith("/chat");
  const isGraphActive = location.pathname.startsWith("/graph");
  const isSavedQueriesActive = location.pathname.startsWith("/saved-queries");
  const isCohortActive = location.pathname.startsWith("/cohorts");
  const isAdminActive = location.pathname.startsWith("/admin");
  const isMcpActive = location.pathname.startsWith("/mcp") || location.pathname.startsWith("/semantic-mcp");
  const isAuthProvidersActive = location.pathname.startsWith("/auth-providers");
  const isOrganizationActive = location.pathname.startsWith("/organization");

  const orgId = currentOrganization?.id || "org_pending";
  const databaseStatusId =
    activeDatabaseId || sourceSetupDatabaseId || scopedDatabaseId || "no-db-selected";
  const footerDatabaseLabel = databaseStatusId === "no-db-selected" ? "workspace" : databaseStatusId;
  const footerConnections = databaseStatusId === "no-db-selected" ? [] : sourceConnections[databaseStatusId] || [];
  const footerPrimaryConnection = footerConnections[0];
  const footerLastSync = footerPrimaryConnection
    ? formatRelativeSyncTime(getConnectionSyncDate(footerPrimaryConnection))
    : "n/a";
  const footerPendingCount = footerConnections.filter((connection) => {
    const status = getConnectionSyncStatus(connection);
    const hasSuccessfulBaseline = Boolean(getConnectionSuccessfulSyncDate(connection));
    return !hasSuccessfulBaseline && (status === "syncing" || status === "running" || status === "pending" || status === "cancelling");
  }).length;
  const footerEntityCount = footerConnections.reduce(
    (sum, connection) =>
      sum + (Number(connection.entity_count ?? connection.entities?.total_entities ?? 0) || 0),
    0
  );
  const footerRawSyncStatus = getConnectionSyncStatus(footerPrimaryConnection);
  const footerSyncStatus = footerPrimaryConnection
    ? footerPendingCount > 0
      ? footerRawSyncStatus
      : "ready"
    : "idle";
  const buildHash =
    import.meta.env.VITE_GIT_SHA || import.meta.env.VITE_COMMIT_SHA || import.meta.env.MODE || "dev";
  const environmentLabel = env.VITE_LOCAL_DEVELOPMENT ? "local" : "prod";

  useEffect(() => {
    if (databaseStatusId === "no-db-selected") return;

    void fetchSourceConnections(databaseStatusId, false);
  }, [databaseStatusId, fetchSourceConnections]);

  const collapsedNavGroups = [
    [
      {
        to: "/",
        label: "Databases",
        isActive: isDatabasesActive,
        icon: <Database className="h-4 w-4" />,
      },
      {
        to: "/query",
        label: "Query Console",
        isActive: isQueryActive,
        icon: <TerminalSquare className="h-4 w-4" />,
      },
      {
        to: "/sources",
        label: "Connectors",
        isActive: isSourceCatalogActive,
        icon: <Plug className="h-4 w-4" />,
      },
      {
        to: "/graph",
        label: "Graph Explorer",
        isActive: isGraphActive,
        icon: <Network className="h-4 w-4" />,
      },
      {
        to: "/saved-queries",
        label: "Saved Queries",
        isActive: isSavedQueriesActive,
        icon: <Bookmark className="h-4 w-4" />,
      },
      {
        to: "/cohorts",
        label: "Cohorts",
        isActive: isCohortActive,
        icon: <Users className="h-4 w-4" />,
      },
    ],
    [
      {
        to: "/mcp",
        label: "API & MCP",
        isActive: isMcpActive,
        icon: <Activity className="h-4 w-4" />,
      },
      {
        to: "/admin",
        label: "Admin",
        isActive: isAdminActive,
        icon: <ShieldCheck className="h-4 w-4" />,
      },
    ],
    [
      {
        to: "/auth-providers",
        label: "Auth Providers",
        isActive: isAuthProvidersActive,
        icon: <Key className="h-4 w-4" />,
      },
      {
        to: "/organization/settings",
        label: "Organization",
        isActive: isOrganizationActive,
        icon: <Settings className="h-4 w-4" />,
      },
    ],
  ];

  const renderSidebarContent = (collapsed: boolean) => (
    <TooltipProvider delayDuration={120}>
      <div
        className={cn(
          "flex h-full flex-col bg-sidebar-background-solid text-sidebar-foreground",
          collapsed && "items-center"
        )}
      >
        <div
          className={cn(
            "flex h-[52px] items-center",
            collapsed ? "justify-center px-2" : "justify-between gap-3 px-4"
          )}
        >
          {!collapsed && <Logo />}
          <button
            type="button"
            onClick={() => setIsSidebarCollapsed((value) => !value)}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border bg-card text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            <PanelLeft className="h-4 w-4" />
          </button>
        </div>

        {collapsed ? (
          <>
            <nav className="flex min-h-0 flex-1 flex-col items-center gap-4 overflow-y-auto px-2 py-3">
              {collapsedNavGroups.map((group, groupIndex) => (
                <div key={groupIndex} className="flex flex-col items-center gap-1.5">
                  {group.map((item) => (
                    <IconRailItem
                      key={item.label}
                      to={item.to}
                      label={item.label}
                      isActive={item.isActive}
                      icon={item.icon}
                    />
                  ))}
                </div>
              ))}
            </nav>

            <div className="flex flex-col items-center gap-1.5 px-2 py-2">
              <IconRailButton label="Help" icon={<CircleHelp className="h-4 w-4" />} />
              <IconRailButton label="Feedback" icon={<Send className="h-4 w-4" />} />
              <UserProfileDropdown collapsed />
            </div>
          </>
        ) : (
          <>
            <ScrollArea className="min-h-0 flex-1">
              <div className="space-y-5 px-2 py-4">
                <NavSection title="Workspace">
                  <NavItem
                    to="/"
                    isActive={isDatabasesActive}
                    icon={<Database className="h-4 w-4" />}
                    count={formatCount(collections.length)}
                  >
                    Databases
                  </NavItem>
                  <NavItem
                    to="/query"
                    isActive={isQueryActive}
                    icon={<TerminalSquare className="h-4 w-4" />}
                  >
                    Query Console
                  </NavItem>
                  <NavItem
                    to="/sources"
                    isActive={isSourceCatalogActive}
                    icon={<Plug className="h-4 w-4" />}
                    count={formatCount(sources.length)}
                  >
                    Connectors
                  </NavItem>
                  <NavItem
                    to="/graph"
                    isActive={isGraphActive}
                    icon={<Network className="h-4 w-4" />}
                  >
                    Graph Explorer
                  </NavItem>
                  <NavItem
                    to="/saved-queries"
                    isActive={isSavedQueriesActive}
                    icon={<Bookmark className="h-4 w-4" />}
                    count={formatCount(savedQueryCount)}
                  >
                    Saved Queries
                  </NavItem>
                  <NavItem
                    to="/cohorts"
                    isActive={isCohortActive}
                    icon={<Users className="h-4 w-4" />}
                  >
                    Cohorts
                  </NavItem>
                </NavSection>

                <NavSection title="Integrations">
                  <NavItem
                    to="/mcp"
                    isActive={isMcpActive}
                    icon={<Activity className="h-4 w-4" />}
                  >
                    API & MCP
                  </NavItem>
                  <NavItem
                    to="/admin"
                    isActive={isAdminActive}
                    icon={<ShieldCheck className="h-4 w-4" />}
                  >
                    Admin
                  </NavItem>
                </NavSection>

                <NavSection title="Settings">
                  <NavItem
                    to="/auth-providers"
                    isActive={isAuthProvidersActive}
                    icon={<Key className="h-4 w-4" />}
                  >
                    Auth Providers
                  </NavItem>
                  <NavItem
                    to="/organization/settings"
                    isActive={isOrganizationActive}
                    icon={<Settings className="h-4 w-4" />}
                  >
                    Organization
                  </NavItem>
                </NavSection>

              </div>
            </ScrollArea>

            <div className="px-3 py-2">
              <div className="mb-2 flex flex-col gap-1">
                <Button variant="ghost" size="sm" className="h-8 w-full justify-start gap-2 px-2 text-xs">
                  <CircleHelp className="h-3.5 w-3.5" />
                  Help
                </Button>
                <Button variant="ghost" size="sm" className="h-8 w-full justify-start gap-2 px-2 text-xs">
                  <Send className="h-3.5 w-3.5" />
                  Feedback
                </Button>
              </div>
              <UserProfileDropdown />
            </div>
          </>
        )}
      </div>
    </TooltipProvider>
  );

  const pageContent = (
    <div className={cn("h-full", isNonScrollable ? "overflow-hidden" : "pb-8")}>
      {location.pathname === "/api-keys" ? (
        <div className="container pb-8 pt-8">
          <div className="mb-8 flex items-center gap-2">
            <Key className="h-6 w-6" />
            <h1 className="text-2xl font-semibold">API Keys</h1>
          </div>
          <div className="max-w-4xl">
            <APIKeysSettings />
          </div>
        </div>
      ) : (
        <Outlet />
      )}
    </div>
  );

  return (
    <TooltipProvider delayDuration={120}>
      <div className="fixed inset-0 flex overflow-hidden bg-background text-foreground">
        <UsageChecker />
        <CollectionCreationModal />
        <SidePanelFlow />

        <aside
          className={cn(
            "hidden h-full shrink-0 border-r border-sidebar-border bg-sidebar-background-solid transition-[width] duration-200 lg:block"
          )}
          style={{ width: isSidebarCollapsed ? SIDEBAR_COLLAPSED_WIDTH : SIDEBAR_WIDTH }}
        >
          {renderSidebarContent(isSidebarCollapsed)}
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header
            className="flex h-[52px] shrink-0 items-center justify-between gap-3 border-b border-border bg-card px-3 md:px-4"
          >
            <div className="flex min-w-0 items-center gap-3">
              <Sheet>
                <SheetTrigger asChild>
                  <Button variant="outline" size="icon" className="h-8 w-8 rounded-md lg:hidden">
                    <Menu className="h-4 w-4" />
                  </Button>
                </SheetTrigger>
                <SheetContent side="left" className="w-[244px] p-0">
                  {renderSidebarContent(false)}
                </SheetContent>
              </Sheet>

              {backTarget && (
                <button
                  type="button"
                  onClick={() => navigate(backTarget)}
                  className="hidden h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border bg-background text-muted-foreground transition hover:bg-muted hover:text-foreground sm:flex"
                  aria-label="Back"
                >
                  <ArrowLeft className="h-4 w-4" />
                </button>
              )}

              <nav aria-label="Breadcrumb" className="min-w-0">
                <ol className="flex min-w-0 items-center gap-1 overflow-hidden text-sm">
                  {breadcrumbs.map((crumb, index) => {
                    const isLast = index === breadcrumbs.length - 1;
                    return (
                      <li key={`${crumb.label}-${index}`} className="flex min-w-0 items-center gap-1">
                        {index > 0 && <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />}
                        {crumb.to && !isLast ? (
                          <Link
                            to={crumb.to}
                            className="min-w-0 truncate rounded px-1 py-0.5 text-muted-foreground transition hover:bg-muted hover:text-foreground"
                          >
                            {crumb.label}
                          </Link>
                        ) : (
                          <span
                            aria-current={isLast ? "page" : undefined}
                            className={cn(
                              "min-w-0 truncate px-1 py-0.5",
                              isLast ? "font-medium text-foreground" : "text-muted-foreground"
                            )}
                          >
                            {crumb.label}
                          </span>
                        )}
                      </li>
                    );
                  })}
                </ol>
              </nav>
            </div>

            <div className="flex shrink-0 items-center gap-2">
              <button className="hidden h-8 min-w-[220px] items-center gap-2 rounded-md border border-border bg-background px-2.5 text-left text-xs text-muted-foreground transition-colors hover:bg-muted md:flex">
                <Search className="h-3.5 w-3.5" />
                <span className="flex-1">Command palette</span>
                <span className="inline-flex items-center gap-0.5 rounded border border-border bg-card px-1.5 py-0.5 font-mono text-[10px]">
                  <Command className="h-2.5 w-2.5" />K
                </span>
              </button>

              <span className="hidden rounded border border-border bg-muted px-2 py-1 font-mono text-[11px] text-muted-foreground sm:inline-flex">
                {environmentLabel}
              </span>

              <span
                className={cn(
                  "hidden items-center gap-1.5 rounded border px-2 py-1 text-[11px] font-medium sm:inline-flex",
                  apiHealth === "healthy" &&
                    "border-green-500/25 bg-green-500/10 text-green-600 dark:text-green-400",
                  apiHealth === "offline" &&
                    "border-destructive/25 bg-destructive/10 text-destructive",
                  apiHealth === "checking" &&
                    "border-border bg-muted text-muted-foreground"
                )}
              >
                <span
                  className={cn(
                    "h-1.5 w-1.5 rounded-full",
                    apiHealth === "healthy" && "bg-green-500",
                    apiHealth === "offline" && "bg-destructive",
                    apiHealth === "checking" && "bg-muted-foreground"
                  )}
                />
                {apiHealth === "healthy" ? "Operational" : apiHealth === "offline" ? "Offline" : "Checking"}
              </span>

              <Tooltip>
                <TooltipTrigger asChild>
                  <button className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-card text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
                    <Bell className="h-4 w-4" />
                  </button>
                </TooltipTrigger>
                <TooltipContent>Notifications</TooltipContent>
              </Tooltip>

              <ThemeMenu />
            </div>
          </header>

          <main className={cn("min-h-0 flex-1 bg-background", isNonScrollable ? "overflow-hidden" : "overflow-auto")}>
            {isBillingRoute ? pageContent : <BillingGuard>{pageContent}</BillingGuard>}
          </main>

          <footer className="hidden h-7 shrink-0 items-center gap-2 overflow-hidden border-t border-border bg-card px-4 font-mono text-[11px] text-muted-foreground md:flex">
            <BookOpen className="h-3.5 w-3.5 text-primary" />
            <span className="truncate">{orgId}</span>
            <span>·</span>
            <span className="truncate">{footerDatabaseLabel}</span>
            <span>·</span>
            <span>last sync {footerLastSync}</span>
            <span>·</span>
            <span>pending {footerPendingCount}</span>
            <span>·</span>
            <span>entities {formatCount(footerEntityCount)}</span>
            <span>·</span>
            <span>sync {footerSyncStatus}</span>
            <span>·</span>
            <span>build {buildHash}</span>
          </footer>
        </div>
      </div>
    </TooltipProvider>
  );
};

export default DashboardLayout;
