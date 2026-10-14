/**
 * Dashboard - Knowledge Graph Chat as main interface
 * Premium UI with glassmorphism, glows, and dynamic gradients.
 */
import { useState, useEffect, useRef, Fragment } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Send, Loader2, Plus,
  Database, Network, X,
  Layers, ExternalLink, ChevronDown, ChevronUp,
  Zap, Settings, Globe, FileText, Blocks,
  Copy, Check, AlertCircle
} from 'lucide-react';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { ChatMessageType } from '@/components/chat/ChatMessage';
import { ThinkingIndicator } from '@/components/chat/ThinkingIndicator';
import { MentionDropdown, useMention } from '@/components/chat/MentionDropdown';
import { cn, normalizeChartPoint } from '@/lib/utils';
import { useCollectionsStore } from '@/lib/stores/collections';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  LineChart,
  Line,
  AreaChart,
  Area,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  RadialBarChart,
  RadialBar,
} from 'recharts';
import {
  graphChat,
  graphChatSearch,
  messageUsesSearchEndpoint,
  expandTraceNeighborhood,
  EntityReference,
  Subgraph,
  SubgraphNode,
  ContextMetadata,
  ChartSpec,
  NeighborhoodResponse,
  subgraphToJson,
  formatEntityType,
  extractSourceFromEntityType
} from '@/lib/graphChatApi';
import { getAppIconUrl } from '@/lib/utils/icons';
import { useTheme } from '@/lib/theme-provider';
import { useChatStore } from '@/lib/stores/chatStore';
import { motion, AnimatePresence } from 'framer-motion';
import { Suspense } from 'react';
import { ContextGraph } from '@/components/graph';

interface ChatHistoryItem {
  role: string;
  content: string;
}

