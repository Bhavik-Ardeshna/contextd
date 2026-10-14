/**
 * ChatMessage - Individual message bubble component
 * 
 * Displays user and assistant messages with proper styling,
 * markdown rendering, entity references, and metadata display.
 */
import { User, Sparkles, Clock, ExternalLink, Database, ChevronDown, ChevronUp } from 'lucide-react';
import { useState } from 'react';
import { normalizeChartPoint } from '@/lib/utils';
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
import { EntityReference, PlotImage, ChartSpec, formatEntityType, extractSourceFromEntityType } from '@/lib/graphChatApi';
import { getAppIconUrl } from '@/lib/utils/icons';
import { useTheme } from '@/lib/theme-provider';

export interface ChatMessageType {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  entity_references?: EntityReference[];
  plot_images?: PlotImage[];
  chart_specs?: ChartSpec[];
  // Loose-typed so we can carry the richer backend trace (queries, path_used,
  // source_types, elapsed_ms, …) without pinning every consumer to a narrow shape.
  context_metadata?: Record<string, unknown> & {
    node_count?: number;
    edge_count?: number;
    search_result_count?: number;
    token_estimate?: number;
    max_depth?: number;
    elapsed_ms?: number;
  };
  // Subgraph returned alongside the message, so opening Decision Trace on a past
  // message shows that message's subgraph, not the latest response's.
  subgraph?: unknown;
  elapsed_ms?: number;
}

interface ChatMessageProps {
  message: ChatMessageType;
  isStreaming?: boolean;
  onViewContext?: () => void;
}

