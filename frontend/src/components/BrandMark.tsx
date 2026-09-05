import { StarFour } from "@phosphor-icons/react";

export function BrandMark({ size = 28, className = "" }: { size?: number; className?: string }) {
  return (
    <StarFour
      size={size}
      weight="duotone"
      aria-hidden="true"
      className={`shrink-0 text-accent ${className}`}
    />
  );
}
