import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { getAppIconUrl } from "@/lib/utils/icons";
import { Info, Check, Box, ChevronsUpDown, Plug } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { useState, useEffect } from "react";
import { useTheme } from "@/lib/theme-provider";
import { Connection } from "@/types";
import { LabelBadge } from "./LabelBadge";
import { env } from "@/config/env";
import { SlackTokenDialog } from "./SlackTokenDialog";

interface UnifiedDataSourceCardProps {
  shortName: string;
  name: string;
  description: string;
  status: "connected" | "disconnected";
  connections: Connection[];
  authType?: string | null;
  labels?: string[];
  entityCount?: number;

  // Mode configuration
  mode: "select" | "manage";

  // Common callbacks
  onInfoClick?: () => void;

  // Select mode properties
  onSelect?: (connectionId: string) => void;
  onAddConnection?: () => void;

  // Manage mode properties
  onManage?: () => void;

  // Custom rendering
  renderConnectionsIndicator?: () => React.ReactNode;
  renderBottomActions?: () => React.ReactNode;

  // Additional dialogs/wizards
  renderDialogs?: () => React.ReactNode;
}

export function UnifiedDataSourceCard({
  shortName,
  name,
  description,
  status,
  connections = [],
  authType,
  labels = [],
  entityCount = 0,
  mode = "select",
  onInfoClick,
  onSelect,
  onAddConnection,
  onManage,
  renderConnectionsIndicator,
  renderBottomActions,
  renderDialogs,
}: UnifiedDataSourceCardProps) {
  const [selectedConnectionId, setSelectedConnectionId] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [showTokenDialog, setShowTokenDialog] = useState(false);
  const { resolvedTheme } = useTheme();
  const activeConnections = connections.filter(conn => conn.status === "active");
  const mostRecentConnection = activeConnections.length > 0
    ? activeConnections.sort((a, b) => new Date(b.modified_at).getTime() - new Date(a.modified_at).getTime())[0]
    : null;

  // Check if we're in local development mode and this is the Slack source
  const isLocalSlack = env.VITE_LOCAL_DEVELOPMENT && shortName === "slack";

  useEffect(() => {
    if (mode === "select" && connections.length > 0) {
      const sortedConnections = [...connections].sort((a, b) =>
        new Date(b.modified_at).getTime() - new Date(a.modified_at).getTime()
      );
      setSelectedConnectionId(sortedConnections[0]?.id || null);
    }
  }, [connections, mode]);

  const handleConnectionSelect = (connectionId: string) => {
    setSelectedConnectionId(connectionId);
    setOpen(false);
    if (onSelect) {
      onSelect(connectionId);
    }
  };

  const handleAddNewConnection = () => {
    setOpen(false);

    // For Slack in local development, show token dialog instead of OAuth flow
    if (isLocalSlack) {
      setShowTokenDialog(true);
    } else if (onAddConnection) {
      onAddConnection();
    }
  };

  const handleManageSource = () => {
    if (onManage) {
      onManage();
    }
  };

  const handleTokenSuccess = (connectionId: string) => {
    setSelectedConnectionId(connectionId);
    if (onSelect) {
      onSelect(connectionId);
    }
  };

  return (
    <>
      <Card className="w-full h-[240px] flex flex-col overflow-hidden group border-border/70 relative rounded-xl dark:bg-slate-900/50 hover:bg-white dark:hover:bg-slate-900/70 transition-colors">
        {/* Auth type badge positioned absolutely in top right */}
        {authType && (
          <div className="absolute top-3 right-3 z-10">
            <span className="text-xs px-2 py-1 rounded-full bg-gray-100 dark:bg-gray-900 font-medium text-muted-foreground">
              {authType.includes("oauth2") ? "OAUTH2" : authType.replace(/_/g, " ").toUpperCase()}
            </span>
          </div>
        )}

        <CardHeader className="p-4 pb-2 flex flex-col items-start h-[90px]">
          <div className="flex items-center mb-2 w-full">
            <div className="w-8 h-8 shrink-0 flex items-center justify-center mr-3">
              <img
                src={getAppIconUrl(shortName, resolvedTheme)}
                alt={`${name} icon`}
                className="w-8 h-8"
              />
            </div>
            <CardTitle className="text-xl line-clamp-1">{name}</CardTitle>
          </div>
          <CardDescription className="line-clamp-2 text-muted-foreground/70 w-full">
            {description.split('\n').slice(0, 2).join('\n')}
          </CardDescription>
        </CardHeader>

        <CardContent className="p-4 pt-2 pb-2 h-[120px] overflow-y-auto">
          {/* Labels section */}
          {labels.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-3">
              {labels.slice(0, 3).map((label) => (
                <LabelBadge key={label} label={label} />
              ))}
              {labels.length > 3 && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-500/15 text-gray-600 dark:text-gray-400">
                      +{labels.length - 3}
                    </span>
                  </TooltipTrigger>
                  <TooltipContent>
                    <div className="flex flex-wrap gap-1.5 max-w-[240px]">
                      {labels.slice(3).map((label) => (
                        <LabelBadge key={label} label={label} />
                      ))}
                    </div>
                  </TooltipContent>
                </Tooltip>
              )}
            </div>
          )}
        </CardContent>

        <CardFooter className="p-4 pt-2 flex flex-col gap-3 mt-auto h-[110px]">
          <div className="flex w-full justify-between items-center">
            {/* Entity count and connections count */}
            <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm text-muted-foreground pb-2">
              <div className="flex items-center gap-1.5">
                <Box className="w-4 h-4" />
                <span>{entityCount === 0 ? "Entities calculated at sync" : `${entityCount} entities`}</span>
              </div>

              {connections.length > 0 && (
                <div className="flex items-center gap-1.5">
                  <Plug className="w-4 h-4" />
                  <span>{connections.length} connection{connections.length !== 1 ? 's' : ''}</span>
                </div>
              )}
            </div>
          </div>

          {/* Connection dropdown or manage button */}
          <div className="flex justify-center w-full">
            {mode === "manage" ? (
              <Button
                variant="default"
                className="h-9 px-4 transition-colors bg-primary/75 w-full"
                size="sm"
                onClick={handleManageSource}
              >
                <span className="text-sm truncate max-w-[240px]">
                  Manage Source
                </span>
              </Button>
            ) : status === "connected" ? (
              <div className="flex w-full justify-center">
                <Button
                  variant="default"
                  className="h-9 px-4 transition-colors rounded-r-none bg-primary/75"
                  size="sm"
                  onClick={() => {
                    if (mostRecentConnection && onSelect) {
                      onSelect(mostRecentConnection.id);
                    }
                  }}
                >
                  <span className="text-sm truncate max-w-[240px]">
                    {mostRecentConnection?.name || "Connection"}
                  </span>
                </Button>
                <DropdownMenu open={open} onOpenChange={setOpen}>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="default"
                      className="h-9 px-2 transition-colors rounded-l-none border-l border-primary-foreground/10 bg-primary/75"
                      size="sm"
                    >
                      <ChevronsUpDown className="h-3.5 w-3.5 opacity-70" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    align="end"
                    className="w-[280px]"
                    style={{
                      maxHeight: '300px',
                      overflowY: 'auto'
                    }}
                  >
                    <DropdownMenuItem
                      className="cursor-pointer"
                      onClick={handleAddNewConnection}
                    >
                      <span className="font-medium text-primary">
                        {isLocalSlack ? "Add new token connection" : "Add new connection"}
                      </span>
                    </DropdownMenuItem>

                    {connections.length > 0 && <DropdownMenuSeparator />}

                    {[...connections]
                      .sort((a, b) => {
                        return new Date(b.modified_at).getTime() - new Date(a.modified_at).getTime();
                      })
                      .map((connection) => (
                        <DropdownMenuItem
                          key={connection.id}
                          className="cursor-pointer"
                          onClick={() => handleConnectionSelect(connection.id)}
                        >
                          <div className="flex items-center justify-between w-full">
                            <div className="flex flex-col">
                              <span className="font-medium">{connection.name}</span>
                              <span className="text-xs text-muted-foreground">
                                ID: {connection.id}
                              </span>
                            </div>
                            {selectedConnectionId === connection.id && (
                              <Check className="h-4 w-4 text-primary ml-2" />
                            )}
                          </div>
                        </DropdownMenuItem>
                      ))
                    }
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            ) : (
              <Button
                variant="outline"
                className="h-9 px-4 transition-colors hover:bg-primary/75 hover:text-white duration-300"
                onClick={handleAddNewConnection}
              >
                <span className="text-sm truncate max-w-[240px]">
                  {isLocalSlack ? "+ Add token connection" : "+ Add connection"}
                </span>
              </Button>
            )}
          </div>
        </CardFooter>
      </Card>

      {/* Render any dialogs/modals if provided */}
      {renderDialogs && renderDialogs()}

      {/* Slack token dialog for local development */}
      {isLocalSlack && (
        <SlackTokenDialog
          open={showTokenDialog}
          onOpenChange={setShowTokenDialog}
          onSuccess={handleTokenSuccess}
        />
      )}
    </>
  );
}
