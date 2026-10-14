import React from 'react';
import { cn } from '@/lib/utils';
import { useTheme } from '@/lib/theme-provider';
import { getAppIconUrl } from '@/lib/utils/icons';
import { ArrowRight, Clock3, Database, GitBranch, Plug } from 'lucide-react';

interface CollectionVisualizationProps {
  collectionName: string;
  humanReadableId: string;
  selectedSource?: string;
  sourceName?: string;
  sourceConnectionName?: string;
  currentStep: string;
}

export const CollectionVisualization: React.FC<CollectionVisualizationProps> = ({
  collectionName,
  humanReadableId,
  selectedSource,
  sourceName,
  sourceConnectionName,
  currentStep,
}) => {
  const { resolvedTheme } = useTheme();
  const sourceLabel = sourceConnectionName || sourceName || selectedSource || 'Source not selected';
  const databaseLabel = collectionName || 'Untitled database';
  const readableId = humanReadableId || 'generated-id';
  const sourceIsSelected = Boolean(selectedSource);

  const getSourceIcon = () => {
    if (!selectedSource) return null;

    const iconUrl = getAppIconUrl(selectedSource, resolvedTheme);

    return (
      <img
        src={iconUrl}
        alt={sourceName || selectedSource}
        className="h-8 w-8 rounded-md object-contain"
      />
    );
  };

  const flowSteps = [
    {
      label: 'Database',
      value: databaseLabel,
      icon: Database,
      state: 'active',
    },
    {
      label: 'Source',
      value: sourceIsSelected ? sourceLabel : 'choose one connector',
      icon: Plug,
      state: sourceIsSelected ? 'active' : 'next',
    },
    {
      label: 'Sync',
      value: 'cursor + schedule',
      icon: Clock3,
      state: 'pending',
    },
    {
      label: 'Graph',
      value: 'entities + edges',
      icon: GitBranch,
      state: 'pending',
    },
  ];

  return (
    <div className="flex h-full flex-col overflow-auto bg-muted/20 px-6 py-6">
      <div className="mx-auto flex w-full max-w-[520px] flex-1 flex-col justify-center">
        <section className="rounded-lg border border-border bg-card p-5 shadow-sm">
          <div className="flex items-start gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-primary/20 bg-primary/10 text-primary">
              <Database className="h-5 w-5" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                Workbench
              </div>
              <h3 className="mt-1 truncate text-lg font-semibold text-foreground">
                {databaseLabel}
              </h3>
              <p className="mt-1 truncate font-mono text-xs text-muted-foreground">{readableId}</p>
            </div>
          </div>

          <div className="mt-5 rounded-lg border border-border bg-background p-3">
            <div className="grid grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr] items-center gap-2">
              {flowSteps.map((step, index) => {
                const Icon = step.icon;
                const isActive = step.state === 'active';
                const isNext = step.state === 'next';
                return (
                  <React.Fragment key={step.label}>
                    <div
                      className={cn(
                        "min-w-0 rounded-md border p-2.5",
                        isActive && "border-primary/25 bg-primary/10",
                        isNext && "border-primary/20 bg-primary/5",
                        !isActive && !isNext && "border-border bg-card"
                      )}
                    >
                      <div
                        className={cn(
                          "mb-2 flex h-7 w-7 items-center justify-center rounded-md border bg-card",
                          isActive && "border-primary/25 text-primary",
                          isNext && "border-primary/20 text-primary",
                          !isActive && !isNext && "border-border text-muted-foreground"
                        )}
                      >
                        <Icon className="h-3.5 w-3.5" />
                      </div>
                      <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                        {step.label}
                      </div>
                      <div className="mt-1 truncate text-[11px] font-medium text-foreground">
                        {step.value}
                      </div>
                    </div>
                    {index < flowSteps.length - 1 && (
                      <div className="flex items-center text-muted-foreground">
                        <ArrowRight className="h-3 w-3" />
                      </div>
                    )}
                  </React.Fragment>
                );
              })}
            </div>
          </div>

          <div className="mt-4 rounded-lg border border-border bg-background p-3">
            <div className="flex items-start gap-3">
              <span className={cn(
                "flex h-9 w-9 shrink-0 items-center justify-center rounded-md border bg-card",
                sourceIsSelected ? "border-primary/20" : "border-dashed border-border"
              )}>
                {getSourceIcon() || <Plug className="h-4 w-4 text-muted-foreground" />}
              </span>
              <div className="min-w-0">
                <div className="text-sm font-semibold text-foreground">
                  {sourceIsSelected ? sourceLabel : 'One connector'}
                </div>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  {sourceIsSelected
                    ? 'This connector will be configured next.'
                    : 'Choose one connector after the database is created.'}
                </p>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
};
