import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ExternalLink, Github } from "lucide-react";

interface ExampleProjectCardProps {
  id: number | string;
  title: string;
  description: string;
  tags?: string[];
  onClick?: () => void;
  icon?: React.ReactNode;
}

export const ExampleProjectCard = ({
  id,
  title,
  description,
  tags = [],
  onClick,
  icon = <Github className="h-5 w-5 text-primary" />
}: ExampleProjectCardProps) => {
  return (
    <div
      className="bg-card border border-border rounded-lg hover:border-border/60 transition-all overflow-hidden group cursor-pointer"
      onClick={onClick}
    >
      <div className="p-4">
        <div className="flex items-start gap-3">
          <div className="flex-shrink-0 mt-0.5">
            <div className="p-2 rounded-md bg-primary/5 group-hover:bg-primary/10 transition-all">
              {icon}
            </div>
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="font-medium text-sm group-hover:text-primary transition-colors line-clamp-1">{title}</h3>
            <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{description}</p>
            {tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {tags.map((tag, index) => (
                  <Badge
                    key={index}
                    variant="secondary"
                    className="text-xs px-2 py-0 h-5 bg-muted/50 text-muted-foreground hover:bg-muted/70 transition-colors"
                  >
                    {tag}
                  </Badge>
                ))}
              </div>
            )}
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 -mt-1 -mr-1 group-hover:bg-primary/10 group-hover:text-primary transition-all"
            onClick={(e) => {
              e.stopPropagation();
              onClick?.();
            }}
          >
            <ExternalLink className="h-3.5 w-3.5 text-muted-foreground" />
          </Button>
        </div>
      </div>
    </div>
  );
};

export default ExampleProjectCard;
