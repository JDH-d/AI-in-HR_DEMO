import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { api } from "../../api/client";
import { useAuth } from "../../app/providers";
import { Button, fieldClass, Hint } from "../../components/ui";

export function FeedbackButtons({ question, answer }: { question: string; answer: string }) {
  const { token } = useAuth();
  const [done, setDone] = useState<number | null>(null);
  const [explain, setExplain] = useState(false);
  const [comment, setComment] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");

  const send = async (rating: number, note = "") => {
    setSending(true);
    setError("");
    try {
      await api("/api/v1/feedback", token, {
        method: "POST",
        body: JSON.stringify({ rating, question, answer, comment: note }),
      });
      setDone(rating);
      setExplain(false);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to send feedback");
    } finally {
      setSending(false);
    }
  };

  if (done !== null) {
    return (
      <p className="text-xs text-muted">
        Thanks — knowledge admins see this feedback without your identity.
      </p>
    );
  }

  return (
    <div>
      <div className="flex items-center gap-1">
        <Hint label="Helpful">
          <button
            type="button"
            aria-label="Helpful"
            disabled={sending}
            onClick={() => send(5)}
            className="rounded-lg p-2 text-muted hover:text-lime disabled:opacity-45"
          >
            <ThumbsUp size={15} />
          </button>
        </Hint>
        <Hint label="Needs work">
          <button
            type="button"
            aria-label="Not helpful"
            disabled={sending}
            onClick={() => setExplain(true)}
            className={`rounded-lg p-2 ${explain ? "bg-danger/10 text-danger" : "text-muted hover:text-danger"}`}
          >
            <ThumbsDown size={15} />
          </button>
        </Hint>
      </div>
      {explain && (
        <div className="mt-3 max-w-xl rounded-2xl border border-danger/20 bg-danger/5 p-4">
          <label className="text-xs font-semibold text-cream">
            What should we improve? <span className="font-normal text-muted">Optional</span>
            <textarea
              className={`${fieldClass} mt-2 min-h-20 resize-none`}
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              placeholder="Missing context, incorrect policy, unclear wording…"
            />
          </label>
          {error && <p className="mt-2 text-xs text-danger">{error}</p>}
          <div className="mt-3 flex flex-wrap justify-end gap-2">
            <Button tone="ghost" onClick={() => setExplain(false)} disabled={sending}>
              Cancel
            </Button>
            <Button tone="secondary" onClick={() => send(1)} disabled={sending}>
              Send without note
            </Button>
            <Button
              tone="danger"
              onClick={() => send(1, comment)}
              disabled={sending || !comment.trim()}
            >
              Send feedback
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
