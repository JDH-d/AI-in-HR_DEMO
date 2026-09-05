import {
  ArrowsClockwise,
  BookOpen,
  CheckCircle,
  MagnifyingGlass,
  ShieldCheck,
  ThumbsDown,
  ThumbsUp,
  Warning,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { api } from "../../api/client";
import type { FeedbackItem, KnowledgeGap, Metrics } from "../../api/types";
import { useAuth } from "../../app/providers";
import { Badge, Button, Card, Drawer, fieldClass } from "../../components/ui";

type QualityMode = "negative" | "gaps" | "positive";

export function QualityPanel({
  metrics,
  onAddSource,
}: {
  metrics?: Metrics;
  onAddSource: () => void;
}) {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<QualityMode>("negative");
  const [search, setSearch] = useState("");
  const [selectedFeedback, setSelectedFeedback] = useState<FeedbackItem | null>(null);
  const [selectedGap, setSelectedGap] = useState<KnowledgeGap | null>(null);
  const feedback = useQuery({
    queryKey: ["admin-feedback"],
    queryFn: () =>
      api<{ feedback: FeedbackItem[] }>("/api/v1/admin/feedback?sentiment=all&limit=500", token),
  });
  const gaps = useQuery({
    queryKey: ["knowledge-gaps"],
    queryFn: () => api<{ questions: KnowledgeGap[] }>("/api/v1/admin/unanswered", token),
  });
  const reviewGap = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "resolved" | "ignored" }) =>
      api(`/api/v1/admin/quality/${id}`, token, {
        method: "POST",
        body: JSON.stringify({ action }),
      }),
    onSuccess: () => {
      setSelectedGap(null);
      void queryClient.invalidateQueries({ queryKey: ["knowledge-gaps"] });
      void queryClient.invalidateQueries({ queryKey: ["metrics"] });
    },
  });
  const feedbackItems = feedback.data?.feedback ?? [];
  const gapItems = gaps.data?.questions ?? [];
  const counts = {
    positive: feedbackItems.filter((item) => item.sentiment === "positive").length,
    negative: feedbackItems.filter((item) => item.sentiment === "negative").length,
    gaps: gapItems.length,
  };
  const needle = search.trim().toLowerCase();
  const visibleFeedback = feedbackItems.filter(
    (item) =>
      item.sentiment === mode &&
      (!needle || `${item.question} ${item.answer} ${item.comment}`.toLowerCase().includes(needle)),
  );
  const visibleGaps = gapItems.filter(
    (item) => !needle || `${item.question} ${item.assistant}`.toLowerCase().includes(needle),
  );
  const loading = feedback.isLoading || gaps.isLoading;
  const failed = feedback.isError || gaps.isError;
  const empty = mode === "gaps" ? visibleGaps.length === 0 : visibleFeedback.length === 0;

  return (
    <div className="space-y-5">
      <div className="grid gap-3 md:grid-cols-3">
        <QualityMetric
          label="Helpful rate"
          value={metrics ? `${metrics.positive_feedback_rate}%` : "—"}
          copy="Share of all ratings marked helpful"
          tone="success"
        />
        <QualityMetric
          label="Needs review"
          value={feedback.data ? counts.negative : "—"}
          copy="Rated answers that may need a fix"
          tone="danger"
        />
        <QualityMetric
          label="Knowledge gaps"
          value={gaps.data ? counts.gaps : "—"}
          copy="Workplace questions with no reliable source"
          tone="warning"
        />
      </div>

      <Card className="overflow-hidden p-0">
        <div className="border-b border-line px-5 py-4">
          <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center">
            <div>
              <h2 className="text-sm font-semibold">Answer quality queue</h2>
              <p className="mt-1 text-sm text-muted">
                Employee feedback and questions missing a company source.
              </p>
            </div>
            <Button
              tone="secondary"
              onClick={() => {
                void feedback.refetch();
                void gaps.refetch();
              }}
              disabled={feedback.isFetching || gaps.isFetching}
            >
              <ArrowsClockwise
                size={18}
                className={feedback.isFetching || gaps.isFetching ? "animate-spin" : ""}
              />
              Refresh
            </Button>
          </div>
          <div className="mt-4 flex flex-col gap-3 xl:flex-row">
            <div className="flex flex-wrap gap-1 rounded-lg bg-ink p-1">
              <QualityTab active={mode === "negative"} onClick={() => setMode("negative")}>
                <ThumbsDown size={18} />
                Needs review · {counts.negative}
              </QualityTab>
              <QualityTab active={mode === "gaps"} onClick={() => setMode("gaps")}>
                <Warning size={18} />
                Knowledge gaps · {counts.gaps}
              </QualityTab>
              <QualityTab active={mode === "positive"} onClick={() => setMode("positive")}>
                <ThumbsUp size={18} />
                Helpful · {counts.positive}
              </QualityTab>
            </div>
            <label className="relative flex-1">
              <span className="sr-only">Search quality signals</span>
              <MagnifyingGlass
                className="absolute left-3 top-1/2 -translate-y-1/2 text-muted"
                size={18}
              />
              <input
                className={`${fieldClass} pl-10`}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search questions, answers, or notes"
              />
            </label>
          </div>
        </div>

        {loading && (
          <div className="grid min-h-56 place-items-center text-sm text-muted">
            Loading quality signals…
          </div>
        )}
        {!loading && failed && (
          <QualityErrorState
            onRetry={() => {
              void feedback.refetch();
              void gaps.refetch();
            }}
          />
        )}
        {!loading && !failed && empty && (
          <EmptyQualityState
            title={
              mode === "negative"
                ? "No answers need review"
                : mode === "gaps"
                  ? "No active knowledge gaps"
                  : "No helpful examples yet"
            }
            copy={
              search
                ? "Try a different search."
                : "New quality signals will appear here automatically."
            }
          />
        )}
        {!loading && !failed && (
          <div className="divide-y divide-line">
            {mode === "gaps"
              ? visibleGaps.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSelectedGap(item)}
                    className="focus-ring grid w-full gap-4 p-5 text-left transition hover:bg-raised/60 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_140px]"
                  >
                    <div>
                      <p className="text-xs font-medium text-muted">Employee question</p>
                      <p className="mt-2 line-clamp-3 text-sm font-semibold leading-6">
                        {item.question}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs font-medium text-muted">Assistant response</p>
                      <p className="mt-2 line-clamp-3 text-sm leading-6 text-muted">
                        {item.assistant}
                      </p>
                    </div>
                    <div className="lg:text-right">
                      <Badge tone="warning">Knowledge gap</Badge>
                      <p className="mt-2 text-xs text-muted">
                        {new Date(item.timestamp).toLocaleString()}
                      </p>
                    </div>
                  </button>
                ))
              : visibleFeedback.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSelectedFeedback(item)}
                    className="focus-ring grid w-full gap-4 p-5 text-left transition hover:bg-raised/60 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_140px]"
                  >
                    <div>
                      <p className="text-xs font-medium text-muted">Employee question</p>
                      <p className="mt-2 line-clamp-3 text-sm font-semibold leading-6">
                        {item.question || "Question was not captured"}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs font-medium text-muted">AI answer</p>
                      <p className="mt-2 line-clamp-3 text-sm leading-6 text-muted">
                        {item.answer || "Answer was not captured for this older feedback signal."}
                      </p>
                      {item.comment && (
                        <p className="mt-3 line-clamp-2 border-l-2 border-line pl-3 text-sm text-cream">
                          “{item.comment}”
                        </p>
                      )}
                    </div>
                    <div className="flex items-start justify-between gap-3 lg:block lg:text-right">
                      <Badge tone={item.sentiment === "positive" ? "success" : "danger"}>
                        {item.sentiment === "positive" ? "Helpful" : "Needs review"}
                      </Badge>
                      <p className="mt-2 text-xs text-muted">
                        {new Date(item.created_at).toLocaleString()}
                      </p>
                      <p className="mt-2 text-xs font-medium text-muted">Anonymous</p>
                    </div>
                  </button>
                ))}
          </div>
        )}
      </Card>

      <Drawer
        open={Boolean(selectedFeedback)}
        onOpenChange={(open) => !open && setSelectedFeedback(null)}
        title="Response feedback"
        description="An anonymized view of the exact exchange the employee rated."
        placement="center"
      >
        {selectedFeedback && (
          <div className="space-y-5">
            <div className="flex items-center justify-between">
              <Badge tone={selectedFeedback.sentiment === "positive" ? "success" : "danger"}>
                {selectedFeedback.sentiment === "positive" ? "Helpful" : "Needs review"}
              </Badge>
              <span className="flex items-center gap-2 text-xs text-muted">
                <ShieldCheck size={18} />
                Anonymous
              </span>
            </div>
            <ConversationBlock
              label="Employee question"
              text={selectedFeedback.question || "Question was not captured."}
              kind="question"
            />
            <ConversationBlock
              label="PeopleFlow answer"
              text={
                selectedFeedback.answer || "Answer was not captured for this older feedback signal."
              }
              kind="answer"
            />
            {selectedFeedback.comment && (
              <section className="rounded-lg border border-line bg-ink p-4">
                <p className="text-xs font-medium text-muted">Employee note</p>
                <p className="mt-3 whitespace-pre-wrap text-sm leading-6">
                  {selectedFeedback.comment}
                </p>
              </section>
            )}
            <p className="text-right text-xs text-muted">
              Received {new Date(selectedFeedback.created_at).toLocaleString()}
            </p>
          </div>
        )}
      </Drawer>

      <Drawer
        open={Boolean(selectedGap)}
        onOpenChange={(open) => !open && setSelectedGap(null)}
        title="Knowledge gap"
        description="A supported workplace question that could not be grounded in the current source library."
        placement="center"
      >
        {selectedGap && (
          <div className="space-y-5">
            <Badge tone="warning">Needs a source</Badge>
            <ConversationBlock
              label="Employee question"
              text={selectedGap.question}
              kind="question"
            />
            <ConversationBlock
              label="PeopleFlow response"
              text={selectedGap.assistant}
              kind="answer"
            />
            {reviewGap.isError && (
              <p className="text-sm text-danger">
                {reviewGap.error instanceof Error
                  ? reviewGap.error.message
                  : "Unable to update this item"}
              </p>
            )}
            <div className="flex flex-wrap justify-end gap-3">
              <Button
                tone="ghost"
                onClick={() => reviewGap.mutate({ id: selectedGap.id, action: "ignored" })}
                disabled={reviewGap.isPending}
              >
                Ignore
              </Button>
              <Button
                tone="secondary"
                onClick={() => {
                  setSelectedGap(null);
                  onAddSource();
                }}
              >
                <BookOpen size={18} />
                Add source
              </Button>
              <Button
                onClick={() => reviewGap.mutate({ id: selectedGap.id, action: "resolved" })}
                disabled={reviewGap.isPending}
              >
                <CheckCircle size={18} />
                Mark resolved
              </Button>
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}

function QualityMetric({
  label,
  value,
  copy,
  tone,
}: {
  label: string;
  value: string | number;
  copy: string;
  tone: "success" | "warning" | "danger";
}) {
  const color =
    tone === "success" ? "text-success" : tone === "warning" ? "text-warning" : "text-danger";
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium">{label}</p>
        <strong className={`text-xl font-semibold tabular-nums ${color}`}>{value}</strong>
      </div>
      <p className="mt-1 text-sm text-muted">{copy}</p>
    </Card>
  );
}

