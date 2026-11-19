import { AlertTriangle, BookOpen, CheckCircle2, RefreshCw, Search, Settings2, ShieldCheck } from "lucide-react";
import type { Metrics } from "../../api/types";
import { Badge, Button, Card, Drawer, LoadingSkeleton, fieldClass } from "../../components/ui";
import { useQuality } from "./useKnowledge";
import { KnowledgeEmptyState } from "./KnowledgeEmptyState";
import type { KnowledgeSection } from "./types";
import { feedbackCount, helpfulRatings } from "./metricsPresentation";
import { MessageContent } from "../../components/MessageContent";
import { KnowledgeToolbar } from "./KnowledgeToolbar";

export function QualitySection({ metrics, onNavigate }: { metrics?: Metrics; onNavigate: (section: KnowledgeSection) => void }) {
  const { mode, setMode, search, setSearch, selectedFeedback, setSelectedFeedback, selectedGap, setSelectedGap, feedback, gaps, reviewGap, counts, visibleFeedback, visibleGaps, empty } = useQuality();
  const activeQuery = mode === "gaps" ? gaps : feedback;
  const ratings = feedbackCount(metrics);
  const modes = [
    {id: "negative" as const, label: "Needs review", count: feedback.data ? counts.negative : undefined},
    {id: "gaps" as const, label: "Knowledge gaps", count: gaps.data ? counts.gaps : undefined},
    {id: "positive" as const, label: "Helpful", count: feedback.data ? counts.positive : undefined},
  ];
  const go = (section: KnowledgeSection) => {
    setSelectedFeedback(null);
    setSelectedGap(null);
    onNavigate(section);
  };

  return <div className="space-y-4">
    <Card padding="none">
      <h2 className="sr-only">Answer quality queue</h2>
      <KnowledgeToolbar summary={<p>Helpful ratings: <strong className="text-cream">{helpfulRatings(metrics)}</strong>{ratings !== undefined && ratings > 0 ? ` · ${ratings} ${ratings === 1 ? "rating" : "ratings"}` : ""}</p>}
        actions={<Button tone="ghost" aria-label="Refresh" className="knowledge-toolbar-refresh" disabled={feedback.isFetching || gaps.isFetching} onClick={() => { void feedback.refetch(); void gaps.refetch(); }}><RefreshCw size={16} aria-hidden="true"/><span className="hidden sm:inline">Refresh</span></Button>}>
        <div role="group" aria-label="Quality view" className="knowledge-tabs">
          {modes.map(item => <button key={item.id} type="button" aria-pressed={mode === item.id} onClick={() => setMode(item.id)} className="focus-ring"><span>{item.label}</span><span aria-label={item.count === undefined ? "Not loaded" : String(item.count)} className="rounded bg-panel px-1 text-xs">{item.count ?? "—"}</span></button>)}
        </div>
        <label className="knowledge-toolbar-search"><span className="sr-only">Search quality records</span>
          <Search size={17} aria-hidden="true"/><input className={`${fieldClass} pl-10`} value={search} onChange={event => setSearch(event.target.value)} placeholder="Search answers" maxLength={200}/>
        </label>
      </KnowledgeToolbar>
      {activeQuery.isLoading && <LoadingSkeleton label="Loading quality records…" className="p-4 sm:p-6"/>}
      {activeQuery.isError && <div role="alert" className="m-4 space-y-3 rounded-lg border border-danger/25 bg-danger/5 p-4"><p className="font-semibold text-danger">Unable to load {mode === "gaps" ? "knowledge gaps" : "feedback"}</p><p className="text-sm text-muted">{activeQuery.data ? "Showing the last loaded records. They may be out of date." : "The records are unavailable. Check the connection and try again."}</p><Button tone="secondary" onClick={() => void activeQuery.refetch()}>Retry quality records</Button></div>}
      {activeQuery.isSuccess && empty && <div>
        <KnowledgeEmptyState title={search.trim() ? "No matching records" : mode === "negative" ? "No answers need review" : mode === "gaps" ? "No active knowledge gaps" : "No helpful examples yet"} copy={search.trim() ? "Change the search or clear it to see all records in this view." : mode === "positive" ? "Responses marked helpful by employees will appear here." : "New items will appear here when employees provide feedback or a question needs a source."}/>
        {search.trim() && <div className="pb-5 text-center"><Button tone="secondary" onClick={() => setSearch("")}>Clear search</Button></div>}
      </div>}
      <div className="divide-y divide-line">
        {mode === "gaps" ? visibleGaps.map(item => <button key={item.id} aria-label={`Review knowledge gap: ${item.question}`} onClick={() => { reviewGap.reset(); setSelectedGap(item); }} className="focus-ring knowledge-quality-row">
          <div className="min-w-0"><p className="text-xs font-medium text-muted">Employee question</p><p className="mt-1 line-clamp-3 text-sm font-semibold leading-6 [overflow-wrap:anywhere]">{item.question}</p></div>
          <div className="min-w-0"><p className="text-xs font-medium text-muted">Assistant response</p><p className="mt-1 line-clamp-3 text-sm leading-6 text-muted [overflow-wrap:anywhere]">{item.assistant}</p></div>
          <div className="knowledge-quality-meta"><Badge tone="warning">Needs a source</Badge><p className="text-xs text-muted">{new Date(item.timestamp).toLocaleDateString()}</p></div>
        </button>) : visibleFeedback.map(item => <button key={item.id} aria-label={`Review feedback: ${item.question || "Older answer"}`} onClick={() => setSelectedFeedback(item)} className="focus-ring knowledge-quality-row">
          <div className="min-w-0"><p className="text-xs font-medium text-muted">Employee question</p><p className="mt-1 line-clamp-3 text-sm font-semibold leading-6 [overflow-wrap:anywhere]">{item.question || "Question was not captured"}</p></div>
          <div className="min-w-0"><p className="text-xs font-medium text-muted">Assistant answer</p><p className="mt-1 line-clamp-3 text-sm leading-6 text-muted [overflow-wrap:anywhere]">{item.answer || "Answer was not captured for this older feedback."}</p>{item.comment && <p className="mt-2 line-clamp-2 rounded-lg bg-raised p-2 text-xs leading-5 [overflow-wrap:anywhere]">“{item.comment}”</p>}</div>
          <div className="knowledge-quality-meta"><Badge tone={item.sentiment === "positive" ? "success" : "warning"}>{item.sentiment === "positive" ? "Helpful" : "Needs review"}</Badge><p className="text-xs text-muted">{new Date(item.created_at).toLocaleDateString()}</p></div>
        </button>)}
      </div>
    </Card>
    <Drawer open={Boolean(selectedFeedback)} onOpenChange={open => !open && setSelectedFeedback(null)} title="Response feedback" description="The question, answer and note submitted with this rating." footer={selectedFeedback?.sentiment === "negative" ? <><Button tone="secondary" onClick={() => go("settings")}><Settings2 size={16} aria-hidden="true"/>Review AI settings</Button><Button onClick={() => go("documents")}><BookOpen size={16} aria-hidden="true"/>Review documents</Button></> : <Button tone="secondary" onClick={() => setSelectedFeedback(null)}>Close</Button>}>
      {selectedFeedback && <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2"><Badge tone={selectedFeedback.sentiment === "positive" ? "success" : "warning"}>{selectedFeedback.sentiment === "positive" ? "Helpful" : "Needs review"}</Badge><span className="flex items-center gap-2 text-xs text-muted"><ShieldCheck size={15} aria-hidden="true"/>Account name hidden</span></div>
        <ConversationBlock label="Employee question" text={selectedFeedback.question || "Question was not captured."}/>
        <ConversationBlock label="PeopleFlow answer" text={selectedFeedback.answer || "Answer was not captured for this older feedback."} markdown/>
        {selectedFeedback.comment && <ConversationBlock label="Employee note" text={selectedFeedback.comment}/>}
        <p className="text-xs text-muted">Received {new Date(selectedFeedback.created_at).toLocaleString()}</p>
        {selectedFeedback.sentiment === "negative" && <section className="border-t border-line pt-4"><h3 className="text-sm font-semibold">Improve future answers</h3><p className="mt-1 text-sm leading-6 text-muted">Check whether the company source is missing or outdated. If the source is correct, review the assistant settings. This feedback stays available for reference.</p></section>}
      </div>}
    </Drawer>
    <Drawer open={Boolean(selectedGap)} onOpenChange={open => !open && !reviewGap.isPending && setSelectedGap(null)} title="Knowledge gap" description="A workplace question that needs a reliable company source." footer={selectedGap && <><Button tone="ghost" onClick={() => reviewGap.mutate({ id: selectedGap.id, action: "ignored" })} disabled={reviewGap.isPending}><AlertTriangle size={16} aria-hidden="true"/>Ignore</Button><Button tone="secondary" disabled={reviewGap.isPending} onClick={() => go("documents")}><BookOpen size={16} aria-hidden="true"/>Add source</Button><Button onClick={() => reviewGap.mutate({ id: selectedGap.id, action: "resolved" })} disabled={reviewGap.isPending}><CheckCircle2 size={16} aria-hidden="true"/>{reviewGap.isPending ? "Saving…" : "Mark resolved"}</Button></>}>
      {selectedGap && <div className="space-y-4">
        <Badge tone="warning">Needs a source</Badge>
        <ConversationBlock label="Employee question" text={selectedGap.question}/>
        <ConversationBlock label="PeopleFlow response" text={selectedGap.assistant} markdown/>
        <p className="rounded-lg border border-line p-4 text-sm leading-6 text-muted">Add or update the relevant source, then mark this item resolved. Ignore it only if it does not belong in the company knowledge base.</p>
        {reviewGap.isError && <p role="alert" className="text-sm text-danger">{reviewGap.error instanceof Error ? reviewGap.error.message : "Unable to update this item. Try again."}</p>}
      </div>}
    </Drawer>
  </div>;
}
function ConversationBlock({ label, text, markdown = false }: { label: string; text: string; markdown?: boolean }) {
  return <section className="min-w-0 border-b border-line pb-4 last:border-0"><h3 className="text-sm font-semibold text-muted">{label}</h3>{markdown ? <div className="mt-2"><MessageContent content={text}/></div> : <p className="mt-2 whitespace-pre-wrap text-sm leading-6 [overflow-wrap:anywhere]">{text}</p>}</section>;
}


