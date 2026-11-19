import { Button, LoadingSkeleton } from "../../components/ui";
import { useManagerOverview } from "./useManagerWorkspace";
import "./manager-workspace.css";

export type QueueFocus = { status: string; attention?: string };
export function ManagerOverview({ onFocus }: { onFocus: (focus: QueueFocus) => void }) {
  const query = useManagerOverview();
  if (query.isLoading) return <LoadingSkeleton label="Loading queue overview…" rows={1}/>;
  if (query.isError) return <div className="manager-inline-error" role="alert"><p>Queue indicators could not be refreshed. You can still work with the request list.</p><Button tone="secondary" onClick={() => void query.refetch()}>Retry indicators</Button></div>;
  if (!query.data?.summary) return null;
  const { summary, policy } = query.data;
  const cards = [
    { label: "New requests", value: summary.new, focus: { status: "submitted" } },
    { label: "Under review", value: summary.in_review, focus: { status: "in_review" } },
    { label: "Needs attention", value: summary.needs_attention, focus: { status: "", attention: "needs_attention" } },
    { label: "Overdue reviews", value: summary.overdue, focus: { status: "", attention: "overdue" } },
  ];
  return <section aria-label="Your queue overview" className="manager-overview">
    <div className="manager-metrics">{cards.map(card => <button key={card.label} className="focus-ring manager-metric" onClick={() => onFocus(card.focus)} aria-label={`${card.label}: ${card.value}. Show requests`}><span>{card.label}</span><strong>{card.value}</strong><span className="manager-metric-link">Show requests</span></button>)}</div>
    <details className="manager-review-policy"><summary className="focus-ring">Queue details and review targets</summary><p className="manager-overview-context">Currently assigned to you · Waiting for employee: {summary.waiting_for_employee} · To complete: {summary.awaiting_completion} · Completed in the last 30 days: {summary.completed_last_30_days}</p><p>{policy.description}</p><p>Needs attention includes overdue reviews, high or urgent priority, reconsideration and employee replies awaiting review. Indicators cover your entire permitted queue, regardless of the list filters. Completed counts distinct requests with a completion in the last 30 days, including those subsequently reopened.</p></details>
  </section>;
}
