import { Button } from "@/components/ui/button";
import { ArrowRight, Plug, Plus } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface RequestConnectorButtonProps {
    onClick?: () => void;
}

export const RequestConnectorButton = ({ onClick }: RequestConnectorButtonProps) => {

    const handleClick = () => {
        if (onClick) {
            onClick();
        } else {
            // Default action: open GitHub issues page for connector requests
            window.open('https://github.com/contextd/contextd/issues/new?labels=connector-request&template=connector_request.md&title=[Connector%20Request]%20', '_blank');
        }
    };

    return (
        <TooltipProvider delayDuration={100}>
            <Tooltip>
                <TooltipTrigger asChild>
                    <div
                        className="group flex min-h-[188px] cursor-pointer flex-col justify-between rounded-lg border border-dashed border-border bg-card p-4 transition-colors hover:border-primary/35 hover:bg-primary/[0.03]"
                        onClick={handleClick}
                    >
                        <div>
                            <div className="flex items-start gap-3">
                                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-border bg-muted text-muted-foreground">
                                    <Plug className="h-5 w-5" />
                                </div>
                                <div className="min-w-0">
                                    <div className="text-sm font-semibold text-foreground">Request connector</div>
                                    <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">custom_provider</div>
                                </div>
                            </div>
                            <p className="mt-3 text-xs leading-5 text-muted-foreground">
                                Need a system that is not listed? Submit a connector request and keep it in the quality layer queue.
                            </p>
                            <div className="mt-3 flex flex-wrap gap-1">
                                <span className="inline-flex h-6 items-center gap-1 rounded border border-border bg-muted/40 px-2 text-[10px] text-muted-foreground">
                                    <Plus className="h-3 w-3" />
                                    Roadmap
                                </span>
                                <span className="inline-flex h-6 items-center rounded border border-border bg-muted/40 px-2 text-[10px] text-muted-foreground">
                                    Custom
                                </span>
                            </div>
                        </div>
                        <div className="mt-4 flex items-center justify-between border-t border-border pt-3">
                            <span className="text-[11px] font-medium text-muted-foreground">GitHub request</span>
                            <Button
                                size="sm"
                                variant="outline"
                                className="h-8 rounded-md border-border bg-background px-3 text-xs"
                            >
                                Request
                                <ArrowRight className="h-3.5 w-3.5" />
                            </Button>
                        </div>
                    </div>
                </TooltipTrigger>
                <TooltipContent side="right" className="max-w-sm p-3">
                    <div className="space-y-1">
                        <p className="font-medium text-sm">Request New Connector</p>
                        <p className="text-xs text-muted-foreground">Opens GitHub to submit your request</p>
                    </div>
                </TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
};

export default RequestConnectorButton;