export function ChatMessage({ message, isStreaming, onViewContext }: ChatMessageProps) {
  const isUser = message.role === 'user';
  const [showReferences, setShowReferences] = useState(false);
  const { resolvedTheme } = useTheme();
  
  // Get references (limit initial display)
  const references = message.entity_references || [];
  const hasReferences = references.length > 0;
  const displayedReferences = showReferences ? references : references.slice(0, 3);
  const hasMoreReferences = references.length > 3;
  
  // Format timestamp
  const formatTime = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };
  
  // Custom markdown components for styling
  const markdownComponents = {
    // Headings
    h1: ({ children }: { children?: React.ReactNode }) => (
      <h1 className="text-lg font-bold text-foreground mt-4 mb-2 first:mt-0">{children}</h1>
    ),
    h2: ({ children }: { children?: React.ReactNode }) => (
      <h2 className="text-base font-semibold text-foreground mt-4 mb-2 first:mt-0">{children}</h2>
    ),
    h3: ({ children }: { children?: React.ReactNode }) => (
      <h3 className="text-sm font-semibold text-foreground mt-3 mb-1.5">{children}</h3>
    ),
    h4: ({ children }: { children?: React.ReactNode }) => (
      <h4 className="text-sm font-medium text-foreground mt-2 mb-1">{children}</h4>
    ),
    
    // Paragraphs
    p: ({ children }: { children?: React.ReactNode }) => (
      <p className="text-foreground/90 my-2 leading-relaxed">{children}</p>
    ),
    
    // Lists
    ul: ({ children }: { children?: React.ReactNode }) => (
      <ul className="list-disc list-inside my-2 space-y-1 text-foreground/90">{children}</ul>
    ),
    ol: ({ children }: { children?: React.ReactNode }) => (
      <ol className="list-decimal list-inside my-2 space-y-1 text-foreground/90">{children}</ol>
    ),
    li: ({ children }: { children?: React.ReactNode }) => (
      <li className="text-foreground/90 leading-relaxed">{children}</li>
    ),
    
    // Inline code
    code: ({ children, className }: { children?: React.ReactNode; className?: string }) => {
      // Check if it's a code block (has language class) or inline code
      const isCodeBlock = className?.startsWith('language-');
      if (isCodeBlock) {
        return (
          <code className="text-sm font-mono text-foreground/90">{children}</code>
        );
      }
      return (
        <code className="bg-muted px-1.5 py-0.5 rounded text-sm font-mono text-primary">
          {children}
        </code>
      );
    },
    
    // Code blocks
    pre: ({ children }: { children?: React.ReactNode }) => (
      <pre className="bg-muted rounded-lg p-3 my-3 overflow-x-auto border border-border">
        {children}
      </pre>
    ),
    
    // Links
    a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
      <a 
        href={href} 
        target="_blank" 
        rel="noopener noreferrer"
        className="text-primary hover:text-primary/80 underline underline-offset-2 transition-colors"
      >
        {children}
      </a>
    ),
    
    // Bold and italic
    strong: ({ children }: { children?: React.ReactNode }) => (
      <strong className="font-semibold text-foreground">{children}</strong>
    ),
    em: ({ children }: { children?: React.ReactNode }) => (
      <em className="italic text-foreground/90">{children}</em>
    ),
    
    // Blockquotes
    blockquote: ({ children }: { children?: React.ReactNode }) => (
      <blockquote className="border-l-4 border-primary/30 pl-4 my-3 text-foreground/80 italic">
        {children}
      </blockquote>
    ),
    
    // Horizontal rule
    hr: () => <hr className="my-4 border-border" />,
    
    // Tables
    table: ({ children }: { children?: React.ReactNode }) => (
      <div className="overflow-x-auto my-3">
        <table className="min-w-full text-sm border border-border rounded-lg">
          {children}
        </table>
      </div>
    ),
    thead: ({ children }: { children?: React.ReactNode }) => (
      <thead className="bg-muted/50">{children}</thead>
    ),
    tbody: ({ children }: { children?: React.ReactNode }) => (
      <tbody className="divide-y divide-border">{children}</tbody>
    ),
    tr: ({ children }: { children?: React.ReactNode }) => (
      <tr className="hover:bg-muted/30 transition-colors">{children}</tr>
    ),
    th: ({ children }: { children?: React.ReactNode }) => (
      <th className="px-3 py-2 text-left font-semibold text-foreground border-b border-border">
        {children}
      </th>
    ),
    td: ({ children }: { children?: React.ReactNode }) => (
      <td className="px-3 py-2 text-foreground/90">{children}</td>
    ),
  };
  
  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      {/* Avatar */}
      <div className={`
        flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center
        ${isUser 
          ? 'bg-primary/20 text-primary'
          : 'bg-primary/20 text-primary'
        }
      `}>
        {isUser ? (
          <User className="w-4 h-4" />
        ) : (
          <Sparkles className="w-4 h-4" />
        )}
      </div>
      
      {/* Message content */}
      <div className={`
        flex-1 max-w-[80%] rounded-2xl px-4 py-3
        ${isUser 
          ? 'bg-primary/10 border border-primary/20'
          : 'bg-muted/50 border border-border'
        }
        ${isStreaming ? 'animate-pulse' : ''}
      `}>
        {/* Content */}
        <div className="text-sm leading-relaxed">
          {isUser ? (
            <p className="text-foreground">{message.content}</p>
          ) : (
            <div className="prose prose-sm max-w-none">
              <ReactMarkdown 
                remarkPlugins={[remarkGfm]}
                components={markdownComponents}
              >
                {message.content}
              </ReactMarkdown>
              {!isStreaming && message.chart_specs && message.chart_specs.length > 0 && (
                <div className="mt-4 space-y-6">
                  {message.chart_specs.map((chart, idx) => {
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
                        const anum = Number(a.name);
                        const bnum = Number(b.name);
                        if (!Number.isNaN(anum) && !Number.isNaN(bnum)) return anum - bnum;
                        return String(a.name).localeCompare(String(b.name));
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
                      return (
                        <div className="rounded border bg-popover px-3 py-2 text-sm shadow-md">
                          <div className="font-medium">{chart.config?.xAxis ?? 'X'}: {String(p?.x ?? '—')}</div>
                          <div>{yName}: {String(p?.y ?? '—')}</div>
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
              {isStreaming && (
                <span className="inline-block w-2 h-4 bg-primary animate-pulse ml-1" />
              )}
            </div>
          )}
        </div>
        
        {/* Metadata footer for assistant messages */}
        {!isUser && !isStreaming && (
          <div className="mt-3 pt-2 border-t border-border/50">
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              {message.created_at && (
                <span className="flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  {formatTime(message.created_at)}
                </span>
              )}
              {message.context_metadata && (
                <>
                  <span className="flex items-center gap-1">
                    <Database className="w-3 h-3" />
                    {message.context_metadata.node_count} nodes
                  </span>
                  {onViewContext && (
                    <button
                      onClick={onViewContext}
                      className="text-primary hover:text-primary/80 transition-colors"
                    >
                      View graph
                    </button>
                  )}
                </>
              )}
            </div>
          </div>
        )}
        
        {/* Entity References */}
        {!isUser && !isStreaming && hasReferences && (
          <div className="mt-3 pt-3 border-t border-border/50">
            <button
              onClick={() => setShowReferences(!showReferences)}
              className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground mb-2 transition-colors"
            >
              <Database className="w-3 h-3" />
              <span>{references.length} referenced entities</span>
              {hasMoreReferences && (
                showReferences ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />
              )}
            </button>
            
            <div className="space-y-1.5">
              {displayedReferences.map((ref) => {
                const sourceIcon = extractSourceFromEntityType(ref.entity_type);
                return (
                  <a
                    key={ref.entity_id}
                    href={ref.url || '#'}
                    target={ref.url ? '_blank' : undefined}
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-muted/50 
                             hover:bg-muted transition-colors group"
                  >
                    {/* Source icon */}
                    <div className="flex-shrink-0 w-5 h-5 rounded flex items-center justify-center bg-muted">
                      {sourceIcon ? (
                        <img 
                          src={getAppIconUrl(sourceIcon, resolvedTheme)} 
                          alt={sourceIcon}
                          className="w-3.5 h-3.5 object-contain"
                          onError={(e) => {
                            e.currentTarget.style.display = 'none';
                          }}
                        />
                      ) : (
                        <Database className="w-3 h-3 text-muted-foreground" />
                      )}
                    </div>
                    
                    {/* Name and type */}
                    <div className="flex-1 min-w-0">
                      <span className="text-xs font-medium text-foreground truncate block">
                        {ref.name}
                      </span>
                    </div>
                    
                    {/* Type badge */}
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                      {formatEntityType(ref.entity_type)}
                    </span>
                    
                    {/* External link */}
                    {ref.url && (
                      <ExternalLink className="w-3 h-3 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                    )}
                  </a>
                );
              })}
              
              {/* Show more/less button */}
              {hasMoreReferences && !showReferences && (
                <button
                  onClick={() => setShowReferences(true)}
                  className="text-xs text-primary hover:text-primary/80 transition-colors"
                >
                  + {references.length - 3} more references
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default ChatMessage;
