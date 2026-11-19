import { useEffect, useRef, useState, type ReactNode } from "react";
import { CheckCircle2 } from "lucide-react";
import type { WorkflowRequest } from "../../api/types";
import { useRequestForm } from "./useRequestForm";
import { useRequestOptions } from "./useRequests";
import { useProtectedNavigation, useUnsavedChanges } from "../../components/UnsavedChanges";
import { requestLabel } from "./requestPresentation";
import { Badge, Button, Drawer, fieldClass, formatStatus, statusTone } from "../../components/ui";
import "./requests.css";
import "./request-wizard.css";

const steps = ["Details", "Timing", "Review"];
const categories: Record<string, string> = { pto: "Vacation / PTO", sick_leave: "Sick leave", document: "Document request" };
type SavedRequest = { request: WorkflowRequest; mode: "submit" | "save" };

function OptionalDateRange({ hasDates, children }: { hasDates: boolean; children: ReactNode }) {
  // Field edits must not collapse the section containing the focused input.
  const [expanded, setExpanded] = useState(hasDates);
  return <details open={expanded} onToggle={event => setExpanded(event.currentTarget.open)}>
    <summary className="focus-ring cursor-pointer rounded py-2 text-sm font-medium">Add an optional date range</summary>
    <div className="mt-2">{children}</div>
  </details>;
}

