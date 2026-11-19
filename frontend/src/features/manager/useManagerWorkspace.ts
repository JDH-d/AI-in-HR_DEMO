import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { BulkReviewResult, ManagerActivity, ManagerOverview, WorkflowRequest } from "../../api/types";
import { useAuth } from "../../app/providers";
import { refreshRequests } from "../requests/useRequests";

export function useManagerOverview() {
  const { token, user } = useAuth();
  return useQuery({ queryKey: ["manager-overview", user?.id], queryFn: () => api<ManagerOverview>("/api/v1/manager/overview", token), enabled: user?.role === "manager", refetchInterval: 60_000 });
}

export function useManagerActivity(open: boolean, offset: number) {
  const { token, user } = useAuth();
  return useQuery({ queryKey: ["manager-activity", user?.id, offset], queryFn: () => api<ManagerActivity>(`/api/v1/manager/activity?limit=20&offset=${offset}`, token), enabled: open && user?.role === "manager" });
}

export function useBulkReview(rows: WorkflowRequest[], scope: string, enabled: boolean) {
  const { token, user } = useAuth();
  const cache = useQueryClient();
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<WorkflowRequest[]>([]);
  const [confirm, setConfirm] = useState(false);
  const [notice, setNotice] = useState("");
  const [outcome, setOutcome] = useState<{ result: BulkReviewResult; items: WorkflowRequest[] } | null>(null);
  const contextKey = JSON.stringify([scope, enabled, user?.id, user?.role]);
  const previousScope = useRef(contextKey);
  const currentScope = useRef(contextKey);
  currentScope.current = contextKey;
  const eligible = enabled && user?.role === "manager"
    ? rows.filter(row => row.status === "submitted" && row.applicant !== user.id && row.approver === user.id)
    : [];
  const mutation = useMutation({
    mutationFn: (items: WorkflowRequest[]) => api<BulkReviewResult>("/api/v1/manager/bulk-start-review", token, {
      method: "POST", body: JSON.stringify({ items: items.map(item => ({ id: item.id, expected_revision: item.revision })) }),
    }),
    onMutate: () => { setOutcome(null); setNotice(""); return contextKey; },
    onSuccess: (result, items, operationScope) => { if (operationScope === currentScope.current) { setOutcome({ result, items }); setNotice(""); } },
    onError: (_error, _items, operationScope) => { if (operationScope === currentScope.current) setNotice("The result could not be confirmed. Reload the queue and check each request before selecting again."); },
    onSettled: async (_result, _error, _items, operationScope) => { if (operationScope === currentScope.current) { setConfirm(false); setSelected([]); setSelecting(false); } await refreshRequests(cache); },
  });
  useEffect(() => {
    if (previousScope.current !== contextKey || !enabled) {
      previousScope.current = contextKey; setSelected([]); setSelecting(false); setConfirm(false); setNotice(""); setOutcome(null);
    }
  }, [contextKey, enabled]);
  useEffect(() => {
    if (mutation.isPending || !selected.length) return;
    const valid = selected.filter(item => eligible.some(row => row.id === item.id && row.revision === item.revision));
    if (valid.length !== selected.length) {
      setSelected(valid); setConfirm(false); setNotice("Some selected requests changed or left this page. Review the queue and select them again if appropriate.");
    }
  }, [rows, selected, user?.id, mutation.isPending]);
  const clear = () => { if (!mutation.isPending) { setSelected([]); setSelecting(false); setConfirm(false); } };
  return {
    selecting, setSelecting, selected, confirm, setConfirm, notice, outcome, mutation, eligible, clear,
    toggle: (row: WorkflowRequest) => {
      if (mutation.isPending || !eligible.some(item => item.id === row.id)) return;
      setSelected(current => current.some(item => item.id === row.id) ? current.filter(item => item.id !== row.id) : [...current, row].slice(0, 20));
    },
    selectAll: () => { if (!mutation.isPending) setSelected(selected.length === eligible.length ? [] : eligible.slice(0, 20)); },
    start: () => { if (enabled && selected.length && selected.every(item => eligible.some(row => row.id === item.id && row.revision === item.revision)) && !mutation.isPending) mutation.mutate(selected); },
  };
}
export type BulkReviewState = ReturnType<typeof useBulkReview>;
