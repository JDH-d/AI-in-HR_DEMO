import {
  ArrowRight,
  ChatCircle,
  FilePlus,
  PaperPlaneTilt,
  SpinnerGap,
} from "@phosphor-icons/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamChat } from "../../api/client";
import type {
  ChatMessage,
  ConversationDetail,
  ConversationSummary,
  WorkflowRequest,
} from "../../api/types";
import { useAuth } from "../../app/providers";
import { BrandMark } from "../../components/BrandMark";
import { Shell } from "../../components/Shell";
import { Button } from "../../components/ui";
import { RequestDrawer } from "../requests/RequestDrawer";
import { ChatMessageItem } from "./ChatMessageItem";
import { restoreConversationMessages } from "./conversationPresentation";
import { DeleteChatDialog } from "./DeleteChatDialog";
import { EmployeeRequestDetails } from "./EmployeeRequestDetails";
import { EmployeeSidebar } from "./EmployeeSidebar";

const suggestions = [
  ["Vacation policy", "How far in advance should I request vacation?"],
  ["Payroll timing", "When is payroll processed?"],
  ["VPN access", "How do I request VPN access?"],
  ["New hire setup", "What should be ready for a new hire on day one?"],
] as const;

const hello: ChatMessage = {
  id: "hello",
  role: "assistant",
  content:
    "Ask about your company’s policies, plan time off, or get help from HR. I’ll find the context and help with the next step.",
};

