import { useState } from "react";
import { Button, fieldClass } from "../../components/ui";

type ReplyTemplate = { id: string; title: string; text: string };
const templates: Record<string, ReplyTemplate[]> = {
  request_information: [
    { id: "clarification", title: "Clarify a detail", text: "Please clarify [[information needed]] so I can review [[specific part of the request]]." },
    { id: "supporting-information", title: "Ask for supporting information", text: "Please provide [[relevant supporting information]] to help me assess [[specific review question]]. Include only information relevant to this request." },
  ],
  approve: [
    { id: "approval", title: "Approval with next steps", text: "I reviewed [[request-specific facts]]. This request can be approved because [[how those facts meet the applicable criteria]]. Next steps: [[what happens next]]." },
    { id: "approval-after-reply", title: "Approval after clarification", text: "Your additional information confirms [[relevant fact]]. This addresses [[review question]] and supports approval because [[request-specific explanation]]. Next steps: [[what happens next]]." },
  ],
  reject: [
    { id: "unmet-requirement", title: "Explain an unmet requirement", text: "I reviewed [[request-specific facts]]. The request does not meet [[applicable requirement]] because [[specific reason]]. You can request reconsideration with [[relevant information or correction]]." },
    { id: "alternative", title: "Explain the decision and an alternative", text: "The request cannot be approved as submitted because [[request-specific reason]]. A possible next step is [[relevant alternative]]. You may request reconsideration and explain what should be reviewed again." },
  ],
  complete: [
    { id: "work-completed", title: "Confirm completed work", text: "Completed [[work performed]] on [[completion date]]. Result: [[outcome or reference]]." },
    { id: "document-delivered", title: "Confirm a document was delivered", text: "The requested [[document]] was delivered through [[approved delivery method]] on [[delivery date]]. Reference: [[relevant reference or next step]]." },
  ],
};

export function hasTemplatePlaceholders(value: string): boolean {
  return value.includes("[[") || value.includes("]]");
}

/** Suggestions are inserted only on request and never replace a manager's notes. */
export function ReplyTemplates({ action, value, disabled, onInsert }: {
  action: string;
  value: string;
  disabled: boolean;
  onInsert: (text: string) => void;
}) {
  const choices = templates[action] ?? [];
  const [selected, setSelected] = useState("");
  const template = choices.find(item => item.id === selected) ?? choices[0];
  if (!template) return null;
  const separator = value.trim() ? "\n\n" : "";
  const exceedsLimit = value.length + separator.length + template.text.length > 10000;
  return <details className="rounded-lg border border-line bg-raised p-3">
    <summary className="focus-ring cursor-pointer rounded text-sm font-semibold">Response templates</summary>
    <div className="mt-3 space-y-3">
      <p className="text-xs leading-5 text-muted">Start with a structure, then replace every [[placeholder]] with facts about this request. A template does not decide the outcome.</p>
      <label className="block text-sm font-medium">Choose a response template<select className={`${fieldClass} mt-1.5`} disabled={disabled} value={template.id} onChange={event => setSelected(event.target.value)}>{choices.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
      <p className="whitespace-pre-wrap rounded-md border border-line bg-panel p-3 text-sm leading-6 [overflow-wrap:anywhere]">{template.text}</p>
      <Button tone="secondary" disabled={disabled || exceedsLimit} onClick={() => onInsert(`${value}${separator}${template.text}`)}>{value.trim() ? "Append template" : "Use template"}</Button>
      {exceedsLimit && <p role="status" className="text-xs leading-5 text-muted">There is not enough space to append this template. Shorten your explanation first; your existing text is kept.</p>}
    </div>
  </details>;
}
