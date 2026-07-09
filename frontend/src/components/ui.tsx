import * as Dialog from "@radix-ui/react-dialog";
import * as Tooltip from "@radix-ui/react-tooltip";
import { X } from "lucide-react";
import { clsx } from "clsx";
import type { ButtonHTMLAttributes, ReactNode } from "react";

export function Button({ className, tone = "primary", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: "primary" | "secondary" | "ghost" | "danger" }) {
  return <button className={clsx("focus-ring inline-flex min-h-10 items-center justify-center gap-2 rounded-xl px-4 text-sm font-semibold transition active:scale-[.98] disabled:pointer-events-none disabled:opacity-45",
    tone === "primary" && "bg-lime text-ink hover:bg-[#dcff82]",
    tone === "secondary" && "border border-line bg-raised text-cream hover:border-[#4b5344]",
    tone === "ghost" && "text-muted hover:bg-raised hover:text-cream",
    tone === "danger" && "bg-danger/12 text-danger hover:bg-danger/20", className)} {...props} />;
}
export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx("rounded-2xl border border-line bg-panel p-5", className)}>{children}</div>;
}
export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "success" | "warning" | "danger" }) {
  return <span className={clsx("inline-flex rounded-full border px-2.5 py-1 text-[11px] font-bold uppercase tracking-[.12em]",
    tone === "neutral" && "border-line bg-raised text-muted", tone === "success" && "border-lime/25 bg-lime-soft text-lime",
    tone === "warning" && "border-coral/25 bg-coral/10 text-coral", tone === "danger" && "border-danger/25 bg-danger/10 text-danger")}>{children}</span>;
}
export function Drawer({ open, onOpenChange, title, description, children }: { open: boolean; onOpenChange: (open: boolean) => void; title: string; description?: string; children: ReactNode }) {
  return <Dialog.Root open={open} onOpenChange={onOpenChange}><Dialog.Portal>
    <Dialog.Overlay className="fixed inset-0 z-40 bg-black/65 backdrop-blur-sm" />
    <Dialog.Content className="soft-shadow fixed inset-y-0 right-0 z-50 w-full max-w-[520px] overflow-y-auto border-l border-line bg-panel p-6 sm:p-8">
      <div className="mb-8 flex items-start justify-between gap-4"><div><Dialog.Title className="text-2xl font-semibold">{title}</Dialog.Title>{description && <Dialog.Description className="mt-2 text-sm leading-6 text-muted">{description}</Dialog.Description>}</div>
      <Dialog.Close asChild><Button tone="ghost" aria-label="Close drawer" className="h-10 w-10 px-0"><X size={18}/></Button></Dialog.Close></div>{children}
    </Dialog.Content></Dialog.Portal></Dialog.Root>;
}
export function Hint({ label, children }: { label: string; children: ReactNode }) {
  return <Tooltip.Provider delayDuration={300}><Tooltip.Root><Tooltip.Trigger asChild>{children}</Tooltip.Trigger><Tooltip.Portal><Tooltip.Content sideOffset={8} className="z-[70] rounded-lg bg-cream px-2.5 py-1.5 text-xs text-ink">{label}</Tooltip.Content></Tooltip.Portal></Tooltip.Root></Tooltip.Provider>;
}
export const fieldClass = "focus-ring w-full rounded-xl border border-line bg-ink px-3.5 py-3 text-sm text-cream placeholder:text-muted/60";
export function statusTone(status: string): "neutral" | "success" | "warning" | "danger" {
  if (["approved","completed","indexed"].includes(status)) return "success";
  if (["submitted","in_review","indexing","draft","pending"].includes(status)) return "warning";
  if (["declined","cancelled","error"].includes(status)) return "danger";
  return "neutral";
}
