import { ArrowRight, BookOpen, MessageSquareWarning, Plug } from "lucide-react";
import type { ReactNode } from "react";
import type { Metrics } from "../../api/types";
import { Button, Card, LoadingSkeleton } from "../../components/ui";
import type { KnowledgeSection } from "./types";
import { feedbackCount, helpfulRatings } from "./metricsPresentation";

export function OverviewSection({ metrics, loading, error, onRetry, onNavigate }: {
  metrics?: Metrics; loading: boolean; error: boolean; onRetry: () => void; onNavigate: (section: KnowledgeSection) => void;
}) {
  const ratings = feedbackCount(metrics);
  const cards = metrics ? [
    ["Questions", metrics.questions, "Recent workplace questions"],
    ["Answers with sources", metrics.questions ? `${metrics.grounded_answer_rate}%` : "No questions yet", "Share of recent answers with evidence"],
    ["Unanswered questions", metrics.unanswered_questions, "Questions needing a reliable source"],
    ["Helpful feedback", helpfulRatings(metrics), ratings === undefined ? "Share of ratings marked helpful" : `${ratings} recorded ${ratings === 1 ? "rating" : "ratings"}`],
    ["Requests created", metrics.requests_created, "Employee requests recorded"],
    ["Requests approved", metrics.requests_approved, "Requests currently approved"],
  ] : [];

  return <div className="space-y-6">
    {loading && <Card><LoadingSkeleton label="Loading overview…"/></Card>}
    {error && <Card><div role="alert" className="space-y-3"><p className="font-semibold text-danger">Unable to refresh the overview</p><p className="text-sm text-muted">{metrics ? "The figures below are from the last successful load and may be out of date." : "The metrics are unavailable. Check the connection and try again."}</p><Button tone="secondary" onClick={onRetry}>Retry overview</Button></div></Card>}
    <div className="knowledge-overview">
    {metrics && <section aria-labelledby="overview-activity-title">
      <div className="knowledge-section-heading"><h2 id="overview-activity-title">Activity at a glance</h2>{typeof metrics.generated_at === "string" && <p className="text-xs text-muted">Updated {new Date(metrics.generated_at).toLocaleString()}</p>}</div>
      <dl className="knowledge-metrics" aria-label="Knowledge metrics">
        {cards.map(([label, value, copy]) => <div key={String(label)} className="knowledge-metric">
          <dt>{label}</dt><dd>{value}<p>{copy}</p></dd>
        </div>)}
      </dl>
    </section>}
    <section className="knowledge-overview-actions" aria-labelledby="overview-actions-title">
      <div className="knowledge-section-heading"><h2 id="overview-actions-title">Manage knowledge</h2></div>
      <div className="knowledge-action-list">
        <OverviewAction title="Review answer quality" copy={metrics && !error ? metrics.unanswered_questions ? `${metrics.unanswered_questions} ${metrics.unanswered_questions === 1 ? "question needs" : "questions need"} a reliable source.` : "No unanswered questions. Review recent feedback." : "Review feedback and questions without sources."} icon={<MessageSquareWarning size={20}/>} onClick={() => onNavigate("quality")}/>
        <OverviewAction title="Manage documents" copy="Add sources and review processing errors." icon={<BookOpen size={20}/>} onClick={() => onNavigate("documents")}/>
        <OverviewAction title="Check notifications" copy="Review connections and delivery results." icon={<Plug size={20}/>} onClick={() => onNavigate("integrations")}/>
      </div>
    </section>
    </div>
  </div>;
}

function OverviewAction({title, copy, icon, onClick}: {title: string; copy: string; icon: ReactNode; onClick: () => void}) {
  return <button onClick={onClick} className="focus-ring">
    <span className="shrink-0 text-muted" aria-hidden="true">{icon}</span><span className="min-w-0 flex-1"><span className="block text-sm font-semibold">{title}</span><span className="mt-1 block text-xs leading-5 text-muted">{copy}</span></span><ArrowRight size={16} className="shrink-0 text-muted" aria-hidden="true"/>
  </button>;
}

