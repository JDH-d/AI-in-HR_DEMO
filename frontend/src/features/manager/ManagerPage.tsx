import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock3, Filter, Inbox, Search, ShieldCheck, XCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "../../api/client";
import type { RequestDetail, WorkflowRequest } from "../../api/types";
import { useAuth } from "../../app/providers";
import { Shell } from "../../components/Shell";
import {
  Badge,
  Button,
  Card,
  Drawer,
  fieldClass,
  formatStatus,
  statusTone,
} from "../../components/ui";
import { DecisionNote, RequestOverview, RequestTimeline } from "../requests/RequestDetails";
import { requestPeriodLabel } from "../requests/requestPresentation";

export function ManagerPage() {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("all");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const requests = useQuery({
    queryKey: ["manager-requests"],
    queryFn: () => api<{ requests: WorkflowRequest[] }>("/api/v1/requests", token),
  });
  const data = requests.data?.requests ?? [];
  const counts = {
    pending: data.filter((request) => ["in_review", "reported"].includes(request.status)).length,
    completed: data.filter((request) => ["approved", "acknowledged"].includes(request.status))
      .length,
    declined: data.filter((request) => request.status === "declined").length,
  };
  const rows = useMemo(
    () =>
      data.filter(
        (request) =>
          (status === "all" || request.status === status) &&
          `${request.type_label} ${request.applicant} ${request.comment}`
            .toLowerCase()
            .includes(search.toLowerCase()),
      ),
    [data, status, search],
  );
  const sidebar = (
    <>
      <Card className="mb-4 bg-lime-soft">
        <p className="text-xs font-semibold text-lime">Manager queue</p>
        <p className="mt-2 text-3xl font-medium">{requests.data ? counts.pending : "—"}</p>
        <p className="text-xs text-muted">waiting for your attention</p>
      </Card>
      <p className="px-3 text-xs leading-5 text-muted">
        Time-off requests need a decision. Sick leave only needs acknowledgement. Every action stays
        in the timeline.
      </p>
    </>
  );

  return (
    <Shell sidebar={sidebar} eyebrow="Manager inbox">
      <div className="mx-auto max-w-7xl p-4 sm:p-8">
        <div className="flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
          <div>
            <p className="text-xs font-bold uppercase tracking-[.18em] text-lime">
              Request workspace
            </p>
            <h1 className="mt-3 text-4xl font-medium tracking-[-.035em]">Manager inbox</h1>
            <p className="mt-2 text-sm text-muted">
              Decide when needed. Acknowledge when approval is not the point.
            </p>
          </div>
          <div className="flex gap-3">
            <Metric label="Open" value={requests.data ? counts.pending : "—"} icon={<Clock3 />} />
            <Metric
              label="Completed"
              value={requests.data ? counts.completed : "—"}
              icon={<CheckCircle2 />}
            />
            <Metric
              label="Declined"
              value={requests.data ? counts.declined : "—"}
              icon={<XCircle />}
            />
          </div>
        </div>

        <Card className="mt-8 overflow-hidden p-0">
          <div className="flex flex-col gap-3 border-b border-line p-4 sm:flex-row">
            <label className="relative flex-1">
              <span className="sr-only">Search requests</span>
              <Search className="absolute left-3 top-3 text-muted" size={17} />
              <input
                className={`${fieldClass} pl-10`}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search requests"
              />
            </label>
            <label className="relative">
              <span className="sr-only">Filter requests by status</span>
              <Filter className="absolute left-3 top-3 text-muted" size={16} />
              <select
                className={`${fieldClass} min-w-44 pl-10`}
                value={status}
                onChange={(event) => setStatus(event.target.value)}
              >
                <option value="all">All statuses</option>
                <option value="in_review">In review</option>
                <option value="reported">Reported</option>
                <option value="acknowledged">Acknowledged</option>
                <option value="approved">Approved</option>
                <option value="declined">Declined</option>
                <option value="cancelled">Cancelled</option>
              </select>
            </label>
          </div>
          <div className="overflow-x-auto">
            {requests.isLoading && (
              <div className="grid min-h-52 place-items-center text-sm text-muted">
                Loading manager queue…
              </div>
            )}
            {requests.isError && (
              <div className="grid min-h-52 place-items-center p-6 text-center">
                <div>
                  <p className="text-sm font-semibold">Unable to load the manager queue</p>
                  <Button className="mt-4" tone="secondary" onClick={() => requests.refetch()}>
                    Try again
                  </Button>
                </div>
              </div>
            )}
            {requests.isSuccess && (
              <table className="w-full min-w-[760px] text-left">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wider text-muted">
                    {["Request", "Employee", "Dates", "Status", "Created", ""].map((column) => (
                      <th key={column} className="px-5 py-3 font-semibold">
                        {column}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((request) => (
                    <tr key={request.id} className="border-t border-line/70 hover:bg-raised/60">
                      <td className="px-5 py-4">
                        <strong className="text-sm">{request.type_label}</strong>
                        <p className="mt-1 max-w-xs truncate text-xs text-muted">
                          {request.comment ||
                            (request.type === "sick_leave" ? "No team note" : "No note")}
                        </p>
                      </td>
                      <td className="px-5 py-4 text-sm">{request.applicant}</td>
                      <td className="px-5 py-4 text-xs text-muted">
                        {requestPeriodLabel(request)}
                      </td>
                      <td className="px-5 py-4">
                        <Badge tone={statusTone(request.status)}>
                          {formatStatus(request.status)}
                        </Badge>
                      </td>
                      <td className="px-5 py-4 text-xs text-muted">
                        {new Date(request.created_at).toLocaleDateString()}
                      </td>
                      <td className="px-5 py-4">
                        <Button tone="secondary" onClick={() => setSelected(request.id)}>
                          Open
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {requests.isSuccess && !rows.length && (
              <div className="grid min-h-52 place-items-center text-sm text-muted">
                <div className="text-center">
                  <Inbox className="mx-auto mb-2" />
                  No requests match this view.
                </div>
              </div>
            )}
          </div>
        </Card>
      </div>
      <DecisionDialog
        key={selected ?? "closed"}
        id={selected}
        onClose={() => setSelected(null)}
        onChanged={() => queryClient.invalidateQueries({ queryKey: ["manager-requests"] })}
      />
    </Shell>
  );
}

function Metric({
  label,
  value,
  icon,
}: {
  label: string;
  value: number | string;
  icon: React.ReactNode;
}) {
  return (
    <Card className="min-w-24 p-3">
      <span className="text-muted [&>svg]:h-4 [&>svg]:w-4">{icon}</span>
      <strong className="mt-2 block text-xl">{value}</strong>
      <span className="text-[10px] uppercase tracking-wider text-muted">{label}</span>
    </Card>
  );
}

function DecisionDialog({
  id,
  onClose,
  onChanged,
}: {
  id: string | null;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { token } = useAuth();
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");
  const detail = useQuery({
    queryKey: ["request-detail", id],
    queryFn: () => api<RequestDetail>(`/api/v1/requests/${id}`, token),
    enabled: Boolean(id),
  });
  const action = useMutation({
    mutationFn: (kind: "approve" | "decline" | "acknowledge") => {
      if (kind === "decline" && !comment.trim()) throw new Error("A decline reason is required.");
      return api(`/api/v1/requests/${id}/${kind}`, token, {
        method: "POST",
        body: JSON.stringify({ comment }),
      });
    },
    onSuccess: async () => {
      setComment("");
      setError("");
      onChanged();
      await detail.refetch();
    },
    onError: (requestError) =>
      setError(requestError instanceof Error ? requestError.message : "Decision failed"),
  });
  const request = detail.data?.request;

  return (
    <Drawer
      open={Boolean(id)}
      onOpenChange={(open) => !open && onClose()}
      title={request?.type_label ?? "Request review"}
      description={
        request?.type === "sick_leave"
          ? "Review availability and acknowledge the report."
          : "Review the request, decision notes, and timeline before deciding."
      }
      placement="center"
    >
      {detail.isLoading && <p className="text-muted">Loading request…</p>}
      {detail.isError && (
        <p className="rounded-xl bg-danger/10 p-3 text-sm text-danger">
          Unable to load this request.
        </p>
      )}
      {request && detail.data && (
        <div className="space-y-6">
          <div className="flex justify-between">
            <Badge tone={statusTone(request.status)}>{formatStatus(request.status)}</Badge>
            <span className="text-xs text-muted">#{request.id.slice(0, 8)}</span>
          </div>
          <RequestOverview request={request} />
          <DecisionNote detail={detail.data} />
          {request.status === "reported" && (
            <section className="rounded-2xl border border-lime/20 bg-lime/5 p-5">
              <div className="flex gap-3">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-lime/12 text-lime">
                  <ShieldCheck size={18} />
                </span>
                <div>
                  <h3 className="text-sm font-semibold">Acknowledge, don’t approve</h3>
                  <p className="mt-1 text-xs leading-5 text-muted">
                    Confirm you have seen the absence and can plan coverage.
                  </p>
                </div>
              </div>
              <label className="mt-5 block text-xs font-semibold text-muted">
                Support note <span className="font-normal">(optional)</span>
                <textarea
                  className={`${fieldClass} mt-2 min-h-20 resize-none`}
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  placeholder="For example: Take care — I’ll cover today’s stand-up."
                />
              </label>
              {error && <p className="mt-3 text-sm text-danger">{error}</p>}
              <Button
                className="mt-4 w-full"
                onClick={() => action.mutate("acknowledge")}
                disabled={action.isPending}
              >
                <CheckCircle2 size={16} />
                {action.isPending ? "Acknowledging…" : "Acknowledge absence"}
              </Button>
            </section>
          )}
          {request.status === "in_review" && (
            <section className="rounded-2xl border border-line bg-ink/35 p-5">
              <label className="block text-xs font-semibold text-muted">
                Decision note
                <textarea
                  className={`${fieldClass} mt-2 min-h-24 resize-none`}
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  placeholder="Add context for the employee. A reason is required when declining."
                />
              </label>
              <p className="mt-2 text-[11px] text-muted">
                The employee will see this note with the final decision.
              </p>
              {error && <p className="mt-3 text-sm text-danger">{error}</p>}
              <div className="mt-4 grid grid-cols-2 gap-3">
                <Button onClick={() => action.mutate("approve")} disabled={action.isPending}>
                  Approve
                </Button>
                <Button
                  tone="danger"
                  onClick={() => action.mutate("decline")}
                  disabled={action.isPending || !comment.trim()}
                >
                  Decline
                </Button>
              </div>
            </section>
          )}
          <RequestTimeline detail={detail.data} />
        </div>
      )}
    </Drawer>
  );
}
