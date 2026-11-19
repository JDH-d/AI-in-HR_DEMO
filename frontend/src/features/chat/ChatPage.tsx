import { useChatWorkspace } from "./useChatWorkspace";
import { ConversationActions, ConversationList, ConversationSearch } from "./ConversationControls";
import { RequestDetailDrawer } from "../requests/RequestDetailDrawer";
import { ArrowUp, FileCheck2, Sparkles } from "lucide-react";
import { useEffect, useLayoutEffect, useRef } from "react";
import type { ChatMessage, WorkflowRequest } from "../../api/types";
import { Shell } from "../../components/Shell";
import { Button, Card, LoadingSkeleton, formatStatus } from "../../components/ui";
import { FeedbackButtons } from "../feedback/FeedbackButtons";
import { RequestDrawer } from "../requests/RequestDrawer";
import { SourceEvidence } from "./SourceEvidence";
import { MessageContent } from "../../components/MessageContent";
const suggestions = [
  ["Vacation policy", "How far in advance should I request vacation?"],
  ["Payroll timing", "When is payroll processed?"],
  ["VPN access", "How do I request VPN access?"],
  ["New hire setup", "What should be ready for a new hire on day one?"],
];

function resizeComposer(input: HTMLTextAreaElement) {
  input.style.height = "auto";
  input.style.height = `${Math.min(160, Math.max(48, input.scrollHeight))}px`;
}

