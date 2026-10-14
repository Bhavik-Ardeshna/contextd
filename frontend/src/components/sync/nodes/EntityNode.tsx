import { memo } from "react";
import { Handle, NodeProps, Position } from "reactflow";
import { Box } from "lucide-react";
import { cn } from "@/lib/utils";

interface EntityNodeData {
  name: string;
  label?: string;
  shortName?: string;
  originalName?: string;
  entityDefinitionId?: string;
  config?: Record<string, any>;
}

interface EntityNodeProps {
  data: EntityNodeData;
}

export const EntityNode = memo(({ data, selected, ...props }: NodeProps) => {
  console.log("EntityNode data:", data);

  return (
    <div className="w-6 h-6 mt-2">
      <div
        className={cn(
          "w-full h-full flex items-center justify-center bg-background/80 backdrop-blur-sm",
          "transition-colors duration-200 cursor-pointer",
          "hover:text-primary rounded-lg",
          selected ? "text-primary shadow-sm shadow-primary/20" : ""
        )}
      >
        <Handle
          type="target"
          position={Position.Left}
          className="w-1 h-1 ml-[1px] border border-background bg-muted-foreground"
        />
        <Box className="w-3 h-3 text-muted-foreground" />
        <Handle
          type="source"
          position={Position.Right}
          className="w-1 h-1 ml-[1px] border border-background bg-muted-foreground"
        />
      </div>
      <div className="absolute -bottom-3 left-1/2 -translate-x-1/2 whitespace-nowrap">
        <span className="text-[6px] text-foreground text-center">
          {data.label || data.name}
        </span>
      </div>
    </div>
  );
});

EntityNode.displayName = "EntityNode";
