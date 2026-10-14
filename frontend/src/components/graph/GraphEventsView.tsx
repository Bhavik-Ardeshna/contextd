import { useState, useEffect } from "react";
import { apiClient } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Loader2, AlertCircle, GitGraph, Link as LinkIcon, FileText, ChevronDown, ChevronRight, User, Tag, Clock, ExternalLink, Flag } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

interface GraphEventsViewProps {
  syncJobId: string;
  className?: string;
}

// Normalized entity data types
interface PersonRef {
  id: string;
  name?: string;
  email?: string;
  role: string;
  avatar_url?: string;
  username?: string;
}

interface TagRef {
  id: string;
  name: string;
  color?: string;
  tag_type?: string;
}

interface StatusRef {
  id?: string;
  name: string;
  color?: string;
  category?: string;
}

interface PriorityRef {
  id?: string;
  name: string;
  level?: number;
  color?: string;
}

interface NormalizedEntityData {
  name?: string;
  description?: string;
  content?: string;
  web_url?: string;
  source_type?: string;
  entity_type?: string;
  people?: PersonRef[];
  tags?: TagRef[];
  status?: StatusRef;
  priority?: PriorityRef;
  entity_created_at?: string;
  entity_updated_at?: string;
  due_at?: string;
  breadcrumb_names?: string[];
}

interface GraphEventData {
  sync_job_id: string;
  total_events: number;
  event_counts: {
    node_events: number;
    edge_events: number;
    metadata_events: number;
  };
  events_by_entity: Record<string, any[]>;
  events_by_type: {
    node: any[];
    edge: any[];
    metadata: any[];
  };
  normalized_entities?: Record<string, NormalizedEntityData>;
}

// Component to display people with avatars and roles
const PeopleDisplay = ({ people }: { people?: PersonRef[] }) => {
  if (!people || people.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2">
      {people.map((person, idx) => (
        <div
          key={idx}
          className="flex items-center gap-1.5 bg-background/50 rounded-full px-2 py-1"
        >
          <Avatar className="h-5 w-5">
            <AvatarFallback className="text-[10px]">
              {(person.name || person.email || "?").charAt(0).toUpperCase()}
            </AvatarFallback>
          </Avatar>
          <span className="text-xs">{person.name || person.email || person.id}</span>
          <Badge variant="secondary" className="text-[10px] px-1 py-0">
            {person.role}
          </Badge>
        </div>
      ))}
    </div>
  );
};

// Component to display tags with colors
const TagsDisplay = ({ tags }: { tags?: TagRef[] }) => {
  if (!tags || tags.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-1.5">
      {tags.map((tag, idx) => (
        <Badge
          key={idx}
          variant="outline"
          className="text-xs"
          style={tag.color ? { borderColor: tag.color, color: tag.color } : undefined}
        >
          <Tag className="h-3 w-3 mr-1" />
          {tag.name}
        </Badge>
      ))}
    </div>
  );
};

// Component to display status
const StatusDisplay = ({ status }: { status?: StatusRef }) => {
  if (!status) return null;

  return (
    <Badge
      variant="secondary"
      className="text-xs"
      style={status.color ? { backgroundColor: `${status.color}20`, borderColor: status.color } : undefined}
    >
      {status.name}
      {status.category && (
        <span className="ml-1 opacity-70">({status.category})</span>
      )}
    </Badge>
  );
};

// Component to display priority
const PriorityDisplay = ({ priority }: { priority?: PriorityRef }) => {
  if (!priority) return null;

  return (
    <Badge
      variant="outline"
      className="text-xs"
      style={priority.color ? { borderColor: priority.color, color: priority.color } : undefined}
    >
      <Flag className="h-3 w-3 mr-1" />
      {priority.name}
      {priority.level !== undefined && (
        <span className="ml-1 opacity-70">(L{priority.level})</span>
      )}
    </Badge>
  );
};

