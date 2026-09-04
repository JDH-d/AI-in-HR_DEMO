export type Role = "employee" | "manager" | "knowledge_admin";

export type User = {
  id: string;
  username: string;
  display_name: string;
  role: Role;
  manager_id?: string | null;
};

export type Source = {
  source: string;
  title: string;
  section: string;
  category: string;
  version: string;
  excerpt: string;
  score: number;
};

export type RequestType = "pto" | "sick_leave";
export type WorkflowStatus =
  | "draft"
  | "in_review"
  | "reported"
  | "acknowledged"
  | "approved"
  | "declined"
  | "cancelled";

export type WorkflowRequest = {
  id: string;
  type: RequestType;
  type_label: string;
  start_date: string | null;
  end_date: string | null;
  duration_days: number | null;
  comment: string;
  applicant: string;
  approver: string;
  status: WorkflowStatus;
  details: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  validation_errors?: string[];
};

export type RequestDetail = {
  request: WorkflowRequest;
  events: RequestEvent[];
  comments: RequestComment[];
};

export type RequestEvent = {
  id: string;
  event_type: string;
  from_status: string | null;
  to_status: string | null;
  actor: string;
  details: Record<string, unknown>;
  created_at: string;
};

export type RequestComment = {
  id: string;
  author: string;
  body: string;
  created_at: string;
};

export type IndexStatus = "pending" | "indexing" | "indexed" | "error";

export type DocumentItem = {
  id: string;
  name: string;
  title: string;
  category: string;
  version: string;
  size: number;
  modified: string;
  index_status: IndexStatus;
  index_mode: "embedding" | "lexical" | null;
  chunk_count: number;
  indexed_at: string | null;
  index_error: string | null;
};

export type FeedbackItem = {
  id: string;
  rating: number;
  sentiment: "positive" | "negative";
  question: string;
  answer: string;
  comment: string;
  created_at: string;
};

export type KnowledgeGap = {
  id: string;
  timestamp: string;
  question: string;
  assistant: string;
};

export type AISettings = {
  strict_grounding: boolean;
  concise_answers: boolean;
  ask_clarifying_questions: boolean;
  suggest_next_steps: boolean;
  show_sources: boolean;
  auto_index_uploads: boolean;
};

export type AISettingsResponse = {
  settings: AISettings;
  system_prompt: string;
  default_system_prompt: string;
};

export type AISettingsTestResult = {
  answer: string;
  intent: string;
  sources: Source[];
  latency_ms: number;
};

export type Metrics = {
  questions: number;
  grounded_answer_rate: number;
  unanswered_questions: number;
  positive_feedback_rate: number;
  requests_created: number;
  requests_approved: number;
  [key: string]: unknown;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  workflow?: WorkflowRequest | null;
  streaming?: boolean;
  error?: boolean;
  question?: string;
  created_at?: string;
};

export type ConversationSummary = {
  id: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
};

export type ConversationDetail = {
  conversation: ConversationSummary;
  messages: ChatMessage[];
};

export type ChatStreamEvent =
  | { type: "start" }
  | { type: "token" | "replace"; content: string }
  | { type: "error"; message: string }
  | {
      type: "complete";
      intent: string;
      language: string;
      outcome_code: string;
      sources: Source[];
      workflow_request: WorkflowRequest | null;
      conversation_id: string;
    };
