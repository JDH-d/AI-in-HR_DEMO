import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { RequestDetail } from "../../api/types";
import { useAuth } from "../../app/providers";
import { Badge, Button, Drawer, formatStatus, statusTone } from "../../components/ui";
import { DecisionNote, RequestOverview, RequestTimeline } from "../requests/RequestDetails";

export function EmployeeRequestDetails({
  id,
  onClose,
}: {
  id: string | null;
  onClose: () => void;
}) {
  const { token } = useAuth();
  const detail = useQuery({
    queryKey: ["request-detail", id],
    queryFn: () => api<RequestDetail>(`/api/v1/requests/${id}`, token),
    refetchInterval: 10_000,
    enabled: Boolean(id),
  });
  const request = detail.data?.request;

  return (
    <Drawer
      open={Boolean(id)}
      onOpenChange={(open) => !open && onClose()}
      title={request?.type_label ?? "Request details"}
      description={
        request?.type === "sick_leave"
          ? "Your availability and manager acknowledgement."
          : "Your time off and manager decision."
      }
    >
      {detail.isLoading && (
        <p role="status" className="py-4 text-sm text-muted">
          Loading request…
        </p>
      )}
      {detail.isError && (
        <div role="alert" className="rounded-lg border border-danger/25 bg-danger/5 p-4">
          <p className="text-sm text-danger">Unable to load this request.</p>
          <Button tone="secondary" className="mt-3" onClick={() => void detail.refetch()}>
            Try again
          </Button>
        </div>
      )}
      {request && detail.data && (
        <div className="space-y-6">
          <div className="flex items-center justify-between border-b border-line pb-4">
            <Badge tone={statusTone(request.status)}>{formatStatus(request.status)}</Badge>
            <span className="text-xs text-muted">#{request.id.slice(0, 8)}</span>
          </div>
          <DecisionNote detail={detail.data} />
          <RequestOverview request={request} />
          <RequestTimeline detail={detail.data} />
        </div>
      )}
    </Drawer>
  );
}