export function ChatPage() {
  const messageViewport = useRef<HTMLDivElement>(null);
  const composerInput = useRef<HTMLTextAreaElement>(null);
  const followLatest = useRef(true);
  // Message changes scroll after React commits them, rather than inside stream callbacks.
  const { employee, conversations, drawer, setDrawer, requestDraft, selectedRequest, setSelectedRequest, requests, openNewRequest, openRequest } = useChatWorkspace(() => {});
  const { messages, draft, setDraft, send, unavailable } = conversations;
  const sending = conversations.pending || Boolean(conversations.id && !conversations.detail.data);
  const showWelcome = messages.length === 0 && !sending && !conversations.detail.isError;
  const previousView = useRef({id: conversations.id, busy: false});
  const EmptyHeading = conversations.detail.data?.conversation ? "h2" : "h1";
  const lastMessage = messages.at(-1);
  useLayoutEffect(() => {
    const input = composerInput.current;
    if (input) resizeComposer(input);
  }, [draft]);
  useEffect(() => {
    const input = composerInput.current;
    if (!input || typeof ResizeObserver === "undefined") return;
    let width = input.clientWidth;
    const observer = new ResizeObserver(() => {
      const nextWidth = input.clientWidth;
      if (nextWidth === width) return;
      width = nextWidth;
      resizeComposer(input);
    });
    observer.observe(input);
    return () => observer.disconnect();
  }, []);
  // Announce turn state once, without reading each streamed token aloud. Errors
  // already have their own alert, and a failed turn must never sound complete.
  const answerStatus = conversations.error || conversations.detail.isError ? ""
    : conversations.canRetry || lastMessage?.status === "failed" ? "The answer could not be completed. Use Retry last message."
    : lastMessage?.status === "pending" || lastMessage?.streaming ? "PeopleFlow is preparing an answer."
    : !sending && lastMessage?.role === "assistant" && lastMessage.status === "complete" ? "Answer ready."
    : "";

  const scrollToLatest = () => {
    const viewport = messageViewport.current;
    if (viewport) viewport.scrollTo({top: viewport.scrollHeight, behavior: "auto"});
  };
  useEffect(() => {
    const viewport = messageViewport.current;
    if (!viewport || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => { if (followLatest.current) scrollToLatest(); });
    observer.observe(viewport);
    return () => observer.disconnect();
  }, []);

  useLayoutEffect(() => {
    if (previousView.current.id !== conversations.id || (!previousView.current.busy && conversations.busy)) {
      followLatest.current = true;
    }
    previousView.current = {id: conversations.id, busy: conversations.busy};
    if (followLatest.current && messages.length) {
      scrollToLatest();
    }
  }, [conversations.id, conversations.busy, messages]);

  const sidebar = <ConversationList history={conversations}/>;

  return (
    <Shell sidebar={sidebar} eyebrow={employee ? "Employee workspace" : "My conversations"} title="My chats"
      headerContent={openNavigation => <ConversationSearch history={conversations} onShowHistory={openNavigation}/> }>
      <div className="chat-workspace">
        <div className="chat-toolbar">
        <ConversationActions key={conversations.id} history={conversations}/>
        {!conversations.detail.data?.conversation && <p className="min-w-0 flex-1 text-sm font-semibold">{conversations.id ? conversations.detail.isError ? "Conversation unavailable" : "Loading conversation…" : "New conversation"}</p>}
        {employee && <Button tone="secondary" className="shrink-0" aria-label="Create request" onClick={openNewRequest}><FileCheck2 size={16}/><span className="hidden sm:inline">Create request</span><span className="sm:hidden">Request</span></Button>}
        </div>
        <div ref={messageViewport} className="chat-messages scrollbar" role="region" aria-label="Conversation messages" tabIndex={0}
          onScroll={event => { const viewport = event.currentTarget; followLatest.current = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight <= 120; }}>
        <div className="chat-reading-column">
        {conversations.id && conversations.detail.isLoading && <LoadingSkeleton label="Loading conversation…"/>}
        {conversations.id && conversations.detail.isError && <div role="alert" className="my-4 space-y-3 rounded-lg border border-danger/25 bg-panel p-4 text-sm">
          <p className="font-semibold text-danger">{unavailable ? "This conversation is no longer available to you." : "The conversation could not be loaded."}</p>
          <p className="leading-6 text-muted">{unavailable ? "Choose another conversation from history or start a new one. Your other conversations stay saved." : conversations.detail.data ? "Previously loaded messages are shown below. Check your connection and reload to see the latest messages." : "Check your connection and reload. You can also choose another conversation from history or start a new one."}</p>
          <div className="flex flex-wrap gap-2"><Button tone="secondary" onClick={() => void conversations.detail.refetch()}>Reload conversation</Button>
          {!conversations.detail.data && <Button tone="ghost" onClick={() => conversations.select(null)}>Start a new conversation</Button>}</div>
        </div>}
        <div className="py-4 sm:py-5">
          {showWelcome && (
            <section className="chat-welcome">
              <EmptyHeading className="max-w-2xl text-2xl font-semibold tracking-tight">
                How can we help with work?
              </EmptyHeading>
              <p className="mt-2 text-sm leading-6 text-muted">Ask in English about company policies, benefits or getting work done. For something that needs review or approval, create a request.</p>
              <div className="chat-suggestions">
                {suggestions.map(([label, prompt]) => (
                  <button
                    key={label}
                    onClick={() => send(prompt)}
                    disabled={sending}
                    className="chat-suggestion focus-ring group"
                  >
                    <span className="text-sm font-semibold text-cream">
                      {label}
                    </span>
                    <span className="mt-1 hidden text-xs leading-5 text-muted group-hover:text-cream sm:block">
                      {prompt}
                    </span>
                  </button>
                ))}
              </div>
            </section>
          )}
          <div className="space-y-5">
            {showWelcome && <p className="text-xs leading-5 text-muted">Your conversations are saved. Select a recent chat or search to pick up where you left off.</p>}
            {messages.map((message) => (
              <Message
                key={message.id}
                message={{
                  ...message,
                  workflow:
                    requests.data?.requests.find(
                      (request) => request.id === message.workflow?.id,
                    ) ?? message.workflow,
                }}
                onOpenRequest={openRequest}
                allowFeedback={employee}
              />
            ))}
          </div>
        </div>
        </div>
        </div>
        <div className="chat-composer">
          <div className="chat-reading-column">
          <p role="status" aria-atomic="true" className="sr-only">{answerStatus}</p>
          {(conversations.error || conversations.canRetry) && <div className="mb-2 rounded-lg border border-danger/25 bg-panel p-3">
            {conversations.error && <p role="alert" className="text-sm text-danger">{conversations.error}</p>}
            <p className="mt-1 text-xs leading-5 text-muted">{draft ? "Your text is kept below. " : ""}{conversations.canRetry ? "Use Retry last message to continue the same attempt without a duplicate." : "Check your connection, then try sending again."}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {conversations.canRetry && <Button tone="secondary" disabled={sending} onClick={conversations.retryLast}>Retry last message</Button>}
              {conversations.id && <Button tone="ghost" onClick={() => void conversations.detail.refetch()}>Reload saved messages</Button>}
            </div>
          </div>}
          <div className="rounded-lg border border-control bg-panel p-2 shadow-sm focus-within:border-lime">
            <div className="flex items-end gap-2">
            <textarea
              ref={composerInput}
              aria-label="Message PeopleFlow AI"
              aria-describedby="message-composer-hint"
              rows={1}
              value={draft}
              maxLength={16000}
              disabled={sending}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  send();
                }
              }}
              placeholder="Ask a question in English…"
              className="focus-ring max-h-40 min-h-12 min-w-0 flex-1 resize-none overflow-y-auto rounded-lg bg-panel px-2 py-3 text-sm leading-6 placeholder:text-muted disabled:bg-raised"
            />
              <Button
                aria-label="Send message"
                className="h-11 w-11 shrink-0 rounded-lg"
                style={{ padding: 0 }}
                disabled={sending || !draft.trim()}
                onClick={() => send()}
              >
                <ArrowUp size={17} />
              </Button>
            </div>
          </div>
          <div className="chat-composer-meta">
            <p id="message-composer-hint" className="text-xs leading-5 text-muted"><span>Answers use company sources when available.</span><span className="hidden sm:block">Enter to send · Shift + Enter for a new line</span></p>
          </div>
          </div>
        </div>
      </div>
      {employee && <RequestDrawer
        open={drawer}
        onOpenChange={setDrawer}
        initial={requestDraft}
        onOpenRequest={setSelectedRequest}
      />}
      {employee && <RequestDetailDrawer
        id={selectedRequest}
        onClose={() => setSelectedRequest(null)}
      />}
    </Shell>
  );
}

