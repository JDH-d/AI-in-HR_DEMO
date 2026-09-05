import { ChatCircle, FileText, Plus, Trash } from "@phosphor-icons/react";
import { useState } from "react";
import type { ConversationSummary, WorkflowRequest } from "../../api/types";
import { Badge, Button, formatStatus, Hint, statusTone } from "../../components/ui";
import { formatRequestDate, requestPeriodLabel } from "../requests/requestPresentation";
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
  onNewChat: () => void;
  onNewRequest: () => void;
  onOpenConversation: (id: string) => void;
  onDeleteConversation: (conversation: ConversationSummary, trigger: HTMLButtonElement) => void;
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
  onNewChat,
  onNewRequest,
  onOpenConversation,
  onDeleteConversation,
  onOpenRequest,
}: EmployeeSidebarProps) {
  const [allRequests, setAllRequests] = useState(false);
  return (
    <>
      <Button
        tone="ghost"
        className="w-full justify-start gap-3 px-4 py-2.5"
        data-new-chat
        disabled={sending}
        onClick={onNewChat}
      >
        <Plus size={20} />
        New Chat
      </Button>
      <h2 className="nav-label">Recents</h2>
      <nav className="space-y-1" aria-label="Conversation history">
        {conversationsLoading && (
          <p className="px-4 py-3 text-xs text-muted" role="status">
            Loading conversations…
          </p>
        )}
        {conversationsError && (
          <p role="status" className="px-4 py-3 text-xs leading-5 text-danger">
            Conversation history is unavailable.
          </p>
        )}
        {!conversationsLoading && !conversationsError && conversations.length === 0 && (
          <p className="px-4 py-2 text-xs leading-5 text-muted">
            Your conversations will appear here.
          </p>
        )}
        {conversations.map((conversation) => (
          <div key={conversation.id} className="conversation-row relative">
            <button
              type="button"
              disabled={sending}
              aria-current={conversation.id === activeConversationId ? "page" : undefined}
              onClick={() => onOpenConversation(conversation.id)}
              className="sidebar-row focus-ring pr-11 disabled:opacity-50"
              title={`${conversation.title} · ${conversationMeta(conversation)}`}
            >
              <ChatCircle size={21} className="shrink-0" />
              <span className="min-w-0 truncate text-sm">{conversation.title}</span>
            </button>
            <Hint label="Delete chat">
              <button
                type="button"
                className="icon-button conversation-delete absolute right-1 top-1/2 -translate-y-1/2 hover:text-danger disabled:opacity-35"
                aria-label={`Delete chat: ${conversation.title}`}
                disabled={sending}
                data-keep-navigation
                onClick={(event) => onDeleteConversation(conversation, event.currentTarget)}
              >
                <Trash size={17} />
              </button>
            </Hint>
          </div>
        ))}
      </nav>
      <div className="mb-1 mt-7 flex items-center justify-between pl-3.5 pr-1">
        <h2 className="text-[11px] font-medium uppercase tracking-[.065em] text-muted">
          My requests
        </h2>
        <Hint label="New request">
          <button
            type="button"
            aria-label="New request"
            className="icon-button"
            onClick={onNewRequest}
          >
            <Plus size={18} />
          </button>
        </Hint>
      </div>
      <nav aria-label="My requests" className="space-y-1">
        {requestsLoading && (
          <p className="px-4 py-3 text-xs text-muted" role="status">
            Loading requests…
          </p>
        )}
        {requestsError && (
          <p className="px-4 py-3 text-xs leading-5 text-danger" role="status">
            Your requests are unavailable.
          </p>
        )}
        {(allRequests ? requests : requests.slice(0, 4)).map((request) => (
          <button
            key={request.id}
            type="button"
            className="sidebar-row focus-ring"
            onClick={() => onOpenRequest(request)}
            aria-label={`Open ${request.type_label} request, status ${formatStatus(request.status)}`}
            title={requestPeriodLabel(request)}
          >
            <FileText size={20} className="shrink-0" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm">{request.type_label}</span>
              <span className="mt-1 block truncate text-[11px] text-muted">
                {request.start_date ? formatRequestDate(request.start_date) : "Dates to confirm"}
              </span>
            </span>
            <Badge tone={statusTone(request.status)}>{formatStatus(request.status)}</Badge>
          </button>
        ))}
        {requests.length > 4 && (
          <button
            type="button"
            className="focus-ring ml-4 rounded py-2 text-xs text-muted hover:text-cream"
            onClick={() => setAllRequests(!allRequests)}
            data-keep-navigation
          >
            {allRequests ? "Show less" : `View all ${requests.length} requests`}
          </button>
        )}
        {!requestsLoading && !requestsError && requests.length === 0 && (
          <p className="px-4 py-2 text-xs leading-5 text-muted">
            Time off and absence reports stay here.
          </p>
        )}
      </nav>
    </>
  );
}
