import { MessageCircleQuestion, Plus } from "lucide-react";
import type { ReactNode } from "react";
import type { ConversationSummary, WorkflowRequest } from "../../api/types";
import { Badge, Button, formatStatus, statusTone } from "../../components/ui";
import { requestPeriodLabel } from "../requests/requestPresentation";
import { conversationMeta } from "./conversationPresentation";

type EmployeeSidebarProps = {
  conversations: ConversationSummary[];
  conversationsLoading: boolean;
  conversationsError: boolean;
  requests: WorkflowRequest[];
  requestsLoading: boolean;
  requestsError: boolean;
  activeConversationId: string | null;
  sending: boolean;
  onNewRequest: () => void;
  onOpenConversation: (id: string) => void;
  onOpenRequest: (request: WorkflowRequest) => void;
};

export function EmployeeSidebar({
  conversations,
  conversationsLoading,
  conversationsError,
  requests,
  requestsLoading,
  requestsError,
  activeConversationId,
  sending,
  onNewRequest,
  onOpenConversation,
  onOpenRequest,
}: EmployeeSidebarProps) {
  return (
    <>
      <Button className="mb-5 w-full justify-start" onClick={onNewRequest}>
        <Plus size={16} />
        New request
      </Button>
      <NavLabel>Recent conversations</NavLabel>
      <nav className="space-y-1.5" aria-label="Conversation history">
        {conversationsLoading &&
          [0, 1, 2].map((item) => (
            <div key={item} className="mx-2 h-12 animate-pulse rounded-xl bg-raised/70" />
          ))}
        {conversationsError && (
          <p className="rounded-xl border border-danger/20 bg-danger/5 px-3 py-3 text-xs leading-5 text-danger">
            Conversation history is unavailable.
          </p>
        )}
        {!conversationsLoading && !conversationsError && conversations.length === 0 && (
          <div className="rounded-xl border border-dashed border-line px-3 py-4 text-xs leading-5 text-muted">
            Your conversations will appear here after the first reply.
          </div>
        )}
        {conversations.map((conversation) => {
          const active = conversation.id === activeConversationId;
          return (
            <button
              key={conversation.id}
              type="button"
              disabled={sending}
              aria-current={active ? "page" : undefined}
              onClick={() => onOpenConversation(conversation.id)}
              className={`focus-ring group flex w-full items-center gap-2.5 rounded-xl border px-2.5 py-2.5 text-left transition disabled:cursor-wait ${active ? "border-lime/20 bg-lime-soft/55 text-cream" : "border-transparent text-muted hover:border-line hover:bg-raised hover:text-cream"}`}
            >
              <span
                className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg ${active ? "bg-lime/15 text-lime" : "bg-raised text-muted group-hover:text-cream"}`}
              >
                <MessageCircleQuestion size={15} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-medium">{conversation.title}</span>
                <span className="mt-0.5 block truncate text-[10px] text-muted">
                  {conversationMeta(conversation)}
                </span>
              </span>
              {active && (
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-lime" aria-hidden="true" />
              )}
            </button>
          );
        })}
      </nav>

      <NavLabel>My requests</NavLabel>
      <div className="space-y-2">
        {requestsLoading && <div className="mx-2 h-20 animate-pulse rounded-xl bg-raised/70" />}
        {requestsError && (
          <p className="rounded-xl border border-danger/20 bg-danger/5 px-3 py-3 text-xs leading-5 text-danger">
            Your requests are unavailable.
          </p>
        )}
        {requests.slice(0, 4).map((request) => (
          <button
            key={request.id}
            type="button"
            className="focus-ring w-full rounded-xl border border-line bg-ink/45 p-3 text-left transition hover:border-lime/30 hover:bg-raised"
            onClick={() => onOpenRequest(request)}
            aria-label={`Open ${request.type_label} request, status ${formatStatus(request.status)}`}
          >
            <div className="flex justify-between gap-2">
              <span className="truncate text-xs font-semibold">{request.type_label}</span>
              <Badge tone={statusTone(request.status)}>{formatStatus(request.status)}</Badge>
            </div>
            <p className="mt-2 truncate text-[11px] text-muted">{requestPeriodLabel(request)}</p>
            {request.status === "declined" && (
              <p className="mt-2 text-[11px] font-semibold text-danger">Open to see the reason</p>
            )}
          </button>
        ))}
        {!requestsLoading && !requestsError && requests.length === 0 && (
          <p className="px-3 text-xs leading-5 text-muted">
            Requests sent for review will stay visible here.
          </p>
        )}
      </div>
    </>
  );
}

function NavLabel({ children }: { children: ReactNode }) {
  return (
    <div className="mb-2 mt-5 px-3 text-[10px] font-bold uppercase tracking-[.16em] text-muted">
      {children}
    </div>
  );
}
