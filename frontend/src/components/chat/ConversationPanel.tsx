/**
 * ConversationPanel - Expandable chat conversation panel
 * 
 * Displays the chat messages with auto-scroll, streaming support,
 * and the ability to expand to fullscreen.
 */
import { useEffect, useRef, useState, useCallback } from 'react';
import { Maximize2, X, Trash2 } from 'lucide-react';
import { ChatMessage, ChatMessageType } from './ChatMessage';
import { ThinkingIndicator } from './ThinkingIndicator';

interface ConversationPanelProps {
  messages: ChatMessageType[];
  isStreaming?: boolean;
  streamingContent?: string;
  contextSummary?: string;
  onExpand?: () => void;
  onClose?: () => void;
  onClear?: () => void;
  maxHeight?: string;
}

export function ConversationPanel({
  messages,
  isStreaming = false,
  streamingContent = '',
  contextSummary,
  onExpand,
  onClose,
  onClear,
  maxHeight = '350px',
}: ConversationPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  
  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (scrollRef.current && isAtBottom) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, streamingContent, isAtBottom]);
  
  // Track scroll position to determine if user scrolled up
  const handleScroll = useCallback(() => {
    if (scrollRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
      const atBottom = scrollHeight - scrollTop - clientHeight < 50;
      setIsAtBottom(atBottom);
    }
  }, []);
  
  // Create a temporary streaming message for display
  const displayMessages = [...messages];
  if (isStreaming && streamingContent) {
    // Add streaming content as a temporary assistant message
    displayMessages.push({
      id: -1,
      role: 'assistant',
      content: streamingContent,
      created_at: new Date().toISOString(),
    });
  }
  
  if (messages.length === 0 && !isStreaming) {
    return null; // Don't show panel if no messages
  }
  
  return (
    <div className="flex flex-col bg-card/50 border border-border rounded-t-2xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-muted/30">
        <span className="text-sm font-medium text-foreground/80">Conversation</span>
        <div className="flex items-center gap-1">
          {onClear && messages.length > 0 && (
            <button
              onClick={onClear}
              className="p-1.5 rounded-lg text-muted-foreground hover:text-destructive 
                       hover:bg-destructive/10 transition-colors"
              title="Clear conversation"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          )}
          {onExpand && (
            <button
              onClick={onExpand}
              className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground 
                       hover:bg-muted transition-colors"
              title="Fullscreen"
            >
              <Maximize2 className="w-4 h-4" />
            </button>
          )}
          {onClose && (
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground 
                       hover:bg-muted transition-colors"
              title="Close"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
      
      {/* Messages */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto scrollbar-thin p-4 space-y-4"
        style={{ maxHeight }}
      >
        {displayMessages.map((message, idx) => (
          <ChatMessage
            key={message.id === -1 ? `streaming-${idx}` : message.id}
            message={message}
            isStreaming={message.id === -1}
          />
        ))}
        
        {/* Thinking indicator when waiting for first chunk */}
        {isStreaming && !streamingContent && (
          <ThinkingIndicator contextSummary={contextSummary} />
        )}
        
        {/* Scroll to bottom indicator */}
        {!isAtBottom && (
          <button
            onClick={() => {
              if (scrollRef.current) {
                scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
                setIsAtBottom(true);
              }
            }}
            className="absolute bottom-4 right-4 px-3 py-1.5 rounded-full
                     bg-primary/20 text-primary text-xs
                     hover:bg-primary/30 transition-colors"
          >
            ↓ New messages
          </button>
        )}
      </div>
    </div>
  );
}

export default ConversationPanel;
