import { useState } from "react";
import { api } from "../../api/client";
import { useAuth } from "../../app/providers";
export function useFeedback(question: string, answer: string) {
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

  return { done, explain, setExplain, comment, setComment, sending, error, send };
}
