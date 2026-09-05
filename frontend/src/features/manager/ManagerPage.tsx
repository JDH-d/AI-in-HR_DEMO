import {
  CheckCircle,
  Clock,
  Funnel,
  MagnifyingGlass,
  ShieldCheck,
  Tray,
  XCircle,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
    <div className="space-y-4">
      <div className="flex items-center gap-3 rounded-lg border border-line bg-panel px-3 py-3 text-sm">
        <Tray size={20} className="text-accent" />
        <span className="flex-1 font-medium">Team requests</span>
        <span className="tabular-nums text-muted">{requests.data ? counts.pending : "—"}</span>
      </div>
      <p className="px-3 text-sm leading-6 text-muted">
        Review time off and acknowledge sick leave from your team.
      </p>
    </div>
  );

  return (
    <Shell sidebar={sidebar} eyebrow="Manager inbox">
      <div className="mx-auto max-w-7xl p-4 sm:p-6 lg:p-8">
        <div className="flex flex-col justify-between gap-5 xl:flex-row xl:items-center">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Manager inbox</h1>
            <p className="mt-1.5 text-sm text-muted">
              Time-off decisions and absence reports, in one place.
            </p>
          </div>
          <div className="flex flex-wrap gap-x-5 gap-y-3">
            <Metric label="Open" value={requests.data ? counts.pending : "—"} icon={<Clock />} />
            <Metric
              label="Completed"
              value={requests.data ? counts.completed : "—"}
              icon={<CheckCircle />}
            />
            <Metric
              label="Declined"
              value={requests.data ? counts.declined : "—"}
              icon={<XCircle />}
            />
          </div>
        </div>

        <Card className="mt-6 overflow-hidden p-0">
          <div className="flex flex-col gap-3 border-b border-line p-4 sm:flex-row">
            <label className="relative flex-1">
              <span className="sr-only">Search requests</span>
              <MagnifyingGlass
                className="absolute left-3 top-1/2 -translate-y-1/2 text-muted"
                size={18}
              />
              <input
                className={`${fieldClass} pl-10`}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search requests or employees"
              />
            </label>
            <label className="relative">
              <span className="sr-only">Filter requests by status</span>
              <Funnel className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" size={18} />
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
                  <tr className="bg-ink text-xs font-medium text-muted">
                    {["Request", "Employee", "Dates", "Status", "Created", ""].map((column) => (
                      <th key={column} scope="col" className="px-5 py-3 font-medium">
                        {column}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((request) => (
                    <tr key={request.id} className="border-t border-line/70 hover:bg-raised/60">
                      <td className="px-5 py-4">
                        <strong className="text-sm font-medium">{request.type_label}</strong>
                        <p className="mt-1 max-w-xs truncate text-xs text-muted">
                          {request.comment ||
                            (request.type === "sick_leave" ? "No team note" : "No note")}
                        </p>
                      </td>
                      <td className="px-5 py-4 text-sm">{request.applicant}</td>
                      <td className="px-5 py-4 text-sm text-muted">
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
                        <Button
                          tone="secondary"
                          aria-label={`Review ${request.type_label} from ${request.applicant}`}
                          onClick={() => setSelected(request.id)}
                        >
                          Review
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
                  <Tray className="mx-auto mb-3 text-muted" size={24} />
                  <p className="font-medium text-cream">
                    {data.length ? "No requests match this view" : "Your team is all caught up"}
                  </p>
                  <p className="mt-1.5 text-sm text-muted">
                    {data.length
                      ? "Try another search or status."
                      : "New requests will appear here."}
                  </p>
                  {data.length > 0 && (
                    <Button
                      tone="ghost"
                      className="mt-3"
                      onClick={() => {
                        setSearch("");
                        setStatus("all");
                      }}
                    >
                      Clear filters
                    </Button>
                  )}
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
    <div className="flex items-center gap-2 text-sm">
      <span className="text-muted [&>svg]:h-[18px] [&>svg]:w-[18px]">{icon}</span>
      <span className="text-muted">{label}</span>
      <strong className="font-semibold tabular-nums">{value}</strong>
    </div>
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
        <div className="rounded-lg border border-danger/20 bg-danger/5 p-4">
          <p className="text-sm text-danger">Unable to load this request.</p>
          <Button className="mt-3" tone="secondary" onClick={() => detail.refetch()}>
            Try again
          </Button>
        </div>
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
            <section className="rounded-lg border border-line bg-ink p-4">
              <div className="flex gap-3">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-accent/12 text-accent">
                  <ShieldCheck size={18} />
                </span>
                <div>
                  <h3 className="text-sm font-semibold">Acknowledge absence</h3>
                  <p className="mt-1 text-sm leading-6 text-muted">
                    Confirm you have seen the absence and can plan coverage.
                  </p>
                </div>
              </div>
              <label className="mt-4 block text-sm font-medium">
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
                <CheckCircle size={18} />
                {action.isPending ? "Acknowledging…" : "Acknowledge absence"}
              </Button>
            </section>
          )}
          {request.status === "in_review" && (
            <section className="rounded-lg border border-line bg-ink p-4">
              <label className="block text-sm font-medium">
                Decision note
                <textarea
                  className={`${fieldClass} mt-2 min-h-24 resize-none`}
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  placeholder="Add context for the employee. A reason is required when declining."
                />
              </label>
              <p className="mt-2 text-xs text-muted">
                The employee will see this note with the final decision.
              </p>
              {error && <p className="mt-3 text-sm text-danger">{error}</p>}
              <div className="mt-4 grid grid-cols-2 gap-3">
                <Button onClick={() => action.mutate("approve")} disabled={action.isPending}>
                  <CheckCircle size={18} />
                  {action.isPending && action.variables === "approve" ? "Approving…" : "Approve"}
                </Button>
                <Button
                  tone="danger"
                  onClick={() => action.mutate("decline")}
                  disabled={action.isPending || !comment.trim()}
                >
                  <XCircle size={18} />
                  {action.isPending && action.variables === "decline" ? "Declining…" : "Decline"}
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
