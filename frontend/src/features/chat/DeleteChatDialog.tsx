import { SpinnerGap, Trash } from "@phosphor-icons/react";
import * as Dialog from "@radix-ui/react-dialog";
import { useRef } from "react";
import type { ConversationSummary } from "../../api/types";
import { Button } from "../../components/ui";

export function DeleteChatDialog({
  conversation,
  busy,
  error,
  onCancel,
  onConfirm,
  onRestoreFocus,
}: {
  conversation: ConversationSummary | null;
  busy: boolean;
  error: string;
  onCancel: () => void;
  onConfirm: () => void;
  onRestoreFocus: () => void;
}) {
  const actions = useRef<HTMLDivElement>(null);
  return (
    <Dialog.Root open={Boolean(conversation)} onOpenChange={(open) => !open && !busy && onCancel()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay fixed inset-0 z-50" />
        <Dialog.Content
          className="dialog-content soft-shadow fixed left-1/2 top-1/2 z-[60] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl border border-line bg-ink p-6"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            actions.current?.querySelector("button")?.focus();
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            onRestoreFocus();
          }}
          onInteractOutside={(event) => event.preventDefault()}
          onEscapeKeyDown={(event) => busy && event.preventDefault()}
        >
          <Dialog.Title className="text-lg font-semibold">Delete chat?</Dialog.Title>
          <p className="mt-3 line-clamp-2 text-sm font-medium" title={conversation?.title}>
            {conversation?.title}
          </p>
          <Dialog.Description className="mt-2 text-sm leading-6 text-muted">
            This chat will be permanently removed. Your requests will stay in My requests.
          </Dialog.Description>
          {error && (
            <p role="alert" className="mt-4 text-sm text-danger">
              {error}
            </p>
          )}
          <div ref={actions} className="mt-6 flex justify-end gap-2">
            <Button tone="secondary" onClick={onCancel} disabled={busy}>
              Cancel
            </Button>
            <Button tone="danger" onClick={onConfirm} disabled={busy}>
              {busy ? <SpinnerGap size={17} className="animate-spin" /> : <Trash size={17} />}
              {busy ? "Deleting…" : "Delete chat"}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