const Dashboard = () => {
  const navigate = useNavigate();
  const { resolvedTheme } = useTheme();

  // Collections
  const { collections, fetchCollections } = useCollectionsStore();
  const defaultCollectionId = collections.length > 0 ? collections[0].readable_id : null;

  useEffect(() => {
    if (collections.length === 0) {
      fetchCollections();
    }
  }, [collections.length, fetchCollections]);

  // Chat store integration
  const chatStore = useChatStore();
  const dashboardChatIdRef = useRef<number | null>(null);

  // Chat state
  const [messages, setMessages] = useState<ChatMessageType[]>([]);
  const [conversationHistory, setConversationHistory] = useState<ChatHistoryItem[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [contextSummary, setContextSummary] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isFocused, setIsFocused] = useState(false);

  // Mention state
  const { isActive: mentionActive, filteredItems: mentionItems, handleMentionSelect } = useMention(input);
  const [mentionIndex, setMentionIndex] = useState(0);

  // Reset mention index when input changes
  useEffect(() => {
    setMentionIndex(0);
  }, [input]);

  // Context panel state
  const [showContextPanel, setShowContextPanel] = useState(false);
  const [currentSubgraph, setCurrentSubgraph] = useState<Subgraph | null>(null);
  const [currentReferences, setCurrentReferences] = useState<EntityReference[]>([]);
  const [currentMetadata, setCurrentMetadata] = useState<ContextMetadata | null>(null);
  const [selectedMessageId, setSelectedMessageId] = useState<number | null>(null);
  const [expandedRefs, setExpandedRefs] = useState<Set<number>>(new Set());

  const inputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const progressIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const progressStepIndexRef = useRef(0);

  const CHAT_PROGRESS_STEPS = [
    'Making research plan...',
    'Running database query...',
    'Analyzing the data...',
    'Generating charts...',
  ];

  // Custom markdown components for chat messages
  const markdownComponents = {
    h1: ({ children }: { children?: React.ReactNode }) => (
      <h1 className="text-lg font-bold text-foreground mt-4 mb-2 first:mt-0">{children}</h1>
    ),
    h2: ({ children }: { children?: React.ReactNode }) => (
      <h2 className="text-base font-semibold text-foreground mt-4 mb-2 first:mt-0">{children}</h2>
    ),
    h3: ({ children }: { children?: React.ReactNode }) => (
      <h3 className="text-sm font-semibold text-foreground mt-3 mb-1.5">{children}</h3>
    ),
    p: ({ children }: { children?: React.ReactNode }) => (
      <p className="text-foreground/90 my-2 leading-relaxed">{children}</p>
    ),
    ul: ({ children }: { children?: React.ReactNode }) => (
      <ul className="list-disc list-inside my-2 space-y-1 text-foreground/90">{children}</ul>
    ),
    ol: ({ children }: { children?: React.ReactNode }) => (
      <ol className="list-decimal list-inside my-2 space-y-1 text-foreground/90">{children}</ol>
    ),
    li: ({ children }: { children?: React.ReactNode }) => (
      <li className="text-foreground/90 leading-relaxed">{children}</li>
    ),
    code: ({ children, className }: { children?: React.ReactNode; className?: string }) => {
      const isCodeBlock = className?.startsWith('language-');
      if (isCodeBlock) {
        return <code className="text-sm font-mono text-foreground/90">{children}</code>;
      }
      return (
        <code className="bg-muted px-1.5 py-0.5 rounded text-sm font-mono text-primary">{children}</code>
      );
    },
    pre: ({ children }: { children?: React.ReactNode }) => (
      <pre className="bg-muted/50 rounded-lg p-3 my-3 overflow-x-auto border border-border/50">{children}</pre>
    ),
    a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
      <a href={href} target="_blank" rel="noopener noreferrer"
        className="text-primary hover:text-primary/80 underline underline-offset-2 transition-colors">{children}</a>
    ),
    strong: ({ children }: { children?: React.ReactNode }) => (
      <strong className="font-semibold text-foreground">{children}</strong>
    ),
    blockquote: ({ children }: { children?: React.ReactNode }) => (
      <blockquote className="border-l-4 border-primary/50 pl-4 my-3 text-foreground/80 italic">{children}</blockquote>
    ),
    table: ({ children }: { children?: React.ReactNode }) => (
      <div className="overflow-x-auto my-3">
        <table className="min-w-full text-sm border border-border/50 rounded-lg">{children}</table>
      </div>
    ),
    th: ({ children }: { children?: React.ReactNode }) => (
      <th className="px-3 py-2 text-left font-semibold text-foreground border-b border-border/50 bg-muted/30">{children}</th>
    ),
    td: ({ children }: { children?: React.ReactNode }) => (
      <td className="px-3 py-2 text-foreground/90 border-b border-border/50">{children}</td>
    ),
  };

  // Toggle expanded references for a message
  const toggleExpandRefs = (messageId: number) => {
    setExpandedRefs(prev => {
      const next = new Set(prev);
      if (next.has(messageId)) {
        next.delete(messageId);
      } else {
        next.add(messageId);
      }
      return next;
    });
  };

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, streamingContent]);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Clear progress interval on unmount
  useEffect(() => {
    return () => {
      if (progressIntervalRef.current) {
        clearInterval(progressIntervalRef.current);
        progressIntervalRef.current = null;
      }
    };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!input.trim() || isStreaming) return;

    if (!defaultCollectionId) {
      setError('No collection available. Please create a collection first.');
      return;
    }

    const userQuery = input;
    const requestStart = Date.now();
    setInput('');
    setIsStreaming(true);
    setStreamingContent('');
    progressStepIndexRef.current = 0;
    setContextSummary(CHAT_PROGRESS_STEPS[0]);
    if (progressIntervalRef.current) clearInterval(progressIntervalRef.current);
    progressIntervalRef.current = setInterval(() => {
      progressStepIndexRef.current = (progressStepIndexRef.current + 1) % CHAT_PROGRESS_STEPS.length;
      setContextSummary(CHAT_PROGRESS_STEPS[progressStepIndexRef.current]);
    }, 2500);
    setError(null);

    // Create chat in store on first message
    if (!dashboardChatIdRef.current) {
      const title = userQuery.slice(0, 50) + (userQuery.length > 50 ? '...' : '');
      dashboardChatIdRef.current = chatStore.createChat(title);
    }

    const userMessage: ChatMessageType = {
      id: Date.now(),
      role: 'user',
      content: userQuery,
      created_at: new Date().toISOString(),
    };
    setMessages(prev => [...prev, userMessage]);
    chatStore.addMessage(dashboardChatIdRef.current, userMessage);

    const newHistory = [...conversationHistory, { role: 'user', content: userQuery }];
    setConversationHistory(newHistory);

    try {
      const chatFn = messageUsesSearchEndpoint(userQuery) ? graphChatSearch : graphChat;
      const response = await chatFn(defaultCollectionId, {
        message: userQuery,
        history: newHistory.slice(-10),
        max_depth: 2,
        search_limit: 10,
        max_context_tokens: 4000,
        include_subgraph: true,
      });

      if (progressIntervalRef.current) {
        clearInterval(progressIntervalRef.current);
        progressIntervalRef.current = null;
      }
      setContextSummary('');

      const elapsedMs = Date.now() - requestStart;

      if (response.subgraph) {
        setCurrentSubgraph(response.subgraph);
      }
      setCurrentReferences(response.entity_references || []);
      setCurrentMetadata(response.context_metadata);

      const fullResponse = response.message;
      let charIndex = 0;

      const streamInterval = setInterval(() => {
        if (charIndex < fullResponse.length) {
          const charsToAdd = fullResponse.slice(charIndex, charIndex + 5);
          setStreamingContent(prev => prev + charsToAdd);
          charIndex += 5;
        } else {
          clearInterval(streamInterval);

          const assistantMessage: ChatMessageType = {
            id: Date.now() + 1,
            role: 'assistant',
            content: fullResponse,
            created_at: new Date().toISOString(),
            entity_references: response.entity_references,
            plot_images: response.plot_images,
            chart_specs: response.chart_specs,
            context_metadata: response.context_metadata,
            subgraph: response.subgraph,
            elapsed_ms: elapsedMs,
          };
          setMessages(prev => [...prev, assistantMessage]);
          setSelectedMessageId(assistantMessage.id);
          if (dashboardChatIdRef.current) {
            chatStore.addMessage(dashboardChatIdRef.current, assistantMessage);
          }

          setConversationHistory(prev => [...prev, { role: 'assistant', content: fullResponse }]);

          setStreamingContent('');
          setIsStreaming(false);
        }
      }, 10);

    } catch (err) {
      console.error('Chat error:', err);
      if (progressIntervalRef.current) {
        clearInterval(progressIntervalRef.current);
        progressIntervalRef.current = null;
      }
      setError(err instanceof Error ? err.message : 'Failed to send message');
      setStreamingContent('');
      setIsStreaming(false);
      setContextSummary('');
    }
  };

  const startNewChat = () => {
    dashboardChatIdRef.current = null;
    setMessages([]);
    setConversationHistory([]);
    setInput('');
    setCurrentSubgraph(null);
    setCurrentReferences([]);
    setCurrentMetadata(null);
    setSelectedMessageId(null);
    setError(null);
    inputRef.current?.focus();
  };

  const handleViewContext = (messageId: number) => {
    const message = messages.find(m => m.id === messageId);
    if (message) {
      setCurrentReferences(message.entity_references || []);
      // Cast: message.context_metadata carries the loose shape; the state prop wants ContextMetadata.
      setCurrentMetadata((message.context_metadata as ContextMetadata | undefined) || null);
      // Rehydrate the subgraph stored on the message so older messages open their own trace
      // instead of showing whatever subgraph the latest response produced.
      if (message.subgraph) {
        setCurrentSubgraph(message.subgraph as Subgraph);
      }
      setSelectedMessageId(messageId);
      setShowContextPanel(true);
    }
  };

  // Derive suggestions from connected collections so they reflect the user's actual data.
  // Falls back to generic starters when no collections are connected yet.
  const quickStarters = (() => {
    if (collections && collections.length > 0) {
      const mention = (c: { name: string; readable_id: string }) => {
        const base = (c.readable_id || c.name).split(/[\s-]+/)[0].toLowerCase();
        return base ? `@${base}` : '';
      };
      const starters: string[] = [];
      collections.slice(0, 2).forEach((c) => {
        const m = mention(c);
        if (m) {
          starters.push(`${m} what tables or entities are available?`);
          starters.push(`${m} summarize activity in the last 7 days`);
        }
      });
      if (starters.length < 4) {
        starters.push('Show me entity counts by type');
        starters.push('What changed yesterday?');
      }
      return starters.slice(0, 4);
    }
    return [
      'What tasks are in progress?',
      'Show me recent activity',
      'Summarize my projects',
      'Who is working on what?',
    ];
  })();

  // Show up to 4 connected collections as @mention chips in the empty state.
  const collectionChips = (collections || []).slice(0, 4).map((c) => {
    const base = (c.readable_id || c.name || '').split(/[\s-]+/)[0].toLowerCase();
    return {
      id: c.readable_id,
      label: c.name,
      mention: base ? `@${base}` : '',
    };
  });

  const renderSearchBar = () => (
    <form onSubmit={handleSubmit} className="relative group w-full text-left">
      <div
        className={cn(
          "relative rounded-2xl transition-all duration-300 shadow-lg border flex flex-col",
          "bg-card/90 backdrop-blur-xl border-border/60",
          isFocused ? "border-primary/40 shadow-xl shadow-primary/5 glow-chat-mode -translate-y-1" : "hover:border-border hover:shadow-xl",
          isFocused || input ? "bg-card" : ""
        )}
      >
        <div className="flex items-center gap-3 px-5 py-3.5">
          <div className="flex-shrink-0">
            {isStreaming ? (
              <Loader2 className="w-5 h-5 text-primary animate-spin" />
            ) : (
              <div className={cn("p-1.5 rounded-lg transition-colors duration-300", isFocused ? "bg-primary/10" : "bg-muted")}>
                <img
                  src="/navios.svg"
                  alt="ContextD"
                  className={cn(
                    "w-5 h-5 transition-all duration-300 object-contain",
                    isFocused || input ? "opacity-100 scale-110" : "opacity-60 grayscale hover:grayscale-0"
                  )}
                />
              </div>
            )}
          </div>

          {mentionActive && (
            <MentionDropdown
              items={mentionItems}
              selectedIndex={mentionIndex}
              onSelect={(item) => {
                const newValue = handleMentionSelect(item, input);
                setInput(newValue);
                inputRef.current?.focus();
              }}
              anchorEl={inputRef.current}
            />
          )}
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (mentionActive && mentionItems.length > 0) {
                if (e.key === 'ArrowDown') {
                  e.preventDefault();
                  setMentionIndex(prev => (prev + 1) % mentionItems.length);
                  return;
                } else if (e.key === 'ArrowUp') {
                  e.preventDefault();
                  setMentionIndex(prev => (prev - 1 + mentionItems.length) % mentionItems.length);
                  return;
                } else if (e.key === 'Enter') {
                  e.preventDefault();
                  const newValue = handleMentionSelect(mentionItems[mentionIndex], input);
                  setInput(newValue);
                  return;
                }
              }
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSubmit(e);
              }
            }}
            onFocus={() => setIsFocused(true)}
            onBlur={() => setIsFocused(false)}
            placeholder="Ask ContextD about your connected data..."
            disabled={isStreaming}
            className="flex-1 bg-transparent text-foreground placeholder-muted-foreground/70
                     outline-none text-base placeholder:font-light font-medium min-w-0"
          />

          <button
            type="submit"
            disabled={!input.trim() || isStreaming}
            className={cn(
              "flex items-center justify-center w-10 h-10 rounded-xl transition-all duration-300 flex-shrink-0",
              input.trim() && !isStreaming
                ? "bg-primary text-primary-foreground hover:bg-primary/90 shadow-md glow-purple transform active:scale-95"
                : "bg-muted text-muted-foreground/50 border border-transparent"
            )}
          >
            {isStreaming ? (
              <Loader2 className="w-4.5 h-4.5 animate-spin" />
            ) : (
              <Send className={cn("w-4.5 h-4.5", input.trim() ? "ml-1" : "")} />
            )}
          </button>
        </div>
        
        {/* Bottom row for Focus Tool */}
        <div className="flex items-center justify-between px-5 pb-3">
          <div className="flex items-center gap-2">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button type="button" className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors bg-muted/40 hover:bg-muted px-2.5 py-1.5 rounded-lg border border-border/40">
                  <Globe className="w-3.5 h-3.5" /> 
                  Focus 
                  <ChevronDown className="w-3 h-3 opacity-50 ml-0.5" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-[180px] z-[100] rounded-xl shadow-lg border-border/50">
                <DropdownMenuItem className="cursor-pointer gap-2 py-2">
                  <Globe className="w-4 h-4 text-muted-foreground"/> 
                  <div className="flex flex-col">
                    <span className="font-medium text-sm">All Data</span>
                    <span className="text-[10px] text-muted-foreground">Search entire graph</span>
                  </div>
                </DropdownMenuItem>
                <DropdownMenuItem className="cursor-pointer gap-2 py-2">
                  <FileText className="w-4 h-4 text-muted-foreground"/> 
                  <div className="flex flex-col">
                    <span className="font-medium text-sm">Documentation</span>
                    <span className="text-[10px] text-muted-foreground">Focus on docs</span>
                  </div>
                </DropdownMenuItem>
                <DropdownMenuItem className="cursor-pointer gap-2 py-2">
                  <Blocks className="w-4 h-4 text-muted-foreground"/> 
                  <div className="flex flex-col">
                    <span className="font-medium text-sm">Tickets</span>
                    <span className="text-[10px] text-muted-foreground">Focus on Jira/Linear</span>
                  </div>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </div>

      <div className="absolute -bottom-6 left-0 right-0 flex justify-center opacity-0 group-hover:opacity-100 transition-opacity">
        <p className="text-[10px] font-medium text-muted-foreground bg-background/80 px-2 py-0.5 rounded-full backdrop-blur-sm border border-border/50">
          Press <kbd className="px-1 py-0.5 rounded bg-muted/80 font-mono text-[9px] text-foreground">Enter</kbd> to send
        </p>
      </div>
    </form>
  );

  return (
    <div className="h-screen flex text-foreground transition-colors duration-200 w-full bg-background">
      {/* Main Chat Area */}
      <div className={cn(
        "flex-1 flex flex-col overflow-hidden transition-all duration-300 relative",
        showContextPanel ? "mr-0" : ""
      )}>
        {/* Floating "New chat" button (only when there is an active conversation) */}
        {messages.length > 0 && (
          <button
            onClick={startNewChat}
            className="absolute top-4 right-4 z-20 flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border/60
                     bg-background/80 backdrop-blur-sm text-muted-foreground hover:text-foreground hover:bg-muted/50
                     transition-colors text-sm shadow-sm"
          >
            <Plus className="w-3.5 h-3.5" />
            New chat
          </button>
        )}

        {/* Messages area */}
        <div className="flex-1 overflow-y-auto scrollbar-thin px-4 sm:px-8 pt-8 pb-32 space-y-8"
          ref={scrollRef}
        >
          {messages.length === 0 && !isStreaming ? (
            // Empty state — tighter layout, personalized to connected collections
            <div className="flex flex-col items-center text-center px-4 w-full max-w-2xl mx-auto pt-[12vh]">
              <div className="w-12 h-12 rounded-2xl bg-primary/10 flex items-center justify-center mb-5">
                <img src="/navios.svg" alt="ContextD" className="w-7 h-7 object-contain" />
              </div>
              <h3 className="text-2xl font-semibold tracking-tight text-foreground mb-1.5">
                What do you want to know?
              </h3>
              <p className="text-sm text-muted-foreground mb-6">
                {collectionChips.length > 0
                  ? 'Type a question or start with a suggestion below.'
                  : 'Connect a source to start asking questions about your data.'}
              </p>

              {/* Search bar */}
              <AnimatePresence>
                {messages.length === 0 && !isStreaming && (
                  <motion.div layoutId="search-bar-wrapper" className="w-full relative z-20 mb-5">
                    {renderSearchBar()}
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Connected source chips — click to prepend @mention */}
              {collectionChips.length > 0 && (
                <div className="flex flex-wrap items-center justify-center gap-2 mb-6">
                  <span className="text-xs text-muted-foreground mr-1">Connected:</span>
                  {collectionChips.map((chip) => (
                    <button
                      key={chip.id}
                      type="button"
                      onClick={() => setInput((prev) => (prev ? `${chip.mention} ${prev}` : `${chip.mention} `))}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs
                               border border-border/60 bg-muted/30 hover:bg-muted hover:border-border
                               text-muted-foreground hover:text-foreground transition-colors"
                      title={`Insert ${chip.mention} into the prompt`}
                    >
                      <span className="font-mono">{chip.mention}</span>
                      <span className="text-muted-foreground/70">·</span>
                      <span>{chip.label}</span>
                    </button>
                  ))}
                </div>
              )}

              {/* Quick starters — derived from connected collections */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full">
                {quickStarters.map((example, idx) => (
                  <button
                    key={idx}
                    onClick={() => setInput(example)}
                    className="text-left px-4 py-3 rounded-xl border border-border/60 bg-card
                             hover:border-border hover:bg-muted/40 transition-colors
                             text-sm text-muted-foreground hover:text-foreground"
                  >
                    <span className="flex items-center gap-2.5">
                      <Zap className="w-3.5 h-3.5 flex-shrink-0 text-primary/70" />
                      <span className="truncate">{example}</span>
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {/* Max width container for messages */}
              <div className="max-w-4xl mx-auto space-y-8">
                {messages
                  .filter((msg) => msg.role === 'user' || msg.role === 'assistant')
                  .map((message) => {
                    const isUser = message.role === 'user';
                    const refs = message.entity_references || [];
                    const isExpanded = expandedRefs.has(message.id);
                    const displayRefs = isExpanded ? refs : refs.slice(0, 4);
                    const hasMoreRefs = refs.length > 4;

                    return (
                      <div key={message.id} className={`flex gap-4 ${isUser ? 'flex-row-reverse' : ''} animate-in fade-in slide-in-from-bottom-4 duration-300`}>
                        {/* Avatar */}
                        <div className={cn(
                          "flex-shrink-0 w-10 h-10 rounded-xl flex items-center justify-center shadow-sm border",
                          isUser
                            ? "bg-gradient-to-br from-primary to-primary/80 border-primary shadow-primary/20 glow-purple"
                            : "bg-card border-border/50"
                        )}>
                          {isUser ? (
                            <span className="text-sm font-bold text-primary-foreground">U</span>
                          ) : (
                            <img
                              src="/navios.svg"
                              alt="ContextD"
                              className="w-6 h-6 object-contain"
                            />
                          )}
                        </div>

                        {/* Message content */}
                        <div className={cn(
                          "flex-1 max-w-[85%] rounded-[1.5rem] px-6 py-4 shadow-sm",
                          isUser
                            ? "bg-primary/5 border border-primary/20 rounded-tr-sm"
                            : "bg-card/80 backdrop-blur-md border border-border/40 rounded-tl-sm shadow-md"
                        )}>
                          <div className={cn("text-[15px] leading-relaxed", isUser ? "text-foreground" : "")}>
                            {isUser ? (
                              <p className="font-medium text-foreground">{message.content}</p>
                            ) : (
                              <>
                                <div className="prose prose-sm md:prose-base prose-neutral dark:prose-invert max-w-none prose-p:leading-relaxed prose-pre:bg-muted/50 prose-pre:border prose-pre:border-border/50">
                                  <ReactMarkdown
                                    remarkPlugins={[remarkGfm]}
                                    components={markdownComponents}
                                  >
                                    {message.content}
                                  </ReactMarkdown>
                                </div>
                                {/* Charts */}
                                {message.chart_specs && message.chart_specs.length > 0 && (
                                  <div className="mt-6 space-y-6">
                                    {message.chart_specs.map((chart: ChartSpec, idx: number) => {
                                      const rawData = chart.data || [];
                                      const isScatter = chart.chart_type === 'scatter';
                                      let data: any[] = isScatter
                                        ? rawData.map((d: Record<string, unknown>) => ({
                                          x: Number((d.x ?? d.name ?? d.label ?? 0) as number),
                                          y: Number((d.y ?? d.value ?? 0) as number),
                                        })).filter((d) => !Number.isNaN(d.x) && !Number.isNaN(d.y))
                                        : rawData.map((d: Record<string, unknown>, i: number) => normalizeChartPoint(d, i)).filter((d) => d.name !== '' || d.value !== 0);
                                      if (chart.chart_type === 'line' || chart.chart_type === 'area') {
                                        data = [...data].sort((a, b) => {
                                          const an = (a as { name: string }).name;
                                          const bn = (b as { name: string }).name;
                                          const anum = Number(an);
                                          const bnum = Number(bn);
                                          if (!Number.isNaN(anum) && !Number.isNaN(bnum)) return anum - bnum;
                                          return String(an).localeCompare(String(bn));
                                        });
                                      }
                                      if (data.length === 0) return null;
                                      const colors = ['#8b5cf6', '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#94a3b8']; // Updated colors to match theme
                                      const yName = chart.config?.yAxis ?? (chart.chart_type === 'histogram' ? 'Count' : 'Value');
                                      const xName = chart.config?.xAxis ?? 'Category';
                                      const margin = { top: 5, right: 5, left: 5, bottom: 5 };
                                      const chartTooltip = ({ active, payload, label }: { active?: boolean; payload?: Array<{ value?: number; payload?: Record<string, unknown> }>; label?: string }) => {
                                        if (!active || !payload?.length) return null;
                                        const p = payload[0]?.payload as Record<string, unknown> | undefined;
                                        const x = p?.name ?? label ?? '';
                                        const y = payload[0]?.value;
                                        return (
                                          <div className="rounded-xl border border-border/50 bg-card/95 backdrop-blur-xl px-4 py-3 text-sm shadow-xl shadow-black/5">
                                            <div className="font-semibold text-foreground mb-1">{xName}: {String(x)}</div>
                                            <div className="text-muted-foreground flex items-center gap-2">
                                              <div className="w-2 h-2 rounded-full bg-primary"></div>
                                              {yName}: <span className="font-medium text-foreground">{y != null ? String(y) : '—'}</span>
                                            </div>
                                          </div>
                                        );
                                      };
                                      const scatterTooltip = ({ active, payload }: { active?: boolean; payload?: Array<{ payload?: { x?: number; y?: number } }> }) => {
                                        if (!active || !payload?.length) return null;
                                        const p = payload[0]?.payload;
                                        const x = p?.x ?? '—';
                                        const y = p?.y ?? '—';
                                        return (
                                          <div className="rounded-xl border border-border/50 bg-card/95 backdrop-blur-xl px-4 py-3 text-sm shadow-xl shadow-black/5">
                                            <div className="font-semibold text-foreground mb-1">{chart.config?.xAxis ?? 'X'}: {String(x)}</div>
                                            <div className="text-muted-foreground flex items-center gap-2">
                                              <div className="w-2 h-2 rounded-full bg-primary"></div>
                                              {yName}: <span className="font-medium text-foreground">{String(y)}</span>
                                            </div>
                                          </div>
                                        );
                                      };
                                      return (
                                        <figure key={idx} className="rounded-2xl border border-border/40 overflow-hidden bg-card/40 backdrop-blur-md p-5 shadow-sm">
                                          {chart.title && (
                                            <figcaption className="text-sm font-semibold text-foreground mb-4">{chart.title}</figcaption>
                                          )}
                                          <ResponsiveContainer width="100%" height={300}>
                                            {chart.chart_type === 'pie' ? (
                                              <PieChart>
                                                <Pie data={data} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={90} innerRadius={60}
                                                  paddingAngle={5} cornerRadius={4} stroke="none"
                                                  label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}>
                                                  {data.map((_, i) => <Cell key={i} fill={colors[i % colors.length]} />)}
                                                </Pie>
                                                <Tooltip content={chartTooltip} />
                                              </PieChart>
                                            ) : chart.chart_type === 'line' ? (
                                              <LineChart data={data} margin={margin}>
                                                <CartesianGrid strokeDasharray="3 3" vertical={false} className="stroke-muted" />
                                                <XAxis dataKey="name" tick={{ fontSize: 12 }} axisLine={false} tickLine={false} />
                                                <YAxis tick={{ fontSize: 12 }} axisLine={false} tickLine={false} />
                                                <Tooltip content={chartTooltip} />
                                                <Legend wrapperStyle={{ paddingTop: '20px' }} iconType="circle" />
                                                <Line type="monotone" dataKey="value" stroke="#8b5cf6" strokeWidth={3} dot={{ r: 4, strokeWidth: 2 }} activeDot={{ r: 6, strokeWidth: 0 }} name={yName} />
                                              </LineChart>
                                            ) : chart.chart_type === 'area' ? (
                                              <AreaChart data={data} margin={margin}>
                                                <defs>
                                                  <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                                                    <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.3} />
                                                    <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0} />
                                                  </linearGradient>
                                                </defs>
                                                <CartesianGrid strokeDasharray="3 3" vertical={false} className="stroke-muted" />
                                                <XAxis dataKey="name" tick={{ fontSize: 12 }} axisLine={false} tickLine={false} />
                                                <YAxis tick={{ fontSize: 12 }} axisLine={false} tickLine={false} />
                                                <Tooltip content={chartTooltip} />
                                                <Legend wrapperStyle={{ paddingTop: '20px' }} iconType="circle" />
                                                <Area type="monotone" dataKey="value" stroke="#8b5cf6" strokeWidth={3} fill="url(#colorValue)" name={yName} />
                                              </AreaChart>
                                            ) : chart.chart_type === 'scatter' ? (
                                              <ScatterChart margin={margin}>
                                                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                                                <XAxis dataKey="x" type="number" name={chart.config?.xAxis ?? 'X'} tick={{ fontSize: 12 }} axisLine={false} tickLine={false} />
                                                <YAxis dataKey="y" type="number" name={chart.config?.yAxis ?? 'Y'} tick={{ fontSize: 12 }} axisLine={false} tickLine={false} />
                                                <Tooltip content={scatterTooltip} cursor={{ strokeDasharray: '3 3', stroke: '#8b5cf6', strokeOpacity: 0.5 }} />
                                                <Scatter name={chart.title || 'Data'} data={data} fill="#8b5cf6" />
                                              </ScatterChart>
                                            ) : chart.chart_type === 'radar' ? (
                                              <RadarChart data={data} margin={margin}>
                                                <PolarGrid stroke="#e2e8f0" />
                                                <PolarAngleAxis dataKey="name" tick={{ fontSize: 11, fill: '#64748b' }} />
                                                <PolarRadiusAxis angle={30} tick={{ fontSize: 10 }} />
                                                <Radar name={yName} dataKey="value" stroke="#8b5cf6" strokeWidth={2} fill="#8b5cf6" fillOpacity={0.3} />
                                                <Tooltip content={chartTooltip} />
                                                <Legend />
                                              </RadarChart>
                                            ) : chart.chart_type === 'radialBar' ? (
                                              <RadialBarChart data={data} margin={margin} innerRadius="30%" outerRadius="100%">
                                                <RadialBar dataKey="value" background fill="#8b5cf6" cornerRadius={10} />
                                                <Legend iconType="circle" layout="vertical" verticalAlign="middle" align="right" />
                                                <Tooltip content={chartTooltip} />
                                              </RadialBarChart>
                                            ) : (
                                              <BarChart data={data} margin={margin}>
                                                <CartesianGrid strokeDasharray="3 3" vertical={false} className="stroke-muted" />
                                                <XAxis dataKey="name" tick={{ fontSize: 12 }} axisLine={false} tickLine={false} />
                                                <YAxis tick={{ fontSize: 12 }} axisLine={false} tickLine={false} />
                                                <Tooltip content={chartTooltip} cursor={{ fill: 'transparent' }} />
                                                <Legend wrapperStyle={{ paddingTop: '20px' }} iconType="circle" />
                                                <Bar dataKey="value" fill="#8b5cf6" name={yName} radius={[6, 6, 0, 0]} />
                                              </BarChart>
                                            )}
                                          </ResponsiveContainer>
                                        </figure>
                                      );
                                    })}
                                  </div>
                                )}
                              </>
                            )}
                          </div>

                          {/* Decision Trace tile + Entity references */}
                          {!isUser && (refs.length > 0 || message.context_metadata) && (
                            <div className="mt-5 pt-4 border-t border-border/40 space-y-3">
                              {/* Decision Trace button — opens the side panel */}
                              <div className="inline-flex items-center gap-2 flex-wrap">
                                <button
                                  type="button"
                                  onClick={() => handleViewContext(message.id)}
                                  className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg
                                           border border-border/60 bg-card hover:border-primary/40
                                           hover:bg-primary/5 text-sm font-medium text-foreground
                                           transition-colors"
                                >
                                  <Network className="w-3.5 h-3.5 text-primary" />
                                  Decision Trace
                                  <ChevronDown className="w-3.5 h-3.5 text-muted-foreground -rotate-90" />
                                </button>
                                {typeof message.elapsed_ms === 'number' && (
                                  <span
                                    className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-muted/50 text-[11px] text-muted-foreground font-mono tabular-nums"
                                    title="Total response time from request to render"
                                  >
                                    <svg
                                      viewBox="0 0 24 24"
                                      fill="none"
                                      stroke="currentColor"
                                      strokeWidth="2"
                                      strokeLinecap="round"
                                      strokeLinejoin="round"
                                      className="w-3 h-3"
                                      aria-hidden="true"
                                    >
                                      <circle cx="12" cy="12" r="9" />
                                      <polyline points="12 7 12 12 15 14" />
                                    </svg>
                                    {formatElapsed(message.elapsed_ms)}
                                  </span>
                                )}
                              </div>
                              {refs.length > 0 && (
                                <div className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-muted-foreground pt-1">
                                  <Database className="w-3.5 h-3.5" />
                                  {refs.length} Sources
                                </div>
                              )}

                              {refs.length > 0 && (
                              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                                {displayRefs.map((ref) => {
                                  const sourceIcon = extractSourceFromEntityType(ref.entity_type);
                                  return (
                                    <a
                                      key={ref.entity_id}
                                      href={ref.url || '#'}
                                      target={ref.url ? '_blank' : undefined}
                                      rel="noopener noreferrer"
                                      className="flex items-center gap-3 px-3.5 py-2.5 rounded-xl bg-muted/40 
                                               hover:bg-muted/80 hover:shadow-sm border border-transparent hover:border-border/50 transition-all duration-200 group"
                                    >
                                      <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-card border border-border/50 shadow-sm flex items-center justify-center">
                                        {sourceIcon ? (
                                          <img
                                            src={getAppIconUrl(sourceIcon, resolvedTheme)}
                                            alt={sourceIcon}
                                            className="w-4.5 h-4.5 object-contain"
                                            onError={(e) => {
                                              e.currentTarget.style.display = 'none';
                                            }}
                                          />
                                        ) : (
                                          <Database className="w-4 h-4 text-muted-foreground" />
                                        )}
                                      </div>
                                      <div className="flex-1 min-w-0">
                                        <span className="text-sm font-medium text-foreground truncate block group-hover:text-primary transition-colors">
                                          {ref.name}
                                        </span>
                                        <span className="text-[11px] font-medium text-muted-foreground/80 mt-0.5 block truncate">
                                          {formatEntityType(ref.entity_type)}
                                        </span>
                                      </div>
                                      {ref.url && (
                                        <div className="w-6 h-6 rounded-full bg-background border border-border/50 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-all transform scale-90 group-hover:scale-100">
                                          <ExternalLink className="w-3 h-3 text-muted-foreground" />
                                        </div>
                                      )}
                                    </a>
                                  );
                                })}
                              </div>
                              )}

                              {hasMoreRefs && (
                                <button
                                  onClick={() => toggleExpandRefs(message.id)}
                                  className="mx-auto w-full max-w-[200px] flex items-center justify-center gap-1.5 mt-3 px-3 py-1.5 rounded-lg text-xs font-medium text-muted-foreground bg-muted/30 hover:bg-muted/60 hover:text-foreground transition-all"
                                >
                                  {isExpanded ? (
                                    <>
                                      <ChevronUp className="w-3.5 h-3.5" />
                                      Show less references
                                    </>
                                  ) : (
                                    <>
                                      <ChevronDown className="w-3.5 h-3.5" />
                                      Show {refs.length - 4} more
                                    </>
                                  )}
                                </button>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}

                {/* Streaming response */}
                {isStreaming && streamingContent && (
                  <div className="flex gap-4 animate-in fade-in slide-in-from-bottom-4 duration-300">
                    <div className="flex-shrink-0 w-10 h-10 rounded-xl bg-card border border-border/50 shadow-sm flex items-center justify-center">
                      <img
                        src="/navios.svg"
                        alt="ContextD"
                        className="w-6 h-6 object-contain"
                      />
                    </div>
                    <div className="flex-1 max-w-[85%] rounded-[1.5rem] px-6 py-4 bg-card/80 backdrop-blur-md border border-border/40 shadow-md">
                      <div className="text-[15px] leading-relaxed prose prose-sm md:prose-base prose-neutral dark:prose-invert max-w-none">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          components={markdownComponents}
                        >
                          {streamingContent}
                        </ReactMarkdown>
                        <span className="inline-block w-2.5 h-4 bg-primary rounded-sm animate-pulse ml-1 align-baseline" />
                      </div>
                    </div>
                  </div>
                )}

                {/* Thinking indicator */}
                {isStreaming && !streamingContent && (
                  <div className="animate-in fade-in slide-in-from-bottom-4 duration-300">
                    <ThinkingIndicator contextSummary={contextSummary} />
                  </div>
                )}
              </div>
            </>
          )}

          {/* Error message */}
          {error && (
            <div className="flex justify-center mt-4">
              <div className="px-5 py-3 rounded-xl bg-status-error/10 border border-status-error/20 text-status-error text-sm font-medium flex items-center gap-2 shadow-sm">
                <X className="w-4 h-4" />
                {error}
              </div>
            </div>
          )}
        </div>

        {/* Floating Input Area (Docked at Bottom) */}
        <div className="absolute bottom-0 left-0 right-0 p-6 pointer-events-none z-20">
          <div className="max-w-4xl mx-auto pointer-events-auto relative">
            {/* Background gradient blur to make input stand out against scrolling messages */}
            <div className={cn(
              "absolute -inset-10 bg-gradient-to-t from-background via-background/90 to-transparent -z-10 pointer-events-none transition-opacity duration-700",
              messages.length === 0 && !isStreaming ? "opacity-0" : "opacity-100"
            )} />

            <AnimatePresence>
              {(messages.length > 0 || isStreaming) && (
                <motion.div 
                  layoutId="search-bar-wrapper"
                  className="w-full relative"
                >
                  {renderSearchBar()}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>



      {/* Glassmorphic Context Sidebar */}
      {showContextPanel && (
        <div className="w-[400px] bg-card/80 backdrop-blur-xl border-l border-border/40 flex flex-col shrink-0 z-10 shadow-[-10px_0_30px_-15px_rgba(0,0,0,0.1)]">
          <div className="flex items-center justify-between px-6 py-5 border-b border-border/40 bg-background/40">
            <h3 className="font-semibold tracking-tight text-foreground flex items-center gap-2.5 text-base">
              <div className="p-1.5 rounded-md bg-primary/10 text-primary">
                <Network className="w-4.5 h-4.5" />
              </div>
              Decision Trace
            </h3>
            <button
              onClick={() => setShowContextPanel(false)}
              className="p-2 rounded-xl border border-border/50 hover:bg-muted hover:border-border text-muted-foreground hover:text-foreground transition-all shadow-sm"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto scrollbar-thin">
            {/* Knowledge Graph Visualization */}
            {currentSubgraph && (
              <div className="p-6 border-b border-border/40 bg-gradient-to-b from-card to-background">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-4">
                  Visual Structure
                </h4>
                <div className="rounded-2xl border border-border/50 shadow-sm overflow-hidden bg-card/50">
                  <Suspense fallback={
                    <div className="h-[240px] flex items-center justify-center bg-muted/20">
                      <Loader2 className="w-6 h-6 animate-spin text-primary/50" />
                    </div>
                  }>
                    <ContextGraph
                      subgraphJson={subgraphToJson(currentSubgraph)}
                      height="240px"
                    />
                  </Suspense>
                </div>
              </div>
            )}

            <div className="p-6 space-y-6 bg-background/30 h-full">
              {/* Path used */}
              {currentMetadata?.path_used && (
                <div>
                  <h4 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                    Execution Path
                  </h4>
                  <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-primary/10 text-primary text-xs font-medium">
                    <Network className="w-3.5 h-3.5" />
                    {currentMetadata.path_used === 'glm_non_deterministic'
                      ? 'GLM agents (R → A → Executor)'
                      : currentMetadata.path_used === 'glm_deterministic'
                      ? 'GLM deterministic (seed + PPR/MST)'
                      : 'Graph search only'}
                  </div>
                  {currentMetadata.collection_name && (
                    <div className="mt-2 text-xs text-muted-foreground">
                      Scoped to{' '}
                      <span className="font-mono text-foreground">
                        {currentMetadata.collection_name}
                      </span>
                      {currentMetadata.source_types && currentMetadata.source_types.length > 0 && (
                        <>
                          {' · '}
                          <span>
                            {currentMetadata.source_types.join(', ')}
                          </span>
                        </>
                      )}
                    </div>
                  )}
                  {currentMetadata.mention_unresolved && (
                    <div className="mt-2 text-xs text-amber-600 dark:text-amber-400">
                      @{currentMetadata.mention_unresolved} didn't match a collection — using current
                    </div>
                  )}
                </div>
              )}

              {/* Summary metrics */}
              {currentMetadata && (
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Summary
                    </h4>
                    {(() => {
                      const elapsedMs =
                        (selectedMessageId != null
                          ? messages.find((m) => m.id === selectedMessageId)?.elapsed_ms
                          : undefined) ??
                        (typeof currentMetadata?.elapsed_ms === 'number'
                          ? (currentMetadata.elapsed_ms as number)
                          : undefined);
                      if (typeof elapsedMs !== 'number') return null;
                      return (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary/10 text-primary text-[10px] font-mono tabular-nums">
                          <svg
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            className="w-3 h-3"
                          >
                            <circle cx="12" cy="12" r="9" />
                            <polyline points="12 7 12 12 15 14" />
                          </svg>
                          {formatElapsed(elapsedMs)}
                        </span>
                      );
                    })()}
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <SummaryStat
                      label="Queries"
                      value={currentMetadata.queries?.length ?? 0}
                      highlighted
                    />
                    <SummaryStat
                      label="Result rows"
                      value={currentMetadata.total_rows ?? 0}
                    />
                    <SummaryStat
                      label="Sources"
                      value={
                        currentMetadata.source_types && currentMetadata.source_types.length > 0
                          ? currentMetadata.source_types.length
                          : currentReferences.length
                      }
                      tooltip={
                        currentMetadata.source_types && currentMetadata.source_types.length > 0
                          ? currentMetadata.source_types.join(', ')
                          : undefined
                      }
                    />
                    <SummaryStat
                      label="Nodes"
                      value={
                        // Prefer the live subgraph size (always matches the visible node list
                        // below); fall back to backend metadata for legacy responses.
                        currentSubgraph?.nodes.length ?? currentMetadata.node_count ?? 0
                      }
                    />
                  </div>
                  {(currentSubgraph?.nodes.length ?? currentMetadata.node_count ?? 0) === 0 &&
                    (currentMetadata.queries?.length ?? 0) > 0 && (
                      <p className="mt-2 text-[11px] text-muted-foreground leading-relaxed">
                        Aggregate query — answer comes from {currentMetadata.total_rows ?? 0}{' '}
                        result row{(currentMetadata.total_rows ?? 0) === 1 ? '' : 's'} below,
                        not graph nodes.
                      </p>
                    )}
                </div>
              )}

              {/* Queries executed */}
              {currentMetadata?.queries && currentMetadata.queries.length > 0 && (
                <div>
                  <h4 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                    Queries Executed ({currentMetadata.queries.length})
                  </h4>
                  <div className="space-y-2">
                    {currentMetadata.queries.map((q, i) => (
                      <QueryItem
                        key={i}
                        index={i + 1}
                        cypher={q.cypher}
                        rowCount={q.row_count}
                        error={q.error || null}
                      />
                    ))}
                  </div>
                </div>
              )}

              {/* Referenced Nodes — linked entities (from search / entity_references) */}
              {currentReferences.length > 0 && (
                <div>
                  <h4 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                    Referenced Nodes ({currentReferences.length})
                  </h4>
                  <div className="space-y-2">
                    {currentReferences.map((ref) => (
                      <NodeReferenceItem
                        key={ref.entity_id}
                        ref_={ref}
                        theme={resolvedTheme}
                      />
                    ))}
                  </div>
                </div>
              )}

              {/* Graph Nodes — every node in the subgraph, expandable with full lineage */}
              {currentSubgraph && currentSubgraph.nodes.length > 0 && (() => {
                const graphNodes = currentSubgraph.nodes;
                // Extract the underlying table node_type from the first Cypher query (if any)
                // so aggregate rows can expand into a real 2-hop neighborhood on demand.
                const firstCypher = currentMetadata?.queries?.[0]?.cypher || '';
                const underlyingTypeMatch = firstCypher.match(/node_type\s*=\s*['"]([^'"]+)['"]/);
                const underlyingNodeType = underlyingTypeMatch ? underlyingTypeMatch[1] : null;
                const expansionCollectionId =
                  currentMetadata?.collection_id || defaultCollectionId || '';
                const typeCounts = graphNodes.reduce<Record<string, number>>((acc, n) => {
                  const t = n.entity_type || 'Unknown';
                  acc[t] = (acc[t] || 0) + 1;
                  return acc;
                }, {});
                const typeBreakdown = Object.entries(typeCounts)
                  .sort((a, b) => b[1] - a[1])
                  .slice(0, 6);
                // Find the maximum numeric value across first-numeric-property of each node
                // (used to size proportional bars inside each card).
                let maxNumeric = 0;
                for (const n of graphNodes) {
                  const p = n.properties || {};
                  for (const v of Object.values(p)) {
                    if (typeof v === 'number' && Number.isFinite(v) && v > maxNumeric) {
                      maxNumeric = v;
                      break;
                    }
                  }
                }
                return (
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                        Graph Nodes ({graphNodes.length})
                      </h4>
                      {currentSubgraph.edges.length > 0 && (
                        <span className="text-[10px] text-muted-foreground">
                          {currentSubgraph.edges.length} edge
                          {currentSubgraph.edges.length === 1 ? '' : 's'}
                        </span>
                      )}
                    </div>

                    {/* Type breakdown — quick taxonomy overview */}
                    {typeBreakdown.length > 1 && (
                      <div className="mb-3 flex flex-wrap gap-1.5">
                        {typeBreakdown.map(([t, n]) => {
                          const c = typeColor(t);
                          return (
                            <span
                              key={t}
                              className={cn(
                                'inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-[10px] font-medium',
                                c.bg,
                                c.fg
                              )}
                            >
                              <span className="font-mono tabular-nums">{n}</span>
                              <span className="truncate max-w-[120px]">
                                {formatEntityType(t)}
                              </span>
                            </span>
                          );
                        })}
                      </div>
                    )}

                    <div className="space-y-2">
                      {graphNodes.map((node, i) => (
                        <GraphNodeItem
                          key={node.id}
                          node={node}
                          subgraph={currentSubgraph}
                          theme={resolvedTheme}
                          index={i}
                          maxNumeric={maxNumeric}
                          collectionId={expansionCollectionId}
                          underlyingNodeType={underlyingNodeType}
                        />
                      ))}
                    </div>
                  </div>
                );
              })()}

              {/* Empty state — only when truly nothing to show */}
              {!currentSubgraph &&
                currentReferences.length === 0 &&
                (!currentMetadata ||
                  (!currentMetadata.queries?.length &&
                    !currentMetadata.node_count &&
                    !currentMetadata.edge_count &&
                    !currentMetadata.search_result_count)) && (
                  <div className="text-center py-16 text-muted-foreground">
                    <div className="w-16 h-16 rounded-2xl bg-muted/50 border border-border/50 flex items-center justify-center mx-auto mb-4">
                      <Database className="w-8 h-8 opacity-30" />
                    </div>
                    <p className="text-sm font-medium">No trace available yet</p>
                    <p className="text-xs mt-1 opacity-70">
                      Start a conversation to see the decision trace
                    </p>
                  </div>
                )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Dashboard;

// ---------- Sidebar helpers ----------

function SummaryStat({
  label,
  value,
  highlighted = false,
  tooltip,
}: {
  label: string;
  value: number;
  highlighted?: boolean;
  tooltip?: string;
}) {
  return (
    <div
      className="px-3 py-2.5 rounded-xl bg-card border border-border/60"
      title={tooltip}
    >
      <div className={cn('text-xl font-semibold tracking-tight', highlighted ? 'text-primary' : 'text-foreground')}>
        {value}
      </div>
      <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground mt-0.5">
        {label}
      </div>
      {tooltip && (
        <div className="mt-0.5 text-[10px] text-muted-foreground/80 truncate">{tooltip}</div>
      )}
    </div>
  );
}

function NodeReferenceItem({
  ref_,
  theme,
}: {
  ref_: EntityReference;
  theme: 'light' | 'dark';
}) {
  const [open, setOpen] = useState(false);
  const sourceIcon = extractSourceFromEntityType(ref_.entity_type);
  const props = ref_.properties || {};
  const propEntries = Object.entries(props).filter(
    ([k, v]) => v !== null && v !== undefined && v !== '' && !k.startsWith('_')
  );

  return (
    <div className="rounded-xl border border-border/60 bg-card overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-muted/40 transition-colors"
      >
        <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-muted/50 border border-border flex items-center justify-center">
          {sourceIcon ? (
            <img
              src={getAppIconUrl(sourceIcon, theme)}
              alt={sourceIcon}
              className="w-4.5 h-4.5 object-contain"
              onError={(e) => {
                e.currentTarget.style.display = 'none';
              }}
            />
          ) : (
            <Database className="w-4 h-4 text-muted-foreground" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-foreground truncate">
              {ref_.name || ref_.node_id}
            </span>
            {ref_.score != null && (
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-primary/10 text-primary flex-shrink-0">
                {ref_.score.toFixed(2)}
              </span>
            )}
          </div>
          <div className="text-[10px] font-medium text-muted-foreground/80 mt-0.5 truncate uppercase tracking-wide">
            {formatEntityType(ref_.entity_type)}
          </div>
        </div>
        {ref_.url && (
          <a
            href={ref_.url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="w-6 h-6 rounded-md hover:bg-muted flex items-center justify-center text-muted-foreground hover:text-primary flex-shrink-0"
            title="Open source"
          >
            <ExternalLink className="w-3.5 h-3.5" />
          </a>
        )}
        {open ? (
          <ChevronUp className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
        ) : (
          <ChevronDown className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
        )}
      </button>
      {open && (
        <div className="border-t border-border/60 bg-muted/20 px-3 py-3 space-y-2">
          <div className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1.5 text-[11px]">
            <span className="text-muted-foreground">node_id</span>
            <span className="font-mono text-foreground break-all">{ref_.node_id}</span>
            {ref_.source && (
              <>
                <span className="text-muted-foreground">source</span>
                <span className="text-foreground">{ref_.source}</span>
              </>
            )}
            {propEntries.length === 0 && (
              <>
                <span className="text-muted-foreground">properties</span>
                <span className="text-muted-foreground/70 italic">none</span>
              </>
            )}
            {propEntries.map(([k, v]) => (
              <Fragment key={k}>
                <span className="text-muted-foreground truncate" title={k}>
                  {k}
                </span>
                <span className="text-foreground break-words">
                  {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                </span>
              </Fragment>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// Deterministic color per entity type for at-a-glance grouping.
function typeColor(type: string): { bg: string; fg: string; ring: string } {
  const palette = [
    { bg: 'bg-violet-500/10', fg: 'text-violet-600 dark:text-violet-400', ring: 'ring-violet-500/20' },
    { bg: 'bg-emerald-500/10', fg: 'text-emerald-600 dark:text-emerald-400', ring: 'ring-emerald-500/20' },
    { bg: 'bg-amber-500/10', fg: 'text-amber-600 dark:text-amber-400', ring: 'ring-amber-500/20' },
    { bg: 'bg-sky-500/10', fg: 'text-sky-600 dark:text-sky-400', ring: 'ring-sky-500/20' },
    { bg: 'bg-rose-500/10', fg: 'text-rose-600 dark:text-rose-400', ring: 'ring-rose-500/20' },
    { bg: 'bg-teal-500/10', fg: 'text-teal-600 dark:text-teal-400', ring: 'ring-teal-500/20' },
    { bg: 'bg-fuchsia-500/10', fg: 'text-fuchsia-600 dark:text-fuchsia-400', ring: 'ring-fuchsia-500/20' },
    { bg: 'bg-indigo-500/10', fg: 'text-indigo-600 dark:text-indigo-400', ring: 'ring-indigo-500/20' },
  ];
  let h = 0;
  for (const c of type) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return palette[h % palette.length];
}

function formatPropValue(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') {
    const abs = Math.abs(v);
    if (abs >= 1000) return v.toLocaleString();
    if (!Number.isInteger(v)) return v.toFixed(2);
    return String(v);
  }
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'object') return JSON.stringify(v);
  const s = String(v);
  return s.length > 200 ? s.slice(0, 200) + '…' : s;
}

function formatElapsed(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(s < 10 ? 2 : 1)}s`;
  const m = Math.floor(s / 60);
  const rs = Math.round(s - m * 60);
  return `${m}m ${rs}s`;
}

function copyToClipboard(text: string) {
  try {
    void navigator.clipboard.writeText(text);
  } catch {
    /* no-op */
  }
}

function GraphNodeItem({
  node,
  subgraph,
  theme,
  index,
  maxNumeric,
  collectionId,
  underlyingNodeType,
}: {
  node: SubgraphNode;
  subgraph: Subgraph;
  theme: 'light' | 'dark';
  index: number;
  maxNumeric: number;
  collectionId: string;
  underlyingNodeType: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [neighborhoodLoading, setNeighborhoodLoading] = useState(false);
  const [neighborhoodError, setNeighborhoodError] = useState<string | null>(null);
  const [neighborhood, setNeighborhood] = useState<NeighborhoodResponse | null>(null);
  const sourceIcon = node.source || extractSourceFromEntityType(node.entity_type);
  const props = node.properties || {};
  const propEntries = Object.entries(props).filter(
    ([k, v]) => v !== null && v !== undefined && v !== '' && !k.startsWith('_')
  );
  const color = typeColor(node.entity_type || 'Unknown');

  // Headline numeric: first numeric property (good for aggregate rows).
  const headlineNumeric = propEntries.find(
    ([, v]) => typeof v === 'number' && Number.isFinite(v as number)
  );
  const numericPct =
    headlineNumeric && maxNumeric > 0
      ? Math.max(6, Math.min(100, ((headlineNumeric[1] as number) / maxNumeric) * 100))
      : 0;

  const outgoing = subgraph.edges
    .filter((e) => e.source === node.id)
    .map((e) => ({
      relationship_type: e.relationship_type,
      other_id: e.target,
      other_name: subgraph.nodes.find((n) => n.id === e.target)?.name || e.target,
      direction: 'out' as const,
    }));
  const incoming = subgraph.edges
    .filter((e) => e.target === node.id)
    .map((e) => ({
      relationship_type: e.relationship_type,
      other_id: e.source,
      other_name: subgraph.nodes.find((n) => n.id === e.source)?.name || e.source,
      direction: 'in' as const,
    }));
  const lineage = [...outgoing, ...incoming];

  return (
    <div
      className={cn(
        'rounded-xl border bg-card overflow-hidden transition-shadow',
        open && 'shadow-sm',
        node.is_primary ? 'border-primary/50 ring-1 ring-primary/15' : 'border-border/60'
      )}
    >
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-start gap-3 px-3 py-2.5 text-left hover:bg-muted/40 transition-colors"
      >
        {/* Ordinal + type-color avatar */}
        <div className="flex flex-col items-center gap-1 flex-shrink-0 pt-0.5">
          <div
            className={cn(
              'w-8 h-8 rounded-lg flex items-center justify-center ring-1',
              color.bg,
              color.ring
            )}
          >
            {sourceIcon ? (
              <img
                src={getAppIconUrl(sourceIcon, theme)}
                alt={sourceIcon}
                className="w-4.5 h-4.5 object-contain"
                onError={(e) => {
                  e.currentTarget.style.display = 'none';
                }}
              />
            ) : (
              <Database className={cn('w-4 h-4', color.fg)} />
            )}
          </div>
          <span className="text-[9px] font-mono text-muted-foreground tabular-nums">
            #{String(index + 1).padStart(2, '0')}
          </span>
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-foreground truncate max-w-[55%]">
              {node.name || node.id}
            </span>
            <span
              className={cn(
                'text-[9px] font-semibold uppercase px-1.5 py-0.5 rounded',
                color.bg,
                color.fg
              )}
            >
              {formatEntityType(node.entity_type)}
            </span>
            {node.is_primary && (
              <span className="text-[9px] font-semibold uppercase px-1.5 py-0.5 rounded bg-primary/10 text-primary">
                primary
              </span>
            )}
          </div>

          {/* Headline data chips */}
          <div className="mt-1 flex items-center gap-1.5 flex-wrap text-[10px] text-muted-foreground">
            {headlineNumeric && (
              <span className="inline-flex items-center gap-1 font-mono tabular-nums text-foreground">
                <span className="text-muted-foreground">{headlineNumeric[0]}</span>
                <span className="font-semibold">{formatPropValue(headlineNumeric[1])}</span>
              </span>
            )}
            {lineage.length > 0 && (
              <span className="inline-flex items-center gap-1">
                <Layers className="w-3 h-3" />
                {lineage.length} link{lineage.length === 1 ? '' : 's'}
              </span>
            )}
            {propEntries.length > 0 && (
              <span className="inline-flex items-center gap-1">
                <Database className="w-3 h-3" />
                {propEntries.length} field{propEntries.length === 1 ? '' : 's'}
              </span>
            )}
            {node.depth != null && node.depth > 0 && (
              <span className="inline-flex items-center gap-1">
                <Network className="w-3 h-3" />
                depth {node.depth}
              </span>
            )}
          </div>

          {/* Proportional bar for numeric values (relative to siblings) */}
          {headlineNumeric && maxNumeric > 0 && (
            <div className="mt-1.5 h-1 rounded-full bg-muted overflow-hidden">
              <div
                className={cn('h-full rounded-full', color.bg.replace('/10', '/60'))}
                style={{ width: `${numericPct}%` }}
              />
            </div>
          )}
        </div>

        {open ? (
          <ChevronUp className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0 mt-1" />
        ) : (
          <ChevronDown className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0 mt-1" />
        )}
      </button>

      {open && (
        <div className="border-t border-border/60 bg-muted/20 px-3 py-3 space-y-3">
          {/* Identity */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/80">
                Identity
              </div>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  copyToClipboard(node.id);
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1200);
                }}
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium text-muted-foreground hover:text-foreground hover:bg-muted"
              >
                {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
                {copied ? 'Copied' : 'Copy id'}
              </button>
            </div>
            <div className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-[11px]">
              <span className="text-muted-foreground">node_id</span>
              <span className="font-mono text-foreground break-all">{node.id}</span>
              <span className="text-muted-foreground">type</span>
              <span className="text-foreground">{node.entity_type}</span>
              {node.source && (
                <>
                  <span className="text-muted-foreground">source</span>
                  <span className="text-foreground">{node.source}</span>
                </>
              )}
              {node.depth != null && (
                <>
                  <span className="text-muted-foreground">depth</span>
                  <span className="text-foreground">{node.depth}</span>
                </>
              )}
            </div>
          </div>

          {/* Properties */}
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/80 mb-1.5">
              Properties ({propEntries.length})
            </div>
            {propEntries.length === 0 ? (
              <div className="text-[11px] text-muted-foreground/70 italic">
                No additional properties
              </div>
            ) : (
              <div className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-[11px]">
                {propEntries.map(([k, v]) => (
                  <Fragment key={k}>
                    <span className="text-muted-foreground truncate" title={k}>
                      {k}
                    </span>
                    <span
                      className={cn(
                        'text-foreground break-words',
                        typeof v === 'number' && 'font-mono tabular-nums'
                      )}
                    >
                      {formatPropValue(v)}
                    </span>
                  </Fragment>
                ))}
              </div>
            )}
          </div>

          {/* Lineage (edges already in this subgraph) */}
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/80 mb-1.5">
              Lineage ({lineage.length})
            </div>
            {lineage.length === 0 ? (
              <div className="text-[11px] text-muted-foreground/70 italic">
                No linked nodes in this subgraph
              </div>
            ) : (
              <div className="space-y-1">
                {lineage.map((link, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-2 text-[11px] px-2 py-1.5 rounded-md bg-background border border-border/60"
                  >
                    <span
                      className={cn(
                        'text-[9px] font-semibold uppercase px-1.5 py-0.5 rounded flex-shrink-0',
                        link.direction === 'out'
                          ? 'bg-primary/10 text-primary'
                          : 'bg-muted text-muted-foreground'
                      )}
                    >
                      {link.direction === 'out' ? '→ out' : '← in'}
                    </span>
                    <span className="font-mono text-muted-foreground text-[10px] flex-shrink-0">
                      {link.relationship_type}
                    </span>
                    <span className="text-foreground truncate flex-1 min-w-0">
                      {link.other_name}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 2-hop neighborhood expansion (for aggregate rows) */}
          {underlyingNodeType && collectionId && (() => {
            // Detect whether this is an aggregate-row pseudo-node.
            const isAggregate =
              node.id.startsWith('row_') ||
              (node.entity_type || '').toLowerCase() === 'row';
            if (!isAggregate) return null;

            // Pick the first non-numeric, non-count property as the filter column.
            const filterEntry = propEntries.find(
              ([k, v]) =>
                typeof v !== 'number' &&
                !/_?count$|_?total$|_?sum$|_?avg$|_?min$|_?max$/i.test(k)
            );
            if (!filterEntry) return null;
            const [filterKey, filterValue] = filterEntry;

            const expand = async () => {
              setNeighborhoodError(null);
              setNeighborhoodLoading(true);
              try {
                const resp = await expandTraceNeighborhood(collectionId, {
                  node_type: underlyingNodeType,
                  filter_key: filterKey,
                  filter_value: filterValue,
                  sample_limit: 3,
                  depth: 2,
                  neighbor_cap: 60,
                });
                setNeighborhood(resp);
              } catch (e) {
                setNeighborhoodError(
                  e instanceof Error ? e.message : 'Failed to expand'
                );
              } finally {
                setNeighborhoodLoading(false);
              }
            };

            return (
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/80">
                    2-hop neighborhood
                  </div>
                  {!neighborhood && !neighborhoodLoading && (
                    <button
                      type="button"
                      onClick={expand}
                      className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-primary/10 text-primary text-[10px] font-semibold hover:bg-primary/20 transition-colors"
                    >
                      <Network className="w-3 h-3" /> Explore
                    </button>
                  )}
                  {neighborhood && (
                    <button
                      type="button"
                      onClick={() => {
                        setNeighborhood(null);
                        setNeighborhoodError(null);
                      }}
                      className="text-[10px] font-medium text-muted-foreground hover:text-foreground"
                    >
                      Clear
                    </button>
                  )}
                </div>

                {neighborhoodLoading && (
                  <div className="flex items-center gap-2 text-[11px] text-muted-foreground py-2">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" /> Expanding from{' '}
                    <span className="font-mono">
                      {filterKey}={String(filterValue)}
                    </span>
                    …
                  </div>
                )}

                {neighborhoodError && (
                  <div className="text-[11px] text-destructive border border-destructive/30 bg-destructive/5 rounded-md px-2 py-1.5 flex items-start gap-1.5">
                    <AlertCircle className="w-3 h-3 mt-0.5 flex-shrink-0" />
                    {neighborhoodError}
                  </div>
                )}

                {!neighborhoodLoading &&
                  !neighborhoodError &&
                  !neighborhood && (
                    <div className="text-[10px] text-muted-foreground/70 italic">
                      Click Explore to sample {filterKey}=
                      <span className="font-mono">{String(filterValue)}</span> nodes and
                      expand 2 hops.
                    </div>
                  )}

                {neighborhood && (
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-muted">
                        <span className="font-mono tabular-nums">
                          {neighborhood.stats.sample_count ?? 0}
                        </span>{' '}
                        seeds
                      </span>
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-muted">
                        <span className="font-mono tabular-nums">
                          {neighborhood.nodes.length}
                        </span>{' '}
                        nodes
                      </span>
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-muted">
                        <span className="font-mono tabular-nums">
                          {neighborhood.edges.length}
                        </span>{' '}
                        edges
                      </span>
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-muted">
                        depth{' '}
                        <span className="font-mono tabular-nums">
                          {neighborhood.stats.depth ?? 2}
                        </span>
                      </span>
                    </div>

                    {/* Type breakdown of the neighborhood */}
                    {(() => {
                      const byType: Record<string, number> = {};
                      for (const n of neighborhood.nodes) {
                        const t = n.node_type || 'Unknown';
                        byType[t] = (byType[t] || 0) + 1;
                      }
                      const entries = Object.entries(byType).sort(
                        (a, b) => b[1] - a[1]
                      );
                      return entries.length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                          {entries.map(([t, n]) => {
                            const c = typeColor(t);
                            return (
                              <span
                                key={t}
                                className={cn(
                                  'inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium',
                                  c.bg,
                                  c.fg
                                )}
                              >
                                <span className="font-mono tabular-nums">{n}</span>
                                <span className="truncate max-w-[100px]">
                                  {formatEntityType(t)}
                                </span>
                              </span>
                            );
                          })}
                        </div>
                      ) : null;
                    })()}

                    {/* Compact node list */}
                    <div className="space-y-1 max-h-60 overflow-y-auto pr-1">
                      {neighborhood.nodes.map((n) => {
                        const c = typeColor(n.node_type || 'Unknown');
                        return (
                          <div
                            key={n.node_id}
                            className={cn(
                              'flex items-center gap-2 text-[11px] px-2 py-1.5 rounded-md border',
                              n.is_seed
                                ? 'bg-primary/5 border-primary/30'
                                : 'bg-background border-border/60'
                            )}
                          >
                            <span
                              className={cn(
                                'text-[9px] font-semibold uppercase px-1 py-0.5 rounded flex-shrink-0',
                                c.bg,
                                c.fg
                              )}
                              title={n.node_type}
                            >
                              {formatEntityType(n.node_type || 'Unknown').slice(0, 10)}
                            </span>
                            {n.is_seed && (
                              <span className="text-[9px] font-semibold uppercase px-1 py-0.5 rounded bg-primary/10 text-primary flex-shrink-0">
                                seed
                              </span>
                            )}
                            <span
                              className="text-foreground truncate flex-1 min-w-0 font-mono"
                              title={n.node_id}
                            >
                              {n.name}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            );
          })()}
        </div>
      )}
    </div>
  );
}

function QueryItem({
  index,
  cypher,
  rowCount,
  error,
}: {
  index: number;
  cypher: string;
  rowCount: number;
  error: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const preview = cypher.replace(/\s+/g, ' ').trim().slice(0, 90);

  const copyCypher = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(cypher);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard permissions not granted */
    }
  };

  return (
    <div className={cn('rounded-xl border bg-card', error ? 'border-destructive/40' : 'border-border/60')}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-start gap-2 px-3 py-2.5 text-left hover:bg-muted/40 transition-colors"
      >
        <div className="flex-shrink-0 mt-0.5">
          {error ? (
            <AlertCircle className="w-3.5 h-3.5 text-destructive" />
          ) : (
            <div className="w-5 h-5 rounded-md bg-muted text-[10px] font-semibold text-muted-foreground flex items-center justify-center">
              {index}
            </div>
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className={cn('text-xs font-medium', error ? 'text-destructive' : 'text-foreground')}>
              {error ? 'Failed' : `${rowCount} row${rowCount === 1 ? '' : 's'}`}
            </span>
            <span className="text-[10px] text-muted-foreground">·</span>
            <span className="text-[10px] text-muted-foreground">{cypher.length} chars</span>
          </div>
          <div className="mt-0.5 text-[11px] font-mono text-muted-foreground truncate">{preview}…</div>
        </div>
        {open ? (
          <ChevronUp className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
        ) : (
          <ChevronDown className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
        )}
      </button>
      {open && (
        <div className="border-t border-border/60 bg-muted/30">
          <div className="flex items-center justify-end px-2 py-1.5 border-b border-border/40">
            <button
              type="button"
              onClick={copyCypher}
              className="inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            >
              {copied ? (
                <>
                  <Check className="w-3 h-3" /> Copied
                </>
              ) : (
                <>
                  <Copy className="w-3 h-3" /> Copy
                </>
              )}
            </button>
          </div>
          <pre className="p-3 text-[11px] font-mono text-foreground/90 whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
            {cypher}
          </pre>
          {error && (
            <div className="p-3 border-t border-border/40 text-[11px] text-destructive bg-destructive/5 whitespace-pre-wrap">
              {error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
