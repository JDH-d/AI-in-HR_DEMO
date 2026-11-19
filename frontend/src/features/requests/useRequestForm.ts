import { refreshRequests } from "./useRequests";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { WorkflowRequest } from "../../api/types";
import { useAuth } from "../../app/providers";
import { createUuid } from "../../utils/uuid";
export function useRequestForm(
  open: boolean,
  initial: WorkflowRequest | null | undefined,
  onSubmitted: (request: WorkflowRequest, mode: "submit" | "save") => void,
) {
  const { token, user } = useAuth();
  const queryClient = useQueryClient();
  const requestId = useRef<string | null>(null);
  const creationKey = useRef<string | null>(null);
  const revision = useRef(1);
  const session = useRef<{ id: string | null } | null>(null);
  const [baseline, setBaseline] = useState<WorkflowRequest | null>(null);
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState("normal");
  const [type, setType] = useState("pto");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [comment, setComment] = useState("");
  const [approver, setApprover] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) { session.current = null; return; }
    if (session.current?.id === (initial?.id ?? null)) return;
    session.current = { id: initial?.id ?? null };
    requestId.current = initial?.id ?? null;
    creationKey.current = null;
    revision.current = initial?.revision ?? 1;
    setBaseline(initial ?? null);
    setTitle(initial?.title ?? "");
    setPriority(initial?.priority ?? "normal");
    setType(initial?.type ?? "pto");
    setStart(initial?.start_date ?? "");
    setEnd(initial?.end_date ?? "");
    setComment(initial?.comment ?? "");
    setApprover(initial?.approver || user?.manager_id || "");
    setError("");
  }, [initial, open, user?.manager_id]);

  const conflict = Boolean(initial && initial.id === requestId.current && initial.revision !== revision.current);
  const reviewLatest = () => {
    if (!initial || !baseline || initial.status !== "draft") return;
    // Explicit three-way merge: preserve local edits; take remote changes in
    // untouched fields. The UI shows the saved version before this is accepted.
    if (title === baseline.title) setTitle(initial.title);
    if (priority === baseline.priority) setPriority(initial.priority);
    if (type === baseline.type) setType(initial.type);
    if (start === (baseline.start_date ?? "")) setStart(initial.start_date ?? "");
    if (end === (baseline.end_date ?? "")) setEnd(initial.end_date ?? "");
    if (comment === baseline.comment) setComment(initial.comment);
    setApprover(initial.approver);
    revision.current = initial.revision;
    setBaseline(initial);
    setError("");
  };
  const refresh = () => void refreshRequests(queryClient, requestId.current);
  const mutation = useMutation({
    mutationFn: async (mode: "submit" | "save" = "submit") => {
      if (conflict) throw new Error("This draft changed. Compare the latest saved version before saving your edits.");
      setError("");
      const fields = {
        title, priority,
        type,
        start_date: start || null,
        end_date: end || null,
        comment,
      };
      if (!requestId.current) {
        // Keep the same owner-scoped key if the server saves but its response is lost.
        // An edited retry conflicts on the server instead of silently reusing old fields.
        creationKey.current ??= createUuid();
        const created = await api<{ request: WorkflowRequest }>(
          "/api/v1/requests",
          token,
          { method: "POST", body: JSON.stringify({ ...fields, creation_key: creationKey.current }) },
        );
        // Retain the persisted draft if submission fails, so retry cannot create a duplicate.
        requestId.current = created.request.id;
        revision.current = created.request.revision;
        if (mode === "save") return created;
        refresh();
      }
      return api<{ request: WorkflowRequest }>(
        `/api/v1/requests/${requestId.current}${mode === "submit" ? "/submit" : ""}`,
        token,
        { method: mode === "submit" ? "POST" : "PATCH", body: JSON.stringify({ ...fields, expected_revision: revision.current }) },
      );
    },
    onSuccess: (data, mode) => {
      revision.current = data.request.revision;
      setBaseline(data.request);
      refresh();
      onSubmitted(data.request, mode);
    },
    onError: (cause: Error) => {
      setError(cause.message);
      refresh();
    },
  });
  const duration =
    start && end && end >= start
      ? Math.round((Date.parse(end) - Date.parse(start)) / 86400000) + 1
      : null;
  const datesRequired = type !== "document";
  const valid = Boolean(
    title.trim().length >= 3 && comment.trim().length >= 3 &&
      approver.trim() &&
      (!datesRequired || (start && end)) &&
      (!start || !end || end >= start),
  );
  const dirty = title !== (baseline?.title ?? "") || priority !== (baseline?.priority ?? "normal") ||
    type !== (baseline?.type ?? "pto") || start !== (baseline?.start_date ?? "") ||
    end !== (baseline?.end_date ?? "") || comment !== (baseline?.comment ?? "");
  return {
    title, setTitle, priority, setPriority,
    type,
    setType,
    start,
    setStart,
    end,
    setEnd,
    comment,
    setComment,
    approver,
    setApprover,
    error,
    conflict, reviewLatest,
    duration,
    datesRequired,
    valid,
    dirty,
    mutation,
  };
}
