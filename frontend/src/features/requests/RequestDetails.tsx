import { Check, MessageSquareText } from "lucide-react";
import type { RequestDetail, RequestEvent, WorkflowRequest } from "../../api/types";
import { employeeRequestStage, nextStep, requestDate, requestLabel } from "./requestPresentation";
import "./request-progress.css";

export function EmployeeRequestProgress({ detail, informationRequest }: { detail: RequestDetail; informationRequest?: RequestEvent }) {
  const { request, allowed_actions } = detail;
  const progress = employeeRequestStage(request.status);
  const canReply = allowed_actions.includes("provide_information");
  const next = request.status === "needs_information"
    ? canReply ? "Read your manager's question, then choose Reply to manager. Sending your reply returns this request to review." : "Read your manager's question below. Reload the request to check the actions currently available to you."
    : request.status === "approved" ? "Read the decision below. Your manager marks the request completed after the approved work is finished."
    : request.status === "rejected" && !allowed_actions.includes("appeal") ? "Read the decision reason and history below. Reconsideration is not currently available for this request."
    : nextStep(request.status, false);
  return <section aria-label="Request progress" className="employee-request-progress" data-attention={request.status === "needs_information" || request.status === "rejected"}>
    <div className="employee-request-progress-heading"><h3>{progress.title}</h3><p>{request.review_round > 1 ? `Reconsideration · review ${request.review_round}` : "Current stage"}</p></div>
    {progress.current !== null && <ol className="employee-request-stages" aria-label="Review stages">{progress.stages.map((label, index) => <li key={label} aria-current={index === progress.current ? "step" : undefined} data-state={index < progress.current! ? "done" : index === progress.current ? "current" : "upcoming"}><span className="employee-request-stage-marker" aria-hidden="true">{index < progress.current! ? <Check size={13}/> : index + 1}</span><span className="employee-request-stage-label">{label}</span><span className="sr-only">{index < progress.current! ? ": reached" : index === progress.current ? ": current stage" : ": not reached"}</span></li>)}</ol>}
    <div className="employee-request-next-step"><h4>What happens next</h4><p>{next}</p></div>
    {request.status === "needs_information" && <section aria-label="Information requested" className="employee-information-request"><h4>Your manager's question</h4>{informationRequest ? <><blockquote>{String(informationRequest.details.comment)}</blockquote><p>{informationRequest.actor} · <time dateTime={informationRequest.created_at}>{requestDate(informationRequest.created_at)}</time></p></> : <p>No question was recorded in the available history. Review the comments or ask your assigned manager what is needed.</p>}</section>}
  </section>;
}

export function RequestOverview({ request, managerName }: { request: WorkflowRequest; managerName?: string }) {
  return <><dl className="request-overview-fields grid grid-cols-2 gap-x-5 gap-y-3 text-sm">
      <Item label="Employee" value={request.applicant} />
      <Item label="Assigned manager" value={managerName || request.approver}/>
      <Item label="Category" value={request.type_label}/>
      <Item label="Priority" value={requestLabel(request.priority)}/>
      {request.start_date && <Item label="Starts" value={request.start_date} />}
      {request.end_date && <Item label="Ends" value={request.end_date} />}
    </dl><p className="mt-3 flex flex-wrap gap-x-4 gap-y-1 border-t border-line pt-3 text-xs leading-5 text-muted">{request.duration_days !== null && <span>{request.duration_days} calendar days</span>}<span>Created <time dateTime={request.created_at}>{requestDate(request.created_at)}</time></span><span>Updated <time dateTime={request.updated_at}>{requestDate(request.updated_at)}</time></span></p></>;
}

export function DecisionNote({ detail }: { detail: RequestDetail }) {
  const decision = latestDecisionEvent(detail);
  const note = decisionComment(detail);
  if (!decision && !["approved", "rejected", "completed"].includes(detail.request.status)) return null;
  const declined = ["declined", "rejected"].includes(decision?.to_status ?? detail.request.status);
  return <section aria-label="Recorded decision" className={declined ? "rounded-lg border border-danger/25 bg-danger/10 p-4" : "rounded-lg border border-lime/20 bg-lime-soft p-4"}>
    <div className="flex gap-3">
      <MessageSquareText className={declined ? "mt-0.5 shrink-0 text-danger" : "mt-0.5 shrink-0 text-lime"} size={18} />
      <div>
        <h3 className="text-sm font-semibold">
          Latest recorded decision: {declined ? "Rejected" : "Approved"}
        </h3>
        <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-cream">{note || "No decision reason was recorded in this older request. Review the history or contact the assigned manager."}</p>
        {typeof decision?.details.basis === "string" && <p className="mt-3 whitespace-pre-wrap text-sm">Policy / criteria: {decision.details.basis}</p>}
        <p className="mt-2 text-xs text-muted">{decision?.actor}{decision && ` · ${requestDate(decision.created_at)}`}</p>
        {["submitted", "in_review", "needs_information"].includes(detail.request.status) && <p className="mt-2 text-sm">Reconsideration is in progress. This earlier decision remains in the record.</p>}
      </div>
    </div>
  </section>;
}

export function RequestTimeline({ detail }: { detail: RequestDetail }) {
  return <details className="rounded-lg border border-line bg-panel p-4">
    <summary className="focus-ring rounded font-semibold">History <span className="ml-1 text-sm font-normal text-muted">({detail.events.length} {detail.events.length === 1 ? "event" : "events"})</span></summary>
    <p className="mt-2 text-xs leading-5 text-muted">Every recorded change, with who made it and when. Oldest first; earlier decisions remain visible.</p>
    <ol className="request-history-list" aria-label="Request history events">
      {detail.events.length === 0 && <li className="text-sm text-muted">No history events are available yet.</li>}
      {detail.events.map((event, index) => {
        const comment = eventComment(event) || detail.comments.find(item => item.id === event.details.comment_id)?.body;
        const attachment = event.details.attachment && typeof event.details.attachment === "object" ? event.details.attachment as Record<string, unknown> : undefined;
        return <li key={event.id} className="relative flex gap-3 pb-5">
          <div className="relative z-10 mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-lime" />
          {index < detail.events.length - 1 && <div className="absolute left-[4px] top-3 h-full w-px bg-line" />}
          <div className="min-w-0">
            <p className="text-sm font-semibold">{eventLabel(event)}</p>
            <p className="mt-1 text-xs text-muted">{event.actor} · <time dateTime={event.created_at}>{requestDate(event.created_at)}</time></p>
            {event.details.changes && typeof event.details.changes === "object" ? <ul className="mt-2 space-y-1 text-xs text-muted">{Object.entries(event.details.changes as Record<string, { before: unknown; after: unknown }>).map(([key, value]) => <li key={key} className="whitespace-pre-wrap break-words">{changeLabel(key)}: {key === "status" ? requestLabel(String(value.before ?? "New")) : String(value.before ?? "—")} → {key === "status" ? requestLabel(String(value.after ?? "—")) : String(value.after ?? "—")}</li>)}</ul> : null}
            {typeof attachment?.filename === "string" && <p className="mt-2 break-words text-xs">File: {attachment.filename}</p>}
            {typeof event.details.basis === "string" && <p className="mt-2 whitespace-pre-wrap text-xs">Policy / criteria: {event.details.basis}</p>}
            {comment && <p className="mt-2 rounded-xl border border-line bg-ink/55 px-3 py-2 text-xs leading-5 text-cream">{comment}</p>}
          </div>
        </li>;
      })}
    </ol>

  </details>;
}

export function decisionComment(detail: RequestDetail): string | null {
  const event = latestDecisionEvent(detail);
  return event ? eventComment(event) : null;
}

export function latestDecisionEvent(detail: RequestDetail): RequestEvent | undefined {
  return [...detail.events].reverse().find(event => event.event_type === "decision_recorded" || (
    event.event_type === "status_changed" && event.from_status !== event.to_status &&
    ["approved", "declined", "rejected"].includes(event.to_status ?? "")
  ));
}

function eventComment(event: RequestEvent): string | null {
  const value = event.details.comment;
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

export function eventLabel(event: RequestEvent): string {
  const labels: Record<string, string> = { draft_created: "Draft created", draft_updated: "Draft updated", request_information: "Manager requested information", provide_information: "Employee replied", reconsideration_requested: "Reconsideration requested", comment_added: "Comment added", attachment_added: "Attachment added", assignee_changed: "Assigned manager changed" };
  if (event.event_type === "decision_recorded") return `${requestLabel(event.to_status ?? "Decision")} decision recorded${typeof event.details.review_round === "number" ? ` · review ${event.details.review_round}` : ""}`;
  if (labels[event.event_type]) return labels[event.event_type];
  if (event.event_type === "status_changed" && event.from_status !== event.to_status) return `${requestLabel(event.from_status ?? "new")} → ${requestLabel(event.to_status ?? "")}`;
  return requestLabel(event.event_type);
}

function changeLabel(key: string): string {
  const labels: Record<string, string> = { approver: "Assigned manager", applicant: "Employee", comment: "Description", type: "Category", review_round: "Review round" };
  return labels[key] ?? requestLabel(key);
}

function Item({ label, value }: { label: string; value: string }) {
  return <div>
    <dt className="text-xs text-muted">{label}</dt>
    <dd className="mt-0.5 break-words font-medium">{value}</dd>
  </div>;
}
