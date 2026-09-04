import { CalendarCheck2, CalendarDays, Check, Clock3, HeartPulse, UserRound } from "lucide-react";
import type { ReactNode } from "react";
import type { RequestType } from "../../api/types";
import { Badge, Card, fieldClass } from "../../components/ui";
import type { useRequestForm } from "./requestFormState";
import { formatRequestDate } from "./requestPresentation";

type RequestFormModel = ReturnType<typeof useRequestForm>;

export function RequestTypeField({
  type,
  onChange,
}: {
  type: RequestType;
  onChange: (type: RequestType) => void;
}) {
  return (
    <label className="block text-xs font-semibold text-muted">
      What do you need? *
      <select
        className={`${fieldClass} mt-2`}
        value={type}
        onChange={(event) => {
          const value = event.target.value;
          if (value === "pto" || value === "sick_leave") onChange(value);
        }}
      >
        <option value="pto">Vacation / PTO</option>
        <option value="sick_leave">Sick leave</option>
      </select>
    </label>
  );
}

export function SickLeaveFields({
  form,
  onInteraction,
}: {
  form: RequestFormModel;
  onInteraction: () => void;
}) {
  const { values } = form;
  const update = (patch: Partial<typeof values>) => {
    form.update(patch);
    onInteraction();
  };

  return (
    <>
      <label className="block text-xs font-semibold text-muted">
        First day away *
        <input
          className={`${fieldClass} mt-2`}
          type="date"
          value={values.start}
          onChange={(event) => {
            form.changeStart(event.target.value);
            onInteraction();
          }}
        />
      </label>

      <fieldset>
        <legend className="text-xs font-semibold text-muted">Expected back *</legend>
        <div className="mt-2 grid grid-cols-3 gap-2">
          <ChoiceButton
            active={values.returnMode === "default"}
            onClick={() => update({ returnMode: "default" })}
            icon={<CalendarCheck2 size={16} />}
          >
            {values.timeAway === "partial_day" ? "Same day" : "Next day"}
          </ChoiceButton>
          <ChoiceButton
            active={values.returnMode === "date"}
            onClick={() =>
              update({
                returnMode: "date",
                customReturn: values.customReturn || form.defaultReturn,
              })
            }
            icon={<CalendarDays size={16} />}
          >
            Pick date
          </ChoiceButton>
          <ChoiceButton
            active={values.returnMode === "unknown"}
            onClick={() => update({ returnMode: "unknown" })}
            icon={<Clock3 size={16} />}
          >
            Not sure
          </ChoiceButton>
        </div>
        {values.returnMode === "date" && (
          <input
            aria-label="Expected return date"
            className={`${fieldClass} mt-3`}
            type="date"
            min={values.start || undefined}
            value={values.customReturn}
            onChange={(event) => update({ customReturn: event.target.value })}
          />
        )}
        {!form.returnIsValid && (
          <p className="mt-2 text-xs text-danger">
            {values.timeAway === "full_day"
              ? "Choose a return date after the first day away."
              : "Expected return cannot be before the first day away."}
          </p>
        )}
      </fieldset>

      <fieldset>
        <legend className="text-xs font-semibold text-muted">Time away *</legend>
        <div className="mt-2 grid grid-cols-2 gap-2">
          <ChoiceButton
            active={values.timeAway === "full_day"}
            onClick={() => update({ timeAway: "full_day" })}
            icon={<HeartPulse size={16} />}
          >
            Full day
          </ChoiceButton>
          <ChoiceButton
            active={values.timeAway === "partial_day"}
            onClick={() => update({ timeAway: "partial_day" })}
            icon={<Clock3 size={16} />}
          >
            Part of day
          </ChoiceButton>
        </div>
        {values.timeAway === "partial_day" && (
          <label className="mt-3 block text-xs text-muted">
            Approximate hours
            <input
              className={`${fieldClass} mt-2`}
              type="number"
              min="0.5"
              max="24"
              step="0.5"
              value={values.partialHours}
              onChange={(event) => update({ partialHours: event.target.value })}
            />
          </label>
        )}
      </fieldset>

      <label className="block text-xs font-semibold text-muted">
        Team note <span className="font-normal">(optional)</span>
        <textarea
          className={`${fieldClass} mt-2 min-h-24 resize-none`}
          value={values.comment}
          onChange={(event) => update({ comment: event.target.value })}
          placeholder="Availability or handoff context."
        />
      </label>

      <button
        type="button"
        role="switch"
        aria-checked={values.extendedOrRecurring}
        onClick={() => update({ extendedOrRecurring: !values.extendedOrRecurring })}
        className="focus-ring flex w-full items-center justify-between gap-4 rounded-2xl border border-line bg-ink/45 p-4 text-left transition hover:border-lime/25 hover:bg-raised"
      >
        <span>
          <strong className="block text-sm text-cream">This may be extended or recurring</strong>
          <span className="mt-1 block text-xs leading-5 text-muted">
            Flags a People Ops follow-up.
          </span>
        </span>
        <span
          className={`relative h-7 w-12 shrink-0 rounded-full border transition ${values.extendedOrRecurring ? "border-lime/40 bg-lime" : "border-line bg-panel"}`}
        >
          <span
            className={`absolute top-1 h-[18px] w-[18px] rounded-full transition ${values.extendedOrRecurring ? "left-[25px] bg-ink" : "left-1 bg-muted"}`}
          />
        </span>
      </button>

      <Card className="grid grid-cols-2 gap-4 bg-ink/50 p-4 text-xs">
        <Summary
          icon={<CalendarDays size={16} />}
          label="First day"
          value={formatRequestDate(values.start || null)}
        />
        <Summary
          icon={<CalendarCheck2 size={16} />}
          label="Expected back"
          value={
            values.returnMode === "unknown"
              ? "Not sure yet"
              : formatRequestDate(form.expectedReturn)
          }
        />
        <Summary
          icon={<Clock3 size={16} />}
          label="Time away"
          value={
            values.timeAway === "partial_day" ? `${values.partialHours || "—"} hours` : "Full day"
          }
        />
        <Summary icon={<UserRound size={16} />} label="Goes to" value="Your manager" />
      </Card>
    </>
  );
}

