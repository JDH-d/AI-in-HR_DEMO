export type Role = "employee" | "manager" | "knowledge_admin";
export type User = { id: string; username: string; display_name: string; role: Role; manager_id?: string | null };
export type Source = { source: string; title: string; section: string; category: string; version: string; excerpt: string; score: number };
export type WorkflowRequest = {
  id: string; type: "pto" | "sick_leave" | "document"; type_label: string;
  start_date: string | null; end_date: string | null; duration_days: number | null;
  comment: string; applicant: string; approver: string; status: string;
  created_at: string; updated_at: string; validation_errors?: string[];
};
export type RequestDetail = { request: WorkflowRequest; events: RequestEvent[]; comments: RequestComment[] };
export type RequestEvent = { id: string; event_type: string; from_status: string | null; to_status: string | null; actor: string; details: Record<string, unknown>; created_at: string };
export type RequestComment = { id: string; author: string; body: string; created_at: string };
export type DocumentItem = { id: string; name: string; title: string; category: string; version: string; size: number; modified: string; index_status: string; chunk_count: number; indexed_at: string | null; index_error: string | null };
export type Metrics = { questions: number; grounded_answer_rate: number; unanswered_questions: number; positive_feedback_rate: number; requests_created: number; requests_approved: number; [key: string]: unknown };
export type ChatMessage = { id: string; role: "user" | "assistant"; content: string; sources?: Source[]; workflow?: WorkflowRequest | null; streaming?: boolean; question?: string };
