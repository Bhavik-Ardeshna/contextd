/**
 * ChatPage - Fullscreen conversation view with context sidebar
 *
 * Provides a dedicated page for AI-powered conversations with
 * full message history, context graph viewing, and entity references.
 */
import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
import {
  Send, Loader2, Plus,
  Database, Network, X,
  Layers, ExternalLink, ChevronDown, ChevronUp
} from 'lucide-react';
import { ChatMessageType } from '@/components/chat/ChatMessage';
import { ThinkingIndicator } from '@/components/chat/ThinkingIndicator';
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
  EntityReference,
  Subgraph,
  ContextMetadata,
  ChartSpec,
  subgraphToJson,
  formatEntityType,
  extractSourceFromEntityType
} from '@/lib/graphChatApi';
import { getAppIconUrl } from '@/lib/utils/icons';
import { useTheme } from '@/lib/theme-provider';
import { useChatStore } from '@/lib/stores/chatStore';

import { Suspense } from 'react';
import { ContextGraph } from '@/components/graph';
import { MentionDropdown, useMention } from '@/components/chat/MentionDropdown';

interface ChatHistoryItem {
  role: string;
  content: string;
}

// Sidebar References Component with show more/less
function SidebarReferences({
  references,
  resolvedTheme
}: {
  references: EntityReference[];
  resolvedTheme: string | undefined;
}) {
  const [isExpanded, setIsExpanded] = useState(false);
  const displayRefs = isExpanded ? references : references.slice(0, 5);
  const hasMore = references.length > 5;

  return (
    <div>
      <h4 className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1.5">
        <Layers className="w-3.5 h-3.5" />
        Referenced Entities ({references.length})
      </h4>
      <div className="space-y-1.5">
        {displayRefs.map((ref) => {
          const sourceIcon = extractSourceFromEntityType(ref.entity_type);
          return (
            <a
              key={ref.entity_id}
              href={ref.url || '#'}
              target={ref.url ? '_blank' : undefined}
              rel="noopener noreferrer"
              className="flex items-center gap-2 px-2.5 py-2 rounded-lg bg-muted/30 border border-transparent
                       hover:bg-muted hover:border-border transition-colors group"
            >
              {/* Source icon */}
              <div className="flex-shrink-0 w-7 h-7 rounded-md flex items-center justify-center bg-background border border-border">
                {sourceIcon ? (
                  <img
                    src={getAppIconUrl(sourceIcon, resolvedTheme)}
                    alt={sourceIcon}
                    className="w-4 h-4 object-contain"
                    onError={(e) => {
                      e.currentTarget.style.display = 'none';
                    }}
                  />
                ) : (
                  <Database className="w-3.5 h-3.5 text-muted-foreground" />
                )}
              </div>

              {/* Name and type */}
              <div className="flex-1 min-w-0">
                <span className="text-xs font-medium text-foreground truncate block">
                  {ref.name}
                </span>
                <span className="text-[10px] text-muted-foreground">
                  {formatEntityType(ref.entity_type)}
                </span>
              </div>

              {/* External link */}
              {ref.url && (
                <ExternalLink className="w-3 h-3 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0" />
              )}
            </a>
          );
        })}
      </div>

      {/* Show more/less button */}
      {hasMore && (
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="flex items-center gap-1.5 mt-2 text-xs text-muted-foreground hover:text-foreground transition-colors w-full justify-center py-1.5 rounded-lg hover:bg-muted/50"
        >
          {isExpanded ? (
            <>
              <ChevronUp className="w-3 h-3" />
              Show less
            </>
          ) : (
            <>
              <ChevronDown className="w-3 h-3" />
              Show {references.length - 5} more
            </>
          )}
        </button>
      )}
    </div>
  );
}

// Type for navigation state
interface ChatNavigationState {
  messages?: ChatMessageType[];
  subgraph?: Subgraph | null;
}