export function EmployeePage() {
  const { token, user } = useAuth();
  const queryClient = useQueryClient();
  const [messages, setMessages] = useState<ChatMessage[]>([hello]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversationLoading, setConversationLoading] = useState(false);
  const [conversationNotice, setConversationNotice] = useState("");
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [requestDraft, setRequestDraft] = useState<WorkflowRequest | null>(null);
  const [selectedRequest, setSelectedRequest] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ConversationSummary | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const deleteTrigger = useRef<HTMLButtonElement | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const followMessages = useRef(true);
  const loadSequence = useRef(0);
  const userId = user?.id ?? "employee";
  const conversationStorageKey = `peopleflow.active-conversation.${userId}`;

  useEffect(() => {
    if (!composer.current) return;
    composer.current.style.height = "auto";
    composer.current.style.height = `${draft ? Math.min(composer.current.scrollHeight, 160) : 42}px`;
  }, [draft]);

  useEffect(() => {
    if (messages.length && followMessages.current)
      bottom.current?.scrollIntoView({ behavior: "auto", block: "end" });
  }, [messages]);

  const conversations = useQuery({
    queryKey: ["conversations", userId],
    queryFn: () => api<{ conversations: ConversationSummary[] }>("/api/v1/conversations", token),
  });
  const requests = useQuery({
    queryKey: ["requests", userId],
    queryFn: () => api<{ requests: WorkflowRequest[] }>("/api/v1/requests", token),
  });

  const startNewChat = useCallback(() => {
    loadSequence.current += 1;
    setConversationId(null);
    setConversationLoading(false);
    setConversationNotice("");
    setMessages([hello]);
    setDraft("");
    followMessages.current = true;
    localStorage.removeItem(conversationStorageKey);
    requestAnimationFrame(() => {
      window.scrollTo({ top: 0, behavior: "auto" });
      composer.current?.focus({ preventScroll: true });
    });
  }, [conversationStorageKey]);

  const openConversation = useCallback(
    async (id: string) => {
      if (id === conversationId || sending) return;
      const sequence = ++loadSequence.current;
      localStorage.setItem(conversationStorageKey, id);
      setConversationId(id);
      setConversationLoading(true);
      setConversationNotice("");
      setMessages([hello]);
      setDraft("");
      followMessages.current = true;
      try {
        const detail = await api<ConversationDetail>(`/api/v1/conversations/${id}`, token);
        if (sequence !== loadSequence.current) return;
        setMessages([hello, ...restoreConversationMessages(detail.messages)]);
        requestAnimationFrame(() => bottom.current?.scrollIntoView({ behavior: "auto" }));
      } catch {
        if (sequence !== loadSequence.current) return;
        setConversationId(null);
        setMessages([hello]);
        setConversationNotice("That conversation is no longer available. A fresh chat is ready.");
        localStorage.removeItem(conversationStorageKey);
      } finally {
        if (sequence === loadSequence.current) setConversationLoading(false);
      }
    },
    [conversationId, conversationStorageKey, sending, token],
  );

  useEffect(() => {
    const savedConversationId = localStorage.getItem(conversationStorageKey);
    if (savedConversationId) void openConversation(savedConversationId);
  }, [conversationStorageKey, openConversation]);

  const openNewRequest = () => {
    setRequestDraft(null);
    setDrawerOpen(true);
  };

  const openRequest = (request: WorkflowRequest) => {
    if (request.status === "draft") {
      setRequestDraft(request);
      setDrawerOpen(true);
    } else {
      setSelectedRequest(request.id);
    }
  };

  const send = async (text = draft) => {
    const prompt = text.trim();
    if (!prompt || sending || conversationLoading) return;
    followMessages.current = true;

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: prompt,
    };
    const assistantId = crypto.randomUUID();
    setMessages((current) => [
      ...current,
      userMessage,
      {
        id: assistantId,
        role: "assistant",
        content: "",
        streaming: true,
        question: prompt,
      },
    ]);
    setDraft("");
    setSending(true);
    setConversationNotice("");

    try {
      await streamChat(
        token,
        prompt,
        (event) => {
          if (event.type === "token") {
            setMessages((current) =>
              current.map((message) =>
                message.id === assistantId
                  ? { ...message, content: message.content + event.content }
                  : message,
              ),
            );
          } else if (event.type === "replace") {
            setMessages((current) =>
              current.map((message) =>
                message.id === assistantId ? { ...message, content: event.content } : message,
              ),
            );
          } else if (event.type === "error") {
            setMessages((current) =>
              current.map((message) =>
                message.id === assistantId
                  ? { ...message, streaming: false, error: true, content: event.message }
                  : message,
              ),
            );
          } else if (event.type === "complete") {
            setConversationId(event.conversation_id);
            localStorage.setItem(conversationStorageKey, event.conversation_id);
            setMessages((current) =>
              current.map((message) =>
                message.id === assistantId
                  ? {
                      ...message,
                      streaming: false,
                      sources: event.sources,
                      workflow: event.workflow_request,
                    }
                  : message,
              ),
            );
          }
        },
        conversationId ?? undefined,
      );
    } catch (error) {
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId
            ? {
                ...message,
                streaming: false,
                error: true,
                content: error instanceof Error ? error.message : "The assistant is unavailable.",
              }
            : message,
        ),
      );
    } finally {
      setSending(false);
      void queryClient.invalidateQueries({ queryKey: ["conversations", userId] });
      void queryClient.invalidateQueries({ queryKey: ["requests", userId] });
    }
  };

  const deleteConversation = async () => {
    if (!deleteTarget || deleting || sending) return;
    const id = deleteTarget.id;
    setDeleting(true);
    setDeleteError("");
    try {
      await api<void>(`/api/v1/conversations/${encodeURIComponent(id)}`, token, {
        method: "DELETE",
      });
      await queryClient.cancelQueries({ queryKey: ["conversations", userId] });
      queryClient.setQueryData<{ conversations: ConversationSummary[] }>(
        ["conversations", userId],
        (current) =>
          current && { conversations: current.conversations.filter((chat) => chat.id !== id) },
      );
      if (conversationId === id) startNewChat();
      setDeleteTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["conversations", userId] });
    } catch (error) {
      setDeleteError(
        error instanceof Error ? error.message : "Couldn't delete this chat. Try again.",
      );
    } finally {
      setDeleting(false);
    }
  };

  const sidebar = (
    <EmployeeSidebar
      conversations={conversations.data?.conversations ?? []}
      conversationsLoading={conversations.isLoading}
      conversationsError={conversations.isError}
      requests={requests.data?.requests ?? []}
      requestsLoading={requests.isLoading}
      requestsError={requests.isError}
      activeConversationId={conversationId}
      sending={sending}
      onNewChat={startNewChat}
      onNewRequest={openNewRequest}
      onOpenConversation={(id) => void openConversation(id)}
      onDeleteConversation={(conversation, trigger) => {
        deleteTrigger.current = trigger;
        setDeleteError("");
        setDeleteTarget(conversation);
      }}
      onOpenRequest={openRequest}
    />
  );

  const activeTitle = conversations.data?.conversations.find(
    (item) => item.id === conversationId,
  )?.title;
  const visibleMessages = messages.filter((message) => message.id !== "hello");

  return (
    <Shell
      sidebar={sidebar}
      eyebrow={activeTitle ?? (visibleMessages.length ? "Conversation" : "New Chat")}
      onLogoClick={startNewChat}
      logoDisabled={sending}
    >
      <div className="chat-workspace">
        <div
          className="chat-scroll scrollbar"
          ref={scroller}
          onScroll={(event) => {
            const el = event.currentTarget;
            followMessages.current = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
          }}
        >
          <div className="chat-thread">
            {conversationNotice && (
              <div
                role="status"
                className="mb-6 rounded-md border border-warning/20 bg-warning/5 px-4 py-3 text-sm text-warning"
              >
                {conversationNotice}
              </div>
            )}
            {conversationLoading ? (
              <div
                className="flex min-h-64 items-center justify-center gap-3 text-sm text-muted"
                role="status"
              >
                <SpinnerGap className="animate-spin text-accent" size={20} />
                Opening conversation…
              </div>
            ) : visibleMessages.length ? (
              <div>
                {visibleMessages.map((message) => (
                  <ChatMessageItem
                    key={message.id}
                    message={
                      message.workflow
                        ? {
                            ...message,
                            workflow:
                              requests.data?.requests.find(
                                (request) => request.id === message.workflow?.id,
                              ) ?? message.workflow,
                          }
                        : message
                    }
                    onOpenRequest={openRequest}
                  />
                ))}
              </div>
            ) : (
              <section className="mx-auto max-w-2xl py-6 sm:py-12">
                <div className="assistant-avatar mb-5">
                  <BrandMark size={28} />
                </div>
                <h2 className="text-2xl font-medium tracking-tight">How can I help?</h2>
                <p className="mt-3 max-w-lg text-sm leading-7 text-muted">{hello.content}</p>
                <div className="mt-8 border-t border-line pt-5">
                  <h3 className="mb-3 text-xs font-medium text-muted">A few things you can ask</h3>
                  <div className="grid gap-x-4 gap-y-1 sm:grid-cols-2">
                    {suggestions.map(([label, prompt]) => (
                      <button
                        key={label}
                        type="button"
                        onClick={() => void send(prompt)}
                        className="focus-ring group flex items-center justify-between gap-3 rounded-md px-3 py-3 text-left text-sm text-muted transition-colors hover:bg-panel hover:text-cream"
                      >
                        <span>{label}</span>
                        <ArrowRight size={16} className="text-muted group-hover:text-accent" />
                      </button>
                    ))}
                  </div>
                </div>
              </section>
            )}
            <div ref={bottom} />
          </div>
        </div>
        <div className="chat-composer-wrap">
          <div className="chat-composer-inner">
            <div className="mb-2 flex gap-1">
              <Button tone="ghost" className="min-h-8 px-2 text-xs" onClick={openNewRequest}>
                <FilePlus size={16} />
                Create request
              </Button>
              <Button
                tone="ghost"
                className="min-h-8 px-2 text-xs"
                disabled={sending || conversationLoading}
                onClick={() => void send("I need help from HR")}
              >
                <ChatCircle size={16} />
                Ask HR
              </Button>
            </div>
            <form
              className="chat-composer"
              onSubmit={(event) => {
                event.preventDefault();
                void send();
              }}
            >
              <textarea
                rows={1}
                ref={composer}
                aria-label="Message PeopleFlow AI"
                value={draft}
                disabled={conversationLoading}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                    event.preventDefault();
                    void send();
                  }
                }}
                placeholder="Message PeopleFlow…"
              />
              <button
                type="submit"
                aria-label={sending ? "Sending message" : "Send message"}
                disabled={sending || conversationLoading || !draft.trim()}
                className="icon-button mb-0.5 text-accent disabled:opacity-35"
              >
                {sending ? (
                  <SpinnerGap className="animate-spin" size={23} />
                ) : (
                  <PaperPlaneTilt size={24} />
                )}
              </button>
            </form>
            <p className="mt-2.5 text-center text-[11px] leading-5 text-muted">
              PeopleFlow can make mistakes. Check important details.
            </p>
          </div>
        </div>
      </div>

      <RequestDrawer
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        initial={requestDraft}
        onSubmitted={(request) => {
          setRequestDraft(request);
          setMessages((current) =>
            current.map((message) =>
              message.workflow?.id === request.id ? { ...message, workflow: request } : message,
            ),
          );
        }}
      />
      <EmployeeRequestDetails id={selectedRequest} onClose={() => setSelectedRequest(null)} />
      <DeleteChatDialog
        conversation={deleteTarget}
        busy={deleting}
        error={deleteError}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => void deleteConversation()}
        onRestoreFocus={() => {
          const trigger = deleteTrigger.current;
          if (trigger?.isConnected && trigger.getClientRects().length) {
            trigger.focus();
            return;
          }
          const newChat = Array.from(
            document.querySelectorAll<HTMLButtonElement>("[data-new-chat]"),
          ).find((button) => button.getClientRects().length);
          (newChat ?? composer.current)?.focus({ preventScroll: true });
        }}
      />
    </Shell>
  );
}
