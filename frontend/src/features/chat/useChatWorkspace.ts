import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { WorkflowRequest } from "../../api/types";
import { useAuth } from "../../app/providers";
import { refreshRequests, useRequests } from "../requests/useRequests";
import { useConversations } from "./useConversations";

export function useChatWorkspace(onUpdate: () => void) {
  const {user} = useAuth();
  const employee = user?.role === "employee";
  const cache = useQueryClient();
  const requests = useRequests();
  const [drawer, setDrawer] = useState(false);
  const [requestDraft, setRequestDraft] = useState<WorkflowRequest | null>(null);
  const [selectedRequest, setSelectedRequest] = useState<string | null>(null);
  const openNewRequest = () => { if (employee) { setRequestDraft(null); setDrawer(true); } };
  const openRequest = (request: WorkflowRequest) => {
    if (!employee) return;
    setSelectedRequest(request.id);
  };
  const conversations = useConversations(onUpdate, request => {
    void refreshRequests(cache); openRequest(request);
  });
  return {employee, conversations, requests, drawer, setDrawer, requestDraft, selectedRequest, setSelectedRequest, openNewRequest, openRequest};
}
