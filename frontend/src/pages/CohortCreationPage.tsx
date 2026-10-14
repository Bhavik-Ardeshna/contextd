/**
 * Cohort creation — chat-style builder. NL prompt at top, each draft appended as a
 * message with collapsible sections (plan, metrics, Cypher, samples). Save inline,
 * then run saved cohorts to browse members.
 */

import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { apiClient } from '@/lib/api';
import { useCollectionsStore } from '@/lib/stores/collections';
import { useOrganizationStore } from '@/lib/stores/organizations';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
  Loader2,
  AlertCircle,
  ArrowUpRight,
  ChevronDown,
  ChevronRight,
  Sparkles,
  Layers,
  CheckCircle2,
} from 'lucide-react';
import { cn } from '@/lib/utils';

// ---------- Types ----------

interface ResearchPlanShape {
  goal: string;
  steps: string[];
  use_p_agent?: boolean;
  p_agent_instruction?: string | null;
}

interface CohortPlan {
  target_node_type: string;
  display_property_keys: string[];
  identifier_property_keys: string[];
  research_plan: ResearchPlanShape;
}

interface ScoringComponent {
  property_key: string;
  weight: number;
  direction: string;
  normalization: Record<string, unknown>;
}

interface ScoringPlan {
  target_node_type: string;
  display_property_keys: string[];
  identifier_property_keys: string[];
  missing_data_policy: string;
  cutoff_method: string;
  components: ScoringComponent[];
  research_plan: ResearchPlanShape;
}

interface DraftResponse {
  mode?: 'list' | 'scoring';
  cohort_plan?: CohortPlan | null;
  scoring_plan?: ScoringPlan | null;
  distribution_summary?: Record<string, unknown> | null;
  score_distribution?: Record<string, unknown> | null;
  cutoff_value?: number | null;
  cutoff_rationale?: string | null;
  cutoff_iterations_used?: number;
  cypher_query?: string | null;
  sample_rows?: Record<string, unknown>[];
  error?: string | null;
  warning?: string | null;
}

interface SavedCohort {
  id: string;
  name: string;
  target_node_type: string;
  cypher_text: string;
  display_property_keys: string[];
  identifier_property_keys: string[];
  cohort_mode?: string;
}

interface RunRow {
  node_id: string;
  fields: Record<string, unknown>;
  final_score?: number | null;
  confidence?: number | null;
}

interface MemberDetail {
  node_id: string;
  node_type?: string | null;
  name?: string | null;
  properties: Record<string, unknown>;
  neighbors: Record<string, unknown>[];
  final_score?: number | null;
  confidence?: number | null;
  score_breakdown?: Record<string, unknown>;
}

type DraftMode = 'list' | 'scoring';

interface AssistantMessage {
  id: string;
  mode: DraftMode;
  draft: DraftResponse;
  prompt: string;
  collectionName: string;
  savedCohortId?: string;
  savedName?: string;
  timestamp: number;
}

// ---------- Helpers ----------

const comp_breakdown_keys = (plan: ScoringPlan): string[] =>
  plan.components.map((c) => `comp_${c.property_key.replace(/[^a-zA-Z0-9_]/g, '_')}`);

const fmtValue = (v: unknown): string =>
  v === null || v === undefined ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v);

const shortUid = () => Math.random().toString(36).slice(2, 10);

// ---------- Section primitive ----------

function Section({
  title,
  subtitle,
  defaultOpen = false,
  children,
  icon,
}: {
  title: string;
  subtitle?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
  icon?: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="border rounded-lg">
      <CollapsibleTrigger asChild>
        <button
          type="button"
          className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-muted/40 transition-colors"
        >
          <div className="flex items-center gap-2 min-w-0">
            {icon}
            <div className="min-w-0">
              <div className="text-sm font-medium truncate">{title}</div>
              {subtitle && (
                <div className="text-xs text-muted-foreground truncate">{subtitle}</div>
              )}
            </div>
          </div>
          {open ? (
            <ChevronDown className="h-4 w-4 flex-shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 flex-shrink-0 text-muted-foreground" />
          )}
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent className="px-4 pb-4">{children}</CollapsibleContent>
    </Collapsible>
  );
}

