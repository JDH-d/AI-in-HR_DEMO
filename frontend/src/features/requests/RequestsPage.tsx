import { useEffect, useRef, useState } from "react";
import { ArrowDown, ArrowLeft, ArrowUp, Bell, Filter, History, Plus, Search, X } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router";
import { useAuth } from "../../app/providers";
import { Shell } from "../../components/Shell";
import { Badge, Button, Card, LoadingSkeleton, PageHeader, fieldClass, statusTone } from "../../components/ui";
import { RequestDetailDrawer, requestNumber } from "./RequestDetailDrawer";
import { RequestDrawer } from "./RequestDrawer";
import { useRequestRefresh, useRequestOptions, useRequests } from "./useRequests";
import { requestDate, requestLabel } from "./requestPresentation";
import { PersonalNotifications } from "../integrations/PersonalNotifications";
import { ManagerOverview, type QueueFocus } from "../manager/ManagerOverview";
import { ManagerActivity } from "../manager/ManagerActivity";
import { ManagerBulkReview } from "../manager/ManagerBulkReview";
import { useBulkReview } from "../manager/useManagerWorkspace";
import "./requests.css";

const sortLabels: Record<string, string> = { updated_at: "Last updated", created_at: "Date created", number: "Request number", title: "Title", priority: "Priority" };