export function PtoFields({
  form,
  onInteraction,
}: {
  form: RequestFormModel;
  onInteraction: () => void;
}) {
  const { values } = form;
  const update = (patch: Partial<typeof values>) => {
    form.update(patch);
    onInteraction();
  };

  return (
    <>
      <fieldset>
        <legend className="text-xs font-semibold text-muted">When will you be away? *</legend>
        <p className="mt-1 text-[11px] leading-5 text-muted">
          Choose the first and last calendar day of your time off.
        </p>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="text-xs font-semibold text-muted">
            First day
            <input
              className={`${fieldClass} mt-2`}
              type="date"
              value={values.start}
              onChange={(event) => {
                form.changeStart(event.target.value);
                onInteraction();
              }}
            />
          </label>
          <label className="text-xs font-semibold text-muted">
            Last day
            <input
              className={`${fieldClass} mt-2`}
              type="date"
              min={values.start || undefined}
              value={values.end}
              onChange={(event) => update({ end: event.target.value })}
            />
          </label>
        </div>
        {values.start && values.end && values.end < values.start && (
          <p className="mt-2 text-xs text-danger">The last day cannot be before the first day.</p>
        )}

        <div className="mt-4 flex items-end justify-between gap-3">
          <div>
            <p className="text-xs font-semibold text-muted">Quick length</p>
            <p className="mt-1 text-[11px] text-muted">
              {values.start
                ? "Counted from your first day."
                : "Choose a first day to use a shortcut."}
            </p>
          </div>
          <span className="shrink-0 text-[10px] uppercase tracking-wider text-muted">
            Calendar days
          </span>
        </div>
        <div className="mt-2 grid grid-cols-3 gap-2">
          {[1, 3, 7].map((days) => (
            <QuickLengthButton
              key={days}
              active={form.duration === days}
              disabled={!values.start}
              label={days === 7 ? "1 week" : `${days} ${days === 1 ? "day" : "days"}`}
              onClick={() => {
                form.choosePtoLength(days);
                onInteraction();
              }}
            />
          ))}
        </div>
      </fieldset>

      <label className="block text-xs font-semibold text-muted">
        Planning note *
        <span className="mt-1 block text-[11px] font-normal leading-5">
          Keep it brief — timing or handoff context is enough.
        </span>
        <textarea
          className={`${fieldClass} mt-2 min-h-24 resize-none`}
          value={values.comment}
          onChange={(event) => update({ comment: event.target.value })}
          placeholder="For example: Planned time off — I’ll hand over current work before I go."
        />
      </label>

      <Card className="overflow-hidden bg-ink/50 p-0">
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          <div>
            <p className="text-xs font-semibold text-cream">Request preview</p>
            <p className="mt-1 text-[11px] text-muted">This is what your manager will review.</p>
          </div>
          <Badge tone={form.formIsReady ? "success" : "neutral"}>
            {form.formIsReady ? "ready" : "draft"}
          </Badge>
        </div>
        <div className="grid grid-cols-2 gap-4 p-4 text-xs">
          <div className="col-span-2">
            <Summary
              icon={<CalendarDays size={16} />}
              label="Dates"
              value={
                form.ptoDatesAreValid
                  ? `${formatRequestDate(values.start)} → ${formatRequestDate(values.end)}`
                  : "Not set"
              }
            />
          </div>
          <Summary
            icon={<Clock3 size={16} />}
            label="Time away"
            value={
              form.duration
                ? `${form.duration} calendar ${form.duration === 1 ? "day" : "days"}`
                : "—"
            }
          />
          <Summary icon={<Check size={16} />} label="Next step" value="Manager review" />
        </div>
      </Card>
    </>
  );
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
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`focus-ring flex min-h-16 flex-col items-start justify-center gap-1 rounded-xl border px-3 py-2 text-left text-xs font-semibold transition ${active ? "border-lime/45 bg-lime-soft text-cream" : "border-line bg-ink/55 text-muted hover:border-lime/25 hover:text-cream"}`}
    >
      <span className={active ? "text-lime" : "text-muted"}>{icon}</span>
      {children}
    </button>
  );
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
  return (
    <button
      type="button"
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      className={`focus-ring rounded-xl border px-3 py-2 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-35 ${active ? "border-lime/45 bg-lime-soft text-lime" : "border-line bg-ink/55 text-muted hover:border-lime/25 hover:text-cream"}`}
    >
      {label}
    </button>
  );
}

function Summary({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="flex gap-2 text-muted">
      <span className="text-lime">{icon}</span>
      <div className="min-w-0">
        <span className="block text-[10px] uppercase tracking-wider">{label}</span>
        <strong className="mt-1 block break-words text-cream">{value}</strong>
      </div>
    </div>
  );
}
