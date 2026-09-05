import { CalendarBlank, CalendarCheck, Check, Clock, Heart, User } from "@phosphor-icons/react";
import { type ReactNode, useId } from "react";
import type { RequestType } from "../../api/types";
import { Badge, fieldClass } from "../../components/ui";
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
    <label className="block text-[13px] font-medium text-cream">
      Request type
      <select
        className={`${fieldClass} mt-2`}
        value={type}
        required
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
  const returnErrorId = useId();
  const hoursErrorId = useId();
  const update = (patch: Partial<typeof values>) => {
    form.update(patch);
    onInteraction();
  };

  return (
    <>
      <label className="block text-[13px] font-medium text-cream">
        First day away *
        <input
          className={`${fieldClass} mt-2`}
          type="date"
          required
          value={values.start}
          onChange={(event) => {
            form.changeStart(event.target.value);
            onInteraction();
          }}
        />
      </label>

      <fieldset>
        <legend className="text-[13px] font-medium text-cream">Expected back *</legend>
        <div className="mt-2 grid grid-cols-3 gap-2">
          <ChoiceButton
            active={values.returnMode === "default"}
            onClick={() => update({ returnMode: "default" })}
            icon={<CalendarCheck size={18} />}
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
            icon={<CalendarBlank size={18} />}
          >
            Pick date
          </ChoiceButton>
          <ChoiceButton
            active={values.returnMode === "unknown"}
            onClick={() => update({ returnMode: "unknown" })}
            icon={<Clock size={18} />}
          >
            Not sure
          </ChoiceButton>
        </div>
        {values.returnMode === "date" && (
          <input
            aria-label="Expected return date"
            aria-invalid={!form.returnIsValid}
            aria-describedby={!form.returnIsValid ? returnErrorId : undefined}
            className={`${fieldClass} mt-3`}
            type="date"
            min={values.start || undefined}
            value={values.customReturn}
            onChange={(event) => update({ customReturn: event.target.value })}
          />
        )}
        {!form.returnIsValid && (
          <p id={returnErrorId} role="status" className="mt-2 text-xs text-danger">
            {values.timeAway === "full_day"
              ? "Choose a return date after the first day away."
              : "Expected return cannot be before the first day away."}
          </p>
        )}
      </fieldset>

      <fieldset>
        <legend className="text-[13px] font-medium text-cream">Time away *</legend>
        <div className="mt-2 grid grid-cols-2 gap-2">
          <ChoiceButton
            active={values.timeAway === "full_day"}
            onClick={() => update({ timeAway: "full_day" })}
            icon={<Heart size={18} />}
          >
            Full day
          </ChoiceButton>
          <ChoiceButton
            active={values.timeAway === "partial_day"}
            onClick={() => update({ timeAway: "partial_day" })}
            icon={<Clock size={18} />}
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
              aria-invalid={!form.hoursAreValid}
              aria-describedby={!form.hoursAreValid ? hoursErrorId : undefined}
              onChange={(event) => update({ partialHours: event.target.value })}
            />
            {!form.hoursAreValid && (
              <span id={hoursErrorId} role="status" className="mt-2 block text-xs text-danger">
                Enter a number of hours greater than 0 and up to 24.
              </span>
            )}
          </label>
        )}
      </fieldset>

      <label className="block text-[13px] font-medium text-cream">
        Team note <span className="font-normal">(optional)</span>
        <textarea
          className={`${fieldClass} mt-2 min-h-24 resize-y`}
          value={values.comment}
          onChange={(event) => update({ comment: event.target.value })}
          placeholder="Availability or handoff context."
        />
      </label>

      <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-line px-3.5 py-3">
        <input
          type="checkbox"
          checked={values.extendedOrRecurring}
          onChange={(event) => update({ extendedOrRecurring: event.target.checked })}
          className="focus-ring mt-0.5 h-4 w-4 shrink-0 accent-accent"
        />
        <span>
          <span className="block text-sm text-cream">This may be extended or recurring</span>
          <span className="mt-1 block text-xs leading-5 text-muted">
            Ask People Ops to follow up.
          </span>
        </span>
      </label>

      <section
        aria-label="Report preview"
        className="grid grid-cols-2 gap-4 rounded-lg border border-line bg-ink p-4 text-xs"
      >
        <Summary
          icon={<CalendarBlank size={18} />}
          label="First day"
          value={formatRequestDate(values.start || null)}
        />
        <Summary
          icon={<CalendarCheck size={18} />}
          label="Expected back"
          value={
            values.returnMode === "unknown"
              ? "Not sure yet"
              : formatRequestDate(form.expectedReturn)
          }
        />
        <Summary
          icon={<Clock size={18} />}
          label="Time away"
          value={
            values.timeAway === "partial_day" ? `${values.partialHours || "—"} hours` : "Full day"
          }
        />
        <Summary icon={<User size={18} />} label="Goes to" value="Your manager" />
      </section>
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
  const datesErrorId = useId();
  const datesInvalid = Boolean(values.start && values.end && values.end < values.start);
  const update = (patch: Partial<typeof values>) => {
    form.update(patch);
    onInteraction();
  };

  return (
    <>
      <fieldset>
        <legend className="text-[13px] font-medium text-cream">When will you be away? *</legend>
        <p className="mt-1 text-xs leading-5 text-muted">
          Choose the first and last calendar day of your time off.
        </p>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="text-[13px] font-medium text-cream">
            First day
            <input
              className={`${fieldClass} mt-2`}
              type="date"
              required
              value={values.start}
              onChange={(event) => {
                form.changeStart(event.target.value);
                onInteraction();
              }}
            />
          </label>
          <label className="text-[13px] font-medium text-cream">
            Last day
            <input
              className={`${fieldClass} mt-2`}
              type="date"
              required
              min={values.start || undefined}
              value={values.end}
              aria-invalid={datesInvalid}
              aria-describedby={datesInvalid ? datesErrorId : undefined}
              onChange={(event) => update({ end: event.target.value })}
            />
          </label>
        </div>
        {datesInvalid && (
          <p id={datesErrorId} role="status" className="mt-2 text-xs text-danger">
            The last day cannot be before the first day.
          </p>
        )}

        <div className="mt-4 flex items-end justify-between gap-3">
          <div>
            <p className="text-[13px] font-medium text-cream">Quick length</p>
            <p className="mt-1 text-xs text-muted">
              {values.start
                ? "Counted from your first day."
                : "Choose a first day to use a shortcut."}
            </p>
          </div>
          <span className="shrink-0 text-xs text-muted">Calendar days</span>
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

      <label className="block text-[13px] font-medium text-cream">
        Planning note *
        <span className="mt-1 block text-xs font-normal leading-5">
          Keep it brief — timing or handoff context is enough.
        </span>
        <textarea
          className={`${fieldClass} mt-2 min-h-24 resize-y`}
          value={values.comment}
          required
          onChange={(event) => update({ comment: event.target.value })}
          placeholder="For example: Planned time off — I’ll hand over current work before I go."
        />
      </label>

      <section
        aria-label="Request preview"
        className="overflow-hidden rounded-lg border border-line bg-ink"
      >
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          <div>
            <h3 className="text-sm font-medium text-cream">Request preview</h3>
            <p className="mt-1 text-xs text-muted">This is what your manager will review.</p>
          </div>
          <Badge tone={form.formIsReady ? "success" : "neutral"}>
            {form.formIsReady ? "ready" : "draft"}
          </Badge>
        </div>
        <div className="grid grid-cols-2 gap-4 p-4 text-xs">
          <div className="col-span-2">
            <Summary
              icon={<CalendarBlank size={18} />}
              label="Dates"
              value={
                form.ptoDatesAreValid
                  ? `${formatRequestDate(values.start)} → ${formatRequestDate(values.end)}`
                  : "Not set"
              }
            />
          </div>
          <Summary
            icon={<Clock size={18} />}
            label="Time away"
            value={
              form.duration
                ? `${form.duration} calendar ${form.duration === 1 ? "day" : "days"}`
                : "—"
            }
          />
          <Summary icon={<Check size={18} />} label="Next step" value="Manager review" />
        </div>
      </section>
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
      className={`focus-ring flex min-h-11 items-center justify-center gap-2 rounded-lg border px-3 py-2 text-left text-[13px] transition ${active ? "border-accent/45 bg-accent-soft text-cream" : "border-line bg-panel text-muted hover:border-accent/25 hover:text-cream"}`}
    >
      <span className={active ? "text-accent" : "text-muted"}>{icon}</span>
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
      className={`focus-ring rounded-lg border px-3 py-2 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-35 ${active ? "border-accent/45 bg-accent-soft text-accent" : "border-line bg-panel text-muted hover:border-accent/25 hover:text-cream"}`}
    >
      {label}
    </button>
  );
}

function Summary({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="flex gap-2 text-muted">
      <span className="text-accent">{icon}</span>
      <div className="min-w-0">
        <span className="block text-xs">{label}</span>
        <span className="mt-1 block break-words text-sm text-cream">{value}</span>
      </div>
    </div>
  );
}
