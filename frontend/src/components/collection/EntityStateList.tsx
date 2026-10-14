import React, { useState, useEffect, useRef } from 'react';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';
import { Plus, FileText, Database, Code, Maximize2, Copy, CheckCircle, ChevronRight, X } from 'lucide-react';
import { EntityState, useEntityStateStore } from '@/stores/entityStateStore';
import { apiClient } from '@/lib/api';
import { DESIGN_SYSTEM } from '@/lib/design-system';
import { GraphEventsView } from '@/components/graph/GraphEventsView';

// Entity Definition type matching backend schema
interface EntityDefinition {
  id: string;
  name: string;
  description?: string;
  type: 'json' | 'file' | 'database';
  entity_schema: string[] | Record<string, any>;
  module_name: string;
  class_name: string;
  parent_id?: string;
  organization_id?: string;
}

interface EntityStateFromBackend {
  entity_type: string;
  total_count: number;
  last_updated_at?: string;
  sync_status: 'pending' | 'syncing' | 'synced' | 'failed';
  error?: string;
}

interface EntityStateListProps {
  state: any | undefined;  // Store connection for real-time updates
  sourceShortName: string;
  sourceConnectionId: string;  // Source connection ID for store subscription
  syncId?: string;  // Initial sync ID (static)
  isDark: boolean;
  onStartSync: () => void;
  isRunning: boolean;
  isPending: boolean;
  entityStates?: EntityStateFromBackend[];  // Primary source from backend
}

interface CombinedEntityRow {
  name: string;
  count: number;
  definition?: EntityDefinition;
  lastUpdated?: string;
  syncStatus?: EntityStateFromBackend["sync_status"];
}

const formatEntityDisplayName = (name: string) =>
  name
    .replace(/^DatabaseTableNode_/, "")
    .replace(/^public_/, "")
    .replace(/Table$/, "")
    .replace(/_/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

const formatEntityTimestamp = (dateStr?: string) => {
  if (!dateStr) return "Never";
  const utcDateStr = dateStr.endsWith('Z') ||
    dateStr.match(/[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?[+-]\d{2}:?\d{2}$/)
    ? dateStr
    : `${dateStr}Z`;
  const date = new Date(utcDateStr);
  if (Number.isNaN(date.getTime())) return "Unknown";

  const diffMs = Date.now() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHrs = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);
  if (diffDays > 0) return `${diffDays}d ago`;
  if (diffHrs > 0) return `${diffHrs}h ago`;
  if (diffMins > 0) return `${diffMins}m ago`;
  return "Just now";
};

// Component for animated count display with blue chip effect
const AnimatedCount: React.FC<{
  count: number;
  isDark: boolean;
  className?: string;
}> = ({ count, isDark, className }) => {
  const [prevCount, setPrevCount] = useState(count);
  const [glowIntensity, setGlowIntensity] = useState(0); // 0 to 1
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    if (count !== prevCount && count > prevCount) {
      // Clear any existing interval
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }

      // Set to full intensity immediately
      setGlowIntensity(1);
      setPrevCount(count);

      // Start decay after 200ms hold
      setTimeout(() => {
        // Use setInterval for continuous decay
        intervalRef.current = setInterval(() => {
          setGlowIntensity(prev => {
            const newIntensity = prev * 0.93; // Decay rate

            // Stop when intensity is very low
            if (newIntensity < 0.01) {
              if (intervalRef.current) {
                clearInterval(intervalRef.current);
                intervalRef.current = null;
              }
              return 0;
            }

            return newIntensity;
          });
        }, 50); // Update every 50ms
      }, 200); // Hold for 200ms before starting decay

    } else if (count !== prevCount) {
      setPrevCount(count);
    }

    // Cleanup on unmount or when count changes
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [count]);

  return (
    <span className="relative inline-flex items-center">
      {/* Blue chip background with dynamic opacity based on glowIntensity */}
      <span
        className={cn(
          "absolute inset-0 rounded-full transition-transform duration-200",
          glowIntensity > 0 ? "scale-110" : "scale-100"
        )}
        style={{
          padding: '2px 8px',
          margin: '0 -8px',
          backgroundColor: isDark
            ? `rgba(59, 130, 246, ${glowIntensity * 0.2})` // blue-500 with dynamic opacity
            : `rgba(96, 165, 250, ${glowIntensity * 0.2})`, // blue-400 with dynamic opacity
          transition: 'background-color 50ms ease-out'
        }}
      />

      {/* The actual count with dynamic text color */}
      <span
        className={cn(
          "relative tabular-nums",
          glowIntensity === 0 && "text-current", // Use default text color when not glowing
          className
        )}
        style={{
          color: glowIntensity > 0
            ? isDark
              ? `rgb(${Math.round(229 - (229 - 96) * glowIntensity)} ${Math.round(231 - (231 - 165) * glowIntensity)} ${Math.round(235 - (235 - 250) * glowIntensity)})` // Interpolate from gray-200 to blue-400
              : `rgb(${Math.round(31 + (37 - 31) * glowIntensity)} ${Math.round(41 + (99 - 41) * glowIntensity)} ${Math.round(55 + (235 - 55) * glowIntensity)})` // Interpolate from gray-800 to blue-600
            : undefined,
          transition: 'none' // Remove transition for smooth real-time updates
        }}
      >
        {count.toLocaleString()}
      </span>
    </span>
  );
};

