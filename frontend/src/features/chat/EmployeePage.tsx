import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, FileCheck2, LoaderCircle, MessageCircleQuestion, Sparkles } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamChat } from "../../api/client";
import type {
  ChatMessage,
  ConversationDetail,
  ConversationSummary,
  WorkflowRequest,
} from "../../api/types";
import { useAuth } from "../../app/providers";
import { Shell } from "../../components/Shell";
import { Button } from "../../components/ui";
import { RequestDrawer } from "../requests/RequestDrawer";
import { ChatMessageItem } from "./ChatMessageItem";
import { restoreConversationMessages } from "./conversationPresentation";
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
    "Good morning. I can answer policy questions with evidence, or turn a clear action into a request you review before sending.",
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
  const bottom = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const loadSequence = useRef(0);
  const userId = user?.id ?? "employee";
  const conversationStorageKey = `peopleflow.active-conversation.${userId}`;

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
            if (event.workflow_request) {
              setRequestDraft(event.workflow_request);
              setDrawerOpen(true);
            }
          }
          bottom.current?.scrollIntoView({ behavior: "smooth" });
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
      onNewRequest={openNewRequest}
      onOpenConversation={(id) => void openConversation(id)}
      onOpenRequest={openRequest}
    />
  );

  return (
    <Shell
      sidebar={sidebar}
      eyebrow="Employee workspace"
      onLogoClick={startNewChat}
      logoDisabled={sending}
    >
      <div className="mx-auto flex min-h-[calc(100vh-64px)] max-w-5xl flex-col px-4 sm:px-8">
        <div className="flex-1 py-8 sm:py-12">
          {conversationNotice && (
            <div
              role="status"
              className="mb-6 rounded-xl border border-coral/20 bg-coral/5 px-4 py-3 text-sm text-coral"
            >
              {conversationNotice}
            </div>
          )}
          {conversationLoading ? (
            <div className="flex min-h-64 items-center justify-center gap-3 text-sm text-muted">
              <LoaderCircle className="animate-spin text-lime" size={18} />
              Opening conversation…
            </div>
          ) : (
            <>
              {messages.length === 1 && (
                <section className="mb-10">
                  <div className="mb-3 flex items-center gap-2 text-xs font-bold uppercase tracking-[.18em] text-lime">
                    <Sparkles size={15} />
                    Suggested actions
                  </div>
                  <h1 className="max-w-2xl text-4xl font-medium tracking-[-.035em] sm:text-5xl">
                    What can we make easier today?
                  </h1>
                  <div className="mt-7 grid gap-3 sm:grid-cols-2">
                    {suggestions.map(([label, prompt]) => (
                      <button
                        key={label}
                        type="button"
                        onClick={() => void send(prompt)}
                        className="focus-ring group rounded-2xl border border-line bg-panel p-4 text-left transition hover:-translate-y-0.5 hover:border-lime/35 hover:bg-raised"
                      >
                        <span className="text-xs font-semibold text-coral">{label}</span>
                        <span className="mt-2 block text-sm leading-6 text-muted group-hover:text-cream">
                          {prompt}
                        </span>
                      </button>
                    ))}
                  </div>
                </section>
              )}
              <div className="space-y-7">
                {messages.map((message) => (
                  <ChatMessageItem key={message.id} message={message} onOpenRequest={openRequest} />
                ))}
                <div ref={bottom} />
              </div>
            </>
          )}
        </div>

        <div className="sticky bottom-0 pb-5 pt-3">
          <div className="mx-auto w-full max-w-3xl">
            <div className="mb-2 flex gap-1 px-1">
              <Button tone="ghost" className="rounded-lg px-3 text-xs" onClick={openNewRequest}>
                <FileCheck2 size={15} />
                Create request
              </Button>
              <Button
                tone="ghost"
                className="rounded-lg px-3 text-xs"
                onClick={() => void send("I need help from HR")}
              >
                <MessageCircleQuestion size={15} />
                Ask HR
              </Button>
            </div>
            <div className="soft-shadow flex items-end gap-2 rounded-2xl border border-line bg-raised p-2 transition-colors focus-within:border-lime/35 focus-within:bg-panel">
              <textarea
                rows={1}
                ref={composer}
                aria-label="Message PeopleFlow AI"
                value={draft}
                disabled={conversationLoading}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void send();
                  }
                }}
                placeholder="What do you need help with?"
                className="max-h-36 min-h-11 flex-1 resize-none overflow-y-auto bg-transparent px-3 py-3 text-[15px] leading-5 outline-none placeholder:text-muted/75 disabled:cursor-wait disabled:opacity-60"
              />
              <Button
                aria-label="Send message"
                className="h-11 w-11 shrink-0 rounded-full px-0"
                disabled={sending || conversationLoading || !draft.trim()}
                onClick={() => void send()}
              >
                <ArrowUp size={24} strokeWidth={3} />
              </Button>
            </div>
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
    </Shell>
  );
}
