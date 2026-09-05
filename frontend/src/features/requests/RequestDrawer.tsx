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
  // Keep this session mounted when the parent receives the newly created request ID.
  // Closing the drawer still unmounts it so the next open starts with fresh values.
  return <RequestDrawerContent open={open} {...props} />;
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
      <Drawer
        open={open}
        onOpenChange={onOpenChange}
        title="Request sent"
        description="Your time off is ready for manager review."
      >
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
    ? "Share your availability with your manager. Medical details are not required."
    : "Review the dates and planning note before sending to your manager.";
  const clearError = () => setError("");

  return (
    <Drawer open={open} onOpenChange={onOpenChange} title={title} description={description}>
      <div className="mb-5 flex items-center justify-between gap-3 border-b border-line pb-4">
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

      <form
        className="space-y-5"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (form.formIsReady && !mutation.isPending) mutation.mutate();
        }}
      >
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

        {error && (
          <p
            role="alert"
            className="rounded-lg border border-danger/25 bg-danger/5 p-3 text-sm text-danger"
          >
            {error}
          </p>
        )}
        <div className="sticky -bottom-6 -mx-6 border-t border-line bg-panel px-6 pb-6 pt-4 sm:-bottom-8 sm:-mx-8 sm:px-8 sm:pb-8">
          {form.isDirty && (
            <p className="mb-3 text-xs leading-5 text-muted">
              Closing will discard unsent changes.
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" tone="secondary" onClick={() => onOpenChange(false)}>
              Close
            </Button>
            <Button type="submit" disabled={mutation.isPending || !form.formIsReady}>
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
      </form>
    </Drawer>
  );
}
