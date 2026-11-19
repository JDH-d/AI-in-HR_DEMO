import { Bell, CheckCircle2, ChevronRight, FilePlus2, HelpCircle, MessageSquare, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import type { WorkflowRequest } from "../../api/types";
import { Shell } from "../../components/Shell";
import { Badge, Button, Card, LoadingSkeleton, PageHeader, statusTone } from "../../components/ui";
import { PersonalNotifications } from "../integrations/PersonalNotifications";
import { RequestDrawer } from "../requests/RequestDrawer";
import { requestNumber } from "../requests/RequestDetailDrawer";
import { requestDate, requestLabel } from "../requests/requestPresentation";
import { EmployeeHelp } from "./EmployeeHelp";
import { useEmployeeHome } from "./useEmployeeHome";
import "./employee-home.css";

const requestUrl = (id: string) => `/requests?request=${encodeURIComponent(id)}`;

function RequestLink({ request, action }: { request: WorkflowRequest; action?: string }) {
  return <Link to={requestUrl(request.id)} className="employee-request-link focus-ring" aria-label={`${action || "Open"} ${requestNumber(request.number)}: ${request.title}`}>
    <div className="min-w-0"><span className="text-xs text-muted">{requestNumber(request.number)} · {request.type_label}</span>
      <strong className="employee-request-title">{request.title || "Untitled draft"}</strong>
      <span className="mt-1 block text-xs text-muted">Updated <time dateTime={request.updated_at}>{requestDate(request.updated_at)}</time></span>
    </div>
    <div className="employee-request-trailing"><Badge tone={statusTone(request.status)}>{requestLabel(request.status)}</Badge>
      {action && <span className="inline-flex items-center gap-1 text-sm font-semibold text-lime">{action}<ChevronRight size={16} aria-hidden="true"/></span>}
    </div>
  </Link>;
}

function Retry({ message, retry }: { message: string; retry: () => void }) {
  return <div role="alert" className="employee-load-error"><p>{message} Check your connection and try again.</p><Button tone="secondary" onClick={retry}>Retry</Button></div>;
}

export function EmployeeHome() {
  const { recent, replies, drafts, chats } = useEmployeeHome();
  const navigate = useNavigate();
  const [creating, setCreating] = useState(false);
  const [notifications, setNotifications] = useState(false);
  const [help, setHelp] = useState(false);
  const counts = recent.isError ? undefined : recent.data?.counts;
  const refresh = () => { void recent.refetch(); void replies.refetch(); void drafts.refetch(); void chats.refetch(); };
  const refreshing = recent.isFetching || replies.isFetching || drafts.isFetching || chats.isFetching;
  const metrics = [
    { title: "Needs your reply", value: counts?.needs_information ?? 0, to: "/requests?status=needs_information", hint: "Your manager is waiting for information" },
    { title: "Drafts", value: counts?.draft ?? 0, to: "/requests?status=draft", hint: "Private until you submit" },
    { title: "In review", value: counts?.in_review ?? 0, to: "/requests?status=in_review", hint: "Your manager is reviewing these" },
  ];
  return <Shell eyebrow="Employee workspace" title="Home">
    <div className="workspace-page employee-home">
      <PageHeader title="Home" description="Your next steps, requests and saved conversations." actions={<>
        <Link className="employee-secondary-link focus-ring" to="/requests">My requests</Link>
        <Button onClick={() => setCreating(true)}><FilePlus2 size={18} aria-hidden="true"/>Create request</Button>
      </>}/>
      <div className="employee-update-bar"><p className="text-xs text-muted">Request updates refresh automatically while this page is open.{recent.dataUpdatedAt > 0 && <> Last successful check {new Date(recent.dataUpdatedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}.</>}</p>
        <Button tone="ghost" disabled={refreshing} onClick={refresh}><RefreshCw size={16} aria-hidden="true"/>{refreshing ? "Refreshing…" : "Refresh updates"}</Button>
      </div>
      <nav className="employee-summary" aria-label="Your request summary">{metrics.map(metric => <Link key={metric.title} to={metric.to} className="employee-summary-item focus-ring" aria-label={`${metric.title}: ${counts ? metric.value : "Count unavailable"}. ${metric.hint}`}>
        <span>{metric.title}</span><strong>{counts ? metric.value : "—"}</strong><small>{metric.hint}</small>
      </Link>)}</nav>
      <div className="employee-home-grid">
        <div className="employee-home-column">
          <Card><h2 className="text-lg font-semibold">Needs your attention</h2><p className="mt-1 text-sm text-muted">Reply to your manager or finish a saved draft.</p>
            <section className="employee-task-section" aria-labelledby="employee-replies-title"><h3 id="employee-replies-title" className="font-semibold">Replies to your manager</h3>
              {replies.isLoading && <LoadingSkeleton rows={2} label="Checking for information requests…"/>}
              {replies.isError ? <Retry message="Your reply tasks could not be refreshed." retry={() => void replies.refetch()}/> : replies.data && (replies.data.requests.length ? <>
                <div className="employee-home-list">{replies.data.requests.map(request => <RequestLink key={request.id} request={request} action="Reply"/>)}</div>
                {replies.data.total > 3 && <Link to="/requests?status=needs_information" className="employee-text-link focus-ring">View all {replies.data.total} requests needing a reply</Link>}
              </> : <p className="employee-empty inline-flex items-start gap-2"><CheckCircle2 size={17} className="mt-0.5 shrink-0 text-lime" aria-hidden="true"/>No replies needed. New requests for information will appear here.</p>)}
            </section>
            <section className="employee-task-section" aria-labelledby="employee-drafts-title"><h3 id="employee-drafts-title" className="font-semibold">Finish a draft</h3>
              {drafts.isLoading && <LoadingSkeleton rows={2} label="Loading your drafts…"/>}
              {drafts.isError ? <Retry message="Your drafts could not be refreshed." retry={() => void drafts.refetch()}/> : drafts.data && (drafts.data.requests.length ? <>
                <div className="employee-home-list">{drafts.data.requests.map(request => <RequestLink key={request.id} request={request} action="Continue draft"/>)}</div>
                {drafts.data.total > 3 && <Link to="/requests?status=draft" className="employee-text-link focus-ring">View all {drafts.data.total} drafts</Link>}
              </> : <p className="employee-empty">No saved drafts. Start a request and save it at any step if you need more time.</p>)}
            </section>
          </Card>
          <Card><div className="employee-section-heading"><h2 className="text-lg font-semibold">Recent requests</h2><Link to="/requests" className="employee-text-link focus-ring">View all requests</Link></div>
            {recent.isLoading && <LoadingSkeleton label="Loading your requests…"/>}
            {recent.isError ? <Retry message="Your requests could not be refreshed." retry={() => void recent.refetch()}/> : recent.data && (recent.data.requests.length ? <div className="employee-home-list">{recent.data.requests.map(request => <RequestLink key={request.id} request={request}/>)}</div> : <div className="employee-empty"><p>No requests yet. Ask for time off or a document in a few short steps.</p><Button className="mt-3" tone="secondary" onClick={() => setCreating(true)}>Start your first request</Button></div>)}
          </Card>
        </div>
        <div className="employee-home-column">
          <Card><div className="employee-section-heading"><h2 className="inline-flex items-center gap-2 text-lg font-semibold"><MessageSquare size={19} aria-hidden="true"/>Saved chats</h2><Link to="/employee" className="employee-text-link focus-ring">My chats</Link></div><p className="mt-1 text-sm text-muted">Continue a conversation or search your chat history.</p>
            {chats.isLoading && <LoadingSkeleton rows={2} label="Loading saved chats…"/>}
            {chats.isError ? <Retry message="Your chats could not be loaded." retry={() => void chats.refetch()}/> : chats.data && (chats.data.conversations.length ? <ul className="employee-home-list">{chats.data.conversations.map(chat => <li key={chat.id}><Link className="employee-chat-link focus-ring" to={`/employee?conversation=${encodeURIComponent(chat.id)}`}><strong>{chat.title}</strong><time dateTime={chat.updated_at}>{requestDate(chat.updated_at)}</time></Link></li>)}</ul> : <p className="employee-empty">No chats yet. Ask a question in English about company policies. Your conversation will be saved.</p>)}
            <Link className="employee-secondary-link focus-ring mt-3" to="/employee">Ask a question</Link>
          </Card>
          <Card><h2 className="inline-flex items-center gap-2 text-lg font-semibold"><Bell size={19} aria-hidden="true"/>Personal notifications</h2><p className="mt-2 text-sm leading-6 text-muted">Connect Slack or Discord for private requests for additional information. Check request status here whenever you need it.</p><Button className="mt-3" tone="secondary" onClick={() => setNotifications(true)}>Manage notifications</Button></Card>
          <Card><h2 className="inline-flex items-center gap-2 text-lg font-semibold"><HelpCircle size={19} aria-hidden="true"/>Need help?</h2><p className="mt-2 text-sm leading-6 text-muted">Find out how to submit a request, reply to your manager or ask for reconsideration.</p><Button className="mt-3" tone="ghost" onClick={() => setHelp(true)}>Open employee help</Button></Card>
        </div>
      </div>
    </div>
    <RequestDrawer open={creating} onOpenChange={setCreating} onOpenRequest={id => navigate(requestUrl(id))}/>
    <PersonalNotifications open={notifications} onOpenChange={setNotifications} hideTrigger/>
    <EmployeeHelp open={help} onOpenChange={setHelp}/>
  </Shell>;
}
