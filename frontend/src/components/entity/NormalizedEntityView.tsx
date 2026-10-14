/**
 * NormalizedEntityView - Displays a normalized entity with rich formatting
 * 
 * Shows all normalized schema fields including:
 * - Name, description, content
 * - People (with avatars and roles)
 * - Tags (with colors)
 * - Relations (with type indicators)
 * - Status and Priority badges
 * - Custom fields
 * - Timestamps
 * - Breadcrumb navigation
 */

import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  User,
  Users,
  Tag,
  Link as LinkIcon,
  Clock,
  ExternalLink,
  Flag,
  CheckCircle,
  ChevronRight,
  Folder,
  FileText,
  Calendar,
  Hash,
} from "lucide-react";
import { cn } from "@/lib/utils";

// Types matching the NormalizedEntity schema
export interface PersonRef {
  id: string;
  name?: string;
  email?: string;
  role: string;
  avatar_url?: string;
  username?: string;
  properties?: Record<string, any>;
}

export interface TagRef {
  id: string;
  name: string;
  color?: string;
  tag_type?: string;
  properties?: Record<string, any>;
}

export interface RelationRef {
  entity_id: string;
  entity_type: string;
  relation_type: string;
  name?: string;
  properties?: Record<string, any>;
}

export interface StatusRef {
  id?: string;
  name: string;
  color?: string;
  category?: string;
  properties?: Record<string, any>;
}

export interface PriorityRef {
  id?: string;
  name: string;
  level?: number;
  color?: string;
  properties?: Record<string, any>;
}

export interface CustomFieldRef {
  id: string;
  name: string;
  field_type: string;
  value: any;
  display_value?: string;
  properties?: Record<string, any>;
}

export interface NormalizedEntityData {
  entity_id?: string;
  entity_type?: string;
  source_type?: string;
  name?: string;
  description?: string;
  content?: string;
  web_url?: string;
  people?: PersonRef[];
  tags?: TagRef[];
  relations?: RelationRef[];
  status?: StatusRef;
  priority?: PriorityRef;
  custom_fields?: CustomFieldRef[];
  entity_created_at?: string;
  entity_updated_at?: string;
  due_at?: string;
  completed_at?: string;
  properties?: Record<string, any>;
  breadcrumb_ids?: string[];
  breadcrumb_names?: string[];
}

interface NormalizedEntityViewProps {
  entity: NormalizedEntityData;
  className?: string;
  compact?: boolean;
}

// Sub-components for different sections

const PersonAvatar = ({ person }: { person: PersonRef }) => (
  <div className="flex items-center gap-3 p-2 rounded-lg bg-muted/50 hover:bg-muted transition-colors">
    <Avatar className="h-10 w-10">
      {person.avatar_url && <AvatarImage src={person.avatar_url} />}
      <AvatarFallback className="text-sm bg-primary/10">
        {(person.name || person.email || "?").charAt(0).toUpperCase()}
      </AvatarFallback>
    </Avatar>
    <div className="flex-1 min-w-0">
      <div className="flex items-center gap-2">
        <span className="font-medium truncate">
          {person.name || person.username || "Unknown"}
        </span>
        <Badge variant="secondary" className="text-xs capitalize">
          {person.role.replace("_", " ")}
        </Badge>
      </div>
      {person.email && (
        <span className="text-xs text-muted-foreground truncate block">
          {person.email}
        </span>
      )}
    </div>
  </div>
);

const PeopleSection = ({ people }: { people: PersonRef[] }) => {
  const [showAll, setShowAll] = useState(false);
  const displayPeople = showAll ? people : people.slice(0, 5);

  // Group by role
  const byRole = people.reduce((acc, person) => {
    const role = person.role || "other";
    if (!acc[role]) acc[role] = [];
    acc[role].push(person);
    return acc;
  }, {} as Record<string, PersonRef[]>);

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold flex items-center gap-2">
        <Users className="h-4 w-4" />
        People ({people.length})
      </h3>
      <div className="grid gap-2">
        {displayPeople.map((person, idx) => (
          <PersonAvatar key={idx} person={person} />
        ))}
      </div>
      {people.length > 5 && !showAll && (
        <Button
          variant="ghost"
          size="sm"
          className="w-full"
          onClick={() => setShowAll(true)}
        >
          Show all {people.length} people
        </Button>
      )}
    </div>
  );
};

