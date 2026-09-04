import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { RequestDetail } from "../../api/types";
import { useAuth } from "../../app/providers";
import { Badge, Drawer, formatStatus, statusTone } from "../../components/ui";
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
          ? "Your absence report, manager acknowledgement, and complete status history."
          : "Your request, manager decision, and complete status history."
      }
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
          <DecisionNote detail={detail.data} />
          <RequestOverview request={request} />
          <RequestTimeline detail={detail.data} />
        </div>
      )}
    </Drawer>
  );
}
