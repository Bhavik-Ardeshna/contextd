import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Eye, ExternalLink, Plus, Loader2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { getAppIconUrl } from "@/lib/utils/icons";
import { useTheme } from "@/lib/theme-provider";
import { cn } from "@/lib/utils";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useCollectionsStore, SourceConnection } from "@/lib/stores";

interface CollectionCardProps {
  id: string;
  name: string;
  readableId: string;
  status?: string;
  onClick?: () => void;
}

export const CollectionCard = ({
  id,
  name,
  readableId,
  status = "active",
  onClick,
}: CollectionCardProps) => {
  const navigate = useNavigate();
  const { resolvedTheme } = useTheme();
  const { fetchSourceConnections, sourceConnections } = useCollectionsStore();
  const [isLoadingConnections, setIsLoadingConnections] = useState(false);

  // Fetch source connections for this collection when the component mounts
  useEffect(() => {
    const loadSourceConnections = async () => {
      if (sourceConnections[readableId]) {
        // Already have the source connections in the store
        return;
      }

      // Set loading state
      setIsLoadingConnections(true);

      try {
        // Fetch source connections from the store (which will cache them)
        await fetchSourceConnections(readableId);
      } catch (error) {
        console.error(`Error fetching source connections for ${readableId}:`, error);
      } finally {
        setIsLoadingConnections(false);
      }
    };

    loadSourceConnections();
  }, [readableId, fetchSourceConnections, sourceConnections]);

  // Get connections for this collection from the store
  const collectionSourceConnections = sourceConnections[readableId] || [];

  const handleClick = () => {
    if (onClick) {
      onClick();
    } else {
      navigate(`/collections/${readableId}`);
    }
  };

  const handleViewClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigate(`/collections/${readableId}`);
  };

  return (
    <div
      className={cn(
        "relative rounded-xl overflow-hidden cursor-pointer min-w-[240px] h-full",
        "border border-border",
        "bg-card",
        "hover:border-border/80 hover:shadow-md transition-all duration-200"
      )}
      onClick={handleClick}
    >
      {/* Card Content */}
      <div className="relative h-full flex flex-col">
        {/* Card Header */}
        <div className="p-4 flex-1">
          <div className="flex justify-between items-start mb-2">
            <h3 className="text-xl font-semibold tracking-tight text-foreground">
              {name}
            </h3>
          </div>
          <p className="text-sm text-muted-foreground mb-3 truncate">
            {readableId}.contextd.local
          </p>

          {/* Status badge */}
          <StatusBadge status={status} showTooltip={true} tooltipContext="collection" />
        </div>

        {/* Card Footer */}
        <div className="border-t border-border p-2 flex justify-between items-center">
          {/* View & Edit Button */}
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground hover:text-foreground hover:bg-muted rounded-lg text-sm"
            onClick={handleViewClick}
          >
            <Eye className="h-4 w-4 mr-1.5" />
            View & edit
          </Button>

          {/* Source connection icons */}
          {isLoadingConnections ? (
            <div className="h-10 w-10 rounded-lg flex items-center justify-center">
              <Loader2 className="h-5 w-5 text-muted-foreground animate-spin" />
            </div>
          ) : collectionSourceConnections.length > 0 ? (
            collectionSourceConnections.length === 1 ? (
              <div className="flex items-center justify-center">
                <div className="h-10 w-10 rounded-lg bg-card border border-border p-1 flex items-center justify-center overflow-hidden">
                  <img
                    src={getAppIconUrl(collectionSourceConnections[0].short_name, resolvedTheme)}
                    alt={collectionSourceConnections[0].name}
                    className="h-full w-full object-contain"
                  />
                </div>
              </div>
            ) : (
              <div className="flex items-center">
                <div className="flex -space-x-2">
                  {collectionSourceConnections.slice(0, 2).map((connection, index) => (
                    <div
                      key={connection.id}
                      className="h-10 w-10 rounded-lg bg-card border border-border p-1.5 flex items-center justify-center overflow-hidden"
                      style={{ zIndex: 2 - index }}
                    >
                      <img
                        src={getAppIconUrl(connection.short_name, resolvedTheme)}
                        alt={connection.name}
                        className="h-full w-full object-contain"
                      />
                    </div>
                  ))}
                </div>
                {collectionSourceConnections.length > 2 && (
                  <div className="ml-1 text-xs font-medium text-muted-foreground">
                    +{collectionSourceConnections.length - 2}
                  </div>
                )}
              </div>
            )
          ) : (
            <div className="h-10 w-10 rounded-lg bg-muted p-2 flex items-center justify-center">
              <Plus className="h-full w-full text-foreground" />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default CollectionCard;
