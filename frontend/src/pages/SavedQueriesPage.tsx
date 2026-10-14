import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Bookmark,
  Clock,
  Database,
  History,
  Play,
  Search,
  Star,
  TerminalSquare,
  Trash2,
} from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useCollectionsStore } from '@/lib/stores/collections';
import { cn } from '@/lib/utils';
import {
  queryConsoleUrl,
  readQueryHistory,
  readSavedQueries,
  SAVED_QUERIES_EVENT,
  writeSavedQueries,
  type QueryHistoryItem,
  type SavedQuery,
} from '@/lib/queryConsoleStorage';

type LibraryRow = {
  id: string;
  title: string;
  query: string;
  databaseId: string;
  databaseName: string;
  createdAt: string;
  updatedAt?: string;
  lastRunAt?: string;
  latencyMs?: number | null;
  resultCount?: number | null;
  rating?: number | null;
  recipe?: SavedQuery['recipe'];
  kind: 'saved' | 'history';
};

function formatMs(value?: number | null) {
  if (!value) return '-';
  if (value >= 1000) return `${(value / 1000).toFixed(1)} s`;
  return `${Math.max(1, Math.round(value))} ms`;
}

function formatRelative(value?: string | null) {
  if (!value) return 'never';
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return 'never';
  const diffSeconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (diffSeconds < 60) return 'just now';
  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 30) return `${diffDays}d ago`;
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(new Date(value));
}

function firstTitle(query: string) {
  return query.replace(/@\w+\b/g, ' ').replace(/\s+/g, ' ').trim().split(/\s+/).slice(0, 7).join(' ') || 'Untitled query';
}

