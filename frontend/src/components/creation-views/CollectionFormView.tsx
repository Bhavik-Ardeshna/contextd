import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCollectionCreationStore } from '@/stores/collectionCreationStore';
import { apiClient } from '@/lib/api';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { ArrowRight, Database, Loader2, Plug } from 'lucide-react';
import { ValidatedInput } from '@/components/ui/validated-input';
import { collectionNameValidation } from '@/lib/validation/rules';

interface CollectionFormViewProps {
  humanReadableId: string;
}

export const CollectionFormView: React.FC<CollectionFormViewProps> = ({ humanReadableId }) => {
  const navigate = useNavigate();
  const {
    collectionName,
    selectedSource,
    sourceName,
    closeModal,
    reset,
    setCollectionData,
    setCollectionId,
  } = useCollectionCreationStore();

  const [name, setName] = useState(collectionName);
  const [isCreating, setIsCreating] = useState(false);
  const isConnectorFirstFlow = Boolean(selectedSource);
  const trimmedName = name.trim();
  const canCreate = trimmedName.length >= 4 && trimmedName.length <= 64 && !isCreating;
  const nextStepLabel = isConnectorFirstFlow
    ? `Configure ${sourceName || selectedSource}`
    : 'Choose one source';
  const actionLabel = isConnectorFirstFlow
    ? 'Create and configure'
    : 'Create and continue';

  // Update store when name changes
  useEffect(() => {
    setCollectionData(name);
  }, [name, setCollectionData]);

  const handleCreate = async () => {
    if (!trimmedName) {
      toast.error('Please enter a database name');
      return;
    }

    setIsCreating(true);
    try {
      const response = await apiClient.post('/collections', {
        name: trimmedName,
        description: `ContextD database boundary for ${trimmedName}`,
      });

      if (!response.ok) {
        throw new Error('Failed to create context database');
      }

      const collection = await response.json();
      const collectionId = collection.readable_id || collection.id;

      // Store collection data
      setCollectionData(trimmedName);
      setCollectionId(collectionId);

      const databaseParam = encodeURIComponent(collectionId);
      const normalizedSource = selectedSource?.toLowerCase().replace('-', '_');
      const setupProviders = new Set(['postgres', 'postgresql', 'clickhouse']);

      closeModal();
      window.setTimeout(() => reset(), 250);

      if (normalizedSource && setupProviders.has(normalizedSource)) {
        const setupProvider = normalizedSource === 'postgres' ? 'postgresql' : normalizedSource;
        navigate(`/sources/${setupProvider}/setup?database=${databaseParam}`);
        return;
      }

      navigate(`/sources?database=${databaseParam}`);

    } catch (error) {
      console.error('Error creating context database:', error);
      toast.error('Failed to create context database');
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div className="flex max-h-[92vh] flex-col bg-card">
      <div className="flex-1 overflow-auto px-6 pb-5 pt-6">
        <div className="flex items-start gap-3 pr-12">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary">
            <Database className="h-5 w-5" />
          </span>
          <div className="min-w-0">
            <h2 className="text-2xl font-semibold tracking-tight text-foreground">
              Create database
            </h2>
            <p className="mt-1 max-w-[400px] text-sm leading-6 text-muted-foreground">
              Name the workbench. You will attach one source in the next step.
            </p>
          </div>
        </div>

        <section className="mt-6">
          <label htmlFor="collection-name" className="text-sm font-medium text-foreground">
            Database name
          </label>
          <ValidatedInput
            id="collection-name"
            type="text"
            placeholder="Customer 360"
            value={name}
            onChange={setName}
            onKeyDown={(event) => event.key === 'Enter' && canCreate && handleCreate()}
            autoFocus
            validation={collectionNameValidation}
            className="mt-2 h-11 rounded-md border-border bg-background text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:ring-1 focus:ring-primary/20"
          />

          <div className="mt-3 flex items-center justify-between gap-3 rounded-md border border-border bg-muted/25 px-3 py-2">
            <span className="text-xs text-muted-foreground">Readable ID</span>
            <span className="min-w-0 truncate text-right font-mono text-xs text-foreground">
              {humanReadableId || 'generated after a valid name'}
            </span>
          </div>
        </section>

        <div className="mt-5 rounded-lg border border-primary/20 bg-primary/5 p-3">
          <div className="flex items-start gap-3">
            <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-primary/20 bg-card text-primary">
              <Plug className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-foreground">Next: {nextStepLabel}</div>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                {isConnectorFirstFlow
                  ? `The next step opens ${sourceName || selectedSource} configuration.`
                  : 'Each database accepts one active connector in this phase.'}
              </p>
            </div>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-end gap-3 border-t border-border bg-muted/20 px-6 py-4">
        <button
          onClick={handleCreate}
          disabled={!canCreate}
          className={cn(
            "inline-flex h-10 min-w-[190px] shrink-0 items-center justify-center gap-2 rounded-md px-4 text-sm font-medium transition-colors",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            canCreate
              ? "bg-primary text-primary-foreground shadow-sm shadow-primary/20 hover:bg-primary/90"
              : "bg-muted text-muted-foreground"
          )}
        >
          {isCreating ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Creating
            </>
          ) : (
            <>
              {actionLabel}
              <ArrowRight className="h-3.5 w-3.5" />
            </>
          )}
        </button>
      </div>
    </div>
  );
};
