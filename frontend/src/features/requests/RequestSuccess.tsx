import { Check } from "lucide-react";

export function PtoSuccess() {
  return (
    <div
      className="request-success grid min-h-[360px] place-items-center py-10"
      role="status"
      aria-live="polite"
    >
      <div className="max-w-xs text-center">
        <div className="request-success-mark relative mx-auto grid h-20 w-20 place-items-center">
          <span className="request-success-halo absolute inset-0 rounded-full border border-lime/25" />
          <span className="relative grid h-14 w-14 place-items-center rounded-2xl bg-lime text-ink shadow-[0_12px_40px_rgba(201,244,91,.18)]">
            <Check size={28} strokeWidth={2.4} />
          </span>
        </div>
        <h3 className="mt-6 text-xl font-semibold leading-8 text-cream">
          We sent your request to your manager.
        </h3>
        <p className="mt-2 text-sm leading-6 text-muted">
          You can follow the decision in My requests.
        </p>
      </div>
    </div>
  );
}