function SavedQueriesPage() {
  const navigate = useNavigate();
  const { collections, fetchCollections } = useCollectionsStore();
  const [savedQueries, setSavedQueries] = useState<SavedQuery[]>(() => readSavedQueries());
  const [history, setHistory] = useState<QueryHistoryItem[]>(() => readQueryHistory());
  const [search, setSearch] = useState('');

  useEffect(() => {
    fetchCollections();
  }, [fetchCollections]);

  useEffect(() => {
    const refresh = () => {
      setSavedQueries(readSavedQueries());
      setHistory(readQueryHistory());
    };

    refresh();
    window.addEventListener('storage', refresh);
    window.addEventListener(SAVED_QUERIES_EVENT, refresh);
    return () => {
      window.removeEventListener('storage', refresh);
      window.removeEventListener(SAVED_QUERIES_EVENT, refresh);
    };
  }, []);

  const databaseNameById = useMemo(
    () => new Map(collections.map((collection) => [collection.readable_id, collection.name || collection.readable_id])),
    [collections]
  );

  const rows = useMemo<LibraryRow[]>(() => {
    const savedRows = savedQueries.map((item) => ({
      ...item,
      databaseName: item.databaseName || databaseNameById.get(item.databaseId) || item.databaseId,
      kind: 'saved' as const,
    }));

    const recentRows = history
      .filter((item) => !savedQueries.some((saved) => saved.query === item.query && saved.databaseId === item.databaseId))
      .slice(0, 8)
      .map((item) => ({
        id: item.id,
        title: firstTitle(item.query),
        query: item.query,
        databaseId: item.databaseId,
        databaseName: item.databaseName || databaseNameById.get(item.databaseId) || item.databaseId,
        createdAt: item.createdAt,
        updatedAt: item.createdAt,
        lastRunAt: item.createdAt,
        latencyMs: item.latencyMs,
        resultCount: item.resultCount,
        recipe: item.recipe || 'rrf',
        kind: 'history' as const,
      }));

    return [...savedRows, ...recentRows];
  }, [databaseNameById, history, savedQueries]);

  const filteredRows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((row) =>
      [row.title, row.query, row.databaseName, row.databaseId, row.recipe]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle))
    );
  }, [rows, search]);

  const openQuery = (row: LibraryRow) => {
    navigate(queryConsoleUrl({ databaseId: row.databaseId, query: row.query, recipe: row.recipe || 'rrf' }));
  };

  const deleteSavedQuery = (row: LibraryRow) => {
    if (row.kind !== 'saved') return;
    const next = savedQueries.filter((item) => item.id !== row.id);
    setSavedQueries(next);
    writeSavedQueries(next);
    toast.success('Saved query removed');
  };

  return (
    <div className="min-h-full bg-background px-4 py-5 text-foreground">
      <div className="mx-auto flex max-w-[1440px] flex-col gap-4">
        <header className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <div className="inline-flex h-8 items-center gap-2 rounded-md border border-primary/25 bg-primary/10 px-3 text-sm font-medium text-primary">
              <Bookmark className="h-4 w-4" />
              Saved query library
            </div>
            <h1 className="mt-3 text-2xl font-semibold tracking-normal text-foreground">Reusable graph query recipes</h1>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
              Open a saved prompt with its database scope, recipe, lineage-aware trace, and context packet ready to run.
            </p>
          </div>
          <Button
            onClick={() => navigate('/query')}
            className="h-9 border border-primary bg-primary text-primary-foreground hover:bg-primary/90"
          >
            <TerminalSquare className="h-4 w-4" />
            Open console
          </Button>
        </header>

        <section className="grid gap-3 md:grid-cols-4">
          {[
            { label: 'Saved', value: savedQueries.length, icon: Bookmark, sub: 'pinned recipes' },
            { label: 'Recent runs', value: history.length, icon: History, sub: 'local audit trail' },
            { label: 'Scoped DBs', value: new Set(rows.map((row) => row.databaseId)).size, icon: Database, sub: 'query coverage' },
            { label: 'Rated', value: savedQueries.filter((item) => item.rating).length, icon: Star, sub: 'feedback memory' },
          ].map((item) => {
            const Icon = item.icon;
            return (
              <div key={item.label} className="rounded-lg border border-border bg-card p-3 shadow-sm">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">{item.label}</div>
                  <Icon className="h-4 w-4 text-primary" />
                </div>
                <div className="mt-2 font-mono text-2xl font-semibold text-foreground">{item.value}</div>
                <div className="mt-1 text-xs text-muted-foreground">{item.sub}</div>
              </div>
            );
          })}
        </section>

        <section className="rounded-lg border border-border bg-card shadow-sm">
          <div className="flex flex-col gap-3 border-b border-border px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h2 className="text-sm font-semibold text-foreground">Query recipes</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                Saved queries stay local until they are promoted to shared workspace recipes.
              </p>
            </div>
            <div className="relative w-full lg:w-[320px]">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                className="h-9 pl-8 text-sm"
                placeholder="Filter saved queries"
              />
            </div>
          </div>

          {filteredRows.length ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[980px] table-fixed text-left text-sm">
                <colgroup>
                  <col className="w-[34%]" />
                  <col className="w-[18%]" />
                  <col className="w-[9%]" />
                  <col className="w-[11%]" />
                  <col className="w-[10%]" />
                  <col className="w-[9%]" />
                  <col className="w-[9%]" />
                </colgroup>
                <thead className="border-b border-border bg-muted/35 text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3 font-semibold">Name</th>
                    <th className="px-4 py-3 font-semibold">Scope</th>
                    <th className="px-4 py-3 font-semibold">Recipe</th>
                    <th className="px-4 py-3 font-semibold">Last run</th>
                    <th className="px-4 py-3 font-semibold">p50 latency</th>
                    <th className="px-4 py-3 font-semibold">Rating</th>
                    <th className="px-4 py-3 text-right font-semibold">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {filteredRows.map((row) => (
                    <tr key={`${row.kind}-${row.id}`} className="transition hover:bg-primary/5">
                      <td className="max-w-0 px-4 py-3">
                        <button type="button" onClick={() => openQuery(row)} className="block w-full min-w-0 text-left">
                          <span className="block truncate font-medium text-foreground">{row.title}</span>
                          <span className="mt-1 block truncate font-mono text-[11px] text-muted-foreground">{row.query}</span>
                        </button>
                      </td>
                      <td className="max-w-0 px-4 py-3">
                        <div className="truncate font-medium text-foreground">{row.databaseName}</div>
                        <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">{row.databaseId}</div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="inline-flex h-7 items-center rounded-md border border-primary/20 bg-primary/10 px-2 font-mono text-[11px] text-primary">
                          {row.recipe === 'graph-chat' ? 'Context chat' : 'RRF'}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2 text-muted-foreground">
                          <Clock className="h-3.5 w-3.5" />
                          {formatRelative(row.lastRunAt || row.createdAt)}
                        </div>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-foreground">{formatMs(row.latencyMs)}</td>
                      <td className="px-4 py-3">
                        <span
                          className={cn(
                            'inline-flex h-7 items-center rounded-md border px-2 text-[11px] font-medium',
                            row.rating
                              ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
                              : 'border-border bg-background text-muted-foreground'
                          )}
                        >
                          {row.rating ? `★ ${row.rating}` : 'unrated'}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-2">
                          <Button variant="outline" size="sm" className="h-8" onClick={() => openQuery(row)}>
                            <Play className="h-3.5 w-3.5" />
                            Open
                          </Button>
                          {row.kind === 'saved' && (
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 text-muted-foreground hover:text-destructive"
                              onClick={() => deleteSavedQuery(row)}
                              aria-label={`Delete ${row.title}`}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="flex min-h-[300px] flex-col items-center justify-center px-6 text-center">
              <div className="rounded-md border border-primary/20 bg-primary/10 p-3 text-primary">
                <Bookmark className="h-6 w-6" />
              </div>
              <h3 className="mt-4 text-base font-semibold text-foreground">No saved query recipes yet</h3>
              <p className="mt-1 max-w-md text-sm leading-6 text-muted-foreground">
                Save a query from the console after it returns a useful answer, then it will appear here with its scope and recipe.
              </p>
              <Button
                onClick={() => navigate('/query')}
                className="mt-4 border border-primary bg-primary text-primary-foreground hover:bg-primary/90"
              >
                <TerminalSquare className="h-4 w-4" />
                Open query console
              </Button>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

export default SavedQueriesPage;