// Component for displaying simplified schema
const SimplifiedSchemaView: React.FC<{ schema: any; isDark: boolean }> = ({ schema, isDark }) => {
  if (!schema || !schema.properties) {
    return (
      <pre className="text-xs font-mono text-muted-foreground p-4">
        {JSON.stringify(schema, null, 2)}
      </pre>
    );
  }

  const properties = Object.entries(schema.properties).filter(([key]) => key !== '...');
  const required = schema.required || [];

  // Separate required and optional fields
  const requiredFields = properties.filter(([key]) => required.includes(key));
  const optionalFields = properties.filter(([key]) => !required.includes(key));

  return (
    <div className="py-1">
      {/* Required fields section */}
      {requiredFields.length > 0 && (
        <div className="relative mb-2">
          <span className="absolute -top-1 right-4 text-[10px] font-normal tracking-wider text-muted-foreground/40">
            MANDATORY
          </span>
          <div className="space-y-0 pt-1">
            {requiredFields.map(([key, value]) => {
              const typeInfo = typeof value === 'object' && value && 'type' in value ? value as any : { type: value };
              const typeStr = typeof typeInfo.type === 'string' ? typeInfo.type : 'object';
              const description = typeInfo.description;

              return (
                <div key={key} className="group py-0.5 px-4">
                  <div className="flex items-baseline gap-3">
                    <div className="flex items-center gap-1.5 min-w-[140px]">
                      <span className={cn(DESIGN_SYSTEM.typography.sizes.label, "font-mono font-medium")}>
                        {key}
                      </span>
                      <span className="text-red-500 text-[10px]">•</span>
                    </div>
                    <span className={cn(
                      DESIGN_SYSTEM.typography.sizes.label,
                      "font-mono px-1.5 py-0.5 rounded",
                      isDark ? "text-blue-400 bg-blue-400/10" : "text-blue-700 bg-blue-50"
                    )}>
                      {typeStr}
                    </span>
                    {description && (
                      <span className={cn(DESIGN_SYSTEM.typography.sizes.label, "text-muted-foreground flex-1")}>
                        {description}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Divider */}
      {requiredFields.length > 0 && optionalFields.length > 0 && (
        <div className="h-px bg-border/30 mx-2 my-2" />
      )}

      {/* Optional fields section */}
      {optionalFields.length > 0 && (
        <div className="relative">
          <span className="absolute -top-1 right-4 text-[10px] font-normal tracking-wider text-muted-foreground/40">
            OPTIONAL
          </span>
          <div className="space-y-0 pt-1">
            {optionalFields.map(([key, value]) => {
              const typeInfo = typeof value === 'object' && value && 'type' in value ? value as any : { type: value };
              const typeStr = typeof typeInfo.type === 'string' ? typeInfo.type : 'object';
              const description = typeInfo.description;

              return (
                <div key={key} className="group py-0.5 px-4">
                  <div className="flex items-baseline gap-3">
                    <span className={cn(DESIGN_SYSTEM.typography.sizes.label, "font-mono min-w-[140px]")}>
                      {key}
                    </span>
                    <span className={cn(
                      DESIGN_SYSTEM.typography.sizes.label,
                      "font-mono px-1.5 py-0.5 rounded",
                      isDark ? "text-gray-400 bg-gray-400/10" : "text-gray-600 bg-gray-100"
                    )}>
                      {typeStr}
                    </span>
                    {description && (
                      <span className={cn(DESIGN_SYSTEM.typography.sizes.label, "text-muted-foreground flex-1")}>
                        {description}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

// Detailed Entity View Component - Separated card design
const EntityDetailView: React.FC<{
  entity: { name: string; count: number; definition?: EntityDefinition };
  syncId?: string;
  sourceConnectionId: string;
  isDark: boolean;
  onClose: () => void;
}> = ({ entity, syncId: initialSyncId, sourceConnectionId, isDark, onClose }) => {
  const [copiedSchema, setCopiedSchema] = useState(false);
  const [sampleEntities, setSampleEntities] = useState<any[]>([]);
  const [isLoadingSamples, setIsLoadingSamples] = useState(false);
  const [samplesError, setSamplesError] = useState<string | null>(null);

  // Subscribe to entity state store for real-time sync_id updates
  const storeConnection = useEntityStateStore((state) => 
    state.sourceConnections.get(sourceConnectionId)
  );

  // Use latest sync_id from store (real-time), fallback to initial prop (static)
  const syncId = storeConnection?.sync_id || initialSyncId;

  // Track previous syncId to detect when a new sync completes
  const prevSyncIdRef = useRef<string | undefined>(syncId);

  useEffect(() => {
    // Auto-fetch samples when a NEW sync completes
    if (syncId && syncId !== prevSyncIdRef.current) {
      setSampleEntities([]); // Clear old samples
      prevSyncIdRef.current = syncId;
      
      // If Example tab is already open, fetch immediately
      // Otherwise it will fetch when user switches to Example tab
    }
  }, [syncId]);

  const copySchema = () => {
    if (entity.definition?.entity_schema) {
      const schemaText = JSON.stringify(entity.definition.entity_schema, null, 2);
      navigator.clipboard.writeText(schemaText);
      setCopiedSchema(true);
      setTimeout(() => setCopiedSchema(false), 2000);
    }
  };

  // Fetch sample entities when the Example tab is selected
  const fetchSampleEntities = async (force = false) => {
    // Check if we have sync_id from props (available after sync runs)
    if (!syncId) {
      setSamplesError('No sync data available. Please run a sync first.');
      return;
    }
    
    // Don't fetch if we already have samples (unless forced)
    if (!force && sampleEntities.length > 0) {
      return;
    }
    
    setIsLoadingSamples(true);
    setSamplesError(null);
    
    try {
      // Use entity definition name if available (already includes "Entity" suffix),
      // otherwise use entity.name and add "Entity" suffix
      const entityType = entity.definition?.name 
        ? entity.definition.name  // e.g., "AsanaTaskEntity"
        : `${entity.name}Entity`;  // e.g., "AsanaTask" -> "AsanaTaskEntity"

      const url = `/entities/samples/${syncId}?entity_type=${entityType}&limit=20`;

      const response = await apiClient.get(url);

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Failed to fetch sample entities: ${response.status} - ${errorText}`);
      }

      const data = await response.json();
      setSampleEntities(data);
    } catch (error) {
      setSamplesError(`Failed to load examples: ${error instanceof Error ? error.message : 'Unknown error'}`);
    } finally {
      setIsLoadingSamples(false);
    }
  };

  return (
    <Card className={cn(
      "overflow-hidden flex flex-col max-h-[500px]",
      isDark ? "bg-gray-900/40 border-gray-800" : "bg-white border-gray-200"
    )}>
      <Tabs 
        defaultValue="schema" 
        className="flex flex-col flex-1 min-h-0 overflow-hidden"
        onValueChange={(value) => {
          if (value === 'example') {
            fetchSampleEntities();
          }
        }}
      >
        {/* Compact Header */}
        <div className={cn(
          "border-b px-4 py-2.5 flex-shrink-0",
          isDark ? "border-gray-800" : "border-gray-200"
        )}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <h4 className="text-sm font-medium">
                {entity.name}
              </h4>
              <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                {entity.count.toLocaleString()} synced
              </Badge>
            </div>

            <div className="flex items-center gap-2">
              {/* Tab Buttons */}
              <TabsList className={cn(
                "h-7 p-0.5 rounded-md",
                isDark ? "bg-gray-800/60" : "bg-gray-100"
              )}>
                <TabsTrigger
                  value="schema"
                  className={cn(
                    "h-6 px-2.5 text-[11px] font-medium rounded",
                    "data-[state=active]:bg-background data-[state=active]:shadow-sm",
                    "transition-all duration-150"
                  )}
                >
                  Schema
                </TabsTrigger>
                <TabsTrigger
                  value="example"
                  className={cn(
                    "h-6 px-2.5 text-[11px] font-medium rounded",
                    "data-[state=active]:bg-background data-[state=active]:shadow-sm",
                    "transition-all duration-150"
                  )}
                >
                  Example
                </TabsTrigger>
                <TabsTrigger
                  value="graph-events"
                  className={cn(
                    "h-6 px-2.5 text-[11px] font-medium rounded",
                    "data-[state=active]:bg-background data-[state=active]:shadow-sm",
                    "transition-all duration-150"
                  )}
                >
                  Graph Events
                </TabsTrigger>
              </TabsList>

              {/* Close button */}
              <Button
                variant="ghost"
                size="icon"
                className={cn(
                  DESIGN_SYSTEM.buttons.heights.compact,
                  "w-6",
                  DESIGN_SYSTEM.radius.button
                )}
                onClick={onClose}
              >
                <X className={DESIGN_SYSTEM.icons.inline} />
              </Button>
            </div>
          </div>
          {entity.definition?.description && (
            <p className={cn(DESIGN_SYSTEM.typography.sizes.body, "text-muted-foreground mt-1")}>
              {entity.definition.description}
            </p>
          )}
        </div>

        {/* Content */}
        <div className="flex-1 min-h-0 overflow-hidden">
          <TabsContent value="schema" className="h-full max-h-[400px] overflow-y-auto overflow-x-hidden scrollbar-thin">
            {entity.definition ? (
              <div className={cn("space-y-3 pb-2 px-1", DESIGN_SYSTEM.typography.sizes.body)}>
                {/* Schema Display */}
                <div className="relative group">
                  <Button
                    variant="ghost"
                    size="icon"
                    className={cn(
                      "absolute -top-1 right-0 w-6 opacity-0 group-hover:opacity-100 transition-opacity z-10",
                      DESIGN_SYSTEM.buttons.heights.compact,
                      isDark ? "hover:bg-gray-800" : "hover:bg-white/80"
                    )}
                    onClick={copySchema}
                  >
                    {copiedSchema ? (
                      <CheckCircle className={cn(DESIGN_SYSTEM.icons.inline, "text-green-500")} />
                    ) : (
                      <Copy className={DESIGN_SYSTEM.icons.inline} />
                    )}
                  </Button>

                  <div className="overflow-x-auto">
                    {(() => {
                      try {
                        const schema = entity.definition.entity_schema;

                        // Handle file type entities
                        if (entity.definition.type === 'file' && Array.isArray(schema)) {
                          return (
                            <div className={cn(DESIGN_SYSTEM.typography.sizes.body)}>
                              <span className="text-muted-foreground">Supported: </span>
                              <span className="font-mono">
                                {(schema as string[]).join(', ')}
                              </span>
                            </div>
                          );
                        }

                        // Parse string schemas
                        const parsedSchema = typeof schema === 'string'
                          ? JSON.parse(schema)
                          : schema;

                        return (
                          <SimplifiedSchemaView
                            schema={parsedSchema}
                            isDark={isDark}
                          />
                        );
                      } catch {
                        return (
                          <div className={cn(DESIGN_SYSTEM.typography.sizes.body, "text-muted-foreground")}>
                            Error loading schema
                          </div>
                        );
                      }
                    })()}
                  </div>
                </div>

                {/* Technical Details - More Compact */}
                <div className="space-y-1.5 pt-1 border-t border-border/30 px-4">
                  <h5 className={cn(
                    DESIGN_SYSTEM.typography.sizes.label,
                    DESIGN_SYSTEM.typography.weights.medium,
                    DESIGN_SYSTEM.typography.cases.uppercase,
                    DESIGN_SYSTEM.typography.tracking.wider,
                    "text-muted-foreground"
                  )}>
                    Technical Details
                  </h5>
                  <div className="space-y-0.5">
                    <div className={cn("flex items-center justify-between", DESIGN_SYSTEM.typography.sizes.body)}>
                      <span className="text-muted-foreground">Module</span>
                      <code className={cn(DESIGN_SYSTEM.typography.sizes.label, "font-mono")}>
                        {entity.definition.module_name}
                      </code>
                    </div>
                    <div className={cn("flex items-center justify-between", DESIGN_SYSTEM.typography.sizes.body)}>
                      <span className="text-muted-foreground">Class</span>
                      <code className={cn(DESIGN_SYSTEM.typography.sizes.label, "font-mono")}>
                        {entity.definition.class_name}
                      </code>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className={cn(DESIGN_SYSTEM.typography.sizes.body, "text-muted-foreground p-4")}>
                No schema available
              </div>
            )}
          </TabsContent>

          <TabsContent 
            value="example" 
            className="h-full max-h-[400px] overflow-y-auto overflow-x-hidden scrollbar-thin px-4 py-3"
          >
            {isLoadingSamples ? (
              <div className={cn(
                "rounded-lg border p-8 mt-4",
                isDark ? "bg-gray-900/20 border-gray-800/50" : "bg-gray-50/50 border-gray-200/50"
              )}>
                <div className="text-center space-y-3">
                  <div className="animate-spin inline-block w-6 h-6 border-2 border-current border-t-transparent text-muted-foreground rounded-full" />
                  <p className="text-sm text-muted-foreground">Loading example data...</p>
                </div>
              </div>
            ) : samplesError ? (
              <div className={cn(
                "rounded-lg border p-8 mt-4",
                isDark ? "bg-red-900/10 border-red-800/50" : "bg-red-50/50 border-red-200/50"
              )}>
                <div className="text-center space-y-3">
                  <p className="text-sm text-red-600 dark:text-red-400">{samplesError}</p>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setSampleEntities([]);
                      setSamplesError(null);
                      fetchSampleEntities();
                    }}
                  >
                    Retry
                  </Button>
                </div>
              </div>
            ) : sampleEntities.length === 0 ? (
              <div className={cn(
                "rounded-lg border p-8 mt-4",
                isDark ? "bg-gray-900/20 border-gray-800/50" : "bg-gray-50/50 border-gray-200/50"
              )}>
                <div className="text-center space-y-3">
                  <div className={cn(
                    "inline-flex p-2.5 rounded-full",
                    isDark ? "bg-gray-800/50" : "bg-gray-100"
                  )}>
                    <FileText className="h-5 w-5 text-muted-foreground" />
                  </div>
                  <div>
                    <p className="text-sm font-medium mb-1">No examples loaded yet</p>
                    <p className={cn(DESIGN_SYSTEM.typography.sizes.body, "text-muted-foreground text-left space-y-1")}>
                      <span className="block">Current syncId: <code className="text-xs bg-muted px-1 rounded">{syncId || 'NOT PROVIDED'}</code></span>
                      <span className="block text-xs">From Store: {storeConnection?.last_sync_job?.id ? '✅' : '❌'} | From Prop: {initialSyncId ? '✅' : '❌'}</span>
                    </p>
                  </div>
	                  <Button
	                    variant="outline"
	                    size="sm"
	                    onClick={() => {
	                      fetchSampleEntities(true); // Force fetch
	                    }}
                    className="mt-2"
                  >
                    🔄 Load Examples Now
                  </Button>
                </div>
              </div>
            ) : (
              <div className="space-y-3 mt-4">
                {sampleEntities.map((sample, index) => {
                  const normalized = sample.__normalized__;
                  const hasNormalized = normalized && Object.keys(normalized).length > 0;
                  
                  return (
                    <div
                      key={index}
                      className={cn(
                        "rounded-lg border p-4",
                        isDark ? "bg-gray-900/40 border-gray-800" : "bg-white border-gray-200"
                      )}
                    >
                      <div className="flex items-center justify-between mb-3">
                        <span className="text-xs font-medium text-muted-foreground">
                          Example {index + 1}
                        </span>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 px-2 text-xs"
                          onClick={() => {
                            navigator.clipboard.writeText(JSON.stringify(sample, null, 2));
                          }}
                        >
                          Copy JSON
                        </Button>
                      </div>
                      
                      {/* Normalized Data Summary */}
                      {hasNormalized && (
                        <div className={cn(
                          "rounded-lg p-3 mb-3 space-y-2",
                          isDark ? "bg-blue-950/30 border border-blue-900/50" : "bg-blue-50 border border-blue-200"
                        )}>
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-medium text-blue-600 dark:text-blue-400">
                              📊 Normalized Data
                            </span>
                          </div>
                          
                          {/* Name & URL */}
                          <div className="space-y-1">
                            {normalized.name && (
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-semibold">{normalized.name}</span>
                                {normalized.web_url && (
                                  <a 
                                    href={normalized.web_url} 
                                    target="_blank" 
                                    rel="noopener noreferrer"
                                    className="text-blue-500 hover:underline text-xs"
                                  >
                                    Open ↗
                                  </a>
                                )}
                              </div>
                            )}
                            {normalized.description && (
                              <p className="text-xs text-muted-foreground line-clamp-2">
                                {normalized.description}
                              </p>
                            )}
                          </div>
                          
                          {/* Status & Priority */}
                          <div className="flex flex-wrap gap-2">
                            {normalized.status && (
                              <span className={cn(
                                "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium",
                                isDark ? "bg-gray-800" : "bg-gray-100"
                              )}>
                                Status: {normalized.status.name}
                              </span>
                            )}
                            {normalized.priority && (
                              <span className={cn(
                                "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium",
                                isDark ? "bg-orange-900/50 text-orange-300" : "bg-orange-100 text-orange-700"
                              )}>
                                Priority: {normalized.priority.name}
                              </span>
                            )}
                          </div>
                          
                          {/* People */}
                          {normalized.people && normalized.people.length > 0 && (
                            <div className="flex flex-wrap gap-1.5">
                              {normalized.people.map((person: any, pidx: number) => (
                                <span
                                  key={pidx}
                                  className={cn(
                                    "inline-flex items-center px-2 py-0.5 rounded-full text-xs",
                                    isDark ? "bg-purple-900/50 text-purple-300" : "bg-purple-100 text-purple-700"
                                  )}
                                >
                                  👤 {person.name || person.email || person.id}
                                  {person.role && person.role !== 'other' && (
                                    <span className="ml-1 opacity-70">({person.role})</span>
                                  )}
                                </span>
                              ))}
                            </div>
                          )}
                          
                          {/* Tags */}
                          {normalized.tags && normalized.tags.length > 0 && (
                            <div className="flex flex-wrap gap-1.5">
                              {normalized.tags.map((tag: any, tidx: number) => (
                                <span
                                  key={tidx}
                                  className={cn(
                                    "inline-flex items-center px-2 py-0.5 rounded-full text-xs",
                                    isDark ? "bg-green-900/50 text-green-300" : "bg-green-100 text-green-700"
                                  )}
                                >
                                  🏷️ {tag.name}
                                </span>
                              ))}
                            </div>
                          )}
                          
                          {/* Timestamps */}
                          {(normalized.entity_created_at || normalized.due_at) && (
                            <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                              {normalized.entity_created_at && (
                                <span>Created: {new Date(normalized.entity_created_at).toLocaleDateString()}</span>
                              )}
                              {normalized.due_at && (
                                <span className="text-amber-600 dark:text-amber-400">
                                  Due: {new Date(normalized.due_at).toLocaleDateString()}
                                </span>
                              )}
                            </div>
                          )}
                        </div>
                      )}
                      
                      {/* Raw JSON (collapsed by default if normalized exists) */}
                      <details open={!hasNormalized}>
                        <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground mb-2">
                          {hasNormalized ? "View Raw Entity Data" : "Entity Data"}
                        </summary>
                        <div className={cn(
                          "rounded p-3 overflow-auto max-h-48 text-xs font-mono",
                          isDark ? "bg-gray-950/50" : "bg-gray-50"
                        )}>
                          <pre className="whitespace-pre-wrap break-words">
                            {JSON.stringify(sample, null, 2)}
                          </pre>
                        </div>
                      </details>
                    </div>
                  );
                })}
              </div>
            )}
          </TabsContent>

          {/* Graph Events Tab */}
          <TabsContent 
            value="graph-events" 
            className="h-full max-h-[400px] overflow-y-auto overflow-x-hidden scrollbar-thin px-4 py-3"
          >
            {storeConnection?.last_sync_job?.id ? (
              <GraphEventsView 
                syncJobId={storeConnection.last_sync_job.id}
                className="mt-4"
              />
            ) : (
              <div className={cn(
                "rounded-lg border p-8 mt-4",
                isDark ? "bg-gray-900/20 border-gray-800/50" : "bg-gray-50/50 border-gray-200/50"
              )}>
                <div className="text-center space-y-3">
                  <p className="text-sm text-muted-foreground">
                    No sync job available. Please run a sync first.
                  </p>
                </div>
              </div>
            )}
          </TabsContent>
        </div>
      </Tabs>
    </Card>
  );
};

// Custom hook for smooth height transitions
const useHeightTransition = (isOpen: boolean) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState<number>(0);
  const [shouldRender, setShouldRender] = useState(false);
  const measureTimeoutRef = useRef<NodeJS.Timeout>();

  useEffect(() => {
    if (isOpen) {
      setShouldRender(true);
      // Measure height after render
      measureTimeoutRef.current = setTimeout(() => {
        if (containerRef.current) {
          const contentElement = containerRef.current.firstElementChild as HTMLElement;
          if (contentElement) {
            const newHeight = contentElement.scrollHeight;
            setHeight(newHeight);
          }
        }
      }, 10);
    } else {
      setHeight(0);
      // Delay unmounting to allow close animation
      const timer = setTimeout(() => setShouldRender(false), 300);
      return () => clearTimeout(timer);
    }

    return () => {
      if (measureTimeoutRef.current) {
        clearTimeout(measureTimeoutRef.current);
      }
    };
  }, [isOpen]);

  // Re-measure on content changes
  useEffect(() => {
    if (isOpen && shouldRender && containerRef.current) {
      const resizeObserver = new ResizeObserver((entries) => {
        for (const entry of entries) {
          const newHeight = entry.contentRect.height;
          if (newHeight > 0) {
            setHeight(newHeight);
          }
        }
      });

      const contentElement = containerRef.current.firstElementChild as HTMLElement;
      if (contentElement) {
        resizeObserver.observe(contentElement);
      }

      return () => resizeObserver.disconnect();
    }
  }, [isOpen, shouldRender]);

  return { containerRef, height, shouldRender };
};

export const EntityStateList: React.FC<EntityStateListProps> = ({
  state,
  sourceShortName,
  sourceConnectionId,
  syncId,
  isDark,
  onStartSync,
  isRunning,
  isPending,
  entityStates
}) => {
  const [expandedEntity, setExpandedEntity] = useState<string | null>(null);
  const [entityDefinitions, setEntityDefinitions] = useState<EntityDefinition[]>([]);
  const [isLoadingDefinitions, setIsLoadingDefinitions] = useState(true);
  const isSyncing = isRunning || isPending;

  // Fetch entity definitions for this source
  useEffect(() => {
    const fetchEntityDefinitions = async () => {
      if (!sourceShortName) return;

      try {
        setIsLoadingDefinitions(true);
        const response = await apiClient.get(`/entities/definitions/by-source/?source_short_name=${sourceShortName}`);
        if (response.ok) {
          const data = await response.json();
          setEntityDefinitions(data);
        }
      } catch {
        setEntityDefinitions([]);
      } finally {
        setIsLoadingDefinitions(false);
      }
    };

    fetchEntityDefinitions();
  }, [sourceShortName]);

  // Combine state counts with entity definitions
  const combinedEntities = React.useMemo(() => {
    // Always prefer store data if it exists and has been updated (real-time updates)
    // The store gets updated via SSE during syncs
    const entityStatesToUse = state?.entity_states && state.entity_states.length > 0
      ? state.entity_states  // Real-time updates from store
      : entityStates;  // Fallback to prop data

    const entityMap = new Map<string, CombinedEntityRow>();

    // Create a mapping from simplified names to definitions
    // E.g., "AsanaTaskEntity" -> "AsanaTask"
    const defBySimpleName = new Map<string, EntityDefinition>();
    entityDefinitions.forEach(def => {
      if (!def.name.includes('Chunk') && !def.name.includes('Parent')) {
        // Remove "Entity" suffix if present for matching
        const simpleName = def.name.replace(/Entity$/, '');
        defBySimpleName.set(simpleName, def);
      }
    });

    if (entityStatesToUse && entityStatesToUse.length > 0) {
      entityStatesToUse.forEach((entityState: EntityStateFromBackend) => {
        // Remove "Entity" suffix from entity_type for display
        const simpleName = entityState.entity_type.replace(/Entity$/, '');
        if (!simpleName.includes('Chunk') && !simpleName.includes('Parent')) {
          const definition = defBySimpleName.get(simpleName);
          entityMap.set(simpleName, {
            name: simpleName,
            count: entityState.total_count,
            definition,
            lastUpdated: entityState.last_updated_at,
            syncStatus: entityState.sync_status,
          });
        }
      });
    }

    // Add any definitions that don't have counts yet
    defBySimpleName.forEach((def, simpleName) => {
      if (!entityMap.has(simpleName)) {
        entityMap.set(simpleName, {
          name: simpleName,
          count: 0,
          definition: def,
          syncStatus: 'pending',
        });
      }
    });

    // Sort by count (descending) then by name
    return Array.from(entityMap.values()).sort((a, b) => {
      if (b.count !== a.count) return b.count - a.count;
      return a.name.localeCompare(b.name);
    });
  }, [state?.entity_states, entityDefinitions, entityStates]);  // Watch for entity_states updates

  // Calculate total
  const totalCount = React.useMemo(() => {
    return combinedEntities.reduce((sum, entity) => sum + entity.count, 0);
  }, [combinedEntities]);

  const handleEntityClick = (entityName: string) => {
    if (expandedEntity === entityName) {
      // Closing the same entity
      setExpandedEntity(null);
    } else {
      // Check if entity exists before expanding
      const entity = combinedEntities.find(e => e.name === entityName);

      if (entity) {
        // Opening a new entity or switching - direct transition
        setExpandedEntity(entityName);

        // Smooth scroll to show the expanded content after a brief delay
        setTimeout(() => {
          const element = document.getElementById('entity-detail-view');
          if (element) {
            element.scrollIntoView({
              behavior: 'smooth',
              block: 'nearest',
              inline: 'nearest'
            });
          }
        }, 100);
      }
    }
  };

  // Use height transition for detail view
  const expandedEntityData = expandedEntity ? combinedEntities.find(e => e.name === expandedEntity) : null;

  // If expandedEntity is set but data not found, clear it
  useEffect(() => {
    if (expandedEntity && !combinedEntities.find(e => e.name === expandedEntity)) {
      setExpandedEntity(null);
    }
  }, [expandedEntity, combinedEntities]);

  const { containerRef, height, shouldRender } = useHeightTransition(!!expandedEntityData);

  return (
    <div className={cn("space-y-3", DESIGN_SYSTEM.typography.sizes.body)}>
      {/* Main Entities Card */}
      <Card className={cn(
        "overflow-hidden relative transition-all duration-500",
        DESIGN_SYSTEM.radius.card,
        isDark ? "bg-gray-900/40" : "bg-white",
        // Subtle animated border for sync status
        isSyncing ? "border-transparent" : isDark ? "border-gray-800" : "border-gray-200"
      )}
        style={{
          // Custom animated border using CSS gradient - blue for both running and pending
          ...(isSyncing && {
            background: isDark
              ? `linear-gradient(${isDark ? '#1a1f2e' : '#ffffff'}, ${isDark ? '#1a1f2e' : '#ffffff'}) padding-box,
               linear-gradient(90deg,
                 #3b82f6 0%,
                 #60a5fa 25%,
                 #3b82f6 50%,
                 #60a5fa 75%,
                 #3b82f6 100%) border-box`
              : `linear-gradient(white, white) padding-box,
               linear-gradient(90deg,
                 #3b82f6 0%,
                 #60a5fa 25%,
                 #3b82f6 50%,
                 #60a5fa 75%,
                 #3b82f6 100%) border-box`,
            border: '1px solid transparent',
            backgroundSize: isSyncing ? '200% 100%, 200% 100%' : '100% 100%, 100% 100%',
            backgroundPosition: isSyncing ? '0 0, 0 0' : '0 0, 0 0',
            animation: isSyncing ? 'borderSlide 3s linear infinite' : 'none',
          })
        }}>
        <CardContent className="p-4">
          {/* Compact Header */}
          <div className={cn("flex items-center mb-4", DESIGN_SYSTEM.spacing.gaps.standard)}>
            <h3 className={cn(
              DESIGN_SYSTEM.typography.sizes.label,
              DESIGN_SYSTEM.typography.weights.semibold,
              DESIGN_SYSTEM.typography.cases.uppercase,
              DESIGN_SYSTEM.typography.tracking.wider,
              "text-muted-foreground"
            )}>
              Entities
            </h3>
            <span className={cn(DESIGN_SYSTEM.typography.sizes.label, "text-muted-foreground")}>
              • {totalCount} total
            </span>
          </div>

          {/* Content */}
          {isLoadingDefinitions ? (
            <div className="flex items-center justify-center py-12">
              <div className={cn(DESIGN_SYSTEM.typography.sizes.body, "text-muted-foreground")}>Loading entities...</div>
            </div>
          ) : combinedEntities.length === 0 ? (
            <div className="flex items-center justify-center py-12">
              <div className="text-center">
                <div className={cn(
                  "inline-flex p-3 rounded-full mb-3",
                  isDark ? "bg-gray-800/40" : "bg-gray-100"
                )}>
                  <Database className="h-5 w-5 text-muted-foreground" />
                </div>
                <h3 className={cn(
                  DESIGN_SYSTEM.typography.sizes.header,
                  DESIGN_SYSTEM.typography.weights.medium,
                  "mb-1"
                )}>No entities synced</h3>
                <p className={cn(
                  DESIGN_SYSTEM.typography.sizes.body,
                  "text-muted-foreground mb-3 max-w-[200px] mx-auto"
                )}>
                  Start a sync to see your data entities
                </p>
                <Button
                  onClick={onStartSync}
                  variant="outline"
                  size="sm"
                  className={cn(
                    DESIGN_SYSTEM.buttons.heights.compact,
                    DESIGN_SYSTEM.typography.sizes.body,
                    DESIGN_SYSTEM.buttons.padding.secondary
                  )}
                >
                  <Plus className={cn(DESIGN_SYSTEM.icons.inline, "mr-1")} />
                  Start Sync
                </Button>
              </div>
            </div>
          ) : (
            <div className="overflow-hidden rounded-md border border-border">
              <div className="grid grid-cols-[1fr_auto] items-center gap-3 border-b border-border bg-muted/30 px-4 py-2">
                <div>
                  <div className="text-sm font-semibold text-foreground">Entity inventory</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    {combinedEntities.length} types synced from {sourceShortName || "source"}
                  </div>
                </div>
                <div className="hidden rounded-md border border-border bg-background px-2.5 py-1 text-xs text-muted-foreground sm:block">
                  Click a row to inspect schema and events
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] text-left text-sm">
                  <thead className="border-b border-border bg-muted/40 text-[10px] uppercase tracking-wider text-muted-foreground">
                    <tr>
                      <th className="px-4 py-2.5 font-medium">Entity type</th>
                      <th className="px-4 py-2.5 text-right font-medium">Records</th>
                      <th className="px-4 py-2.5 font-medium">Status</th>
                      <th className="px-4 py-2.5 font-medium">Updated</th>
                      <th className="px-4 py-2.5 text-right font-medium">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {combinedEntities.map((entity) => {
                      const isExpanded = expandedEntityData?.name === entity.name;
                      const isDisabled = entity.count === 0;
                      const share = totalCount > 0 ? Math.max(3, Math.min(100, (entity.count / totalCount) * 100)) : 0;
                      const status = entity.syncStatus || (entity.count > 0 ? "synced" : "pending");
                      const statusTone =
                        status === "failed"
                          ? "border-red-500/20 bg-red-500/10 text-red-600 dark:text-red-400"
                          : status === "syncing"
                            ? "border-blue-500/20 bg-blue-500/10 text-blue-600 dark:text-blue-400"
                            : status === "synced"
                              ? "border-green-500/20 bg-green-500/10 text-green-600 dark:text-green-400"
                              : "border-border bg-muted/40 text-muted-foreground";

                      return (
                        <tr
                          key={entity.name}
                          className={cn(
                            "group transition-colors",
                            isExpanded ? "bg-primary/5" : "hover:bg-muted/30",
                            isDisabled && "opacity-60"
                          )}
                        >
                          <td className="px-4 py-3">
                            <button
                              type="button"
                              onClick={() => !isDisabled && handleEntityClick(entity.name)}
                              disabled={isDisabled}
                              className="flex min-w-0 items-center gap-3 text-left disabled:cursor-not-allowed"
                            >
                              <span className={cn(
                                "flex h-8 w-8 shrink-0 items-center justify-center rounded-md border",
                                isExpanded
                                  ? "border-primary/30 bg-primary/10 text-primary"
                                  : "border-border bg-background text-muted-foreground"
                              )}>
                                <Database className="h-4 w-4" />
                              </span>
                              <span className="min-w-0">
                                <span className="block truncate font-medium text-foreground">
                                  {formatEntityDisplayName(entity.name)}
                                </span>
                                <span className="mt-0.5 block truncate font-mono text-xs text-muted-foreground">
                                  {entity.name}
                                </span>
                              </span>
                            </button>
                          </td>
                          <td className="px-4 py-3 text-right">
                            <div className="ml-auto w-32">
                              <div className="mb-1 font-mono text-sm font-semibold text-foreground">
                                <AnimatedCount count={entity.count} isDark={isDark} />
                              </div>
                              <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                                <div className="h-full rounded-full bg-primary" style={{ width: `${share}%` }} />
                              </div>
                            </div>
                          </td>
                          <td className="px-4 py-3">
                            <span className={cn("inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium capitalize", statusTone)}>
                              <span className="h-1.5 w-1.5 rounded-full bg-current" />
                              {status}
                            </span>
                          </td>
                          <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                            {formatEntityTimestamp(entity.lastUpdated)}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <Button
                              type="button"
                              size="sm"
                              variant={isExpanded ? "secondary" : "outline"}
                              onClick={() => handleEntityClick(entity.name)}
                              disabled={isDisabled}
                              className="h-8 gap-1.5"
                            >
                              {isExpanded ? "Hide" : "View"}
                              <ChevronRight className={cn("h-3.5 w-3.5 transition-transform", isExpanded && "rotate-90")} />
                            </Button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Separated Detail View with smooth height transition */}
      <div
        id="entity-detail-view"
        ref={containerRef}
        style={{
          height: `${height}px`,
          transition: 'height 300ms cubic-bezier(0.4, 0, 0.2, 1)',
          overflow: 'hidden'
        }}
      >
        {shouldRender && expandedEntityData && (
          <div className={cn(
            "transition-opacity duration-200",
            expandedEntityData ? "opacity-100" : "opacity-0"
          )}>
            <EntityDetailView
              entity={expandedEntityData}
              syncId={syncId}
              sourceConnectionId={sourceConnectionId}
              isDark={isDark}
              onClose={() => setExpandedEntity(null)}
            />
          </div>
        )}
      </div>
    </div>
  );
};

export default EntityStateList;
