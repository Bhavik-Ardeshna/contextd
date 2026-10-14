import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";
import { getAppIconUrl } from "@/lib/utils/icons";
import { useTheme } from "@/lib/theme-provider";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { SingleActionCheckResponse } from "@/types";

interface SourceButtonProps {
  id: string;
  name: string;
  shortName: string;
  onClick?: () => void;
  disabled?: boolean;
  usageCheckDetails?: {
    source_connections?: SingleActionCheckResponse | null;
    entities?: SingleActionCheckResponse | null;
  };
}

export const SourceButton = ({ id, name, shortName, onClick, disabled, usageCheckDetails }: SourceButtonProps) => {
  const { resolvedTheme } = useTheme();

  // Get color class based on shortName
  const getColorClass = (shortName: string) => {
    const colors = [
      "bg-blue-500",
      "bg-green-500",
      "bg-purple-500",
      "bg-orange-500",
      "bg-pink-500",
      "bg-indigo-500",
      "bg-red-500",
      "bg-yellow-500",
    ];

    // Hash the short name to get a consistent color
    const index = shortName.split("").reduce((acc, char) => acc + char.charCodeAt(0), 0) % colors.length;
    return colors[index];
  };

  // Source icon component
  const SourceIcon = () => (
    <div className="flex items-center justify-center w-8 h-8 sm:w-9 sm:h-9 md:w-10 md:h-10 overflow-hidden rounded-md flex-shrink-0">
      <img
        src={getAppIconUrl(shortName, resolvedTheme)}
        alt={`${shortName} icon`}
        className="w-7 h-7 sm:w-8 sm:h-8 md:w-9 md:h-9 object-contain"
        onError={(e) => {
          // Fallback to initials if icon fails to load
          e.currentTarget.style.display = 'none';
          e.currentTarget.parentElement!.classList.add(getColorClass(shortName));
          e.currentTarget.parentElement!.innerHTML = `<span class="text-white font-semibold text-xs sm:text-sm">${shortName.substring(0, 2).toUpperCase()}</span>`;
        }}
      />
    </div>
  );

  // Determine which action is blocking and get tooltip content
  const getTooltipContent = () => {
    if (!usageCheckDetails || !disabled) return null;

    const { source_connections, entities } = usageCheckDetails;

    if (source_connections && !source_connections.allowed && source_connections.reason === 'usage_limit_exceeded') {
      return (
        <>
          Source connection limit reached.{' '}
          <a
            href="/organization/settings?tab=billing"
            className="underline"
            onClick={(e) => e.stopPropagation()}
          >
            Upgrade your plan
          </a>
          {' '}for more connections.
        </>
      );
    } else if (entities && !entities.allowed && entities.reason === 'usage_limit_exceeded') {
      return (
        <>
          Entity processing limit reached.{' '}
          <a
            href="/organization/settings?tab=billing"
            className="underline"
            onClick={(e) => e.stopPropagation()}
          >
            Upgrade your plan
          </a>
          {' '}to process more data.
        </>
      );
    }

    return 'Unable to create collection at this time.';
  };

  const tooltipContent = getTooltipContent();

  const buttonContent = (
    <div
      className={cn(
        "border rounded-lg overflow-hidden group transition-all duration-200 min-w-0",
        disabled
          ? "border-border bg-muted/30 opacity-50 cursor-not-allowed"
          : "border-border hover:border-primary/30 bg-card hover:bg-muted/50 hover:shadow-sm cursor-pointer"
      )}
      onClick={disabled ? undefined : onClick}
    >
      <div className="flex items-center justify-between gap-3 p-2 sm:p-3 md:p-4">
        <div className="flex min-w-0 flex-1 items-center gap-2 sm:gap-3">
          <SourceIcon />
          <span className={cn(
            "min-w-0 truncate text-xs font-medium text-foreground sm:text-sm",
            disabled && "text-muted-foreground"
          )}>{name}</span>
        </div>
        <Button
          size="icon"
          variant="ghost"
          disabled={disabled}
          className={cn(
            "h-6 w-6 sm:h-7 sm:w-7 md:h-8 md:w-8 rounded-full flex-shrink-0 transition-all duration-200",
            disabled
              ? "bg-muted/50 text-muted-foreground cursor-not-allowed"
              : "bg-muted text-foreground hover:bg-muted/80 group-hover:text-primary"
          )}
        >
          <Plus className="h-3 w-3 sm:h-3.5 sm:w-3.5 md:h-4 md:w-4 transition-transform group-hover:scale-110" />
        </Button>
      </div>
    </div>
  );

  if (disabled && tooltipContent) {
    return (
      <TooltipProvider delayDuration={100}>
        <Tooltip>
          <TooltipTrigger asChild>
            <span tabIndex={0} className="w-full">
              {buttonContent}
            </span>
          </TooltipTrigger>
          <TooltipContent className="max-w-xs">
            <p className="text-xs">{tooltipContent}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  return buttonContent;
};

export default SourceButton;
