import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { WorkflowRequest } from "../../api/types";
import { useAuth } from "../../app/providers";
import { Badge, Button, Drawer, formatStatus, statusTone } from "../../components/ui";
import { PtoFields, RequestTypeField, SickLeaveFields } from "./RequestFormFields";
import { PtoSuccess } from "./RequestSuccess";
import { useRequestForm } from "./requestFormState";

type RequestDrawerProps = {
  open: boolean;
  onOpenChange: (value: boolean) => void;
  initial?: WorkflowRequest | null;
  onSubmitted?: (request: WorkflowRequest) => void;
};

export function RequestDrawer({ open, ...props }: RequestDrawerProps) {
  if (!open) return null;
  return <RequestDrawerContent key={props.initial?.id ?? "new-request"} open={open} {...props} />;
}

function RequestDrawerContent({ open, onOpenChange, initial, onSubmitted }: RequestDrawerProps) {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  const form = useRequestForm(initial);
  const [activeDraft, setActiveDraft] = useState<WorkflowRequest | null>(initial ?? null);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!submitted) return;
    const closeTimer = window.setTimeout(() => onOpenChange(false), 2600);
    return () => window.clearTimeout(closeTimer);
  }, [onOpenChange, submitted]);

  const mutation = useMutation({
    mutationFn: async () => {
      let request = activeDraft;
      if (!request) {
        const created = await api<{ request: WorkflowRequest }>("/api/v1/requests", token, {
          method: "POST",
          body: JSON.stringify(form.payload),
        });
        request = created.request;
        setActiveDraft(request);
        void queryClient.invalidateQueries({ queryKey: ["requests"] });
      }
      return api<{ request: WorkflowRequest }>(`/api/v1/requests/${request.id}/submit`, token, {
        method: "POST",
        body: JSON.stringify(form.payload),
      });
    },
    onMutate: () => setError(""),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["requests"] });
      onSubmitted?.(result.request);
      if (result.request.type === "pto") {
        setSubmitted(true);
      } else {
        onOpenChange(false);
      }
    },
    onError: (requestError) => {
      setError(requestError instanceof Error ? requestError.message : "Unable to submit");
    },
  });

  if (submitted) {
    return (
      <Drawer open={open} onOpenChange={onOpenChange} title="Request sent">
        <PtoSuccess />
      </Drawer>
    );
  }

  const title = form.isSickLeave
    ? activeDraft
      ? "Review sick leave"
      : "Report sick leave"
    : activeDraft
      ? "Review time off"
      : "Plan time off";
  const description = form.isSickLeave
    ? "Let your manager know when you will be away. This is a notification, not an approval request."
    : "Your manager only gets the dates and a short planning note. Nothing is sent until you confirm.";
  const clearError = () => setError("");

  return (
    <Drawer open={open} onOpenChange={onOpenChange} title={title} description={description}>
      <div className="mb-6 flex items-center justify-between gap-3">
        <Badge tone={statusTone(activeDraft?.status ?? "draft")}>
          {activeDraft?.status
            ? formatStatus(activeDraft.status)
            : form.isSickLeave
              ? "new report"
              : "new request"}
        </Badge>
        <span className="text-right text-xs text-muted">
          {form.isSickLeave
            ? "Only availability details are required"
            : "Dates and a short note are required"}
        </span>
      </div>

      <div className="space-y-5">
        <RequestTypeField
          type={form.values.type}
          onChange={(type) => {
            form.changeType(type);
            clearError();
          }}
        />
        {form.isSickLeave ? (
          <SickLeaveFields form={form} onInteraction={clearError} />
        ) : (
          <PtoFields form={form} onInteraction={clearError} />
        )}

        {error && <p className="rounded-xl bg-danger/10 p-3 text-sm text-danger">{error}</p>}
        <div className="flex gap-3">
          <Button tone="secondary" className="flex-1" onClick={() => onOpenChange(false)}>
            {activeDraft ? "Keep as draft" : "Close"}
          </Button>
          <Button
            className="flex-1"
            disabled={mutation.isPending || !form.formIsReady}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending
              ? form.isSickLeave
                ? "Reporting…"
                : "Sending…"
              : form.isSickLeave
                ? "Report sick leave"
                : "Send for approval"}
          </Button>
        </div>
      </div>
    </Drawer>
  );
}
