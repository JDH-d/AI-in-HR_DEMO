import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, downloadFile } from "../../api/client";
import type { AISettings, AISettingsResponse, AISettingsTestResult, DocumentItem, FeedbackItem, KnowledgeGap, Metrics } from "../../api/types";
import { useAuth } from "../../app/providers";
export function useKnowledgeMetrics() {
 const { token } = useAuth();
 return useQuery({ queryKey: ["metrics"], queryFn: () => api<{ metrics: Metrics }>("/api/v1/admin/metrics", token) });
}

function useSavedAISettings() {
 const { token } = useAuth();
 return useQuery({ queryKey: ["ai-settings"], queryFn: () => api<AISettingsResponse>("/api/v1/admin/ai-settings", token) });
}

function useRefreshKnowledge() {
 const queryClient = useQueryClient();
 return (...keys: string[]) => Promise.all(keys.map(key => queryClient.invalidateQueries({ queryKey: [key] })));
}

export function useDocuments() {
  const { token } = useAuth();
  const refresh = useRefreshKnowledge();
  const [uploadOpen, setUploadOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<DocumentItem | null>(null);
  const [downloadError, setDownloadError] = useState("");
  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: () => api<{ documents: DocumentItem[] }>("/api/v1/documents", token),
  });
  const list = documents.data?.documents ?? [];
  const stats = {
    indexed: list.filter(item => item.index_status === "indexed").length,
    pending: list.filter(item => ["pending", "indexing"].includes(item.index_status)).length,
    errors: list.filter(item => item.index_status === "error").length,
  };
  const indexing = useMutation({
    mutationFn: (id: string) => api(`/api/v1/documents/${id}/index`, token, { method: "POST" }),
    onSuccess: () => refresh("documents"),
  });
  const removing = useMutation({
    mutationFn: (id: string) => api(`/api/v1/documents/${id}`, token, { method: "DELETE" }),
    onSuccess: () => {
      setDeleteTarget(null);
      void refresh("documents", "metrics");
    },
  });
  const download = async (document: DocumentItem) => {
    setDownloadError("");
    try {
      await downloadFile(`/api/v1/documents/${document.id}/download`, token, document.name.split("/").pop() ?? document.name);
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : "Unable to download the document");
    }
  };

  return { uploadOpen, setUploadOpen, deleteTarget, setDeleteTarget, downloadError, documents, list, stats, indexing, removing, download };
}

export function useDocumentUpload(onOpenChange: (open: boolean) => void) {
  const { token } = useAuth();
  const refresh = useRefreshKnowledge();
  const [file, setFile] = useState<File | null>(null);
  const aiSettings = useSavedAISettings();
  const autoIndex = aiSettings.data?.settings.auto_index_uploads ?? true;
  const upload = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("Choose a document before uploading.");
      const form = new FormData();
      form.append("file", file);
      return api<{ document: DocumentItem }>("/api/v1/documents", token, { method: "POST", body: form });
    },
    onSuccess: () => {
      void refresh("documents", "metrics");
      setFile(null);
      onOpenChange(false);
    },
  });
  return { file, setFile, autoIndex, aiSettings, upload };
}

export function useQuality() {
  const { token } = useAuth();
  const refresh = useRefreshKnowledge();
  const [mode, setMode] = useState<"negative" | "gaps" | "positive">("negative");
  const [search, setSearch] = useState("");
  const [selectedFeedback, setSelectedFeedback] = useState<FeedbackItem | null>(null);
  const [selectedGap, setSelectedGap] = useState<KnowledgeGap | null>(null);
  const feedback = useQuery({ queryKey: ["admin-feedback"], queryFn: () => api<{ feedback: FeedbackItem[] }>("/api/v1/admin/feedback?sentiment=all&limit=500", token) });
  const gaps = useQuery({ queryKey: ["knowledge-gaps"], queryFn: () => api<{ questions: KnowledgeGap[] }>("/api/v1/admin/unanswered", token) });
  const reviewGap = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "resolved" | "ignored" }) => api(`/api/v1/admin/quality/${id}`, token, { method: "POST", body: JSON.stringify({ action }) }),
    onSuccess: () => {
      setSelectedGap(null);
      void refresh("knowledge-gaps", "metrics");
    },
  });
  const feedbackItems = feedback.data?.feedback ?? [];
  const gapItems = gaps.data?.questions ?? [];
  const counts = {
    positive: feedbackItems.filter(item => item.sentiment === "positive").length,
    negative: feedbackItems.filter(item => item.sentiment === "negative").length,
    gaps: gapItems.length,
  };
  const needle = search.trim().toLowerCase();
  const visibleFeedback = feedbackItems.filter(item => item.sentiment === mode && (!needle || `${item.question} ${item.answer} ${item.comment}`.toLowerCase().includes(needle)));
  const visibleGaps = gapItems.filter(item => !needle || `${item.question} ${item.assistant}`.toLowerCase().includes(needle));
  const loading = feedback.isLoading || gaps.isLoading;
  const empty = mode === "gaps" ? !visibleGaps.length : !visibleFeedback.length;

  return { mode, setMode, search, setSearch, selectedFeedback, setSelectedFeedback, selectedGap, setSelectedGap, feedback, gaps, reviewGap, counts, visibleFeedback, visibleGaps, loading, empty };
}

export function useAISettings() {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  const defaults: AISettings = { strict_grounding: true, concise_answers: true, ask_clarifying_questions: true, suggest_next_steps: true, show_sources: true, auto_index_uploads: true };
  const [draft, setDraft] = useState<{settings: AISettings; prompt: string} | null>(null);
  const [question, setQuestion] = useState("When are salaries paid?");
  const loaded = useSavedAISettings();
  // Background refreshes must never overwrite edits waiting to be applied.
  const settings = draft?.settings ?? loaded.data?.settings ?? defaults;
  const prompt = draft?.prompt ?? loaded.data?.system_prompt ?? "";
  const dirty = loaded.data
    ? JSON.stringify(settings) !== JSON.stringify(loaded.data.settings) || prompt !== loaded.data.system_prompt
    : false;
  const save = useMutation({
    mutationFn: () => api<AISettingsResponse>("/api/v1/admin/ai-settings", token, { method: "PUT", body: JSON.stringify({ settings, system_prompt: prompt }) }),
    onSuccess: data => {
      queryClient.setQueryData(["ai-settings"], data);
      setDraft(null);
    },
  });
  const preview = useMutation({
    mutationFn: () => api<AISettingsTestResult>("/api/v1/admin/ai-settings/test", token, { method: "POST", body: JSON.stringify({ question, settings, system_prompt: prompt }) }),
  });
  const changeSetting = (key: keyof AISettings, checked: boolean) => {
    setDraft(current => ({ settings: { ...(current?.settings ?? settings), [key]: checked }, prompt: current?.prompt ?? prompt }));
    preview.reset();
    save.reset();
  };
  const changePrompt = (value: string) => {
    setDraft(current => ({ settings: current?.settings ?? settings, prompt: value }));
    preview.reset();
    save.reset();
  };
  const changeQuestion = (value: string) => {
    setQuestion(value);
    preview.reset();
  };
  const reset = () => {
    if (!loaded.data) return;
    setDraft(null);
    preview.reset();
    save.reset();
  };
  const previewSourceTitles = [...new Set((preview.data?.sources ?? []).map(source => source.title))];

  return { loaded, settings, prompt, question, dirty, save, preview, changeSetting, changePrompt, changeQuestion, reset, previewSourceTitles };
}
