import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, ChevronDown, FileCheck2, MessageCircleQuestion, Plus, Search, Sparkles, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { api, streamChat } from "../../api/client";
import type {
  ChatMessage,
  ConversationDetail,
  ConversationSummary,
  RequestDetail,
  Source,
  WorkflowRequest,
} from "../../api/types";
import { useAuth } from "../../app/providers";
import { Shell } from "../../components/Shell";
import { Badge, Button, Card, Drawer, formatStatus, statusTone } from "../../components/ui";
import { FeedbackButtons } from "../feedback/FeedbackButtons";
import { DecisionNote, RequestOverview, RequestTimeline } from "../requests/RequestDetails";
import { RequestDrawer } from "../requests/RequestDrawer";

const suggestions = [
  ["Vacation policy", "How far in advance should I request vacation?"],
  ["Payroll timing", "When is payroll processed?"],
  ["VPN access", "How do I request VPN access?"],
  ["New hire setup", "What should be ready for a new hire on day one?"],
];
const recentConversationLimit = 3;
const hello: ChatMessage = {
  id: "hello",
  role: "assistant",
  content: "Good morning. I can answer policy questions with evidence, or turn a clear action into a request you review before sending.",
};

export function EmployeePage() {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  const [messages, setMessages] = useState<ChatMessage[]>([hello]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [openingConversationId, setOpeningConversationId] = useState<string | null>(null);
  const [conversationError, setConversationError] = useState("");
  const [conversationToDelete, setConversationToDelete] = useState<ConversationSummary | null>(null);
  const [deletingConversationId, setDeletingConversationId] = useState<string | null>(null);
  const [conversationDeleteError, setConversationDeleteError] = useState("");
  const [conversationHistoryOpen, setConversationHistoryOpen] = useState(true);
  const [showAllConversations, setShowAllConversations] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [requestDraft, setRequestDraft] = useState<WorkflowRequest | null>(null);
  const [selectedRequest, setSelectedRequest] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const requests = useQuery({
    queryKey: ["requests"],
    queryFn: () => api<{ requests: WorkflowRequest[] }>("/api/v1/requests", token),
  });
  const conversations = useQuery({
    queryKey: ["conversations"],
    queryFn: () => api<{ conversations: ConversationSummary[] }>("/api/v1/conversations", token),
  });
  const activeConversation = conversations.data?.conversations.find(
    conversation => conversation.id === activeConversationId,
  );
  const conversationItems = conversations.data?.conversations ?? [];
  const visibleConversations = showAllConversations
    ? conversationItems
    : conversationItems.slice(0, recentConversationLimit);

  const startNewConversation = () => {
    setMessages([hello]);
    setDraft("");
    setActiveConversationId(null);
    setConversationError("");
  };
  const toggleConversationHistory = () => {
    if (conversationHistoryOpen) setShowAllConversations(false);
    setConversationHistoryOpen(current => !current);
  };
  const openNewRequest = () => {
    setRequestDraft(null);
    setDrawer(true);
  };
  const openRequest = (request: WorkflowRequest) => {
    if (request.status === "draft") {
      setRequestDraft(request);
      setDrawer(true);
      return;
    }
    setSelectedRequest(request.id);
  };
  const openSavedConversation = async (conversationId: string) => {
    if (openingConversationId) return;
    setConversationError("");
    setOpeningConversationId(conversationId);
    try {
      const detail = await api<ConversationDetail>(
        `/api/v1/conversations/${conversationId}`,
        token,
      );
      let previousQuestion = "";
      const restored = detail.messages.map<ChatMessage>(message => {
        if (message.role === "user") {
          previousQuestion = message.content;
          return { id: message.id, role: "user", content: message.content };
        }
        return {
          id: message.id,
          role: "assistant",
          content: message.content,
          sources: message.sources,
          workflow: message.workflow_request ?? null,
          question: previousQuestion,
        };
      });
      setMessages(restored.length ? restored : [hello]);
      setActiveConversationId(conversationId);
      setDrawer(false);
      setRequestDraft(null);
      bottom.current?.scrollIntoView({ behavior: "smooth" });
    } catch (error) {
      setConversationError(
        error instanceof Error ? error.message : "Unable to open this conversation.",
      );
    } finally {
      setOpeningConversationId(null);
    }
  };
  const deleteConversation = async () => {
    if (!conversationToDelete || deletingConversationId) return;
    const conversationId = conversationToDelete.id;
    setConversationDeleteError("");
    setDeletingConversationId(conversationId);
    try {
      await api(
        `/api/v1/conversations/${conversationId}`,
        token,
        { method: "DELETE" },
      );
      queryClient.setQueryData<{ conversations: ConversationSummary[] }>(
        ["conversations"],
        current => ({
          conversations: (current?.conversations ?? []).filter(
            conversation => conversation.id !== conversationId,
          ),
        }),
      );
      if (activeConversationId === conversationId) startNewConversation();
      if (conversationItems.length - 1 <= recentConversationLimit) {
        setShowAllConversations(false);
      }
      setConversationToDelete(null);
    } catch (error) {
      setConversationDeleteError(
        error instanceof Error ? error.message : "Unable to delete this conversation.",
      );
    } finally {
      setDeletingConversationId(null);
    }
  };
  const send = async (text = draft) => {
    const prompt = text.trim();
    if (!prompt || sending) return;
    const userMessage: ChatMessage = { id: crypto.randomUUID(), role: "user", content: prompt };
    const assistantId = crypto.randomUUID();
    setMessages(current => [...current, userMessage, { id: assistantId, role: "assistant", content: "", streaming: true, question: prompt }]);
    setDraft("");
    setSending(true);
    const history = [...messages.filter(message => message.id !== "hello"), userMessage].map(message => ({ role: message.role, content: message.content }));
    try {
      let conversationId = activeConversationId;
      if (!conversationId) {
        const created = await api<{ conversation: ConversationSummary }>(
          "/api/v1/conversations",
          token,
          { method: "POST" },
        );
        conversationId = created.conversation.id;
        setActiveConversationId(conversationId);
      }
      await streamChat(token, history, event => {
        if (event.type === "token") {
          setMessages(current => current.map(message => message.id === assistantId ? { ...message, content: message.content + String(event.content) } : message));
        }
        if (event.type === "complete") {
          const workflow = (event.workflow_request ?? null) as WorkflowRequest | null;
          setMessages(current => current.map(message => message.id === assistantId ? {
            ...message,
            streaming: false,
            sources: (event.sources ?? []) as Source[],
            workflow,
          } : message));
          if (workflow) {
            setRequestDraft(workflow);
            setDrawer(true);
          }
          void queryClient.invalidateQueries({ queryKey: ["conversations"] });
        }
        bottom.current?.scrollIntoView({ behavior: "smooth" });
      }, conversationId);
    } catch (error) {
      setMessages(current => current.map(message => message.id === assistantId ? {
        ...message,
        streaming: false,
        content: error instanceof Error ? error.message : "The assistant is unavailable.",
      } : message));
    } finally {
      setSending(false);
    }
  };

  const sidebar = <>
    <Button className="mb-5 w-full justify-start" onClick={startNewConversation}><Plus size={16} />New conversation</Button>
    <button
      className="focus-ring mb-2 mt-5 flex w-full items-center justify-between rounded-md px-3 text-left text-muted transition hover:text-cream"
      onClick={toggleConversationHistory}
      aria-expanded={conversationHistoryOpen}
      aria-controls="recent-conversations-list"
      aria-label={`${conversationHistoryOpen ? "Collapse" : "Expand"} recent conversations`}
    >
      <span className="text-[10px] font-bold uppercase tracking-[.16em]">
        Recent conversations
      </span>
      <span className="flex items-center gap-1.5 text-[10px] font-bold">
        {conversations.data && <span>{conversationItems.length}</span>}
        <ChevronDown
          className={`transition-transform ${conversationHistoryOpen ? "rotate-180" : ""}`}
          size={12}
        />
      </span>
    </button>
    {conversationHistoryOpen && <div id="recent-conversations-list" className="space-y-1">
      {visibleConversations.map(conversation => {
        const active = conversation.id === activeConversationId;
        return <div
          key={conversation.id}
          className={`group flex w-full items-stretch rounded-xl transition ${active ? "bg-lime-soft text-cream" : "text-muted hover:bg-raised hover:text-cream"}`}
        >
          <button
            className="focus-ring flex min-w-0 flex-1 items-start gap-2 rounded-xl px-3 py-2.5 text-left"
            onClick={() => void openSavedConversation(conversation.id)}
            disabled={Boolean(openingConversationId || deletingConversationId)}
            aria-label={`Open conversation ${conversation.title}`}
          >
            <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${active ? "bg-lime" : "bg-coral"}`} />
            <span className="min-w-0">
              <span className="block truncate text-sm font-semibold">{conversation.title}</span>
              <span className="mt-1 block text-[10px] text-muted">
                {openingConversationId === conversation.id ? "Opening..." : formatConversationTime(conversation.updated_at)}
              </span>
            </span>
          </button>
          <button
            className="focus-ring m-1.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg text-muted transition hover:bg-danger/10 hover:text-danger disabled:opacity-45"
            onClick={() => {
              setConversationDeleteError("");
              setConversationToDelete(conversation);
            }}
            disabled={Boolean(deletingConversationId)}
            aria-label={`Delete conversation ${conversation.title}`}
          >
            <Trash2 size={14} />
          </button>
        </div>;
      })}
      {conversations.isLoading && <p className="px-3 text-xs leading-5 text-muted">Loading conversations...</p>}
      {conversations.isError && <p className="px-3 text-xs leading-5 text-danger">Unable to load conversations.</p>}
      {!conversations.isLoading && !conversations.data?.conversations.length && <p className="px-3 text-xs leading-5 text-muted">Your saved HR conversations will appear here.</p>}
      {conversationError && <p className="px-3 text-xs leading-5 text-danger">{conversationError}</p>}
      {conversationItems.length > recentConversationLimit && <button
        className="focus-ring w-full rounded-lg px-3 py-2 text-left text-xs font-semibold text-lime transition hover:bg-raised"
        onClick={() => setShowAllConversations(current => !current)}
        aria-expanded={showAllConversations}
      >
        {showAllConversations ? "Show recent" : `Show all (${conversationItems.length})`}
      </button>}
    </div>}
    <NavLabel>My requests</NavLabel>
    <div className="space-y-2">
      {requests.data?.requests.slice(0, 4).map(request => <button
        key={request.id}
        className="focus-ring w-full rounded-xl border border-line bg-ink/45 p-3 text-left transition hover:border-lime/30 hover:bg-raised"
        onClick={() => openRequest(request)}
        aria-label={`Open ${request.type_label} request, status ${formatStatus(request.status)}`}
      >
        <div className="flex justify-between gap-2">
          <span className="truncate text-xs font-semibold">{request.type_label}</span>
          <Badge tone={statusTone(request.status)}>{formatStatus(request.status)}</Badge>
        </div>
        <p className="mt-2 text-[11px] text-muted">{request.start_date ?? "No date"}{request.duration_days ? ` · ${request.duration_days}d` : ""}</p>
        {request.status === "declined" && <p className="mt-2 text-[11px] font-semibold text-danger">Open to see the reason</p>}
      </button>)}
      {!requests.data?.requests.length && <p className="px-3 text-xs leading-5 text-muted">Requests sent for review will stay visible here.</p>}
    </div>
  </>;

  return <Shell sidebar={sidebar} eyebrow="Employee workspace">
    <div className="mx-auto flex min-h-[calc(100vh-64px)] max-w-5xl flex-col px-4 sm:px-8">
      <div className="flex-1 py-8 sm:py-12">
        {messages.length > 1 && <section className="mb-8 border-b border-line pb-5">
          <p className="text-[10px] font-bold uppercase tracking-[.16em] text-lime">Conversation</p>
          <h1 className="mt-2 text-2xl font-medium tracking-[-.025em]">
            {activeConversation?.title ?? "New conversation"}
          </h1>
        </section>}
        {messages.length === 1 && <section className="mb-10">
          <div className="mb-3 flex items-center gap-2 text-xs font-bold uppercase tracking-[.18em] text-lime"><Sparkles size={15} />Suggested actions</div>
          <h1 className="max-w-2xl text-4xl font-medium tracking-[-.035em] sm:text-5xl">What can we make easier today?</h1>
          <div className="mt-7 grid gap-3 sm:grid-cols-2">
            {suggestions.map(([label, prompt]) => <button key={label} onClick={() => send(prompt)} className="focus-ring group rounded-2xl border border-line bg-panel p-4 text-left transition hover:-translate-y-0.5 hover:border-lime/35 hover:bg-raised">
              <span className="text-xs font-semibold text-coral">{label}</span>
              <span className="mt-2 block text-sm leading-6 text-muted group-hover:text-cream">{prompt}</span>
            </button>)}
          </div>
        </section>}
        <div className="space-y-7">
          {messages.map(message => <Message key={message.id} message={message} onOpenRequest={request => { setRequestDraft(request); setDrawer(true); }} />)}
          <div ref={bottom} />
        </div>
      </div>
      <div className="sticky bottom-0 pb-5 pt-3">
        <div className="mb-2 flex gap-2">
          <Button tone="ghost" onClick={openNewRequest}><FileCheck2 size={15} />Create request</Button>
          <Button tone="ghost" onClick={() => setDraft("I need help from HR with ")}><MessageCircleQuestion size={15} />Ask HR</Button>
        </div>
        <div className="soft-shadow rounded-2xl border border-line bg-raised p-2">
          <textarea aria-label="Message PeopleFlow AI" value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); send(); } }} placeholder="Ask a question or describe what you need…" className="max-h-40 min-h-14 w-full resize-none bg-transparent px-3 py-2 text-sm outline-none placeholder:text-muted" />
          <div className="flex items-center justify-between px-2 pb-1"><span className="text-[11px] text-muted">Answers include source evidence when available.</span><Button aria-label="Send message" className="h-10 w-10 rounded-xl px-0" disabled={sending || !draft.trim()} onClick={() => send()}><ArrowUp size={17} /></Button></div>
        </div>
      </div>
    </div>
    <RequestDrawer open={drawer} onOpenChange={setDrawer} initial={requestDraft} />
    <Drawer
      open={Boolean(conversationToDelete)}
      onOpenChange={open => {
        if (!open && !deletingConversationId) {
          setConversationDeleteError("");
          setConversationToDelete(null);
        }
      }}
      title="Delete conversation?"
      description="This permanently removes the conversation and all of its messages."
      placement="center"
    >
      <div className="space-y-5">
        <Card className="bg-ink/60 p-4">
          <p className="text-[10px] font-bold uppercase tracking-[.16em] text-muted">
            Conversation
          </p>
          <p className="mt-2 text-sm font-semibold">
            {conversationToDelete?.title}
          </p>
        </Card>
        {conversationDeleteError && <p className="rounded-xl bg-danger/10 p-3 text-sm text-danger">
          {conversationDeleteError}
        </p>}
        <div className="flex justify-end gap-3">
          <Button
            tone="secondary"
            onClick={() => setConversationToDelete(null)}
            disabled={Boolean(deletingConversationId)}
          >
            Cancel
          </Button>
          <Button
            tone="danger"
            onClick={() => void deleteConversation()}
            disabled={Boolean(deletingConversationId)}
          >
            <Trash2 size={15} />
            {deletingConversationId ? "Deleting..." : "Delete conversation"}
          </Button>
        </div>
      </div>
    </Drawer>
    <EmployeeRequestDetails id={selectedRequest} onClose={() => setSelectedRequest(null)} />
  </Shell>;
}

function EmployeeRequestDetails({ id, onClose }: { id: string | null; onClose: () => void }) {
  const { token } = useAuth();
  const detail = useQuery({
    queryKey: ["request-detail", id],
    queryFn: () => api<RequestDetail>(`/api/v1/requests/${id}`, token),
    enabled: Boolean(id),
  });
  const request = detail.data?.request;
  return <Drawer
    open={Boolean(id)}
    onOpenChange={open => !open && onClose()}
    title={request?.type_label ?? "Request details"}
    description="Your request, manager decision, and complete status history."
  >
    {detail.isLoading && <p className="text-muted">Loading request…</p>}
    {detail.isError && <p className="rounded-xl bg-danger/10 p-3 text-sm text-danger">Unable to load this request.</p>}
    {request && detail.data && <div className="space-y-6">
      <div className="flex justify-between">
        <Badge tone={statusTone(request.status)}>{formatStatus(request.status)}</Badge>
        <span className="text-xs text-muted">#{request.id.slice(0, 8)}</span>
      </div>
      <DecisionNote detail={detail.data} />
      <RequestOverview request={request} />
      <RequestTimeline detail={detail.data} />
    </div>}
  </Drawer>;
}

function Message({ message, onOpenRequest }: { message: ChatMessage; onOpenRequest: (request: WorkflowRequest) => void }) {
  if (message.role === "user") return <div className="message-enter ml-auto max-w-[78%] rounded-2xl rounded-br-md bg-cream px-4 py-3 text-sm leading-6 text-ink">{message.content}</div>;
  return <article className="message-enter max-w-3xl">
    <div className="mb-2 flex items-center gap-2"><span className="grid h-7 w-7 place-items-center rounded-lg bg-lime text-ink"><Sparkles size={14} /></span><strong className="text-xs">PeopleFlow</strong>{message.sources?.length ? <Badge tone="success">Grounded</Badge> : null}</div>
    <div className={`whitespace-pre-wrap text-[15px] leading-7 text-cream ${message.streaming ? "token-caret" : ""}`}>{message.content || "Thinking with your company knowledge…"}</div>
    {message.workflow && <Card className="mt-4 border-coral/25 bg-coral/5"><div className="flex items-center justify-between gap-4"><div><span className="text-xs font-bold uppercase tracking-wider text-coral">Action detected</span><p className="mt-1 text-sm">A request draft is ready. Nothing has been sent for review.</p></div><Button onClick={() => onOpenRequest(message.workflow!)}>Review draft</Button></div></Card>}
    {message.sources?.length ? <details className="group mt-4"><summary className="focus-ring flex w-fit list-none items-center gap-2 rounded-lg py-2 text-xs font-semibold text-muted hover:text-cream"><Search size={14} />Sources · {message.sources.length}<ChevronDown className="transition group-open:rotate-180" size={14} /></summary><div className="mt-2 grid gap-3">{message.sources.map(source => <Card key={`${source.source}-${source.section}`} className="p-4"><div className="flex items-center justify-between gap-3"><strong className="text-xs">{source.title}</strong><span className="text-[10px] text-muted">v{source.version}</span></div><p className="mt-1 text-[11px] text-coral">{source.section}</p><mark className="mt-3 block bg-lime/10 px-3 py-2 text-xs leading-6 text-cream">{source.excerpt}</mark></Card>)}</div></details> : null}
    {message.id !== "hello" && !message.streaming && <div className="mt-3"><FeedbackButtons question={message.question ?? ""} answer={message.content} /></div>}
  </article>;
}

function NavLabel({ children }: { children: React.ReactNode }) {
  return <div className="mb-2 mt-5 px-3 text-[10px] font-bold uppercase tracking-[.16em] text-muted">{children}</div>;
}

function formatConversationTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const dayDifference = Math.round(
    (startOfToday.getTime() - startOfDate.getTime()) / 86_400_000,
  );
  const time = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (dayDifference === 0) return `Today, ${time}`;
  if (dayDifference === 1) return "Yesterday";
  return date.toLocaleDateString([], { day: "2-digit", month: "short" });
}
