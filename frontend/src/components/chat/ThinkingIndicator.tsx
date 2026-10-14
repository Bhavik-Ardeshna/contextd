/**
 * ThinkingIndicator - Animated indicator while processing
 * 
 * Shows a visually appealing loading state during AI generation.
 */
import { Sparkles } from 'lucide-react';

interface ThinkingIndicatorProps {
  contextSummary?: string;
}

export function ThinkingIndicator({ contextSummary }: ThinkingIndicatorProps) {
  return (
    <div className="flex gap-3">
      {/* Avatar */}
      <div className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center
                      bg-primary/20 text-primary animate-pulse">
        <Sparkles className="w-4 h-4" />
      </div>
      
      {/* Thinking content */}
      <div className="flex-1 max-w-[80%] rounded-2xl px-4 py-3 bg-muted/50 border border-border">
        <div className="flex items-center gap-2">
          <div className="flex gap-1">
            <span className="w-2 h-2 bg-primary rounded-full animate-bounce" 
                  style={{ animationDelay: '0ms' }} />
            <span className="w-2 h-2 bg-primary rounded-full animate-bounce" 
                  style={{ animationDelay: '150ms' }} />
            <span className="w-2 h-2 bg-primary rounded-full animate-bounce" 
                  style={{ animationDelay: '300ms' }} />
          </div>
          <span className="text-sm text-muted-foreground">
            {contextSummary || 'Analyzing your data...'}
          </span>
        </div>
      </div>
    </div>
  );
}

export default ThinkingIndicator;