function QualityTab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`focus-ring flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm whitespace-nowrap ${active ? "bg-panel font-medium text-accent shadow-sm" : "text-muted hover:bg-panel/60 hover:text-cream"}`}
    >
      {children}
    </button>
  );
}

function ConversationBlock({
  label,
  text,
  kind,
}: {
  label: string;
  text: string;
  kind: "question" | "answer";
}) {
  return (
    <section
      className={`rounded-lg border border-line p-4 ${kind === "question" ? "bg-ink" : "bg-panel"}`}
    >
      <p className="text-xs font-medium text-muted">{label}</p>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-cream">{text}</p>
    </section>
  );
}

function EmptyQualityState({ title, copy }: { title: string; copy: string }) {
  return (
    <div className="grid min-h-56 place-items-center p-6 text-center">
      <div>
        <CheckCircle className="mx-auto text-muted" size={24} />
        <h3 className="mt-3 font-semibold">{title}</h3>
        <p className="mt-2 text-sm text-muted">{copy}</p>
      </div>
    </div>
  );
}

function QualityErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="grid min-h-56 place-items-center p-6 text-center">
      <div>
        <Warning className="mx-auto text-danger" />
        <h3 className="mt-3 font-semibold">Unable to load quality signals</h3>
        <p className="mt-2 text-sm text-muted">The review queue could not be retrieved.</p>
        <Button className="mt-5" tone="secondary" onClick={onRetry}>
          <ArrowsClockwise size={18} />
          Try again
        </Button>
      </div>
    </div>
  );
}