export function RequestDrawer({ open, onOpenChange, initial, onOpenRequest }: {
  open: boolean;
  onOpenChange: (value: boolean) => void;
  initial?: WorkflowRequest | null;
  onOpenRequest?: (id: string) => void;
}) {
  const [step, setStep] = useState(0);
  const [saved, setSaved] = useState<SavedRequest | null>(null);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const closeAfterSave = useRef(false);
  const fields = useRef<HTMLFieldSetElement>(null);
  const stepHeading = useRef<HTMLHeadingElement>(null);
  const errorNotice = useRef<HTMLParagraphElement>(null);
  const protect = useProtectedNavigation();
  const {
    title, setTitle, priority, setPriority, type, setType, start, setStart, end, setEnd,
    comment, setComment, approver, error, conflict, reviewLatest, duration, datesRequired,
    valid, dirty, mutation,
  } = useRequestForm(open, initial, (request, mode) => {
    clearUnsavedChanges();
    setDiscardOpen(false);
    if (closeAfterSave.current) onOpenChange(false);
    else setSaved({ request, mode });
    closeAfterSave.current = false;
  });
  const clearUnsavedChanges = useUnsavedChanges(open && dirty && !saved);
  const options = useRequestOptions();
  const managerName = options.data?.managers?.find(item => item.id === approver)?.display_name || approver;
  const detailsValid = title.trim().length >= 3 && comment.trim().length >= 3;
  const rangeInvalid = Boolean(start && end && end < start);
  const timingValid = (!datesRequired || Boolean(start && end)) && !rangeInvalid;
  const titleInvalid = (showErrors || Boolean(title)) && title.trim().length < 3;
  const descriptionInvalid = (showErrors || Boolean(comment)) && comment.trim().length < 3;

  useEffect(() => {
    setStep(0); setSaved(null); setDiscardOpen(false); setShowErrors(false); closeAfterSave.current = false;
  }, [open, initial?.id]);
  useEffect(() => {
    if (!open) return;
    const frame = requestAnimationFrame(() => stepHeading.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [open, step, saved]);
  useEffect(() => {
    if (error && !mutation.isPending && !discardOpen) errorNotice.current?.focus();
  }, [error, mutation.isPending, discardOpen]);

  const close = () => {
    if (mutation.isPending) return;
    if (dirty && !saved) setDiscardOpen(true); else onOpenChange(false);
  };
  const goTo = (next: number) => { setShowErrors(false); setStep(next); };
  const focusInvalid = () => requestAnimationFrame(() => fields.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus());
  const next = () => {
    if ((step === 0 && !detailsValid) || (step === 1 && !timingValid)) {
      setShowErrors(true); focusInvalid(); return;
    }
    goTo(step + 1);
  };
  const saveDraft = (andClose = false) => { closeAfterSave.current = andClose; mutation.mutate("save"); };
  const submit = () => {
    if (!valid) {
      setStep(!detailsValid ? 0 : !timingValid ? 1 : 2);
      setShowErrors(true); focusInvalid(); return;
    }
    closeAfterSave.current = false;
    mutation.mutate("submit");
  };
  const openSaved = () => {
    if (!saved) return;
    const id = saved.request.id;
    protect(() => {
      onOpenChange(false);
      if (onOpenRequest) onOpenRequest(id);
      else window.location.assign(`/requests?request=${encodeURIComponent(id)}`);
    });
  };
  const dateFields = <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
    <label className="text-sm font-medium">Starts {datesRequired && "*"}<input className={`${fieldClass} mt-1.5`} type="date" value={start} onChange={event => setStart(event.target.value)} aria-required={datesRequired} aria-invalid={rangeInvalid || (showErrors && datesRequired && !start)} aria-describedby={rangeInvalid || (showErrors && datesRequired && !start) ? "request-date-error" : undefined}/></label>
    <label className="text-sm font-medium">Ends {datesRequired && "*"}<input className={`${fieldClass} mt-1.5`} type="date" min={start || undefined} value={end} onChange={event => setEnd(event.target.value)} aria-required={datesRequired} aria-invalid={rangeInvalid || (showErrors && datesRequired && !end)} aria-describedby={rangeInvalid || (showErrors && datesRequired && !end) ? "request-date-error" : undefined}/></label>
    {(rangeInvalid || (showErrors && datesRequired && (!start || !end))) && <p id="request-date-error" role="alert" className="text-sm text-danger sm:col-span-2">{rangeInvalid ? "End date cannot be earlier than start date." : "Choose both a start and an end date."}</p>}
  </div>;
  const number = saved ? `REQ-${String(saved.request.number).padStart(6, "0")}` : "";

  return <>
    <Drawer open={open} onOpenChange={value => { if (!value) close(); }}
      title={saved ? saved.mode === "save" ? "Draft saved" : "Request submitted" : initial ? "Edit draft" : "Create request"}
      description={saved ? "Your request is saved in your request history." : "Three short steps. You can save a private draft at any time."}
      footer={saved ? <div className="form-actions"><Button tone="secondary" onClick={() => onOpenChange(false)}>Close</Button><Button onClick={openSaved}>Open request</Button></div> : <div className="space-y-2">
        <div className="request-wizard-footer">
          <Button tone="ghost" disabled={mutation.isPending} onClick={step === 0 ? close : () => goTo(step - 1)}>{step === 0 ? "Close" : "Back"}</Button>
          <Button tone="secondary" disabled={mutation.isPending || conflict} onClick={() => saveDraft()}>{mutation.isPending && mutation.variables === "save" ? "Saving…" : "Save draft"}</Button>
          {step < 2 ? <Button disabled={mutation.isPending} onClick={next}>Continue</Button> : <Button disabled={mutation.isPending || conflict || !approver} onClick={submit}>{mutation.isPending && mutation.variables === "submit" ? "Submitting…" : "Submit request"}</Button>}
        </div>
        <p className="text-xs leading-5 text-muted">{!approver ? "A manager must be assigned before you can submit. You can still save a draft." : step === 2 ? "Submitting sends this request to your assigned manager." : "Save a draft to finish later. It stays private until you submit."}</p>
      </div>}>
      {saved ? <section className="request-wizard-receipt success-feedback" aria-label="Request saved">
        <CheckCircle2 size={30} aria-hidden="true" className="text-lime"/>
        <h3 ref={stepHeading} tabIndex={-1} className="focus-ring rounded text-xl font-semibold">{number}</h3>
        <p className="font-medium [overflow-wrap:anywhere]">{saved.request.title || "Untitled draft"}</p>
        <Badge tone={statusTone(saved.request.status)}>{requestLabel(saved.request.status)}</Badge>
        <p role="status" className="text-sm leading-6 text-muted">{saved.mode === "save" ? "Your private draft is saved. Open it from My requests when you are ready to continue." : "Your request has been submitted for review. Open it to see its status, comments and history."}</p>
      </section> : <div className="space-y-4">
        <ol className="request-wizard-steps" aria-label="Request steps">{steps.map((label, index) => <li key={label} aria-current={index === step ? "step" : undefined}><span aria-hidden="true">{index + 1}</span>{label}</li>)}</ol>
        <div className="flex items-start justify-between gap-3"><div><h3 ref={stepHeading} tabIndex={-1} className="focus-ring rounded text-base font-semibold">{step === 0 ? "What do you need?" : step === 1 ? "When and how urgent?" : "Review your request"}</h3><p className="mt-1 text-xs text-muted">Step {step + 1} of 3{step < 2 && " · Required fields marked *"}</p></div><Badge tone={statusTone(initial?.status ?? "draft")}>{initial?.status ? formatStatus(initial.status) : "New draft"}</Badge></div>
        {error && <p ref={errorNotice} tabIndex={-1} role="alert" className="focus-ring rounded-lg bg-danger/10 p-3 text-sm text-danger">{error} Your entries are kept. Review them and try again.</p>}
        {conflict && initial && <div role="status" className="space-y-3 rounded-lg border border-line p-4 text-sm">
          <p>This draft changed. Your unsaved edits are kept in the steps below.</p><p className="font-semibold">Latest saved version</p>
          <p className="whitespace-pre-wrap [overflow-wrap:anywhere]">{initial.title}<br/>{initial.comment}</p><p>{initial.type_label} · {initial.priority} · {initial.start_date || "No start date"} → {initial.end_date || "No end date"}</p>
          {initial.status === "draft" ? <><p>Compare before continuing. Your edited fields take precedence; untouched fields use the latest saved values.</p><Button tone="secondary" onClick={reviewLatest}>Keep my edits and merge latest changes</Button></> : <p>This request is now {formatStatus(initial.status)} and can no longer be edited as a draft.</p>}
        </div>}
        <fieldset ref={fields} disabled={mutation.isPending} className="request-form-fields min-w-0 space-y-4">
          <legend className="sr-only">{steps[step]}</legend>
          {step === 0 && <>
            <label className="block text-sm font-medium">Category *<select className={`${fieldClass} mt-1.5`} value={type} aria-required="true" onChange={event => setType(event.target.value)}>{Object.entries(categories).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label className="block text-sm font-medium">Title *<input className={`${fieldClass} mt-1.5`} minLength={3} maxLength={160} aria-required="true" aria-describedby="request-title-help" aria-invalid={titleInvalid} value={title} onChange={event => setTitle(event.target.value)}/></label>
            <p id="request-title-help" className={`-mt-2 text-xs ${titleInvalid ? "text-danger" : "text-muted"}`}>Name what you need in 3–160 characters.</p>
            <label className="block text-sm font-medium">Description *<textarea className={`${fieldClass} mt-1.5 min-h-28 resize-y`} value={comment} onChange={event => setComment(event.target.value)} maxLength={10000} minLength={3} aria-required="true" aria-describedby="request-description-help" aria-invalid={descriptionInvalid} placeholder="What do you need, and why?"/></label>
            <p id="request-description-help" className={`-mt-2 text-xs leading-5 ${descriptionInvalid ? "text-danger" : "text-muted"}`}>{descriptionInvalid ? "Add at least 3 characters to explain your request." : "Include relevant facts only. Leave out diagnoses and unrelated personal information."}</p>
          </>}
          {step === 1 && <>
            <label className="block text-sm font-medium">Priority<select className={`${fieldClass} mt-1.5`} value={priority} onChange={event => setPriority(event.target.value)}>{["low", "normal", "high", "urgent"].map(value => <option key={value} value={value}>{requestLabel(value)}</option>)}</select></label>
            {datesRequired ? dateFields : <OptionalDateRange hasDates={Boolean(start || end)}>{dateFields}</OptionalDateRange>}
            {duration !== null && <p className="text-sm text-muted">{duration} calendar {duration === 1 ? "day" : "days"}</p>}
            {!datesRequired && <p className="text-xs leading-5 text-muted">Dates are optional for a document request. Continue if they do not apply.</p>}
          </>}
          {step === 2 && <>
            <section className="request-wizard-review" aria-labelledby="request-review-details"><div><h4 id="request-review-details" className="font-semibold">Request details</h4><Button tone="ghost" onClick={() => goTo(0)}>Edit details</Button></div><dl><div><dt>Category</dt><dd>{categories[type] || requestLabel(type)}</dd></div><div><dt>Title</dt><dd>{title}</dd></div><div><dt>Description</dt><dd className="whitespace-pre-wrap">{comment}</dd></div></dl></section>
            <section className="request-wizard-review" aria-labelledby="request-review-timing"><div><h4 id="request-review-timing" className="font-semibold">Timing and priority</h4><Button tone="ghost" onClick={() => goTo(1)}>Edit timing</Button></div><dl><div><dt>Priority</dt><dd>{requestLabel(priority)}</dd></div><div><dt>Dates</dt><dd>{start || end ? `${start || "No start date"} → ${end || "No end date"}` : "No dates needed"}{duration !== null && ` · ${duration} calendar ${duration === 1 ? "day" : "days"}`}</dd></div></dl></section>
          </>}
          <div className="request-wizard-recipient"><span>Assigned manager</span><strong>{managerName || "No manager assigned"}</strong>{!approver && <p>Ask your administrator to assign a manager before submitting.</p>}</div>
        </fieldset>
      </div>}
    </Drawer>
    <Drawer open={open && discardOpen} onOpenChange={setDiscardOpen} title="Save your changes?" description="Your draft has unsaved changes. Keep editing, save the draft, or discard only these changes." placement="center" size="small" footer={<div className="form-actions">
      <Button tone="secondary" disabled={mutation.isPending} onClick={() => { closeAfterSave.current = false; setDiscardOpen(false); }}>Continue editing</Button>
      <Button tone="danger" disabled={mutation.isPending} onClick={() => { clearUnsavedChanges(); setDiscardOpen(false); onOpenChange(false); }}>Discard changes</Button>
      <Button disabled={mutation.isPending || conflict} onClick={() => saveDraft(true)}>{mutation.isPending ? "Saving…" : "Save draft and close"}</Button>
    </div>}>{error && <p role="alert" className="text-sm text-danger">{error}</p>}</Drawer>
  </>;
}
