import { CalendarBlank, CaretDown, FileText } from "@phosphor-icons/react";
import type { ChatMessage, WorkflowRequest } from "../../api/types";
import { BrandMark } from "../../components/BrandMark";
import { Badge, Button, formatStatus, statusTone } from "../../components/ui";
import { FeedbackButtons } from "../feedback/FeedbackButtons";
import { formatRequestDate, timeAwayLabel } from "../requests/requestPresentation";
import { workflowMessage } from "./conversationPresentation";

function period(request: WorkflowRequest) {
  if (!request.start_date) return "Dates to confirm";
  if (!request.end_date || request.start_date === request.end_date)
    return formatRequestDate(request.start_date);
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).formatRange(
    new Date(`${request.start_date}T12:00:00`),
    new Date(`${request.end_date}T12:00:00`),
  );
}

export function ChatMessageItem({
  message,
  onOpenRequest,
}: {
  message: ChatMessage;
  onOpenRequest: (request: WorkflowRequest) => void;
}) {
  if (message.role === "user")
    return <div className="chat-message message-enter user-message">{message.content}</div>;
  const workflow = message.workflow;
  const content = workflow && !message.error ? workflowMessage(workflow) : message.content;
  return (
    <article
      className="chat-message message-enter assistant-message"
      aria-label="PeopleFlow response"
    >
      <div className="assistant-avatar">
        <BrandMark size={28} />
      </div>
      <div className="min-w-0">
        <div
          className={`assistant-copy whitespace-pre-wrap break-words ${message.error ? "text-danger" : "text-cream"} ${message.streaming ? "token-caret" : ""}`}
          role={message.error ? "alert" : undefined}
        >
          {content || "Looking through your company knowledge…"}
        </div>
        {!!message.sources?.length && (
          <details className="source-disclosure">
            <summary className="source-summary focus-ring">
              <FileText size={16} className="shrink-0" />
              <span className="max-w-60 truncate">
                {message.sources.length === 1
                  ? message.sources[0].title
                  : `${message.sources.length} sources`}
              </span>
              <span className="text-success">·</span>
              <span>{message.sources.length === 1 ? "Source" : "View"}</span>
              <CaretDown className="source-caret ml-1" size={13} />
            </summary>
            <div className="mt-3 divide-y divide-line rounded-md border border-line bg-panel px-4">
              {message.sources.map((source) => (
                <section key={`${source.source}-${source.section}`} className="py-4">
                  <div className="flex items-start justify-between gap-3">
                    <h3 className="text-xs font-medium">{source.title}</h3>
                    <span className="text-[11px] text-muted">v{source.version}</span>
                  </div>
                  <p className="mt-1 text-xs text-accent">{source.section}</p>
                  <blockquote className="mt-3 border-l-2 border-accent/40 pl-3 text-xs leading-6 text-muted">
                    {source.excerpt}
                  </blockquote>
                </section>
              ))}
            </div>
          </details>
        )}
        {workflow && (
          <section className="request-inline" aria-label={`${workflow.type_label} request`}>
            <div className="flex items-center gap-3 border-b border-line pb-3">
              <FileText size={18} className="text-muted" />
              <h3 className="flex-1 text-sm font-medium">{workflow.type_label}</h3>
              <Badge tone={workflow.status === "draft" ? "neutral" : statusTone(workflow.status)}>
                {formatStatus(workflow.status)}
              </Badge>
            </div>
            <div className="my-4 flex items-start gap-3">
              <CalendarBlank size={24} className="mt-0.5 shrink-0 text-muted" />
              <div className="min-w-0">
                <p className="text-xl font-semibold tracking-tight">{period(workflow)}</p>
                <p className="mt-1 text-sm text-muted">
                  {workflow.type === "sick_leave"
                    ? timeAwayLabel(workflow)
                    : workflow.duration_days
                      ? `${workflow.duration_days} calendar ${workflow.duration_days === 1 ? "day" : "days"}`
                      : "Duration to confirm"}
                </p>
                {workflow.comment && (
                  <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6 text-muted">
                    {workflow.comment}
                  </p>
                )}
              </div>
            </div>
            <div className="border-t border-line pt-3">
              <Button onClick={() => onOpenRequest(workflow)}>
                {workflow.status === "draft" ? "Review request" : "View request"}
              </Button>
            </div>
          </section>
        )}
        {message.id !== "hello" && !message.streaming && !message.error && (
          <div className="mt-2">
            <FeedbackButtons question={message.question ?? ""} answer={content} />
          </div>
        )}
      </div>
    </article>
  );
}