function ChatPage() {
  const { chatId } = useParams<{ chatId?: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { resolvedTheme } = useTheme();

  // Chat store integration
  const chatStore = useChatStore();
  const currentChatIdRef = useRef<number | null>(chatId ? Number(chatId) : null);

  // Get navigation state passed by callers that open chat with prefilled context.
  const navigationState = location.state as ChatNavigationState | null;

  // Get collections
  const { collections, fetchCollections } = useCollectionsStore();
  const defaultCollectionId = collections.length > 0 ? collections[0].readable_id : null;

  // Fetch collections on mount
  useEffect(() => {
    if (collections.length === 0) {
      fetchCollections();
    }
  }, [collections.length, fetchCollections]);

  // Chat state - initialize from store, navigation state, or empty
  const [messages, setMessages] = useState<ChatMessageType[]>(() => {
    if (navigationState?.messages) return navigationState.messages;
    if (chatId) {
      const stored = useChatStore.getState().getChat(Number(chatId));
      return stored?.messages || [];
    }
    return [];
  });
  const [conversationHistory, setConversationHistory] = useState<ChatHistoryItem[]>(() => {
    if (navigationState?.messages) {
      return navigationState.messages.map(m => ({
        role: m.role,
        content: m.content,
      }));
    }
    if (chatId) {
      const stored = useChatStore.getState().getChat(Number(chatId));
      if (stored?.messages) {
        return stored.messages.map(m => ({
          role: m.role,
          content: m.content,
        }));
      }
    }
    return [];
  });
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
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

  // Context panel state - open if we have subgraph from navigation
  const [showContextPanel, setShowContextPanel] = useState(
    !!(navigationState?.subgraph)
  );
  const [currentSubgraph, setCurrentSubgraph] = useState<Subgraph | null>(
    navigationState?.subgraph || null
  );
  const [currentReferences, setCurrentReferences] = useState<EntityReference[]>(() => {
    // Extract references from last assistant message if available
    const lastAssistant = navigationState?.messages?.filter(m => m.role === 'assistant').pop();
    return lastAssistant?.entity_references || [];
  });
  const [currentMetadata, setCurrentMetadata] = useState<ContextMetadata | null>(() => {
    const lastAssistant = navigationState?.messages?.filter(m => m.role === 'assistant').pop();
    return lastAssistant?.context_metadata || null;
  });
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
      <pre className="bg-muted rounded-lg p-3 my-3 overflow-x-auto border border-border">{children}</pre>
    ),
    a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
      <a href={href} target="_blank" rel="noopener noreferrer"
        className="text-foreground hover:text-muted-foreground underline underline-offset-2 transition-colors">{children}</a>
    ),
    strong: ({ children }: { children?: React.ReactNode }) => (
      <strong className="font-semibold text-foreground">{children}</strong>
    ),
    blockquote: ({ children }: { children?: React.ReactNode }) => (
      <blockquote className="border-l-4 border-primary/30 pl-4 my-3 text-foreground/80 italic">{children}</blockquote>
    ),
    table: ({ children }: { children?: React.ReactNode }) => (
      <div className="overflow-x-auto my-3">
        <table className="min-w-full text-sm border border-border rounded-lg">{children}</table>
      </div>
    ),
    th: ({ children }: { children?: React.ReactNode }) => (
      <th className="px-3 py-2 text-left font-semibold text-foreground border-b border-border bg-muted/50">{children}</th>
    ),
    td: ({ children }: { children?: React.ReactNode }) => (
      <td className="px-3 py-2 text-foreground/90 border-b border-border">{children}</td>
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

  // On mount: persist navigation state messages to store, or redirect if chat not found
  useEffect(() => {
    if (navigationState?.messages && navigationState.messages.length > 0) {
      // Create a chat in the store from navigation state
      const firstUserMsg = navigationState.messages.find(m => m.role === 'user');
      const title = firstUserMsg
        ? firstUserMsg.content.slice(0, 50) + (firstUserMsg.content.length > 50 ? '...' : '')
        : 'New Conversation';
      const newId = chatStore.createChat(title);
      currentChatIdRef.current = newId;
      navigationState.messages.forEach(m => chatStore.addMessage(newId, m));
      navigate(`/chat/${newId}`, { replace: true });
      // Replace current history entry without the state
      window.history.replaceState({}, '', `/chat/${newId}`);
    } else if (chatId) {
      const stored = useChatStore.getState().getChat(Number(chatId));
      if (!stored) {
        // Chat not found in store, redirect to new chat
        navigate('/chat', { replace: true });
      } else {
        chatStore.setActiveChat(Number(chatId));
      }
    }
  }, []);

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

    // Create chat in store on first message if needed
    if (!currentChatIdRef.current) {
      const title = userQuery.slice(0, 50) + (userQuery.length > 50 ? '...' : '');
      const newId = chatStore.createChat(title);
      currentChatIdRef.current = newId;
      navigate(`/chat/${newId}`, { replace: true });
    }

    // Add optimistic user message
    const userMessage: ChatMessageType = {
      id: Date.now(),
      role: 'user',
      content: userQuery,
      created_at: new Date().toISOString(),
    };
    setMessages(prev => [...prev, userMessage]);
    chatStore.addMessage(currentChatIdRef.current, userMessage);

    // Update conversation history
    const newHistory = [...conversationHistory, { role: 'user', content: userQuery }];
    setConversationHistory(newHistory);

    try {
      // Call the real chat API (use deterministic path when message contains @search)
      const chatFn = messageUsesSearchEndpoint(userQuery) ? graphChatSearch : graphChat;
      const response = await chatFn(defaultCollectionId, {
        message: userQuery,
        history: newHistory.slice(-10), // Keep last 10 messages for context
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

      // Store context for sidebar
      if (response.subgraph) {
        setCurrentSubgraph(response.subgraph);
      }
      setCurrentReferences(response.entity_references || []);
      setCurrentMetadata(response.context_metadata);

      // Simulate streaming for smoother UX
      const fullResponse = response.message;
      let charIndex = 0;

      const streamInterval = setInterval(() => {
        if (charIndex < fullResponse.length) {
          const charsToAdd = fullResponse.slice(charIndex, charIndex + 5);
          setStreamingContent(prev => prev + charsToAdd);
          charIndex += 5;
        } else {
          clearInterval(streamInterval);

          // Add complete assistant message
          const assistantMessage: ChatMessageType = {
            id: Date.now() + 1,
            role: 'assistant',
            content: fullResponse,
            created_at: new Date().toISOString(),
            entity_references: response.entity_references,
            plot_images: response.plot_images,
            chart_specs: response.chart_specs,
            context_metadata: response.context_metadata,
          };
          setMessages(prev => [...prev, assistantMessage]);
          setSelectedMessageId(assistantMessage.id);
          if (currentChatIdRef.current) {
            chatStore.addMessage(currentChatIdRef.current, assistantMessage);
          }

          // Update conversation history
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
    currentChatIdRef.current = null;
    chatStore.setActiveChat(null);
    setMessages([]);
    setConversationHistory([]);
    setInput('');
    setCurrentSubgraph(null);
    setCurrentReferences([]);
    setCurrentMetadata(null);
    setSelectedMessageId(null);
    setError(null);
    navigate('/chat');
    inputRef.current?.focus();
  };


  // Handle viewing context for a specific message
  const handleViewContext = (messageId: number) => {
    const message = messages.find(m => m.id === messageId);
    if (message && message.entity_references) {
      setCurrentReferences(message.entity_references);
      setCurrentMetadata(message.context_metadata || null);
      setSelectedMessageId(messageId);
      setShowContextPanel(true);
    }
  };

  // Quick starter examples
  const quickStarters = [
    'What tasks are in progress?',
    'Show me recent activity',
    'Summarize my projects',
    'Who is working on what?',
  ];

  return (
    <div className="flex h-full min-h-0 w-full bg-background text-foreground transition-colors duration-200">
      {/* Main Chat Area */}
      <div className={cn(
        "flex-1 flex flex-col overflow-hidden transition-all duration-300",
        showContextPanel ? "mr-0" : ""
      )}>
        {/* Chat Header */}
        <div className="h-14 flex items-center justify-between px-6 border-b border-border bg-background shrink-0">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-muted flex items-center justify-center flex-shrink-0">
                <img
                  src="/navios.svg"
                  alt="ContextD"
                  className="w-5 h-5 object-contain opacity-70"
                />
              </div>
              <div>
                <h1 className="text-sm font-medium text-foreground">
                  Knowledge Graph Chat
                </h1>
                <p className="text-[10px] text-muted-foreground">
                  {messages.length > 0 ? `${messages.length} messages` : 'AI-powered insights'}
                </p>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {messages.length > 0 && (
              <button
                onClick={startNewChat}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-muted
                         text-muted-foreground hover:text-foreground hover:bg-muted/80 transition-colors text-xs font-medium border border-border"
              >
                <Plus className="w-3.5 h-3.5" />
                New Chat
              </button>
            )}
          </div>
        </div>

        {/* Messages area */}
        <div className="flex-1 overflow-y-auto scrollbar-thin p-6 space-y-6 min-h-0"
             ref={scrollRef}
        >
          {isLoading ? (
            <div className="flex items-center justify-center h-full">
              <Loader2 className="w-8 h-8 text-primary animate-spin" />
            </div>
          ) : messages.length === 0 && !isStreaming ? (
            // Empty state with ContextD branding
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="w-24 h-24 rounded-3xl bg-muted/50 border border-border
                            flex items-center justify-center mb-8 relative">
                <img
                  src="/navios.svg"
                  alt="ContextD"
                  className="w-14 h-14 object-contain"
                />
              </div>
              <h2 className="text-2xl font-semibold text-foreground mb-3">
                Ask me anything about your data
              </h2>
              <p className="text-muted-foreground max-w-md mb-10">
                I can search your ContextD graph, lineage, and temporal facts to answer
                questions about connected sources.
              </p>

              {/* Quick starters */}
              <div className="grid grid-cols-2 gap-3 max-w-2xl">
                {quickStarters.map((example, idx) => (
                  <button
                    key={idx}
                    onClick={() => setInput(example)}
                    className="text-left px-5 py-4 rounded-xl bg-card border border-border
                             hover:border-primary/50 hover:bg-muted/50 transition-all duration-200
                             text-sm text-muted-foreground hover:text-foreground group"
                  >
                    <span className="group-hover:text-primary transition-colors">→</span>{' '}
                    {example}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {/* Max width container for messages */}
              <div className="max-w-4xl mx-auto space-y-6">
                {messages
                  .filter((msg) => msg.role === 'user' || msg.role === 'assistant')
                  .map((message) => {
                    const isUser = message.role === 'user';
                    const refs = message.entity_references || [];
                    const isExpanded = expandedRefs.has(message.id);
                    const displayRefs = isExpanded ? refs : refs.slice(0, 4);
                    const hasMoreRefs = refs.length > 4;

                    return (
                      <div key={message.id} className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
                        {/* Avatar with ContextD logo */}
                        <div className={cn(
                          "flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center",
                          isUser ? "bg-muted" : "bg-muted"
                        )}>
                          {isUser ? (
                            <div className="w-5 h-5 rounded-full bg-primary/20 flex items-center justify-center">
                              <span className="text-xs font-medium text-primary">U</span>
                            </div>
                          ) : (
                            <img
                              src="/navios.svg"
                              alt="ContextD"
                              className="w-5 h-5 object-contain"
                            />
                          )}
                        </div>

                        {/* Message content */}
                        <div className={cn(
                          "flex-1 max-w-[85%] rounded-2xl px-4 py-3",
                          isUser
                            ? "bg-muted border border-border"
                            : "bg-card border border-border"
                        )}>
                          {/* Content */}
                          <div className="text-sm leading-relaxed">
                            {isUser ? (
                              <p className="text-foreground">{message.content}</p>
                            ) : (
                              <>
                                <div className="prose prose-sm max-w-none">
                                  <ReactMarkdown
                                    remarkPlugins={[remarkGfm]}
                                    components={markdownComponents}
                                  >
                                    {message.content}
                                  </ReactMarkdown>
                                </div>
                                {/* Charts from P-Agent (JSON Bridge) */}
                                {message.chart_specs && message.chart_specs.length > 0 && (
                                  <div className="mt-4 space-y-6">
                                    {message.chart_specs.map((chart: ChartSpec, idx: number) => {
                                      const rawData = chart.data || [];
                                      const isScatter = chart.chart_type === 'scatter';
                                      let data = isScatter
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
                                      const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#94a3b8'];
                                      const yName = chart.config?.yAxis ?? (chart.chart_type === 'histogram' ? 'Count' : 'Value');
                                      const xName = chart.config?.xAxis ?? 'Category';
                                      const margin = { top: 5, right: 5, left: 5, bottom: 5 };
                                      const chartTooltip = ({ active, payload, label }: { active?: boolean; payload?: Array<{ value?: number; payload?: Record<string, unknown> }>; label?: string }) => {
                                        if (!active || !payload?.length) return null;
                                        const p = payload[0]?.payload as Record<string, unknown> | undefined;
                                        const x = p?.name ?? label ?? '';
                                        const y = payload[0]?.value;
                                        return (
                                          <div className="rounded border bg-popover px-3 py-2 text-sm shadow-md">
                                            <div className="font-medium">{xName}: {String(x)}</div>
                                            <div>{yName}: {y != null ? String(y) : '—'}</div>
                                          </div>
                                        );
                                      };
                                      const scatterTooltip = ({ active, payload }: { active?: boolean; payload?: Array<{ payload?: { x?: number; y?: number } }> }) => {
                                        if (!active || !payload?.length) return null;
                                        const p = payload[0]?.payload;
                                        const x = p?.x ?? '—';
                                        const y = p?.y ?? '—';
                                        return (
                                          <div className="rounded border bg-popover px-3 py-2 text-sm shadow-md">
                                            <div className="font-medium">{chart.config?.xAxis ?? 'X'}: {String(x)}</div>
                                            <div>{yName}: {String(y)}</div>
                                          </div>
                                        );
                                      };
                                      return (
                                        <figure key={idx} className="rounded-lg border border-border overflow-hidden bg-muted/20 p-3">
                                          {chart.title && (
                                            <figcaption className="text-sm font-medium text-foreground mb-2">{chart.title}</figcaption>
                                          )}
                                          <ResponsiveContainer width="100%" height={280}>
                                            {chart.chart_type === 'pie' ? (
                                              <PieChart>
                                                <Pie data={data} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80}
                                                  label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}>
                                                  {data.map((_, i) => <Cell key={i} fill={colors[i % colors.length]} />)}
                                                </Pie>
                                                <Tooltip content={({ active, payload }) => {
                                                  if (!active || !payload?.length) return null;
                                                  const name = (payload[0]?.payload as Record<string, unknown>)?.name ?? '';
                                                  const value = payload[0]?.value;
                                                  return (
                                                    <div className="rounded border bg-popover px-3 py-2 text-sm shadow-md">
                                                      <div className="font-medium">{xName}: {String(name)}</div>
                                                      <div>{yName}: {value != null ? String(value) : '—'}</div>
                                                    </div>
                                                  );
                                                }} />
                                              </PieChart>
                                            ) : chart.chart_type === 'line' ? (
                                              <LineChart data={data} margin={margin}>
                                                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                                                <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                                                <YAxis tick={{ fontSize: 12 }} />
                                                <Tooltip content={chartTooltip} />
                                                <Legend />
                                                <Line type="monotone" dataKey="value" stroke="hsl(var(--chart-1))" strokeWidth={2} name={yName} />
                                              </LineChart>
                                            ) : chart.chart_type === 'area' ? (
                                              <AreaChart data={data} margin={margin}>
                                                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                                                <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                                                <YAxis tick={{ fontSize: 12 }} />
                                                <Tooltip content={chartTooltip} />
                                                <Legend />
                                                <Area type="monotone" dataKey="value" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.4} name={yName} />
                                              </AreaChart>
                                            ) : chart.chart_type === 'scatter' ? (
                                              <ScatterChart margin={margin}>
                                                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                                                <XAxis dataKey="x" type="number" name={chart.config?.xAxis ?? 'X'} tick={{ fontSize: 12 }} />
                                                <YAxis dataKey="y" type="number" name={chart.config?.yAxis ?? 'Y'} tick={{ fontSize: 12 }} />
                                                <Tooltip content={scatterTooltip} cursor={{ strokeDasharray: '3 3' }} />
                                                <Scatter name={chart.title || 'Data'} data={data} fill="#3b82f6" />
                                              </ScatterChart>
                                            ) : chart.chart_type === 'radar' ? (
                                              <RadarChart data={data} margin={margin}>
                                                <PolarGrid />
                                                <PolarAngleAxis dataKey="name" tick={{ fontSize: 11 }} />
                                                <PolarRadiusAxis angle={30} tick={{ fontSize: 10 }} />
                                                <Radar name={yName} dataKey="value" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.5} />
                                                <Tooltip content={chartTooltip} />
                                                <Legend />
                                              </RadarChart>
                                            ) : chart.chart_type === 'radialBar' ? (
                                              <RadialBarChart data={data} margin={margin} innerRadius="10%" outerRadius="90%">
                                                <RadialBar dataKey="value" nameKey="name" fill="#3b82f6" stroke="#3b82f6" />
                                                <Legend />
                                                <Tooltip content={chartTooltip} />
                                              </RadialBarChart>
                                            ) : (
                                              <BarChart data={data} margin={margin}>
                                                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                                                <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                                                <YAxis tick={{ fontSize: 12 }} />
                                                <Tooltip content={chartTooltip} />
                                                <Legend />
                                                <Bar dataKey="value" fill="#3b82f6" name={yName} radius={[4, 4, 0, 0]} />
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

                          {/* Entity References (cos_poc style) */}
                          {!isUser && refs.length > 0 && (
                            <div className="mt-4 pt-3 border-t border-border">
                              <div className="flex items-center justify-between mb-2">
                                <span className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
                                  <Database className="w-3 h-3" />
                                  {refs.length} Referenced Entities
                                </span>
                                {message.context_metadata && (
                                  <button
                                    onClick={() => handleViewContext(message.id)}
                                    className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                                  >
                                    View Graph
                                  </button>
                                )}
                              </div>

                              <div className="grid grid-cols-2 gap-2">
                                {displayRefs.map((ref) => {
                                  const sourceIcon = extractSourceFromEntityType(ref.entity_type);
                                  return (
                                    <a
                                      key={ref.entity_id}
                                      href={ref.url || '#'}
                                      target={ref.url ? '_blank' : undefined}
                                      rel="noopener noreferrer"
                                      className="flex items-center gap-2 px-3 py-2 rounded-lg bg-muted/50
                                               hover:bg-muted transition-colors group border border-transparent hover:border-border"
                                    >
                                      {/* Source icon */}
                                      <div className="flex-shrink-0 w-7 h-7 rounded-md flex items-center justify-center bg-background border border-border">
                                        {sourceIcon ? (
                                          <img
                                            src={getAppIconUrl(sourceIcon, resolvedTheme)}
                                            alt={sourceIcon}
                                            className="w-4 h-4 object-contain"
                                            onError={(e) => {
                                              e.currentTarget.style.display = 'none';
                                            }}
                                          />
                                        ) : (
                                          <Database className="w-3.5 h-3.5 text-muted-foreground" />
                                        )}
                                      </div>

                                      {/* Name and type */}
                                      <div className="flex-1 min-w-0 overflow-hidden">
                                        <span className="text-xs font-medium text-foreground truncate block">
                                          {ref.name}
                                        </span>
                                        <span className="text-[10px] text-muted-foreground">
                                          {formatEntityType(ref.entity_type)}
                                        </span>
                                      </div>

                                      {/* External link */}
                                      {ref.url && (
                                        <ExternalLink className="w-3 h-3 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0" />
                                      )}
                                    </a>
                                  );
                                })}
                              </div>

                              {/* Show more/less button */}
                              {hasMoreRefs && (
                                <button
                                  onClick={() => toggleExpandRefs(message.id)}
                                  className="flex items-center gap-1.5 mt-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
                                >
                                  {isExpanded ? (
                                    <>
                                      <ChevronUp className="w-3 h-3" />
                                      Show less
                                    </>
                                  ) : (
                                    <>
                                      <ChevronDown className="w-3 h-3" />
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
                  <div className="flex gap-3">
                    <div className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center bg-muted">
                      <img
                        src="/navios.svg"
                        alt="ContextD"
                        className="w-5 h-5 object-contain"
                      />
                    </div>
                    <div className="flex-1 max-w-[85%] rounded-2xl px-4 py-3 bg-card border border-border">
                      <div className="text-sm leading-relaxed prose prose-sm max-w-none">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          components={markdownComponents}
                        >
                          {streamingContent}
                        </ReactMarkdown>
                        <span className="inline-block w-2 h-4 bg-primary animate-pulse ml-1" />
                      </div>
                    </div>
                  </div>
                )}

                {/* Thinking indicator */}
                {isStreaming && !streamingContent && (
                  <ThinkingIndicator contextSummary={contextSummary} />
                )}
              </div>
            </>
          )}

          {/* Error message */}
          {error && (
            <div className="flex justify-center">
              <div className="px-4 py-2 rounded-lg bg-status-error-subtle text-status-error text-sm">
                {error}
              </div>
            </div>
          )}
        </div>

        {/* Input Area - relative positioned, centered with messages */}
        <div className="shrink-0 bg-background px-6 pb-6 pt-2">
          <div className="max-w-4xl mx-auto">
            <form onSubmit={handleSubmit}>
              <div
                className={cn(
                  "relative rounded-xl transition-all duration-200",
                  "bg-muted/50 border border-border",
                  isFocused && "border-muted-foreground/50 bg-background"
                )}
              >
                <div className="flex items-center gap-3 px-4 py-3">
                  {/* ContextD logo / Loading indicator */}
                  <div className="flex-shrink-0">
                    {isStreaming ? (
                      <Loader2 className="w-5 h-5 text-muted-foreground animate-spin" />
                    ) : (
                      <img
                        src="/navios.svg"
                        alt="ContextD"
                        className={cn(
                          "w-5 h-5 transition-opacity duration-200 object-contain",
                          isFocused || input ? "opacity-100" : "opacity-50"
                        )}
                      />
                    )}
                  </div>

                  {/* Simple Input */}
                  <div className="relative flex-1 flex items-center">
                    {/* Mention Dropdown */}
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
                      placeholder="Ask a question about your data..."
                      disabled={isStreaming}
                      className="flex-1 w-full bg-transparent text-foreground placeholder-muted-foreground
                               outline-none text-sm"
                    />
                  </div>

                  {/* Send button */}
                  <button
                    type="submit"
                    disabled={!input.trim() || isStreaming}
                    className={cn(
                      "flex items-center justify-center w-8 h-8 rounded-lg transition-all duration-200 flex-shrink-0",
                      input.trim() && !isStreaming
                        ? "bg-foreground text-background hover:bg-foreground/90"
                        : "bg-transparent text-muted-foreground"
                    )}
                  >
                    {isStreaming ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Send className="w-4 h-4" />
                    )}
                  </button>
                </div>
              </div>

              {/* Hint text */}
              <p className="text-[10px] text-muted-foreground text-center mt-2">
                Press <kbd className="px-1 py-0.5 rounded bg-muted font-mono text-[9px]">Enter</kbd> to send
              </p>
            </form>
          </div>
        </div>
      </div>

      {/* Context Sidebar */}
      {showContextPanel && (
        <div className="w-[380px] border-l border-border bg-background flex flex-col shrink-0">
          {/* Sidebar Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-muted/30">
            <h3 className="font-medium text-foreground flex items-center gap-2 text-sm">
              <Database className="w-4 h-4 text-muted-foreground" />
              Context
            </h3>
            <button
              onClick={() => setShowContextPanel(false)}
              className="p-1.5 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto">
            {/* Knowledge Graph Visualization */}
            {currentSubgraph && (
              <div className="p-4 border-b border-border">
                <h4 className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1.5">
                  <Network className="w-3.5 h-3.5" />
                  Knowledge Graph
                </h4>
                <Suspense fallback={
                  <div className="h-[200px] flex items-center justify-center bg-muted/50 rounded-lg">
                    <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
                  </div>
                }>
                  <ContextGraph
                    subgraphJson={subgraphToJson(currentSubgraph)}
                    height="200px"
                  />
                </Suspense>
              </div>
            )}

            <div className="p-4 space-y-4">
              {/* Stats */}
              {currentMetadata && (
                <div className="grid grid-cols-3 gap-2">
                  <div className="px-3 py-2 rounded-lg bg-muted/50 border border-border">
                    <div className="text-lg font-semibold text-foreground">
                      {currentMetadata.node_count}
                    </div>
                    <div className="text-[10px] text-muted-foreground">Nodes</div>
                  </div>
                  <div className="px-3 py-2 rounded-lg bg-muted/50 border border-border">
                    <div className="text-lg font-semibold text-foreground">
                      {currentMetadata.edge_count}
                    </div>
                    <div className="text-[10px] text-muted-foreground">Edges</div>
                  </div>
                  <div className="px-3 py-2 rounded-lg bg-muted/50 border border-border">
                    <div className="text-lg font-semibold text-foreground">
                      {currentMetadata.search_result_count}
                    </div>
                    <div className="text-[10px] text-muted-foreground">Hits</div>
                  </div>
                </div>
              )}

              {/* Entity References - show 5 with expand */}
              {currentReferences.length > 0 && (
                <SidebarReferences
                  references={currentReferences}
                  resolvedTheme={resolvedTheme}
                />
              )}

              {/* Empty state */}
              {!currentSubgraph && currentReferences.length === 0 && !currentMetadata && (
                <div className="text-center py-8 text-muted-foreground">
                  <Database className="w-8 h-8 mx-auto mb-2 opacity-30" />
                  <p className="text-sm">No context available yet</p>
                  <p className="text-xs mt-1">Start a conversation to see graph context</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default ChatPage;
