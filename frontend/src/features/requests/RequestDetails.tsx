import { ChatText, CheckCircle, Clock, ShieldCheck, Umbrella } from "@phosphor-icons/react";
import type { RequestDetail, RequestEvent, WorkflowRequest } from "../../api/types";
import { Card } from "../../components/ui";
import {
  expectedReturnLabel,
  formatRequestDate,
  getSickLeaveDetails,
  timeAwayLabel,
} from "./requestPresentation";

export function RequestOverview({ request }: { request: WorkflowRequest }) {
  if (request.type === "sick_leave") return <SickLeaveOverview request={request} />;
  return <PtoOverview request={request} />;
}

function PtoOverview({ request }: { request: WorkflowRequest }) {
  const duration = request.duration_days
    ? `${request.duration_days} calendar ${request.duration_days === 1 ? "day" : "days"}`
    : "Not set";
  return (
    <Card className="bg-ink">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[13px] font-medium text-muted">Approval request</p>
          <p className="mt-2 text-sm leading-6 text-muted">
            Planned time away with the dates and context needed for a clear decision.
          </p>
        </div>
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-raised text-muted">
          <Umbrella size={18} />
        </span>
      </div>
      <dl className="mt-5 grid grid-cols-2 gap-4 text-sm">
        <Item label="Employee" value={request.applicant} />
        <Item label="Time away" value={duration} />
        <Item label="First day" value={formatRequestDate(request.start_date)} />
        <Item label="Last day" value={formatRequestDate(request.end_date)} />
      </dl>
      <div className="mt-5 border-t border-line pt-4">
        <p className="text-[13px] font-medium text-muted">Planning note</p>
        <p className={`mt-2 text-sm leading-6 ${request.comment ? "text-cream" : "text-muted"}`}>
          {request.comment || "No planning note was added."}
        </p>
      </div>
      {["draft", "in_review"].includes(request.status) && (
        <div className="mt-4 flex gap-2 text-xs leading-5 text-muted">
          <Clock className="mt-0.5 shrink-0 text-accent" size={18} />A manager decision is required
          before this time off is approved.
        </div>
      )}
    </Card>
  );
}

function SickLeaveOverview({ request }: { request: WorkflowRequest }) {
  const details = getSickLeaveDetails(request);
  return (
    <Card className="bg-ink">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[13px] font-medium text-accent">Availability report</p>
          <p className="mt-2 text-sm leading-6 text-muted">
            This absence is shared for awareness and coverage, not approval.
          </p>
        </div>
        <ShieldCheck className="shrink-0 text-accent" size={19} />
      </div>
      <dl className="mt-5 grid grid-cols-2 gap-4 text-sm">
        <Item label="Employee" value={request.applicant} />
        <Item label="First day away" value={formatRequestDate(request.start_date)} />
        <Item label="Expected back" value={expectedReturnLabel(request)} />
        <Item label="Time away" value={timeAwayLabel(request)} />
      </dl>
      {details.extendedOrRecurring && (
        <div className="mt-5 rounded-lg border border-warning/25 bg-warning/5 px-4 py-3">
          <p className="text-xs font-semibold text-muted">People Ops follow-up flagged</p>
          <p className="mt-1 text-xs leading-5 text-muted">
            The employee indicated this absence may be extended or recurring.
          </p>
        </div>
      )}
      <div className="mt-5 border-t border-line pt-4">
        <p className="text-[13px] font-medium text-muted">Team note</p>
        <p className={`mt-2 text-sm leading-6 ${request.comment ? "text-cream" : "text-muted"}`}>
          {request.comment || "No availability or handoff note was added."}
        </p>
      </div>
    </Card>
  );
}

export function DecisionNote({ detail }: { detail: RequestDetail }) {
  const note = decisionComment(detail);
  if (!note) return null;
  const declined = detail.request.status === "declined";
  return (
    <section
      className={
        declined
          ? "rounded-lg border border-danger/25 bg-danger/10 p-5"
          : "rounded-lg border border-accent/20 bg-accent-soft p-5"
      }
    >
      <div className="flex gap-3">
        <ChatText
          className={declined ? "mt-0.5 shrink-0 text-danger" : "mt-0.5 shrink-0 text-accent"}
          size={18}
        />
        <div>
          <h3 className="text-[13px] font-medium text-muted">
            {declined
              ? "Reason for decline"
              : detail.request.status === "acknowledged"
                ? "Acknowledgement note"
                : "Decision note"}
          </h3>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-cream">{note}</p>
        </div>
      </div>
    </section>
  );
}

export function RequestTimeline({ detail }: { detail: RequestDetail }) {
  return (
    <section>
      <h3 className="mb-4 text-[13px] font-medium text-muted">Timeline</h3>
      <div>
        {detail.events.map((event) => {
          const comment = eventComment(event);
          return (
            <div key={event.id} className="flex gap-3 pb-5">
              <CheckCircle size={18} className="mt-0.5 shrink-0 text-muted" />
              <div className="min-w-0">
                <p className="text-sm font-medium">{eventLabel(event)}</p>
                <p className="mt-1 text-xs text-muted">
                  {event.actor} · {new Date(event.created_at).toLocaleString()}
                </p>
                {comment && (
                  <p className="mt-2 rounded-lg border border-line bg-ink px-3 py-2 text-xs leading-5 text-cream">
                    {comment}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {detail.comments.length > 0 && (
        <div className="mt-1 border-t border-line pt-4">
          <h3 className="mb-3 text-[13px] font-medium text-muted">Comments</h3>
          <div className="space-y-3">
            {detail.comments.map((comment) => (
              <div key={comment.id} className="rounded-lg border border-line bg-ink p-3">
                <p className="text-sm leading-6">{comment.body}</p>
                <p className="mt-2 text-xs text-muted">
                  {comment.author} · {new Date(comment.created_at).toLocaleString()}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

export function decisionComment(detail: RequestDetail): string | null {
  const event = [...detail.events]
    .reverse()
    .find((item) => item.to_status === detail.request.status && eventComment(item));
  return event ? eventComment(event) : null;
}

function eventComment(event: RequestEvent): string | null {
  const value = event.details.comment;
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function eventLabel(event: RequestEvent): string {
  if (event.to_status === "reported") return "Sick leave reported";
  if (event.to_status === "acknowledged") return "Manager acknowledged";
  const value = (event.to_status || event.event_type).replaceAll("_", " ");
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function Item({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-1 break-words text-sm">{value}</dd>
    </div>
  );
}