const TagsSection = ({ tags }: { tags: TagRef[] }) => (
  <div className="space-y-2">
    <h3 className="text-sm font-semibold flex items-center gap-2">
      <Tag className="h-4 w-4" />
      Tags ({tags.length})
    </h3>
    <div className="flex flex-wrap gap-2">
      {tags.map((tag, idx) => (
        <Badge
          key={idx}
          variant="outline"
          className="text-sm py-1 px-2"
          style={
            tag.color
              ? { borderColor: tag.color, color: tag.color, backgroundColor: `${tag.color}10` }
              : undefined
          }
        >
          {tag.name}
          {tag.tag_type && (
            <span className="ml-1 opacity-60">({tag.tag_type})</span>
          )}
        </Badge>
      ))}
    </div>
  </div>
);

const RelationsSection = ({ relations }: { relations: RelationRef[] }) => {
  const getRelationIcon = (type: string) => {
    switch (type) {
      case "parent":
      case "child":
        return <Folder className="h-3 w-3" />;
      case "depends_on":
      case "blocks":
        return <LinkIcon className="h-3 w-3" />;
      default:
        return <LinkIcon className="h-3 w-3" />;
    }
  };

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold flex items-center gap-2">
        <LinkIcon className="h-4 w-4" />
        Relations ({relations.length})
      </h3>
      <div className="space-y-2">
        {relations.map((relation, idx) => (
          <div
            key={idx}
            className="flex items-center gap-2 p-2 rounded-lg bg-muted/50 text-sm"
          >
            {getRelationIcon(relation.relation_type)}
            <Badge variant="secondary" className="text-xs capitalize">
              {relation.relation_type.replace("_", " ")}
            </Badge>
            <ChevronRight className="h-3 w-3 text-muted-foreground" />
            <span className="truncate flex-1">
              {relation.name || relation.entity_id}
            </span>
            <span className="text-xs text-muted-foreground">
              {relation.entity_type}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};

const StatusBadge = ({ status }: { status: StatusRef }) => (
  <Badge
    variant="secondary"
    className="text-sm py-1 px-3"
    style={
      status.color
        ? { backgroundColor: `${status.color}20`, borderColor: status.color, color: status.color }
        : undefined
    }
  >
    <CheckCircle className="h-3 w-3 mr-1.5" />
    {status.name}
    {status.category && (
      <span className="ml-1 opacity-60">• {status.category}</span>
    )}
  </Badge>
);

const PriorityBadge = ({ priority }: { priority: PriorityRef }) => (
  <Badge
    variant="outline"
    className="text-sm py-1 px-3"
    style={
      priority.color
        ? { borderColor: priority.color, color: priority.color }
        : undefined
    }
  >
    <Flag className="h-3 w-3 mr-1.5" />
    {priority.name}
    {priority.level !== undefined && (
      <span className="ml-1 opacity-60">L{priority.level}</span>
    )}
  </Badge>
);

const CustomFieldsSection = ({ fields }: { fields: CustomFieldRef[] }) => (
  <div className="space-y-2">
    <h3 className="text-sm font-semibold flex items-center gap-2">
      <Hash className="h-4 w-4" />
      Custom Fields ({fields.length})
    </h3>
    <div className="grid gap-2">
      {fields.map((field, idx) => (
        <div
          key={idx}
          className="flex items-center justify-between p-2 rounded-lg bg-muted/50 text-sm"
        >
          <div className="flex items-center gap-2">
            <span className="font-medium">{field.name}</span>
            <Badge variant="outline" className="text-xs">
              {field.field_type}
            </Badge>
          </div>
          <span className="text-muted-foreground truncate max-w-[200px]">
            {field.display_value || String(field.value)}
          </span>
        </div>
      ))}
    </div>
  </div>
);

const TimestampsSection = ({ entity }: { entity: NormalizedEntityData }) => {
  const timestamps = [
    { label: "Created", value: entity.entity_created_at },
    { label: "Updated", value: entity.entity_updated_at },
    { label: "Due", value: entity.due_at },
    { label: "Completed", value: entity.completed_at },
  ].filter((t) => t.value);

  if (timestamps.length === 0) return null;

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold flex items-center gap-2">
        <Calendar className="h-4 w-4" />
        Timestamps
      </h3>
      <div className="grid grid-cols-2 gap-2">
        {timestamps.map((ts, idx) => (
          <div key={idx} className="flex items-center gap-2 text-sm">
            <Clock className="h-3 w-3 text-muted-foreground" />
            <span className="text-muted-foreground">{ts.label}:</span>
            <span>{new Date(ts.value!).toLocaleDateString()}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

const BreadcrumbSection = ({ names }: { names: string[] }) => (
  <div className="flex items-center gap-1 text-sm text-muted-foreground overflow-x-auto">
    <Folder className="h-4 w-4 flex-shrink-0" />
    {names.map((name, idx) => (
      <span key={idx} className="flex items-center">
        {idx > 0 && <ChevronRight className="h-3 w-3 mx-1" />}
        <span className="truncate max-w-[150px]">{name}</span>
      </span>
    ))}
  </div>
);

// Main component
export const NormalizedEntityView = ({
  entity,
  className,
  compact = false,
}: NormalizedEntityViewProps) => {
  if (compact) {
    return (
      <div className={cn("space-y-3 p-3 rounded-lg bg-muted/30", className)}>
        {/* Header */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            {entity.name && (
              <h3 className="font-semibold truncate">{entity.name}</h3>
            )}
            {entity.entity_type && (
              <span className="text-xs text-muted-foreground">
                {entity.entity_type}
              </span>
            )}
          </div>
          {entity.web_url && (
            <a
              href={entity.web_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-muted-foreground hover:text-foreground"
            >
              <ExternalLink className="h-4 w-4" />
            </a>
          )}
        </div>

        {/* Status/Priority */}
        {(entity.status || entity.priority) && (
          <div className="flex items-center gap-2">
            {entity.status && <StatusBadge status={entity.status} />}
            {entity.priority && <PriorityBadge priority={entity.priority} />}
          </div>
        )}

        {/* People preview */}
        {entity.people && entity.people.length > 0 && (
          <div className="flex items-center gap-1">
            <User className="h-3 w-3 text-muted-foreground" />
            <span className="text-xs text-muted-foreground">
              {entity.people.length} {entity.people.length === 1 ? "person" : "people"}
            </span>
          </div>
        )}

        {/* Tags preview */}
        {entity.tags && entity.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {entity.tags.slice(0, 3).map((tag, idx) => (
              <Badge
                key={idx}
                variant="outline"
                className="text-xs"
                style={tag.color ? { borderColor: tag.color } : undefined}
              >
                {tag.name}
              </Badge>
            ))}
            {entity.tags.length > 3 && (
              <span className="text-xs text-muted-foreground">
                +{entity.tags.length - 3}
              </span>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <Card className={cn("w-full", className)}>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <CardTitle className="flex items-center gap-2">
              {entity.name || "Unnamed Entity"}
              {entity.web_url && (
                <a
                  href={entity.web_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-muted-foreground hover:text-foreground"
                >
                  <ExternalLink className="h-4 w-4" />
                </a>
              )}
            </CardTitle>
            {entity.entity_type && (
              <CardDescription className="flex items-center gap-2 mt-1">
                <Badge variant="outline" className="text-xs">
                  {entity.entity_type}
                </Badge>
                {entity.source_type && (
                  <Badge variant="secondary" className="text-xs">
                    {entity.source_type}
                  </Badge>
                )}
              </CardDescription>
            )}
          </div>

          {/* Status and Priority */}
          <div className="flex items-center gap-2 flex-shrink-0">
            {entity.status && <StatusBadge status={entity.status} />}
            {entity.priority && <PriorityBadge priority={entity.priority} />}
          </div>
        </div>

        {/* Breadcrumb */}
        {entity.breadcrumb_names && entity.breadcrumb_names.length > 0 && (
          <BreadcrumbSection names={entity.breadcrumb_names} />
        )}
      </CardHeader>

      <CardContent className="space-y-6">
        {/* Description */}
        {entity.description && (
          <div className="space-y-2">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <FileText className="h-4 w-4" />
              Description
            </h3>
            <p className="text-sm text-muted-foreground whitespace-pre-wrap">
              {entity.description}
            </p>
          </div>
        )}

        {/* People */}
        {entity.people && entity.people.length > 0 && (
          <>
            <Separator />
            <PeopleSection people={entity.people} />
          </>
        )}

        {/* Tags */}
        {entity.tags && entity.tags.length > 0 && (
          <>
            <Separator />
            <TagsSection tags={entity.tags} />
          </>
        )}

        {/* Relations */}
        {entity.relations && entity.relations.length > 0 && (
          <>
            <Separator />
            <RelationsSection relations={entity.relations} />
          </>
        )}

        {/* Custom Fields */}
        {entity.custom_fields && entity.custom_fields.length > 0 && (
          <>
            <Separator />
            <CustomFieldsSection fields={entity.custom_fields} />
          </>
        )}

        {/* Timestamps */}
        <Separator />
        <TimestampsSection entity={entity} />

        {/* Additional Properties (if any) */}
        {entity.properties && Object.keys(entity.properties).length > 0 && (
          <>
            <Separator />
            <div className="space-y-2">
              <h3 className="text-sm font-semibold">Additional Properties</h3>
              <pre className="text-xs bg-muted p-3 rounded-lg overflow-auto max-h-48">
                {JSON.stringify(entity.properties, null, 2)}
              </pre>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
};

export default NormalizedEntityView;