function Message({
  message,
  onOpenRequest,
  allowFeedback,
}: {
  message: ChatMessage;
  onOpenRequest: (request: WorkflowRequest) => void;
  allowFeedback: boolean;
}) {
  if (message.role === "user")
    return (
      <div className="message-enter ml-auto max-w-[90%] whitespace-pre-wrap rounded-xl rounded-br-sm border border-line bg-panel px-3 py-2.5 text-sm leading-6 text-cream [overflow-wrap:anywhere] sm:max-w-[85%]">
        {message.content}
        <MessageTime message={message}/>
      </div>
    );
  return (
    <article className="message-enter max-w-3xl [overflow-wrap:anywhere]">
      <div className="mb-2 flex items-center gap-2">
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-accent text-on-accent">
          <Sparkles size={14} />
        </span>
        <strong className="text-xs">PeopleFlow</strong>
      </div>
      <MessageContent content={message.content || (message.status === "failed" ? "This answer could not be completed." : "Thinking with your company knowledge…")} streaming={message.streaming}/>
      <MessageTime message={message}/>
      {message.workflow && (
        <Card className="mt-4 border-coral/25 bg-coral/5">
          <div className="flex flex-col items-start gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <span className="text-xs font-bold uppercase tracking-wider text-coral">
                {message.workflow.status === "draft" ? "Request draft" : "Your request"}
              </span>
              <p className="mt-1 text-sm">
                {message.workflow.status === "draft"
                  ? "A request draft is ready. Nothing has been sent for review."
                  : `Request status: ${formatStatus(message.workflow.status)}.`}
              </p>
            </div>
            <Button onClick={() => onOpenRequest(message.workflow!)}>
              {message.workflow.status === "draft"
                ? "Review draft"
                : "View request"}
            </Button>
          </div>
        </Card>
      )}
      <div className="mt-1 flex flex-wrap items-start gap-x-3">
      <SourceEvidence sources={message.sources}/>
      {allowFeedback && !message.streaming && message.status !== "pending" && message.status !== "failed" && (
        <div className="min-w-0 max-w-full">
          <FeedbackButtons
            question={message.question ?? ""}
            answer={message.content}
          />
        </div>
      )}
      </div>
    </article>
  );
}

function MessageTime({message}: {message: ChatMessage}) {
  if (!message.created_at) return null;
  return <time dateTime={message.created_at} className="mt-1 block text-xs leading-5 text-muted">{new Date(message.created_at).toLocaleString()}</time>;
}

