/**
 * Knowledge Graph Page
 * 
 * Full-page view of the unified knowledge graph
 */

import { KnowledgeGraphView } from '@/components/graph/KnowledgeGraphView';
import { useOrganizationStore } from '@/lib/stores/organizations';
import { useCollectionsStore, type SourceConnection } from '@/lib/stores/collections';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { apiClient } from '@/lib/api';
import { InfoIcon, Loader2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

export function GraphPage() {
  const currentOrganization = useOrganizationStore((state) => state.currentOrganization);
  const { collections, fetchCollections, isLoading: collectionsLoading } = useCollectionsStore();
  const [sourceConnections, setSourceConnections] = useState<SourceConnection[]>([]);
  const [connectionsLoading, setConnectionsLoading] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const databaseId = searchParams.get('database') || undefined;

  useEffect(() => {
    fetchCollections().catch(() => undefined);
  }, [fetchCollections]);

  useEffect(() => {
    let cancelled = false;
    setConnectionsLoading(true);
    apiClient
      .get('/source-connections/?limit=1000')
      .then(async (response) => {
        if (!response.ok) return [];
        return (await response.json()) as SourceConnection[];
      })
      .then((connections) => {
        if (!cancelled) setSourceConnections(connections);
      })
      .catch(() => {
        if (!cancelled) setSourceConnections([]);
      })
      .finally(() => {
        if (!cancelled) setConnectionsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const connectionByCollection = useMemo(() => {
    const byCollection = new Map<string, SourceConnection>();
    sourceConnections.forEach((connection) => {
      const readableId = connection.readable_collection_id || connection.collection;
      if (!readableId) return;
      const existing = byCollection.get(readableId);
      if (!existing || Number(connection.entity_count || 0) > Number(existing.entity_count || 0)) {
        byCollection.set(readableId, connection);
      }
    });
    return byCollection;
  }, [sourceConnections]);

  const collectionOptions = useMemo(
    () =>
      collections
        .map((collection) => {
          const connection = connectionByCollection.get(collection.readable_id);
          const entityCount = Number(connection?.entity_count || 0);
          return {
            value: collection.readable_id,
            label: collection.name || collection.readable_id,
            count: entityCount,
            status: entityCount > 0 ? 'graph ready' : connection ? 'waiting for sync' : 'no source',
          };
        })
        .sort((left, right) => {
          const leftReady = Number(left.count || 0) > 0 ? 1 : 0;
          const rightReady = Number(right.count || 0) > 0 ? 1 : 0;
          if (leftReady !== rightReady) return rightReady - leftReady;
          return Number(right.count || 0) - Number(left.count || 0);
        }),
    [collections, connectionByCollection]
  );

  const defaultDatabaseId = useMemo(() => {
    if (databaseId) return databaseId;
    return collectionOptions.find((option) => Number(option.count || 0) > 0)?.value || collectionOptions[0]?.value;
  }, [collectionOptions, databaseId]);

  useEffect(() => {
    if (databaseId || !defaultDatabaseId) return;
    const next = new URLSearchParams(searchParams);
    next.set('database', defaultDatabaseId);
    setSearchParams(next, { replace: true });
  }, [databaseId, defaultDatabaseId, searchParams, setSearchParams]);

  const handleCollectionChange = (collectionId: string) => {
    const next = new URLSearchParams(searchParams);
    if (collectionId) {
      next.set('database', collectionId);
    } else {
      next.delete('database');
    }
    setSearchParams(next, { replace: true });
  };

  if (!currentOrganization) {
    return (
      <div className="container mx-auto p-6">
        <Alert>
          <InfoIcon className="h-4 w-4" />
          <AlertDescription>
            Please select an organization to view the ContextD graph
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  if (!databaseId && (collectionsLoading || connectionsLoading)) {
    return (
      <div className="flex h-full items-center justify-center bg-background text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin text-primary" />
        Loading graph workbench...
      </div>
    );
  }

  return (
    <div className="h-full w-full flex flex-col">
      <KnowledgeGraphView
        organizationId={currentOrganization.id}
        initialCollectionId={databaseId || defaultDatabaseId}
        lockCollection={false}
        collectionOptions={collectionOptions}
        onCollectionChange={handleCollectionChange}
      />
    </div>
  );
}
