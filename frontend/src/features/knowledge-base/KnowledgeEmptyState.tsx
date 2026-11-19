import { CheckCircle2 } from "lucide-react";
export function KnowledgeEmptyState({ title, copy }: { title: string; copy: string }) {
  return <div className="grid min-h-56 place-items-center p-6 text-center"><div><CheckCircle2 className="mx-auto text-lime" /><h3 className="mt-3 font-semibold">{title}</h3><p className="mt-2 text-sm text-muted">{copy}</p></div></div>;
}
