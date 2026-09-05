import { CheckCircle } from "@phosphor-icons/react";

export function PtoSuccess() {
  return (
    <div
      className="flex min-h-64 items-center justify-center py-8"
      role="status"
      aria-live="polite"
    >
      <div className="max-w-xs text-center">
        <CheckCircle size={36} className="mx-auto text-success" />
        <h3 className="mt-4 text-lg font-medium leading-7 text-cream">
          We sent your request to your manager.
        </h3>
        <p className="mt-2 text-sm leading-6 text-muted">
          You can follow the decision in My requests.
        </p>
      </div>
    </div>
  );
}
