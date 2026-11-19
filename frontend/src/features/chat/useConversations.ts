import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { api, ApiError, streamChat } from "../../api/client";
import type { ChatMessage, Conversation, ConversationDetail, ConversationList, WorkflowRequest } from "../../api/types";
import { useAuth } from "../../app/providers";
import { useProtectedNavigation, useUnsavedChanges } from "../../components/UnsavedChanges";
import { createUuid } from "../../utils/uuid";

export function useConversations(onUpdate: () => void, onWorkflow: (request: WorkflowRequest) => void) {
  const { token, user } = useAuth();
  const cache = useQueryClient();
  const [params, setParams] = useSearchParams();
  const id = params.get("conversation");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const setDraftProtection = useUnsavedChanges(Boolean(draft.trim()) && !busy);
  const protect = useProtectedNavigation();
  const lock = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const newId = useRef<string | null>(null);
  const locallyCreatedId = useRef<string | null>(null);
  const [optimistic, setOptimistic] = useState<{id: string; messages: ChatMessage[]} | null>(null);
  const [retry, setRetry] = useState<{conversationId: string; requestId: string; content: string} | null>(null);
  const listKey = ["conversations", user?.id];
  const detailKey = (value: string | null) => ["conversation", user?.id, value];
  const load = (value: string, signal?: AbortSignal) => api<ConversationDetail>(`/api/v1/conversations/${value}`, token, { signal });

  useEffect(() => { const timer = setTimeout(() => setQuery(search), 250); return () => clearTimeout(timer); }, [search]);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    // Creating a chat is part of sending the current draft. A fast failed send
    // can finish before this effect runs; its recovered text must survive.
    if (id && locallyCreatedId.current === id) { locallyCreatedId.current = null; return; }
    if (!lock.current) { setDraft(""); setError(""); setRetry(null); }
  }, [id]);
  const list = useInfiniteQuery({
    queryKey: [...listKey, query], initialPageParam: 0,
    queryFn: ({pageParam, signal}) => api<ConversationList>(`/api/v1/conversations?q=${encodeURIComponent(query)}&offset=${pageParam}&limit=50`, token, {signal}),
    getNextPageParam: (last, pages) => last.has_more ? pages.reduce((total, page) => total + page.conversations.length, 0) : undefined,
  });
  const savedDetail = useQuery({
    queryKey: detailKey(id), enabled: Boolean(id),
    queryFn: ({signal}) => load(id!, signal),
    refetchInterval: (state) => state.state.data?.messages.some(m => m.status === "pending") ? 2000 : false,
  });
  // A refetch error retains cached data in React Query. Never render a conversation
  // the server has confirmed is deleted or no longer accessible.
  const inaccessible = savedDetail.error instanceof ApiError && [403, 404].includes(savedDetail.error.status);
  const detail = inaccessible ? {...savedDetail, data: undefined} : savedDetail;
  const messages = inaccessible ? [] : optimistic?.id === id ? optimistic.messages : (detail.data?.messages ?? []);
  useEffect(() => {
    if (inaccessible) void cache.invalidateQueries({queryKey: ["conversations", user?.id]});
  }, [cache, id, inaccessible, user?.id]);
  const pending = busy || messages.some(m => m.status === "pending");
  const selectNow = (value: string | null) => {
    setDraftProtection();
    setDraft(""); setError(""); setRetry(null); setOptimistic(null);
    setParams(value ? {conversation: value} : {});
  };
  const select = (value: string | null) => {
    if (lock.current || value === id) return;
    // Do not clear text until the user has accepted leaving the current chat.
    protect(() => selectNow(value));
  };
  const create = async () => {
    newId.current ??= createUuid();
    const result = await api<{conversation: Conversation}>("/api/v1/conversations", token,
      {method: "POST", body: JSON.stringify({id: newId.current})});
    newId.current = null;
    cache.setQueryData(detailKey(result.conversation.id), {...result, messages: []});
    locallyCreatedId.current = result.conversation.id;
    setDraftProtection();
    setParams({conversation: result.conversation.id});
    void cache.invalidateQueries({queryKey: listKey});
    return result.conversation.id;
  };
  const createNewConversation = async () => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError("");
    try { await create(); setDraft(""); setRetry(null); setOptimistic(null); }
    catch (cause) { setDraftProtection(Boolean(draft.trim())); setError(cause instanceof Error ? cause.message : "Unable to create conversation."); }
    finally { lock.current = false; setBusy(false); }
  };
  const newConversation = () => {
    if (lock.current) return;
    let operation: Promise<void> | undefined;
    // In particular, do not POST an empty chat before discard is confirmed.
    protect(() => { operation = createNewConversation(); return operation; });
    return operation;
  };
  const sendNow = async (text: string, retryTurn?: {conversationId: string; requestId: string; content: string}) => {
    const content = text.trim();
    if (!content || lock.current || pending || (id && !detail.data)) return;
    lock.current = true; setBusy(true); setError("");
    let target = id;
    let submitted: {requestId: string} | null = null;
    try {
      target = retryTurn?.conversationId ?? target ?? await create();
      const sameRetry = retry?.conversationId === target && retry.content === content ? retry : null;
      const request = retryTurn ?? sameRetry ?? {conversationId: target, requestId: createUuid(), content};
      submitted = request;
      setRetry(request);
      const previous = (cache.getQueryData<ConversationDetail>(detailKey(target))?.messages ?? []).filter(m => m.turn_id !== request.requestId);
      const userMessage: ChatMessage = {id: `${request.requestId}-user`, turn_id: request.requestId, role: "user", content, created_at: new Date().toISOString(), status: "complete"};
      const assistant: ChatMessage = {id: `${request.requestId}-assistant`, turn_id: request.requestId, role: "assistant", content: "", status: "pending", streaming: true};
      setOptimistic({id: target, messages: [...previous, userMessage, assistant]}); setDraft("");
      controller.current = new AbortController();
      await streamChat(token, request, event => {
        if (event.type === "start") {
          setOptimistic({id: target!, messages: [...previous, event.user_message as ChatMessage, assistant]});
        } else if (event.type === "token") {
          setOptimistic(current => current && ({...current, messages: current.messages.map(m => m.id === assistant.id ? {...m, content: m.content + String(event.content)} : m)}));
        } else if (event.type === "complete") {
          const message = event.message as ChatMessage;
          const saved = {conversation: event.conversation as Conversation, messages: [...previous, event.user_message as ChatMessage, message]};
          cache.setQueryData(detailKey(target), saved);
          setOptimistic({id: target!, messages: saved.messages}); setRetry(null);
          if (message.workflow) onWorkflow(message.workflow);
        }
        onUpdate();
      }, controller.current.signal);
    } catch (cause) {
      setDraft(current => current || text);
      setDraftProtection(true);
      if (!(cause instanceof DOMException && cause.name === "AbortError"))
        setError(cause instanceof Error ? cause.message : "Unable to send. Reload the conversation to check saved messages.");
    } finally {
      if (target) {
        try {
          const saved = await cache.fetchQuery({queryKey: detailKey(target), queryFn: () => load(target!), staleTime: 0});
          if (saved.messages.some(message => message.turn_id === submitted?.requestId && message.role === "assistant" && message.status === "complete")) {
            setDraftProtection();
            setRetry(null); setError(""); setDraft(current => current.trim() === content ? "" : current);
          }
        } catch { /* Keep the error visible; the persisted history can be reloaded. */ }
      }
      setOptimistic(null); lock.current = false; setBusy(false);
      void cache.invalidateQueries({queryKey: listKey});
    }
  };
  const send = async (text = draft, retryTurn?: {conversationId: string; requestId: string; content: string}) => {
    if (lock.current || pending) return;
    if (draft.trim() && text.trim() !== draft.trim()) {
      let operation: Promise<void> | undefined;
      // Suggested questions and retries must not overwrite a different draft.
      protect(() => { operation = sendNow(text, retryTurn); return operation; });
      await operation;
    } else await sendNow(text, retryTurn);
  };
  const retryLast = () => {
    const last = messages.at(-1);
    const question = messages.find(m => m.turn_id === last?.turn_id && m.role === "user");
    const request = retry ?? (id && question && last?.status === "failed" ? {conversationId: id, requestId: last.turn_id!, content: question.content} : null);
    if (request) void send(request.content, request);
  };
  const rename = async (title: string) => {
    if (!id) return;
    await api(`/api/v1/conversations/${id}`, token, {method: "PATCH", body: JSON.stringify({title})});
    await Promise.all([cache.invalidateQueries({queryKey: listKey}), cache.invalidateQueries({queryKey: detailKey(id)})]);
  };
  const remove = async () => {
    if (!id) return;
    await api(`/api/v1/conversations/${id}`, token, {method: "DELETE"});
    // The delete confirmation explicitly includes the unsent text in this chat.
    cache.removeQueries({queryKey: detailKey(id)}); selectNow(null);
    await cache.invalidateQueries({queryKey: listKey});
  };
  return {id, search, setSearch, searchPending: search !== query, draft, setDraft, error, busy, pending, messages, list, detail, unavailable: inaccessible, select,
    newConversation, send, rename, remove, retryLast, canRetry: !pending && Boolean(retry || messages.at(-1)?.status === "failed")};
}