// Normalized entity summary component
const NormalizedEntitySummary = ({ normalized }: { normalized?: NormalizedEntityData }) => {
  if (!normalized) return null;

  return (
    <div className="mt-2 p-3 bg-background/50 rounded-lg space-y-2">
      {/* Entity name and description */}
      {normalized.name && (
        <div className="flex items-center justify-between">
          <span className="font-medium text-sm">{normalized.name}</span>
          {normalized.web_url && (
            <a
              href={normalized.web_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
            >
              <ExternalLink className="h-3 w-3" />
              Open
            </a>
          )}
        </div>
      )}

      {normalized.description && (
        <p className="text-xs text-muted-foreground line-clamp-2">
          {normalized.description}
        </p>
      )}

      {/* Status and Priority row */}
      {(normalized.status || normalized.priority) && (
        <div className="flex items-center gap-2 flex-wrap">
          <StatusDisplay status={normalized.status} />
          <PriorityDisplay priority={normalized.priority} />
        </div>
      )}

      {/* People */}
      {normalized.people && normalized.people.length > 0 && (
        <div>
          <span className="text-xs text-muted-foreground flex items-center gap-1 mb-1">
            <User className="h-3 w-3" />
            People ({normalized.people.length})
          </span>
          <PeopleDisplay people={normalized.people} />
        </div>
      )}

      {/* Tags */}
      {normalized.tags && normalized.tags.length > 0 && (
        <div>
          <span className="text-xs text-muted-foreground flex items-center gap-1 mb-1">
            <Tag className="h-3 w-3" />
            Tags
          </span>
          <TagsDisplay tags={normalized.tags} />
        </div>
      )}

      {/* Timestamps */}
      {(normalized.entity_created_at || normalized.due_at) && (
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          {normalized.entity_created_at && (
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              Created: {new Date(normalized.entity_created_at).toLocaleDateString()}
            </span>
          )}
          {normalized.due_at && (
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              Due: {new Date(normalized.due_at).toLocaleDateString()}
            </span>
          )}
        </div>
      )}

      {/* Breadcrumb */}
      {normalized.breadcrumb_names && normalized.breadcrumb_names.length > 0 && (
        <div className="text-xs text-muted-foreground">
          📁 {normalized.breadcrumb_names.join(" > ")}
        </div>
      )}
    </div>
  );
};

// Event card component with expandable JSON and normalized data
const EventCard = ({ event, index, normalized }: { event: any; index: number; normalized?: NormalizedEntityData }) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [showJson, setShowJson] = useState(false);

  // Use event's normalized data if available, otherwise use passed normalized
  const eventNormalized = event.normalized_entity || normalized;

  return (
    <div className="border rounded-lg bg-muted/50 overflow-hidden">
      <Button
        variant="ghost"
        className="w-full p-3 hover:bg-muted/70 text-left flex items-start justify-between"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex-1 space-y-2">
          <div className="flex items-center justify-between">
            <Badge variant="outline">{event.event_type}</Badge>
            <span className="text-xs text-muted-foreground">
              {event.entity_type}
            </span>
          </div>
          {/* Show entity name from normalized data if available */}
          {event.entity_name && (
            <div className="text-sm font-medium">{event.entity_name}</div>
          )}
          <div className="text-xs text-muted-foreground">
            Field: <span className="font-mono">{event.field_name}</span>
          </div>
          {/* Quick preview of people and tags */}
          {event.people && event.people.length > 0 && (
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <User className="h-3 w-3" />
              {event.people.length} {event.people.length === 1 ? "person" : "people"}
            </div>
          )}
          {event.tags && event.tags.length > 0 && (
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <Tag className="h-3 w-3" />
              {event.tags.length} {event.tags.length === 1 ? "tag" : "tags"}
            </div>
          )}
        </div>
        <div className="ml-2 flex-shrink-0">
          {isExpanded ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
        </div>
      </Button>
      
      {isExpanded && (
        <div className="px-3 pb-3 border-t">
          {/* Normalized entity summary */}
          {eventNormalized && (
            <NormalizedEntitySummary normalized={eventNormalized} />
          )}
          
          {/* Toggle for raw JSON */}
          <div className="mt-2">
            <Button
              variant="ghost"
              size="sm"
              className="text-xs"
              onClick={(e) => {
                e.stopPropagation();
                setShowJson(!showJson);
              }}
            >
              {showJson ? "Hide" : "Show"} Raw JSON
            </Button>
            
            {showJson && (
              <pre className="text-xs bg-background p-3 rounded mt-2 overflow-auto max-h-96 font-mono">
                {JSON.stringify(event, null, 2)}
              </pre>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export const GraphEventsView = ({ syncJobId, className }: GraphEventsViewProps) => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [eventData, setEventData] = useState<GraphEventData | null>(null);

  useEffect(() => {
    const fetchEvents = async () => {
      try {
        setLoading(true);
        setError(null);

        const response = await apiClient.get(
          `/graph-events/sync-jobs/${syncJobId}/graph-events`
        );

        if (!response.ok) {
          throw new Error(`Failed to fetch events: ${response.status}`);
        }

        const data = await response.json();
        setEventData(data);
      } catch (err) {
        console.error("Error fetching graph events:", err);
        setError(err instanceof Error ? err.message : "Failed to load events");
      } finally {
        setLoading(false);
      }
    };

    if (syncJobId) {
      fetchEvents();
    }
  }, [syncJobId]);

  if (loading) {
    return (
      <Card className={cn("w-full", className)}>
        <CardContent className="flex items-center justify-center py-12">
          <div className="flex flex-col items-center gap-3">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            <p className="text-sm text-muted-foreground">Loading graph events...</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Alert variant="destructive" className={className}>
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (!eventData || eventData.total_events === 0) {
    return (
      <Card className={cn("w-full", className)}>
        <CardContent className="py-12">
          <div className="text-center text-muted-foreground">
            <GitGraph className="h-12 w-12 mx-auto mb-3 opacity-50" />
            <p>No graph events generated for this sync</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className={cn("w-full", className)}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <GitGraph className="h-5 w-5" />
          Graph Events
        </CardTitle>
        <CardDescription>
          Generated {eventData.total_events} events for sync job
        </CardDescription>
      </CardHeader>
      <CardContent>
        {/* Summary badges */}
        <div className="flex gap-2 mb-6">
          <Badge variant="secondary" className="flex items-center gap-1">
            <GitGraph className="h-3 w-3" />
            {eventData.event_counts.node_events} Nodes
          </Badge>
          <Badge variant="secondary" className="flex items-center gap-1">
            <LinkIcon className="h-3 w-3" />
            {eventData.event_counts.edge_events} Edges
          </Badge>
          <Badge variant="secondary" className="flex items-center gap-1">
            <FileText className="h-3 w-3" />
            {eventData.event_counts.metadata_events} Metadata
          </Badge>
        </div>

        {/* Tabs for different views */}
        <Tabs defaultValue="by-type" className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="by-type">By Type</TabsTrigger>
            <TabsTrigger value="by-entity">By Entity</TabsTrigger>
          </TabsList>

          {/* By Type View */}
          <TabsContent value="by-type" className="space-y-4">
            {/* Node Events */}
            {eventData.events_by_type.node.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold mb-2 flex items-center gap-2">
                  <GitGraph className="h-4 w-4" />
                  Node Events ({eventData.events_by_type.node.length})
                </h3>
                <div className="space-y-2">
                  {eventData.events_by_type.node.slice(0, 10).map((event, idx) => (
                    <EventCard 
                      key={idx} 
                      event={event} 
                      index={idx}
                      normalized={eventData.normalized_entities?.[event.entity_id]}
                    />
                  ))}
                  {eventData.events_by_type.node.length > 10 && (
                    <p className="text-xs text-muted-foreground text-center py-2">
                      ... and {eventData.events_by_type.node.length - 10} more
                    </p>
                  )}
                </div>
              </div>
            )}

            {/* Edge Events */}
            {eventData.events_by_type.edge.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold mb-2 flex items-center gap-2">
                  <LinkIcon className="h-4 w-4" />
                  Edge Events ({eventData.events_by_type.edge.length})
                </h3>
                <div className="space-y-2">
                  {eventData.events_by_type.edge.slice(0, 10).map((event, idx) => (
                    <EventCard 
                      key={idx} 
                      event={event} 
                      index={idx}
                      normalized={eventData.normalized_entities?.[event.entity_id]}
                    />
                  ))}
                  {eventData.events_by_type.edge.length > 10 && (
                    <p className="text-xs text-muted-foreground text-center py-2">
                      ... and {eventData.events_by_type.edge.length - 10} more
                    </p>
                  )}
                </div>
              </div>
            )}

            {/* Metadata Events */}
            {eventData.events_by_type.metadata.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold mb-2 flex items-center gap-2">
                  <FileText className="h-4 w-4" />
                  Metadata Events ({eventData.events_by_type.metadata.length})
                </h3>
                <div className="space-y-2">
                  {eventData.events_by_type.metadata.slice(0, 10).map((event, idx) => (
                    <EventCard 
                      key={idx} 
                      event={event} 
                      index={idx}
                      normalized={eventData.normalized_entities?.[event.entity_id]}
                    />
                  ))}
                  {eventData.events_by_type.metadata.length > 10 && (
                    <p className="text-xs text-muted-foreground text-center py-2">
                      ... and {eventData.events_by_type.metadata.length - 10} more
                    </p>
                  )}
                </div>
              </div>
            )}
          </TabsContent>

          {/* By Entity View */}
          <TabsContent value="by-entity" className="space-y-4">
            {Object.entries(eventData.events_by_entity)
              .slice(0, 5)
              .map(([entityId, events]) => {
                const normalizedEntity = eventData.normalized_entities?.[entityId];
                return (
                  <div key={entityId} className="border rounded-lg p-3">
                    {/* Entity header with normalized data */}
                    <div className="mb-3">
                      {normalizedEntity?.name ? (
                        <div className="flex items-center justify-between">
                          <h3 className="text-sm font-semibold">{normalizedEntity.name}</h3>
                          {normalizedEntity.web_url && (
                            <a
                              href={normalizedEntity.web_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-xs text-muted-foreground hover:text-foreground"
                            >
                              <ExternalLink className="h-3 w-3" />
                            </a>
                          )}
                        </div>
                      ) : (
                        <h3 className="text-sm font-semibold truncate">
                          Entity: <span className="font-mono text-xs">{entityId}</span>
                        </h3>
                      )}
                      
                      {/* Show status/priority inline for entity */}
                      {(normalizedEntity?.status || normalizedEntity?.priority) && (
                        <div className="flex items-center gap-2 mt-1">
                          <StatusDisplay status={normalizedEntity?.status} />
                          <PriorityDisplay priority={normalizedEntity?.priority} />
                        </div>
                      )}
                      
                      {/* People summary for entity */}
                      {normalizedEntity?.people && normalizedEntity.people.length > 0 && (
                        <div className="mt-2">
                          <PeopleDisplay people={normalizedEntity.people.slice(0, 3)} />
                          {normalizedEntity.people.length > 3 && (
                            <span className="text-xs text-muted-foreground ml-1">
                              +{normalizedEntity.people.length - 3} more
                            </span>
                          )}
                        </div>
                      )}
                      
                      {/* Tags for entity */}
                      {normalizedEntity?.tags && normalizedEntity.tags.length > 0 && (
                        <div className="mt-2">
                          <TagsDisplay tags={normalizedEntity.tags.slice(0, 5)} />
                          {normalizedEntity.tags.length > 5 && (
                            <span className="text-xs text-muted-foreground ml-1">
                              +{normalizedEntity.tags.length - 5} more
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                    
                    {/* Events for this entity */}
                    <div className="space-y-2">
                      <span className="text-xs text-muted-foreground">
                        {events.length} {events.length === 1 ? "event" : "events"}
                      </span>
                      {events.slice(0, 5).map((event: any, idx: number) => (
                        <EventCard 
                          key={idx} 
                          event={event} 
                          index={idx}
                          normalized={normalizedEntity}
                        />
                      ))}
                      {events.length > 5 && (
                        <p className="text-xs text-muted-foreground text-center py-1">
                          ... and {events.length - 5} more
                        </p>
                      )}
                    </div>
                  </div>
                );
              })}
            {Object.keys(eventData.events_by_entity).length > 5 && (
              <p className="text-xs text-muted-foreground text-center py-2">
                ... and {Object.keys(eventData.events_by_entity).length - 5} more
                entities
              </p>
            )}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
};

export default GraphEventsView;