// ---------- Page ----------

export default function CohortCreationPage() {
  const currentOrganization = useOrganizationStore((s) => s.currentOrganization);
  const { collections, fetchCollections, isLoading: collectionsLoading } = useCollectionsStore();

  const [readableId, setReadableId] = useState<string>('');
  const [draftMode, setDraftMode] = useState<DraftMode>('list');
  const [message, setMessage] = useState('');
  const [draftLoading, setDraftLoading] = useState(false);

  const [result, setResult] = useState<AssistantMessage | null>(null);

  const [saved, setSaved] = useState<SavedCohort[]>([]);
  const [selectedCohortId, setSelectedCohortId] = useState<string | null>(null);
  const [runRows, setRunRows] = useState<RunRow[]>([]);
  const [runMeta, setRunMeta] = useState<{ total: number; offset: number; limit: number } | null>(
    null
  );
  const [runLoading, setRunLoading] = useState(false);

  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detail, setDetail] = useState<MemberDetail | null>(null);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    fetchCollections(true).catch(() => undefined);
  }, [fetchCollections]);

  const loadSaved = useCallback(async () => {
    if (!readableId) return;
    const res = await apiClient.get(`/collections/${readableId}/cohorts`);
    if (!res.ok) return;
    const data = (await res.json()) as SavedCohort[];
    setSaved(data);
  }, [readableId]);

  useEffect(() => {
    if (readableId) {
      setSelectedCohortId(null);
      setRunRows([]);
      setRunMeta(null);
      loadSaved();
    }
  }, [readableId, loadSaved]);

  // Auto-scroll when a new draft lands
  useEffect(() => {
    if (result || draftLoading) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  }, [result, draftLoading]);

  const collectionName = useMemo(
    () => collections.find((c) => c.readable_id === readableId)?.name || '',
    [collections, readableId]
  );

  const runDraft = async () => {
    const trimmed = message.trim();
    if (!readableId || !trimmed) return;
    setResult(null);
    setDraftLoading(true);
    try {
      const res = await apiClient.post(`/collections/${readableId}/cohorts/draft`, {
        message: trimmed,
        mode: draftMode,
      });
      const data = (await res.json()) as DraftResponse;
      const draft: DraftResponse = res.ok
        ? data
        : { error: (data as { detail?: string }).detail || res.statusText, mode: draftMode };
      setResult({
        id: shortUid(),
        mode: draft.mode ?? draftMode,
        draft,
        prompt: trimmed,
        collectionName: collectionName || readableId,
        timestamp: Date.now(),
      });
    } catch (e) {
      setResult({
        id: shortUid(),
        mode: draftMode,
        draft: { error: e instanceof Error ? e.message : 'Draft failed', mode: draftMode },
        prompt: trimmed,
        collectionName: collectionName || readableId,
        timestamp: Date.now(),
      });
    } finally {
      setDraftLoading(false);
    }
  };

  const saveCurrentResult = async (name: string) => {
    if (!result) return;
    const { draft, mode } = result;
    const isScoring = mode === 'scoring' && !!draft.scoring_plan;
    if (!readableId || !draft.cypher_query || !name.trim()) return;
    if (isScoring ? !draft.scoring_plan : !draft.cohort_plan) return;

    const body: Record<string, unknown> = {
      name: name.trim(),
      target_node_type: isScoring
        ? draft.scoring_plan!.target_node_type
        : draft.cohort_plan!.target_node_type,
      cypher_text: draft.cypher_query,
      display_property_keys: isScoring
        ? draft.scoring_plan!.display_property_keys
        : draft.cohort_plan!.display_property_keys,
      identifier_property_keys: isScoring
        ? draft.scoring_plan!.identifier_property_keys
        : draft.cohort_plan!.identifier_property_keys,
      cohort_mode: mode,
    };
    if (isScoring) {
      body.scoring_spec = draft.scoring_plan as unknown as Record<string, unknown>;
      body.distribution_probe_snapshot = draft.distribution_summary ?? null;
      body.cutoff_value = draft.cutoff_value ?? null;
      body.cutoff_iterations_used = draft.cutoff_iterations_used ?? null;
      body.score_breakdown_keys = comp_breakdown_keys(draft.scoring_plan!);
    }

    const res = await apiClient.post(`/collections/${readableId}/cohorts`, body);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert((err as { detail?: string }).detail || 'Save failed');
      return;
    }
    const created = (await res.json()) as { id: string };
    setResult((r) =>
      r ? { ...r, savedCohortId: created.id, savedName: name.trim() } : r
    );
    await loadSaved();
  };

  const runMembers = async (cohortId: string) => {
    if (!readableId) return;
    setRunLoading(true);
    setSelectedCohortId(cohortId);
    try {
      const res = await apiClient.post(
        `/collections/${readableId}/cohorts/${cohortId}/run`,
        {},
        { offset: 0, limit: 50 }
      );
      const data = await res.json();
      if (!res.ok) {
        setRunRows([]);
        setRunMeta(null);
        return;
      }
      setRunRows((data.rows || []) as RunRow[]);
      setRunMeta({
        total: data.total_fetched,
        offset: data.offset,
        limit: data.limit,
      });
    } finally {
      setRunLoading(false);
    }
  };

  const openDetail = async (nodeId: string) => {
    if (!readableId || !selectedCohortId) return;
    setDetailOpen(true);
    setDetailLoading(true);
    setDetail(null);
    try {
      const q = new URLSearchParams({ node_id: nodeId });
      const res = await apiClient.get(
        `/collections/${readableId}/cohorts/${selectedCohortId}/member-detail?${q.toString()}`
      );
      const data = (await res.json()) as MemberDetail;
      if (res.ok) setDetail(data);
    } finally {
      setDetailLoading(false);
    }
  };

  const runColumnKeys =
    runRows.length > 0
      ? [
          ...new Set([
            ...runRows.flatMap((r) => Object.keys(r.fields || {})),
            ...(runRows.some((r) => r.final_score != null) ? ['final_score'] : []),
            ...(runRows.some((r) => r.confidence != null) ? ['confidence'] : []),
          ]),
        ]
      : [];

  if (!currentOrganization) {
    return (
      <div className="container mx-auto p-6">
        <Alert>
          <AlertDescription>Select an organization to use cohort creation.</AlertDescription>
        </Alert>
      </div>
    );
  }

  // ---------- Render ----------

  return (
    <div className="container max-w-5xl mx-auto p-6 pb-24 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Cohort Builder</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Describe who should be in the cohort. Choose list-only or weighted scoring, then review,
          save, and run.
        </p>
      </div>

      {/* --- Builder card (top, like Action Builder) --- */}
      <div className="border rounded-2xl bg-background shadow-sm">
        <div className="flex items-start gap-3 px-5 py-4">
          <div className="relative mt-1">
            <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
              <Sparkles className="h-4 w-4 text-primary" />
            </div>
            <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 bg-blue-500 rounded-full ring-2 ring-background" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline gap-2">
              <span className="font-semibold text-sm">Cohort Builder</span>
              <span className="text-xs text-muted-foreground">
                Describe the cohort you want to create
              </span>
            </div>
            <Textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  runDraft();
                }
              }}
              placeholder="e.g. High-value customers who haven't ordered in 30 days, open high-priority tickets, prospects in onboarding…"
              rows={3}
              disabled={!readableId}
              className="mt-2 border-0 focus-visible:ring-0 resize-none shadow-none p-0 text-sm placeholder:text-muted-foreground/60"
            />
          </div>
        </div>

        <div className="border-t px-5 py-3 flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2 flex-wrap">
            <Select
              value={readableId || undefined}
              onValueChange={setReadableId}
              disabled={collectionsLoading}
            >
              <SelectTrigger className="h-9 w-auto min-w-[180px] rounded-full text-sm">
                <SelectValue
                  placeholder={collectionsLoading ? 'Loading…' : 'Select Collection…'}
                />
              </SelectTrigger>
              <SelectContent>
                {collections.map((c) => (
                  <SelectItem key={c.readable_id} value={c.readable_id}>
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <div className="h-5 w-px bg-border" />

            <Select
              value={draftMode}
              onValueChange={(v) => setDraftMode(v as DraftMode)}
              disabled={!readableId}
            >
              <SelectTrigger className="h-9 w-auto rounded-full text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="list">Member list (Cypher)</SelectItem>
                <SelectItem value="scoring">Weighted scoring + cutoff</SelectItem>
              </SelectContent>
            </Select>

            <span
              className={cn(
                'inline-flex items-center gap-1.5 h-9 px-3 rounded-full text-xs border border-dashed',
                draftMode === 'scoring'
                  ? 'border-amber-400/50 text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/20'
                  : 'border-emerald-400/50 text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-emerald-950/20'
              )}
            >
              <Layers className="h-3 w-3" />
              {draftMode === 'scoring' ? 'Scoring' : 'List'}
            </span>
          </div>

          <Button
            onClick={runDraft}
            disabled={!readableId || !message.trim() || draftLoading}
            size="icon"
            className="h-9 w-9 rounded-full"
            aria-label="Generate draft"
          >
            {draftLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ArrowUpRight className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>

      {/* --- Draft result --- */}
      {!result && !draftLoading && (
        <div className="text-center py-16 text-sm text-muted-foreground">
          <Sparkles className="h-6 w-6 mx-auto mb-3 text-muted-foreground/50" />
          Your draft result will appear here.
          <br />
          {readableId
            ? 'Type a cohort description above and hit ⌘↵ to send.'
            : 'Start by choosing a collection.'}
        </div>
      )}

      {draftLoading && <ProcessingIndicator />}

      {!draftLoading && result && (
        <AssistantBubble msg={result} onSave={saveCurrentResult} />
      )}

      <div ref={messagesEndRef} />

      {/* --- Saved cohorts panel --- */}
      {readableId && (
        <Collapsible defaultOpen>
          <div className="border rounded-xl">
            <CollapsibleTrigger asChild>
              <button
                type="button"
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-muted/40 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <Layers className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm font-medium">Saved cohorts</span>
                  <span className="text-xs text-muted-foreground">
                    {saved.length} saved · select one to browse members
                  </span>
                </div>
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent className="px-4 pb-4 space-y-4">
              {saved.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  No cohorts saved yet for this collection.
                </p>
              )}
              {saved.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {saved.map((c) => (
                    <Button
                      key={c.id}
                      variant={selectedCohortId === c.id ? 'default' : 'outline'}
                      size="sm"
                      onClick={() => runMembers(c.id)}
                      className="rounded-full"
                    >
                      {c.name}
                      {c.cohort_mode === 'scoring' && (
                        <span className="ml-1 text-xs opacity-70">· scoring</span>
                      )}
                    </Button>
                  ))}
                </div>
              )}

              {runLoading && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" /> Loading members…
                </div>
              )}

              {runMeta && !runLoading && (
                <p className="text-xs text-muted-foreground">
                  Showing {runRows.length} rows (fetched {runMeta.total} from graph, offset{' '}
                  {runMeta.offset}, limit {runMeta.limit})
                </p>
              )}

              {runRows.length > 0 && (
                <div className="rounded-md border overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>node_id</TableHead>
                        {runColumnKeys.map((k) => (
                          <TableHead key={k}>{k}</TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {runRows.map((row) => (
                        <TableRow
                          key={row.node_id}
                          className="cursor-pointer hover:bg-muted/50"
                          onClick={() => openDetail(row.node_id)}
                        >
                          <TableCell className="font-mono text-xs max-w-[200px] truncate">
                            {row.node_id}
                          </TableCell>
                          {runColumnKeys.map((k) => (
                            <TableCell key={k} className="max-w-[200px] truncate">
                              {k === 'final_score'
                                ? row.final_score != null
                                  ? String(row.final_score)
                                  : ''
                                : k === 'confidence'
                                  ? row.confidence != null
                                    ? String(row.confidence)
                                    : ''
                                  : fmtValue(row.fields[k])}
                            </TableCell>
                          ))}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CollapsibleContent>
          </div>
        </Collapsible>
      )}

      {/* --- Member detail sheet --- */}
      <Sheet open={detailOpen} onOpenChange={setDetailOpen}>
        <SheetContent className="sm:max-w-lg overflow-y-auto">
          <SheetHeader>
            <SheetTitle>Member detail</SheetTitle>
            <SheetDescription>Properties and 1-hop neighbors from the graph.</SheetDescription>
          </SheetHeader>
          {detailLoading && (
            <div className="flex items-center gap-2 mt-6 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading…
            </div>
          )}
          {detail && !detailLoading && (
            <div className="mt-6 space-y-4 text-sm">
              <div>
                <span className="font-medium">node_id</span>
                <p className="font-mono text-xs break-all">{detail.node_id}</p>
              </div>
              {detail.node_type && (
                <div>
                  <span className="font-medium">Type</span>
                  <p>{detail.node_type}</p>
                </div>
              )}
              {detail.name && (
                <div>
                  <span className="font-medium">Name</span>
                  <p>{detail.name}</p>
                </div>
              )}
              {(detail.final_score != null || detail.confidence != null) && (
                <div className="flex flex-wrap gap-4">
                  {detail.final_score != null && (
                    <div>
                      <span className="font-medium">final_score</span>
                      <p>{String(detail.final_score)}</p>
                    </div>
                  )}
                  {detail.confidence != null && (
                    <div>
                      <span className="font-medium">confidence</span>
                      <p>{String(detail.confidence)}</p>
                    </div>
                  )}
                </div>
              )}
              {detail.score_breakdown && Object.keys(detail.score_breakdown).length > 0 && (
                <div>
                  <span className="font-medium">Score breakdown</span>
                  <ScrollArea className="h-40 rounded border p-2 mt-1">
                    <pre className="text-xs whitespace-pre-wrap">
                      {JSON.stringify(detail.score_breakdown, null, 2)}
                    </pre>
                  </ScrollArea>
                </div>
              )}
              <div>
                <span className="font-medium">Properties</span>
                <ScrollArea className="h-48 rounded border p-2 mt-1">
                  <pre className="text-xs whitespace-pre-wrap">
                    {JSON.stringify(detail.properties, null, 2)}
                  </pre>
                </ScrollArea>
              </div>
              {detail.neighbors && detail.neighbors.length > 0 && (
                <div>
                  <span className="font-medium">Neighbors</span>
                  <ScrollArea className="h-40 rounded border p-2 mt-1">
                    <pre className="text-xs whitespace-pre-wrap">
                      {JSON.stringify(detail.neighbors, null, 2)}
                    </pre>
                  </ScrollArea>
                </div>
              )}
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}

// ---------- Message subcomponents ----------

function ProcessingIndicator() {
  return (
    <div className="flex items-center justify-center gap-3 py-12 text-sm text-muted-foreground">
      <Loader2 className="h-5 w-5 animate-spin text-primary" />
      <div className="flex items-center gap-1.5">
        <span>Processing</span>
        <span className="inline-flex gap-0.5">
          <span className="w-1 h-1 rounded-full bg-muted-foreground animate-bounce [animation-delay:-0.3s]" />
          <span className="w-1 h-1 rounded-full bg-muted-foreground animate-bounce [animation-delay:-0.15s]" />
          <span className="w-1 h-1 rounded-full bg-muted-foreground animate-bounce" />
        </span>
      </div>
    </div>
  );
}

function AssistantBubble({
  msg,
  onSave,
}: {
  msg: AssistantMessage;
  onSave: (name: string) => void;
}) {
  const { draft, mode, savedCohortId, savedName } = msg;
  const [name, setName] = useState('');
  const [saving, setSaving] = useState(false);

  const plan: CohortPlan | ScoringPlan | null =
    mode === 'scoring' ? draft.scoring_plan ?? null : draft.cohort_plan ?? null;
  const hasSaveable = !!plan && !!draft.cypher_query && !draft.error;
  const sampleCount = draft.sample_rows?.length ?? 0;

  const handleSave = async () => {
    if (!name.trim() || saving) return;
    setSaving(true);
    try {
      await onSave(name);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex gap-3">
      <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
        <Sparkles className="h-4 w-4 text-primary" />
      </div>
      <div className="flex-1 min-w-0 space-y-3">
        {/* Summary header */}
        <div className="rounded-2xl border bg-card px-4 py-3">
          <div className="flex items-center gap-2 flex-wrap text-sm">
            {draft.error ? (
              <span className="inline-flex items-center gap-1.5 text-destructive">
                <AlertCircle className="h-4 w-4" /> Draft failed
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 font-medium">
                <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                {mode === 'scoring' ? 'Scoring plan' : 'Member list'} drafted
              </span>
            )}
            {plan && (
              <>
                <span className="text-muted-foreground">·</span>
                <span className="font-mono text-xs bg-muted px-1.5 py-0.5 rounded">
                  {plan.target_node_type}
                </span>
              </>
            )}
            {sampleCount > 0 && (
              <>
                <span className="text-muted-foreground">·</span>
                <span className="text-xs text-muted-foreground">
                  {sampleCount} sample row{sampleCount === 1 ? '' : 's'}
                </span>
              </>
            )}
            {mode === 'scoring' && draft.cutoff_value != null && (
              <>
                <span className="text-muted-foreground">·</span>
                <span className="text-xs">
                  cutoff{' '}
                  <span className="font-mono">{Number(draft.cutoff_value).toFixed(3)}</span>
                </span>
              </>
            )}
          </div>
          {plan && (
            <p className="text-sm text-muted-foreground mt-1.5">{plan.research_plan.goal}</p>
          )}
        </div>

        {draft.error && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Draft error</AlertTitle>
            <AlertDescription className="whitespace-pre-wrap">{draft.error}</AlertDescription>
          </Alert>
        )}

        {draft.warning && !draft.error && (
          <Alert>
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Zero rows — check query</AlertTitle>
            <AlertDescription className="whitespace-pre-wrap text-sm">
              {draft.warning}
            </AlertDescription>
          </Alert>
        )}

        {plan && (
          <Section
            title="Plan"
            subtitle={`${plan.display_property_keys.length} columns · ${plan.identifier_property_keys.length} identifiers`}
            defaultOpen={false}
          >
            <div className="space-y-2 text-sm">
              <Row label="Node type" value={plan.target_node_type} mono />
              <Row label="Display columns" value={plan.display_property_keys.join(', ') || '—'} />
              <Row
                label="Identifiers"
                value={plan.identifier_property_keys.join(', ') || '—'}
              />
              {mode === 'scoring' && 'missing_data_policy' in plan && (
                <>
                  <Row label="Missing data" value={plan.missing_data_policy} />
                  <div>
                    <div className="text-xs font-medium text-muted-foreground mb-1">
                      Components
                    </div>
                    <ul className="list-disc pl-5 space-y-0.5 text-sm">
                      {(plan as ScoringPlan).components.map((c, i) => (
                        <li key={i}>
                          <span className="font-mono text-xs">{c.property_key}</span> — weight{' '}
                          {c.weight} ({c.direction})
                        </li>
                      ))}
                    </ul>
                  </div>
                </>
              )}
              {plan.research_plan.steps.length > 0 && (
                <div>
                  <div className="text-xs font-medium text-muted-foreground mb-1">Steps</div>
                  <ul className="list-disc pl-5 space-y-0.5 text-sm">
                    {plan.research_plan.steps.map((s, i) => (
                      <li key={i} className="text-muted-foreground">
                        {s}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </Section>
        )}

        {mode === 'scoring' &&
          (draft.distribution_summary || draft.score_distribution || draft.cutoff_value != null) && (
            <Section
              title="Metrics"
              subtitle="Probe, score distribution, cutoff"
              defaultOpen={false}
            >
              <div className="space-y-3">
                {draft.cutoff_value != null && (
                  <div className="text-sm space-y-1">
                    <div>
                      <span className="font-medium">Cutoff: </span>
                      <span className="font-mono">
                        {Number(draft.cutoff_value).toFixed(4)}
                      </span>
                    </div>
                    {draft.cutoff_rationale && (
                      <div className="text-muted-foreground">{draft.cutoff_rationale}</div>
                    )}
                    <div className="text-xs text-muted-foreground">
                      Iterations: {draft.cutoff_iterations_used ?? 0}
                    </div>
                  </div>
                )}
                {draft.distribution_summary && (
                  <div>
                    <div className="text-xs font-medium text-muted-foreground mb-1">
                      Probe summary
                    </div>
                    <ScrollArea className="h-32 rounded border p-2 font-mono text-xs bg-muted/30">
                      <pre className="whitespace-pre-wrap">
                        {JSON.stringify(draft.distribution_summary, null, 2)}
                      </pre>
                    </ScrollArea>
                  </div>
                )}
                {draft.score_distribution && (
                  <div>
                    <div className="text-xs font-medium text-muted-foreground mb-1">
                      Score distribution
                    </div>
                    <ScrollArea className="h-32 rounded border p-2 font-mono text-xs bg-muted/30">
                      <pre className="whitespace-pre-wrap">
                        {JSON.stringify(draft.score_distribution, null, 2)}
                      </pre>
                    </ScrollArea>
                  </div>
                )}
              </div>
            </Section>
          )}

        {draft.cypher_query && (
          <Section title="Cypher" subtitle={`${draft.cypher_query.length} chars`} defaultOpen={false}>
            <ScrollArea className="h-40 rounded border p-3 font-mono text-xs bg-muted/30">
              <pre className="whitespace-pre-wrap">{draft.cypher_query}</pre>
            </ScrollArea>
          </Section>
        )}

        {draft.sample_rows && draft.sample_rows.length > 0 && (
          <Section
            title="Sample rows"
            subtitle={`${Math.min(draft.sample_rows.length, 8)} of ${draft.sample_rows.length} shown`}
            defaultOpen
          >
            <div className="rounded-md border overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    {Object.keys(draft.sample_rows[0]).map((k) => (
                      <TableHead key={k}>{k}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {draft.sample_rows.slice(0, 8).map((row, i) => (
                    <TableRow key={i}>
                      {Object.values(row).map((v, j) => (
                        <TableCell key={j} className="max-w-[240px] truncate">
                          {fmtValue(v)}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </Section>
        )}

        {hasSaveable && !savedCohortId && (
          <div className="flex flex-col sm:flex-row gap-2 sm:items-center border rounded-lg p-3 bg-muted/20">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Name this cohort (e.g. 'At-risk Enterprise Accounts')"
              className="flex-1"
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  handleSave();
                }
              }}
            />
            <Button onClick={handleSave} disabled={!name.trim() || saving} size="sm">
              {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Save cohort
            </Button>
          </div>
        )}

        {savedCohortId && (
          <div className="inline-flex items-center gap-2 text-sm text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-emerald-950/20 px-3 py-2 rounded-full">
            <CheckCircle2 className="h-4 w-4" />
            Saved as <span className="font-medium">{savedName}</span>
          </div>
        )}
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex gap-2 text-sm">
      <span className="text-muted-foreground min-w-[110px]">{label}</span>
      <span className={cn('flex-1 break-words', mono && 'font-mono text-xs')}>{value}</span>
    </div>
  );
}
