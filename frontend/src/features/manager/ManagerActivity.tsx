import { useEffect, useState } from "react";
import { Button, Drawer, LoadingSkeleton } from "../../components/ui";
import { eventLabel } from "../requests/RequestDetails";
import { requestDate } from "../requests/requestPresentation";
import { useManagerActivity } from "./useManagerWorkspace";

export function ManagerActivity({ open, onOpenChange, onOpenRequest }: { open: boolean; onOpenChange: (value: boolean) => void; onOpenRequest: (id: string) => void }) {
  const [offset, setOffset] = useState(0);
  const query = useManagerActivity(open, offset);
  useEffect(() => { if (open) setOffset(0); }, [open]);
  useEffect(() => {
    if (query.data && offset > 0 && offset >= query.data.total) setOffset(Math.max(0, (Math.ceil(query.data.total / 20) - 1) * 20));
  }, [query.data, offset]);
  return <Drawer open={open} onOpenChange={onOpenChange} placement="center" size="large" title="Activity log" description="Recorded actions on requests currently assigned to you. Newest first; the complete history is available in each request.">
    <div className="space-y-4">
      {query.isLoading && <LoadingSkeleton label="Loading activity…" rows={3}/>}
      {query.isError && <div role="alert" className="manager-inline-error"><p>Activity could not be loaded. Check your connection and try again.</p><Button tone="secondary" onClick={() => void query.refetch()}>Retry activity</Button></div>}
      {query.isSuccess && query.data?.events.length === 0 && <p>No activity is available for your current queue. Submitted requests and their recorded actions will appear here.</p>}
      {query.isSuccess && <ol className="manager-activity-list">{query.data?.events.map(event => <li key={event.id}>
        <div><strong>{eventLabel(event)}</strong><time dateTime={event.created_at}>{requestDate(event.created_at)}</time></div>
        <p className="text-xs text-muted">By {event.actor}</p>
        <Button tone="ghost" className="manager-activity-request" onClick={() => { onOpenChange(false); onOpenRequest(event.request_id); }}>REQ-{String(event.request_number).padStart(6, "0")} · {event.request_title}</Button>
        {typeof event.details.comment === "string" && <p className="manager-activity-note">{event.details.comment}</p>}
      </li>)}</ol>}
      {query.isSuccess && query.data && <nav aria-label="Activity pages" className="manager-activity-pages"><p>{query.data.events.length ? offset + 1 : 0}–{Math.min(offset + query.data.events.length, query.data.total)} of {query.data.total}</p><div><Button tone="secondary" disabled={!offset || query.isFetching} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous activity</Button><Button tone="secondary" disabled={offset + 20 >= query.data.total || query.isFetching} onClick={() => setOffset(offset + 20)}>Next activity</Button></div></nav>}
    </div>
  </Drawer>;
}
