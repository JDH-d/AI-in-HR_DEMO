import { MessageSquareText } from "lucide-react";
import type { RequestDetail, RequestEvent, WorkflowRequest } from "../../api/types";
import { Card } from "../../components/ui";

export function RequestOverview({ request }: { request: WorkflowRequest }) {
  return <Card className="bg-ink/50">
    <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
      <Item label="Employee" value={request.applicant} />
      <Item label="Duration" value={request.duration_days ? `${request.duration_days} days` : "—"} />
      <Item label="Starts" value={request.start_date ?? "—"} />
      <Item label="Ends" value={request.end_date ?? "—"} />
    </dl>
    <div className="mt-5 border-t border-line pt-5">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted">Employee note</p>
      <p className="mt-2 text-sm leading-6">{request.comment}</p>
    </div>
  </Card>;
}

export function DecisionNote({ detail }: { detail: RequestDetail }) {
  const note = decisionComment(detail);
  if (!note) return null;
  const declined = detail.request.status === "declined";
  return <section className={declined ? "rounded-2xl border border-danger/25 bg-danger/10 p-5" : "rounded-2xl border border-lime/20 bg-lime-soft p-5"}>
    <div className="flex gap-3">
      <MessageSquareText className={declined ? "mt-0.5 shrink-0 text-danger" : "mt-0.5 shrink-0 text-lime"} size={18} />
      <div>
        <h3 className="text-xs font-bold uppercase tracking-wider text-muted">
          {declined ? "Reason for decline" : "Decision note"}
        </h3>
        <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-cream">{note}</p>
      </div>
    </div>
  </section>;
}

export function RequestTimeline({ detail }: { detail: RequestDetail }) {
  return <section>
    <h3 className="mb-4 text-xs font-bold uppercase tracking-wider text-muted">Timeline</h3>
    <div>
      {detail.events.map((event, index) => {
        const comment = eventComment(event);
        return <div key={event.id} className="relative flex gap-3 pb-5">
          <div className="relative z-10 mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-lime" />
          {index < detail.events.length - 1 && <div className="absolute left-[4px] top-3 h-full w-px bg-line" />}
          <div className="min-w-0">
            <p className="text-sm font-semibold">{eventLabel(event)}</p>
            <p className="mt-1 text-xs text-muted">{event.actor} · {new Date(event.created_at).toLocaleString()}</p>
            {comment && <p className="mt-2 rounded-xl border border-line bg-ink/55 px-3 py-2 text-xs leading-5 text-cream">{comment}</p>}
          </div>
        </div>;
      })}
    </div>
    {detail.comments.length > 0 && <div className="mt-1 border-t border-line pt-5">
      <h3 className="mb-3 text-xs font-bold uppercase tracking-wider text-muted">Comments</h3>
      <div className="space-y-3">
        {detail.comments.map(comment => <div key={comment.id} className="rounded-xl border border-line bg-ink/45 p-3">
          <p className="text-sm leading-6">{comment.body}</p>
          <p className="mt-2 text-[11px] text-muted">{comment.author} · {new Date(comment.created_at).toLocaleString()}</p>
        </div>)}
      </div>
    </div>}
  </section>;
}

export function decisionComment(detail: RequestDetail): string | null {
  const event = [...detail.events].reverse().find(item => item.to_status === detail.request.status && eventComment(item));
  return event ? eventComment(event) : null;
}

function eventComment(event: RequestEvent): string | null {
  const value = event.details.comment;
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function eventLabel(event: RequestEvent): string {
  if (event.to_status) return event.to_status.replaceAll("_", " ");
  return event.event_type.replaceAll("_", " ");
}

function Item({ label, value }: { label: string; value: string }) {
  return <div>
    <dt className="text-[10px] uppercase tracking-wider text-muted">{label}</dt>
    <dd className="mt-1 break-words font-semibold">{value}</dd>
  </div>;
}
