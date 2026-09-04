import type { ChatMessage, ConversationSummary, WorkflowRequest } from "../../api/types";
import { formatStatus } from "../../components/ui";

export function restoreConversationMessages(messages: ChatMessage[]): ChatMessage[] {
  let latestQuestion = "";
  return messages.map((message) => {
    if (message.role === "user") {
      latestQuestion = message.content;
      return message;
    }
    return { ...message, question: latestQuestion };
  });
}

export function conversationMeta(conversation: ConversationSummary, now = new Date()): string {
  const turns = Math.ceil(conversation.message_count / 2);
  const updated = new Date(conversation.updated_at);
  const sameDay = updated.toDateString() === now.toDateString();
  const date = sameDay
    ? updated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : updated.toLocaleDateString([], { month: "short", day: "numeric" });
  return `${turns} ${turns === 1 ? "exchange" : "exchanges"} · ${date}`;
}

export function workflowMessage(request: WorkflowRequest): string {
  if (request.status === "draft") {
    return request.type === "sick_leave"
      ? "A sick leave report is ready. Nothing has been shared yet."
      : "A request draft is ready. Nothing has been sent for review.";
  }
  if (request.status === "reported") return "Your sick leave was shared with your manager.";
  if (request.status === "in_review") return "Your time-off request is with your manager.";
  return `Current status: ${formatStatus(request.status)}.`;
}
