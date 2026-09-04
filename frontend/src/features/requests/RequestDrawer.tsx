import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CalendarCheck2,
  CalendarDays,
  Check,
  Clock3,
  HeartPulse,
  UserRound,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import type { WorkflowRequest } from "../../api/types";
import { useAuth } from "../../app/providers";
import {
  Badge,
  Button,
  Card,
  Drawer,
  fieldClass,
  formatStatus,
  statusTone,
} from "../../components/ui";
import {
  addIsoDays,
  formatRequestDate,
  getSickLeaveDetails,
  todayIso,
  type SickTimeAway,
} from "./requestPresentation";

type RequestType = WorkflowRequest["type"];
type ReturnMode = "default" | "date" | "unknown";

export function RequestDrawer({
  open,
  onOpenChange,
  initial,
}: {
  open: boolean;
  onOpenChange: (value: boolean) => void;
  initial?: WorkflowRequest | null;
}) {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  const [type, setType] = useState<RequestType>("pto");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [comment, setComment] = useState("");
  const [returnMode, setReturnMode] = useState<ReturnMode>("default");
  const [customReturn, setCustomReturn] = useState("");
  const [timeAway, setTimeAway] = useState<SickTimeAway>("full_day");
  const [partialHours, setPartialHours] = useState("4");
  const [extendedOrRecurring, setExtendedOrRecurring] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    setSubmitted(false);
    if (!initial) {
      setType("pto");
      setStart("");
      setEnd("");
      setComment("");
      setReturnMode("default");
      setCustomReturn("");
      setTimeAway("full_day");
      setPartialHours("4");
      setExtendedOrRecurring(false);
      return;
    }

    setType(initial.type);
    setStart(initial.start_date ?? "");
    setEnd(initial.end_date ?? "");
    setComment(initial.comment);

    const sickLeave = getSickLeaveDetails(initial);
    setTimeAway(sickLeave.timeAway);
    setPartialHours(String(sickLeave.partialHours ?? 4));
    setExtendedOrRecurring(sickLeave.extendedOrRecurring);
    const defaultReturn = initial.start_date
      ? addIsoDays(initial.start_date, sickLeave.timeAway === "partial_day" ? 0 : 1)
      : "";
    if (sickLeave.expectedReturnUnknown) {
      setReturnMode("unknown");
      setCustomReturn("");
    } else if (!sickLeave.expectedReturnDate || sickLeave.expectedReturnDate === defaultReturn) {
      setReturnMode("default");
      setCustomReturn("");
    } else {
      setReturnMode("date");
      setCustomReturn(sickLeave.expectedReturnDate);
    }
  }, [initial, open]);

  useEffect(() => {
    if (!submitted) return;
    const closeTimer = window.setTimeout(() => onOpenChange(false), 2600);
    return () => window.clearTimeout(closeTimer);
  }, [onOpenChange, submitted]);

  const isSickLeave = type === "sick_leave";
  const defaultReturn = start ? addIsoDays(start, timeAway === "partial_day" ? 0 : 1) : "";
  const expectedReturn = returnMode === "unknown"
    ? null
    : returnMode === "default"
      ? defaultReturn
      : customReturn || null;
  const sickLeaveEnd = start && expectedReturn
    ? [start, addIsoDays(expectedReturn, -1)].sort().at(-1) ?? start
    : null;
  const parsedHours = Number(partialHours);
  const returnIsValid = returnMode === "unknown" || Boolean(
    start
    && expectedReturn
    && (timeAway === "partial_day" ? expectedReturn >= start : expectedReturn > start),
  );
  const hoursAreValid = timeAway === "full_day"
    || (Number.isFinite(parsedHours) && parsedHours > 0 && parsedHours <= 24);
  const ptoDatesAreValid = Boolean(start && end && end >= start);
  const duration = ptoDatesAreValid
    ? Math.round((new Date(end).getTime() - new Date(start).getTime()) / 86400000) + 1
    : null;
  const formIsReady = isSickLeave
    ? Boolean(start && returnIsValid && hoursAreValid)
    : Boolean(comment.trim() && ptoDatesAreValid);

  const requestPayload = () => ({
    type,
    start_date: start || null,
    end_date: isSickLeave ? sickLeaveEnd : end || null,
    comment: comment.trim(),
    details: isSickLeave ? {
      expected_return_date: expectedReturn,
      expected_return_unknown: returnMode === "unknown",
      time_away: timeAway,
      partial_hours: timeAway === "partial_day" ? parsedHours : null,
      extended_or_recurring: extendedOrRecurring,
    } : {},
  });

  const choosePtoLength = (days: number) => {
    if (!start) return;
    setEnd(addIsoDays(start, days - 1));
    setError("");
  };

  const mutation = useMutation({
    mutationFn: async () => {
      let request = initial;
      const payload = requestPayload();
      if (!request) {
        const created = await api<{ request: WorkflowRequest }>("/api/v1/requests", token, {
          method: "POST",
          body: JSON.stringify(payload),
        });
        request = created.request;
      }
      return api<{ request: WorkflowRequest }>(`/api/v1/requests/${request.id}/submit`, token, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    onSuccess: result => {
      void queryClient.invalidateQueries({ queryKey: ["requests"] });
      if (result.request.type === "pto") {
        setSubmitted(true);
        return;
      }
      onOpenChange(false);
    },
    onError: requestError => setError(
      requestError instanceof Error ? requestError.message : "Unable to submit",
    ),
  });

  const title = isSickLeave
    ? initial ? "Review sick leave" : "Report sick leave"
    : initial ? "Review time off" : "Plan time off";
  const description = isSickLeave
    ? "Let your manager know when you will be away. This is a notification, not an approval request."
    : "Your manager only gets the dates and a short planning note. Nothing is sent until you confirm.";

  if (submitted) {
    return <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title="Request sent"
    >
      <PtoSuccess />
    </Drawer>;
  }

  return <Drawer
    open={open}
    onOpenChange={onOpenChange}
    title={title}
    description={description}
  >
    <div className="mb-6 flex items-center justify-between gap-3">
      <Badge tone={statusTone(initial?.status ?? "draft")}>
        {initial?.status ? formatStatus(initial.status) : isSickLeave ? "new report" : "new request"}
      </Badge>
      <span className="text-right text-xs text-muted">
        {isSickLeave
          ? "Only availability details are required"
          : "Dates and a short note are required"}
      </span>
    </div>

    <div className="space-y-5">
      <label className="block text-xs font-semibold text-muted">
        What do you need? *
        <select
          className={`${fieldClass} mt-2`}
          value={type}
          onChange={event => {
            const nextType = event.target.value as RequestType;
            setType(nextType);
            setError("");
            if (nextType === "sick_leave" && !start) setStart(todayIso());
          }}
        >
          <option value="pto">Vacation / PTO</option>
          <option value="sick_leave">Sick leave</option>
        </select>
      </label>

      {isSickLeave ? <>
        <label className="block text-xs font-semibold text-muted">
          First day away *
          <input
            className={`${fieldClass} mt-2`}
            type="date"
            value={start}
            onChange={event => setStart(event.target.value)}
          />
        </label>

        <fieldset>
          <legend className="text-xs font-semibold text-muted">Expected back *</legend>
          <div className="mt-2 grid grid-cols-3 gap-2">
            <ChoiceButton
              active={returnMode === "default"}
              onClick={() => setReturnMode("default")}
              icon={<CalendarCheck2 size={16} />}
            >
              {timeAway === "partial_day" ? "Same day" : "Next day"}
            </ChoiceButton>
            <ChoiceButton
              active={returnMode === "date"}
              onClick={() => {
                setReturnMode("date");
                if (!customReturn) setCustomReturn(defaultReturn);
              }}
              icon={<CalendarDays size={16} />}
            >
              Pick date
            </ChoiceButton>
            <ChoiceButton
              active={returnMode === "unknown"}
              onClick={() => setReturnMode("unknown")}
              icon={<Clock3 size={16} />}
            >
              Not sure
            </ChoiceButton>
          </div>
          {returnMode === "date" && <input
            aria-label="Expected return date"
            className={`${fieldClass} mt-3`}
            type="date"
            min={start || undefined}
            value={customReturn}
            onChange={event => setCustomReturn(event.target.value)}
          />}
          {!returnIsValid && <p className="mt-2 text-xs text-danger">
            {timeAway === "full_day"
              ? "Choose a return date after the first day away."
              : "Expected return cannot be before the first day away."}
          </p>}
        </fieldset>

        <fieldset>
          <legend className="text-xs font-semibold text-muted">Time away *</legend>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <ChoiceButton
              active={timeAway === "full_day"}
              onClick={() => setTimeAway("full_day")}
              icon={<HeartPulse size={16} />}
            >
              Full day
            </ChoiceButton>
            <ChoiceButton
              active={timeAway === "partial_day"}
              onClick={() => setTimeAway("partial_day")}
              icon={<Clock3 size={16} />}
            >
              Part of day
            </ChoiceButton>
          </div>
          {timeAway === "partial_day" && <label className="mt-3 block text-xs text-muted">
            Approximate hours
            <input
              className={`${fieldClass} mt-2`}
              type="number"
              min="0.5"
              max="24"
              step="0.5"
              value={partialHours}
              onChange={event => setPartialHours(event.target.value)}
            />
          </label>}
        </fieldset>

        <label className="block text-xs font-semibold text-muted">
          Team note <span className="font-normal">(optional)</span>
          <textarea
            className={`${fieldClass} mt-2 min-h-24 resize-none`}
            value={comment}
            onChange={event => setComment(event.target.value)}
            placeholder="Availability or handoff context."
          />
        </label>

        <button
          type="button"
          role="switch"
          aria-checked={extendedOrRecurring}
          onClick={() => setExtendedOrRecurring(value => !value)}
          className="focus-ring flex w-full items-center justify-between gap-4 rounded-2xl border border-line bg-ink/45 p-4 text-left transition hover:border-lime/25 hover:bg-raised"
        >
          <span>
            <strong className="block text-sm text-cream">This may be extended or recurring</strong>
            <span className="mt-1 block text-xs leading-5 text-muted">
              Flags a People Ops follow-up.
            </span>
          </span>
          <span className={`relative h-7 w-12 shrink-0 rounded-full border transition ${extendedOrRecurring ? "border-lime/40 bg-lime" : "border-line bg-panel"}`}>
            <span className={`absolute top-1 h-[18px] w-[18px] rounded-full transition ${extendedOrRecurring ? "left-[25px] bg-ink" : "left-1 bg-muted"}`} />
          </span>
        </button>

        <Card className="grid grid-cols-2 gap-4 bg-ink/50 p-4 text-xs">
          <Summary icon={<CalendarDays size={16} />} label="First day" value={formatRequestDate(start || null)} />
          <Summary
            icon={<CalendarCheck2 size={16} />}
            label="Expected back"
            value={returnMode === "unknown" ? "Not sure yet" : formatRequestDate(expectedReturn)}
          />
          <Summary
            icon={<Clock3 size={16} />}
            label="Time away"
            value={timeAway === "partial_day" ? `${partialHours || "—"} hours` : "Full day"}
          />
          <Summary icon={<UserRound size={16} />} label="Goes to" value="Your manager" />
        </Card>
      </> : <>
        <fieldset>
          <legend className="text-xs font-semibold text-muted">When will you be away? *</legend>
          <p className="mt-1 text-[11px] leading-5 text-muted">Choose the first and last calendar day of your time off.</p>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="text-xs font-semibold text-muted">
              First day
              <input
                className={`${fieldClass} mt-2`}
                type="date"
                value={start}
                onChange={event => {
                  const nextStart = event.target.value;
                  setStart(nextStart);
                  if (nextStart && (!end || end < nextStart)) setEnd(nextStart);
                  setError("");
                }}
              />
            </label>
            <label className="text-xs font-semibold text-muted">
              Last day
              <input
                className={`${fieldClass} mt-2`}
                type="date"
                min={start || undefined}
                value={end}
                onChange={event => {
                  setEnd(event.target.value);
                  setError("");
                }}
              />
            </label>
          </div>
          {start && end && end < start && <p className="mt-2 text-xs text-danger">
            The last day cannot be before the first day.
          </p>}

          <div className="mt-4 flex items-end justify-between gap-3">
            <div>
              <p className="text-xs font-semibold text-muted">Quick length</p>
              <p className="mt-1 text-[11px] text-muted">
                {start ? "Counted from your first day." : "Choose a first day to use a shortcut."}
              </p>
            </div>
            <span className="shrink-0 text-[10px] uppercase tracking-wider text-muted">Calendar days</span>
          </div>
          <div className="mt-2 grid grid-cols-3 gap-2">
            <QuickLengthButton
              active={duration === 1}
              disabled={!start}
              label="1 day"
              onClick={() => choosePtoLength(1)}
            />
            <QuickLengthButton
              active={duration === 3}
              disabled={!start}
              label="3 days"
              onClick={() => choosePtoLength(3)}
            />
            <QuickLengthButton
              active={duration === 7}
              disabled={!start}
              label="1 week"
              onClick={() => choosePtoLength(7)}
            />
          </div>
        </fieldset>

        <label className="block text-xs font-semibold text-muted">
          Planning note *
          <span className="mt-1 block text-[11px] font-normal leading-5">
            Keep it brief — timing or handoff context is enough.
          </span>
          <textarea
            className={`${fieldClass} mt-2 min-h-24 resize-none`}
            value={comment}
            onChange={event => {
              setComment(event.target.value);
              setError("");
            }}
            placeholder="For example: Planned time off — I’ll hand over current work before I go."
          />
        </label>

        <Card className="overflow-hidden bg-ink/50 p-0">
          <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
            <div>
              <p className="text-xs font-semibold text-cream">Request preview</p>
              <p className="mt-1 text-[11px] text-muted">This is what your manager will review.</p>
            </div>
            <Badge tone={formIsReady ? "success" : "neutral"}>{formIsReady ? "ready" : "draft"}</Badge>
          </div>
          <div className="grid grid-cols-2 gap-4 p-4 text-xs">
            <div className="col-span-2">
              <Summary
                icon={<CalendarDays size={16} />}
                label="Dates"
                value={ptoDatesAreValid
                  ? `${formatRequestDate(start)} → ${formatRequestDate(end)}`
                  : "Not set"}
              />
            </div>
            <Summary
              icon={<Clock3 size={16} />}
              label="Time away"
              value={duration ? `${duration} calendar ${duration === 1 ? "day" : "days"}` : "—"}
            />
            <Summary icon={<Check size={16} />} label="Next step" value="Manager review" />
          </div>
        </Card>
      </>}

      {error && <p className="rounded-xl bg-danger/10 p-3 text-sm text-danger">{error}</p>}
      <div className="flex gap-3">
        <Button tone="secondary" className="flex-1" onClick={() => onOpenChange(false)}>
          {initial ? "Keep as draft" : "Close"}
        </Button>
        <Button
          className="flex-1"
          disabled={mutation.isPending || !formIsReady}
          onClick={() => mutation.mutate()}
        >
          {mutation.isPending
            ? isSickLeave ? "Reporting…" : "Sending…"
            : isSickLeave ? "Report sick leave" : "Send for approval"}
        </Button>
      </div>
    </div>
  </Drawer>;
}

function ChoiceButton({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean;
  onClick: () => void;
  icon: ReactNode;
  children: ReactNode;
}) {
  return <button
    type="button"
    aria-pressed={active}
    onClick={onClick}
    className={`focus-ring flex min-h-16 flex-col items-start justify-center gap-1 rounded-xl border px-3 py-2 text-left text-xs font-semibold transition ${active ? "border-lime/45 bg-lime-soft text-cream" : "border-line bg-ink/55 text-muted hover:border-lime/25 hover:text-cream"}`}
  >
    <span className={active ? "text-lime" : "text-muted"}>{icon}</span>
    {children}
  </button>;
}

function QuickLengthButton({
  active,
  disabled,
  label,
  onClick,
}: {
  active: boolean;
  disabled: boolean;
  label: string;
  onClick: () => void;
}) {
  return <button
    type="button"
    aria-pressed={active}
    disabled={disabled}
    onClick={onClick}
    className={`focus-ring rounded-xl border px-3 py-2 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-35 ${active ? "border-lime/45 bg-lime-soft text-lime" : "border-line bg-ink/55 text-muted hover:border-lime/25 hover:text-cream"}`}
  >
    {label}
  </button>;
}

function PtoSuccess() {
  return <div
    className="request-success grid min-h-[360px] place-items-center py-10"
    role="status"
    aria-live="polite"
  >
    <div className="max-w-xs text-center">
      <div className="request-success-mark relative mx-auto grid h-20 w-20 place-items-center">
        <span className="request-success-halo absolute inset-0 rounded-full border border-lime/25" />
        <span className="relative grid h-14 w-14 place-items-center rounded-2xl bg-lime text-ink shadow-[0_12px_40px_rgba(201,244,91,.18)]">
          <Check size={28} strokeWidth={2.4} />
        </span>
      </div>
      <h3 className="mt-6 text-xl font-semibold leading-8 text-cream">
        We sent your request to your manager.
      </h3>
      <p className="mt-2 text-sm leading-6 text-muted">
        You can follow the decision in My requests.
      </p>
    </div>
  </div>;
}

function Summary({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return <div className="flex gap-2 text-muted">
    <span className="text-lime">{icon}</span>
    <div className="min-w-0">
      <span className="block text-[10px] uppercase tracking-wider">{label}</span>
      <strong className="mt-1 block break-words text-cream">{value}</strong>
    </div>
  </div>;
}
