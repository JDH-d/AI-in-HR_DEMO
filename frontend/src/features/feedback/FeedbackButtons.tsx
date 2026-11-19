import { useFeedback } from "./useFeedback";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { Button, Hint, fieldClass } from "../../components/ui";
import { useUnsavedChanges } from "../../components/UnsavedChanges";
export function FeedbackButtons({ question, answer }: { question: string; answer: string }) {
  const { done, explain, setExplain, comment, setComment, sending, error, send } = useFeedback(question, answer);
  useUnsavedChanges(done === null && explain && Boolean(comment.trim()));

  if (done !== null) {
    return <p role="status" className="success-feedback text-xs text-muted">Thanks — knowledge admins see this feedback without your identity.</p>;
  }

  return <div>
    <div className="flex items-center gap-1">
      <Hint label="Helpful"><Button tone="ghost" aria-label="Helpful" disabled={sending} onClick={() => send(5)} className="h-11 w-11 hover:text-lime" style={{padding: 0}}><ThumbsUp size={15} aria-hidden="true"/></Button></Hint>
      <Hint label="Needs work"><Button tone={explain ? "secondary" : "ghost"} aria-label="Not helpful" aria-expanded={explain} disabled={sending} onClick={() => setExplain(true)} className="h-11 w-11" style={{padding: 0}}><ThumbsDown size={15} aria-hidden="true"/></Button></Hint>
    </div>
    {error && <p role="alert" className="mt-2 text-xs text-danger">{error} Please try again.</p>}
    {explain && <div className="mt-2 max-w-xl rounded-lg border border-line bg-panel p-3">
      <label className="text-sm font-medium text-cream">What should we improve? <span className="font-normal text-muted">Optional</span>
        <textarea className={`${fieldClass} mt-2 min-h-20 resize-none`} disabled={sending} value={comment} onChange={event => setComment(event.target.value)} placeholder="Missing context, incorrect policy, unclear wording…" />
      </label>
      <div className="mt-3 flex flex-wrap justify-end gap-2">
        <Button tone="ghost" onClick={() => setExplain(false)} disabled={sending}>Cancel</Button>
        <Button tone="secondary" onClick={() => send(1)} disabled={sending}>Send without note</Button>
        <Button onClick={() => send(1, comment)} disabled={sending || !comment.trim()}>Send feedback</Button>
      </div>
    </div>}
  </div>;
}