export function RequestsPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const manager = user?.role === "manager";
  const refresh = useRequestRefresh();
  const [params, setParams] = useSearchParams();
  const selected = params.get("request");
  const creating = !manager && !selected && params.get("new") === "1";
  const setCreating = (open: boolean) => setParams(current => {
    const updated = new URLSearchParams(current);
    if (open) { updated.set("new", "1"); updated.delete("request"); }
    else updated.delete("new");
    return updated;
  }, { replace: true });
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const previousSelected = useRef<string | null>(selected);
  const listPosition = useRef(0);
  const listHeading = useRef<HTMLHeadingElement>(null);
  const options = useRequestOptions();
  const filters = {
    q: params.get("q") ?? "",
    status: params.get("status") === "all" ? "" : (params.get("status") ?? (manager && !params.get("attention") ? "submitted" : "")),
    category: params.get("category") ?? "",
    priority: params.get("priority") ?? "",
    sort: Object.hasOwn(sortLabels, params.get("sort") ?? "") ? params.get("sort")! : manager ? "created_at" : "updated_at",
    order: params.get("order") === "asc" || (manager && !params.has("order") && !params.has("sort")) ? "asc" : "desc",
    offset: /^\d+$/.test(params.get("offset") ?? "") ? params.get("offset")! : "0",
    limit: "20",
    ...(manager ? { assignee: params.get("assignee") ?? "", attention: ["overdue", "needs_attention"].includes(params.get("attention") ?? "") ? params.get("attention")! : "" } : {}),
  };
  const query = useRequests(manager ? "manager-requests" : "requests", filters);
  const rows = query.data?.requests ?? [];
  const bulk = useBulkReview(rows, JSON.stringify(filters), manager && !selected);
  const reload = () => { void refresh(); void options.refetch(); };
  const offset = Number(filters.offset);
  const hasFilters = Boolean(filters.q || filters.status || filters.category || filters.priority || filters.assignee || filters.attention);
  const change = (key: string, value: string) => setParams(current => {
    const updated = new URLSearchParams(current);
    if (key === "status" && !value) updated.set(key, "all");
    else if (value) updated.set(key, value); else updated.delete(key);
    if (key !== "offset") updated.delete("offset");
    return updated;
  }, { replace: true });
  const clearFilters = () => setParams(current => {
    const updated = new URLSearchParams(current);
    ["q", "category", "priority", "assignee", "attention", "offset", "sort", "order"].forEach(key => updated.delete(key));
    updated.set("status", "all");
    return updated;
  }, { replace: true });
  const focusQueue = (focus: QueueFocus) => { void refresh(); setParams(current => {
    const updated = new URLSearchParams(current);
    ["q", "category", "priority", "assignee", "attention", "offset", "sort", "order"].forEach(key => updated.delete(key));
    updated.set("status", focus.status || "all");
    if (focus.attention) updated.set("attention", focus.attention);
    return updated;
  }, { replace: true }); };
  const changeView = (status: string) => setParams(current => {
    const updated = new URLSearchParams(current);
    updated.set("status", status || "all"); updated.delete("attention"); updated.delete("offset");
    return updated;
  }, { replace: true });
  const sortBy = (key: string) => setParams(current => {
    const updated = new URLSearchParams(current);
    updated.set("sort", key);
    updated.set("order", filters.sort === key && filters.order === "desc" ? "asc" : "desc");
    updated.delete("offset");
    return updated;
  }, { replace: true });
  const setSelected = (id: string | null) => {
    if (id && !selected) listPosition.current = window.scrollY;
    setParams(current => {
      const updated = new URLSearchParams(current);
      if (id) updated.set("request", id); else updated.delete("request");
      updated.delete("new");
      return updated;
    });
  };
  useEffect(() => {
    if (!selected && previousSelected.current) {
      (document.getElementById(`request-${previousSelected.current}`) ?? listHeading.current)?.focus({ preventScroll: true });
      window.scrollTo?.({ top: listPosition.current });
    }
    previousSelected.current = selected;
  }, [selected, query.data]);
  useEffect(() => {
    // Processing the last item can shrink a filtered queue. Use its nearest page.
    if (selected || !query.isSuccess || !query.data || offset === 0 || offset < query.data.total) return;
    const lastOffset = Math.max(0, Math.ceil(query.data.total / 20) - 1) * 20;
    setParams(current => {
      const updated = new URLSearchParams(current);
      if (lastOffset) updated.set("offset", String(lastOffset)); else updated.delete("offset");
      return updated;
    }, { replace: true });
  }, [selected, query.isSuccess, query.data, offset, setParams]);
  const quickViews = manager
    ? [["submitted", "New"], ["in_review", "In review"], ["needs_information", "Waiting for employee"], ["approved", "To complete"], ["", "All requests"]]
    : [["", "All requests"], ["needs_information", "Needs your reply"], ["draft", "Drafts"]];
  const extraFilters = Number(Boolean(filters.category)) + Number(Boolean(filters.priority)) + Number(Boolean(filters.assignee)) + Number(Boolean(filters.attention)) + Number(!quickViews.some(([status]) => status === filters.status));
  const search = <label className="relative block w-full min-w-0"><span className="sr-only">Search</span><Search aria-hidden="true" size={17} className="pointer-events-none absolute left-3 top-3 text-muted"/><input className={`${fieldClass} pl-9`} placeholder={manager ? "Search your review queue" : "Search your requests"} maxLength={200} value={filters.q} onChange={event => change("q", event.target.value)}/></label>;
  const sortIndicator = (key: string) => filters.sort === key ? (filters.order === "asc" ? <ArrowUp size={13} aria-hidden="true"/> : <ArrowDown size={13} aria-hidden="true"/>) : null;

  return <Shell eyebrow={manager ? "Manager workspace" : "Employee workspace"} headerContent={!selected ? search : undefined}>
    <div className={`workspace-page requests-workspace ${manager && selected ? "requests-workspace-split" : ""}`}>
      <div className={selected ? "sr-only" : "request-page-heading"}><PageHeader headingRef={listHeading} title={manager ? "Review queue" : "My requests"} description={manager ? "Review your assigned requests. New requests are shown oldest first." : "Track progress and respond to your manager."} actions={!selected ? manager ? <><Button tone="secondary" onClick={() => setActivityOpen(true)}><History size={16} aria-hidden="true" className="hidden sm:block"/>Activity log</Button><Button tone="secondary" onClick={() => setNotificationsOpen(true)}><Bell size={16} aria-hidden="true" className="hidden sm:block"/>Notifications</Button></> : <><Button tone="ghost" className="request-back-to-chats" aria-label="Back to chats" onClick={() => navigate("/employee")}><ArrowLeft size={16} aria-hidden="true"/><span>Back to chats</span></Button><Button onClick={() => setCreating(true)}><Plus size={16} aria-hidden="true"/>New request</Button></> : undefined}/></div>
      {manager && !selected && <ManagerOverview onFocus={focusQueue}/>}
      <div className={manager && selected ? "request-split" : ""}>
        <div className={`request-list space-y-3 ${selected ? manager ? "request-list-with-selection" : "hidden" : ""}`}>
          {selected && manager && search}
          <div className="request-list-controls">
          <nav aria-label="Request views" className="request-view-tabs">{quickViews.map(([value, label]) => <button key={value} aria-pressed={filters.status === value && !filters.attention} onClick={() => changeView(value)} className={`focus-ring flex min-h-11 items-center gap-2 border-b-2 px-3 py-2 text-sm ${filters.status === value && !filters.attention ? "border-lime font-semibold text-lime" : "border-transparent text-muted hover:text-cream"}`}>
            {label}{value && query.isSuccess && <span className="rounded bg-raised px-1.5 text-xs tabular-nums">{query.data.counts[value] ?? 0}</span>}
          </button>)}</nav>
          <label className="request-view-mobile"><span className="sr-only">Request view</span><select className={fieldClass} value={filters.status} onChange={event => changeView(event.target.value)}>{quickViews.map(([value, label]) => <option key={value} value={value}>{label}{value && query.isSuccess ? ` (${query.data.counts[value] ?? 0})` : ""}</option>)}{!quickViews.some(([value]) => value === filters.status) && <option value={filters.status}>{requestLabel(filters.status)}</option>}</select></label>
          <Button tone="secondary" aria-expanded={filtersOpen} aria-controls="request-extra-filters" onClick={() => setFiltersOpen(value => !value)}><Filter size={16} aria-hidden="true"/>Filters{extraFilters > 0 ? ` (${extraFilters})` : ""}</Button>
          </div>
          <section aria-label="Request filters" className="space-y-3">
            {filtersOpen && <div id="request-extra-filters" className="grid gap-3 rounded-lg border border-line bg-panel p-3 sm:grid-cols-3">
              <label className="text-sm font-medium">Status<select className={`${fieldClass} mt-1`} value={filters.status} onChange={event => change("status", event.target.value)}><option value="">All statuses</option>{options.data?.statuses.filter(status => !manager || status !== "draft").map(status => <option key={status} value={status}>{requestLabel(status)}</option>)}</select></label>
              <label className="text-sm font-medium">Category<select className={`${fieldClass} mt-1`} value={filters.category} onChange={event => change("category", event.target.value)}><option value="">All categories</option>{Object.entries(options.data?.categories ?? {}).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
              <label className="text-sm font-medium">Priority<select className={`${fieldClass} mt-1`} value={filters.priority} onChange={event => change("priority", event.target.value)}><option value="">All priorities</option>{options.data?.priorities.map(value => <option key={value} value={value}>{requestLabel(value)}</option>)}</select></label>
              {manager && <><label className="text-sm font-medium">Assigned manager<select className={`${fieldClass} mt-1`} value={filters.assignee} onChange={event => change("assignee", event.target.value)}><option value="">All accessible assignments</option><option value={user.id}>{user.display_name || user.id} (you)</option>{filters.assignee && filters.assignee !== user.id && <option value={filters.assignee}>Unavailable manager</option>}</select></label><label className="text-sm font-medium">Attention<select className={`${fieldClass} mt-1`} value={filters.attention} onChange={event => change("attention", event.target.value)}><option value="">Any attention level</option><option value="overdue">Overdue reviews</option><option value="needs_attention">Needs attention</option></select></label><p className="text-xs leading-5 text-muted sm:col-span-3">Your role gives access only to requests assigned to you. Filtering does not expand access to another manager's queue.</p></>}
              <label className="text-sm font-medium">Sort by<select className={`${fieldClass} mt-1`} value={filters.sort} onChange={event => change("sort", event.target.value)}>{Object.entries(sortLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
              <label className="text-sm font-medium">Order<select className={`${fieldClass} mt-1`} value={filters.order} onChange={event => change("order", event.target.value)}><option value="desc">Descending</option><option value="asc">Ascending</option></select></label>
              <div className="flex justify-between gap-2 sm:col-span-3"><Button tone="ghost" disabled={!hasFilters} onClick={clearFilters}>Clear filters</Button><Button tone="secondary" onClick={() => setFiltersOpen(false)}>Done</Button></div>
            </div>}
            {extraFilters > 0 && !filtersOpen && <div className="flex flex-wrap items-center gap-2 text-xs text-muted"><span>{[filters.category && (options.data?.categories[filters.category] ?? filters.category), filters.priority && `${requestLabel(filters.priority)} priority`, filters.assignee && (filters.assignee === user?.id ? `Assigned to ${user.display_name || "you"}` : "Unavailable assignment"), filters.attention && requestLabel(filters.attention), !quickViews.some(([status]) => status === filters.status) && requestLabel(filters.status)].filter(Boolean).join(" · ")}</span><button className="focus-ring inline-flex min-h-11 items-center gap-1 rounded px-2 font-medium" onClick={clearFilters}><X size={14} aria-hidden="true"/>Clear filters</button></div>}
          </section>
          {query.isLoading && <LoadingSkeleton label="Loading requests…" rows={3}/>}
          {(query.isError || options.isError) && <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-danger/30 bg-danger/10 p-4 text-sm"><p>{query.isError ? "Requests could not be refreshed. Check your connection and try again." : "Filters could not be loaded. Try again to see all filter options."}{query.data && " Previously loaded results are shown below."}</p><Button tone="secondary" onClick={() => { void query.refetch(); void options.refetch(); }}>Retry</Button></div>}
          {query.isSuccess && !rows.length && <Card><h2 className="font-semibold">{hasFilters ? "No matching requests" : "No requests yet"}</h2><p className="mt-2 text-sm text-muted">{hasFilters ? "Try another search or clear the filters to see more requests." : manager ? "Requests assigned to you will appear here." : "Create a request when you need help. You can save a private draft first."}</p>{hasFilters ? <Button tone="secondary" className="mt-4" onClick={clearFilters}>Show all requests</Button> : !manager && <Button className="mt-4" onClick={() => setCreating(true)}>Create your first request</Button>}</Card>}
          {manager && !selected && query.data && <ManagerBulkReview state={bulk} disabled={query.isError || query.isFetching} onReload={reload} onOpenRequest={setSelected} onReviewQueue={() => changeView("in_review")}/>}
          {rows.length > 0 && <section aria-label="Request results" aria-busy={query.isFetching} className="request-results overflow-hidden rounded-lg border border-line bg-panel">
            <table className="request-table w-full border-collapse text-left text-sm">
              <caption className="sr-only">{manager ? "Requests assigned to you" : "Your requests"}</caption>
              <thead className="bg-raised text-xs text-muted"><tr>
                <th scope="col" aria-sort={filters.sort === "title" ? filters.order === "asc" ? "ascending" : "descending" : "none"}><button className="focus-ring flex min-h-11 items-center gap-2 rounded font-semibold" onClick={() => sortBy("title")}>Request{sortIndicator("title")}</button></th>
                <th scope="col">{manager ? "Employee" : "Assigned manager"}</th>
                <th scope="col" aria-sort={filters.sort === "priority" ? filters.order === "asc" ? "ascending" : "descending" : "none"}><button className="focus-ring flex min-h-11 items-center gap-2 rounded font-semibold" onClick={() => sortBy("priority")}>Priority{sortIndicator("priority")}</button></th>
                <th scope="col">Status</th>
                <th scope="col" aria-sort={filters.sort === "updated_at" ? filters.order === "asc" ? "ascending" : "descending" : "none"}><button className="focus-ring flex min-h-11 items-center gap-2 rounded font-semibold" onClick={() => sortBy("updated_at")}>Updated{sortIndicator("updated_at")}</button></th>
              </tr></thead>
              <tbody>{rows.map(request => <tr key={request.id} className={selected === request.id ? "bg-lime-soft" : "hover:bg-raised/60"}>
                <td className="request-title"><div className="flex min-w-0 items-start gap-3">{manager && bulk.selecting && <label className="manager-row-selection"><input type="checkbox" className="manager-row-checkbox focus-ring" aria-label={`Select ${requestNumber(request.number)}`} title={request.status !== "submitted" ? "Only new requests can be started together" : undefined} disabled={bulk.mutation.isPending || query.isFetching || query.isError || !bulk.eligible.some(item => item.id === request.id)} checked={bulk.selected.some(item => item.id === request.id)} onChange={() => bulk.toggle(request)}/></label>}<button id={`request-${request.id}`} className="focus-ring block min-h-11 min-w-0 w-full rounded text-left" onClick={() => setSelected(request.id)} aria-current={selected === request.id ? "true" : undefined} aria-label={`Open ${requestNumber(request.number)}: ${request.title}`}><span className="block text-xs text-muted">{requestNumber(request.number)} · {request.type_label}</span><span className="mt-0.5 block break-words font-semibold">{request.title || request.type_label}</span>{manager && request.manager_attention && (request.manager_attention.due_at || request.manager_attention.reasons.length > 0) && <span className="manager-attention-label">{request.manager_attention.overdue ? "Overdue" : request.manager_attention.reasons.includes("employee_reply") ? "Employee replied" : request.manager_attention.reasons.includes("reconsideration") ? "Reconsideration" : request.manager_attention.reasons.includes("high_priority") ? "Needs attention" : "Review target"}{request.manager_attention.due_at && ` · ${requestDate(request.manager_attention.due_at)}`}</span>}</button></div></td>
                <td className="request-person text-muted"><span className="request-mobile-label">{manager ? "Employee: " : "Assigned to: "}</span>{manager ? request.applicant : options.data?.managers?.find(item => item.id === request.approver)?.display_name ?? request.approver}</td>
                <td className={`request-priority ${["high", "urgent"].includes(request.priority) ? "font-semibold text-coral" : "text-muted"}`}>{requestLabel(request.priority)}<span className="request-mobile-label"> priority</span></td>
                <td className="request-status"><Badge tone={statusTone(request.status)}>{requestLabel(request.status)}</Badge></td>
                <td className="request-updated text-xs text-muted"><time dateTime={request.updated_at}>{requestDate(request.updated_at)}</time></td>
              </tr>)}</tbody>
            </table>
          </section>}
          {query.data && <nav aria-label="Request pages" className="flex flex-wrap items-center justify-between gap-2"><p aria-live="polite" className="text-xs text-muted">{rows.length ? offset + 1 : 0}–{rows.length ? Math.min(offset + rows.length, query.data.total) : 0} of {query.data.total}</p><div className="flex gap-1"><Button tone="ghost" disabled={offset === 0 || query.isFetching} onClick={() => change("offset", String(Math.max(0, offset - 20)))}>Previous</Button><Button tone="ghost" disabled={offset + rows.length >= query.data.total || query.isFetching} onClick={() => change("offset", String(offset + 20))}>Next</Button></div></nav>}
        </div>
        {selected && <div className="min-w-0"><RequestDetailDrawer key={selected} id={selected} onClose={() => setSelected(null)} presentation="page"/></div>}
      </div>
    </div>
    <RequestDrawer open={creating} onOpenChange={setCreating} onOpenRequest={setSelected}/>
    {manager && <><ManagerActivity open={activityOpen} onOpenChange={setActivityOpen} onOpenRequest={setSelected}/><PersonalNotifications open={notificationsOpen} onOpenChange={setNotificationsOpen} hideTrigger/></>}
  </Shell>;
}
