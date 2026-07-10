import { useQuery } from "@tanstack/react-query";
import { ArrowUp, ChevronDown, FileCheck2, MessageCircleQuestion, Plus, Search, Sparkles } from "lucide-react";
import { useRef, useState } from "react";
import { api, streamChat } from "../../api/client";
import type { ChatMessage, RequestDetail, Source, WorkflowRequest } from "../../api/types";
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
const hello: ChatMessage = {
  id: "hello",
  role: "assistant",
  content: "Good morning. I can answer policy questions with evidence, or turn a clear action into a request you review before sending.",
};

export function EmployeePage() {
  const { token } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([hello]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [requestDraft, setRequestDraft] = useState<WorkflowRequest | null>(null);
  const [selectedRequest, setSelectedRequest] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const requests = useQuery({
    queryKey: ["requests"],
    queryFn: () => api<{ requests: WorkflowRequest[] }>("/api/v1/requests", token),
  });

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
        }
        bottom.current?.scrollIntoView({ behavior: "smooth" });
      });
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
    <Button className="mb-5 w-full justify-start" onClick={openNewRequest}><Plus size={16} />New request</Button>
    <NavLabel>Recent conversations</NavLabel>
    <div className="space-y-1">
      {["Vacation planning", "Payroll schedule", "VPN access process"].map((label, index) => <button key={label} className="focus-ring w-full truncate rounded-xl px-3 py-2.5 text-left text-sm text-muted hover:bg-raised hover:text-cream">
        <MessageCircleQuestion className="mr-2 inline" size={14} />{label}
        {index === 0 && <span className="ml-2 inline-block h-1.5 w-1.5 rounded-full bg-lime" />}
      </button>)}
    </div>
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
