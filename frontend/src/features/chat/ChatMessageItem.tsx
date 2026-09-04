import { ChevronDown, Search, Sparkles } from "lucide-react";
import type { ChatMessage, WorkflowRequest } from "../../api/types";
import { Badge, Button, Card } from "../../components/ui";
import { FeedbackButtons } from "../feedback/FeedbackButtons";
import { workflowMessage } from "./conversationPresentation";

export function ChatMessageItem({
  message,
  onOpenRequest,
}: {
  message: ChatMessage;
  onOpenRequest: (request: WorkflowRequest) => void;
}) {
  if (message.role === "user") {
    return (
      <div className="message-enter ml-auto max-w-[78%] rounded-2xl rounded-br-md bg-cream px-4 py-3 text-sm leading-6 text-ink">
        {message.content}
      </div>
    );
  }
  const workflow = message.workflow;

  return (
    <article className="message-enter max-w-3xl">
      <div className="mb-2 flex items-center gap-2">
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-lime text-ink">
          <Sparkles size={14} />
        </span>
        <strong className="text-xs">PeopleFlow</strong>
        {message.sources?.length ? <Badge tone="success">Grounded</Badge> : null}
      </div>
      <div
        className={`whitespace-pre-wrap text-[15px] leading-7 ${message.error ? "text-danger" : "text-cream"} ${message.streaming ? "token-caret" : ""}`}
      >
        {message.content || "Thinking with your company knowledge…"}
      </div>
      {workflow && (
        <Card className="mt-4 border-coral/25 bg-coral/5">
          <div className="flex items-center justify-between gap-4">
            <div>
              <span className="text-xs font-bold uppercase tracking-wider text-coral">
                {workflow.status === "draft" ? "Action detected" : "Request updated"}
              </span>
              <p className="mt-1 text-sm">{workflowMessage(workflow)}</p>
            </div>
            <Button onClick={() => onOpenRequest(workflow)}>
              {workflow.status === "draft" ? "Review draft" : "View request"}
            </Button>
          </div>
        </Card>
      )}
      {message.sources?.length ? (
        <details className="group mt-4">
          <summary className="focus-ring flex w-fit list-none items-center gap-2 rounded-lg py-2 text-xs font-semibold text-muted hover:text-cream">
            <Search size={14} />
            Sources · {message.sources.length}
            <ChevronDown className="transition group-open:rotate-180" size={14} />
          </summary>
          <div className="mt-2 grid gap-3">
            {message.sources.map((source) => (
              <Card key={`${source.source}-${source.section}`} className="p-4">
                <div className="flex items-center justify-between gap-3">
                  <strong className="text-xs">{source.title}</strong>
                  <span className="text-[10px] text-muted">v{source.version}</span>
                </div>
                <p className="mt-1 text-[11px] text-coral">{source.section}</p>
                <mark className="mt-3 block bg-lime/10 px-3 py-2 text-xs leading-6 text-cream">
                  {source.excerpt}
                </mark>
              </Card>
            ))}
          </div>
        </details>
      ) : null}
      {message.id !== "hello" && !message.streaming && !message.error && (
        <div className="mt-3">
          <FeedbackButtons question={message.question ?? ""} answer={message.content} />
        </div>
      )}
    </article>
  );
}
